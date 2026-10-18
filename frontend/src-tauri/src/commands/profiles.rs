//! Profile commands: list, select, edit, delete.

use serde::Serialize;
use streamarr_desktop_player::profile::{suggest_id, Profile, ServerAddress};
use tauri::State;

use crate::AppState;

/// A profile as the UI sees it.
///
/// Deliberately *not* the domain `Profile` itself: the UI does not need the
/// internals, and a separate shape means a change to the stored format does not
/// silently change the IPC contract. Paths are included because the settings screen
/// has to show the user where their `mpv.conf` lives — they are paths the app
/// already owns, derived from the profile id, not paths the UI supplied.
#[derive(Debug, Clone, Serialize)]
pub struct ProfileView {
    pub id: String,
    pub name: String,
    pub server_url: String,
    pub resolve_override: Option<String>,
    pub is_active: bool,
    pub user_label: Option<String>,
    pub mpv_config_path: String,
    pub directory: String,
    pub preferences: PreferencesView,
}

#[derive(Debug, Clone, Serialize)]
pub struct PreferencesView {
    pub fullscreen_on_play: bool,
    pub confirm_transcode: bool,
    pub audio_language: Option<String>,
    pub subtitle_language: Option<String>,
}

fn view(profile: &Profile, root: &std::path::Path, active: Option<&str>) -> ProfileView {
    ProfileView {
        id: profile.id.clone(),
        name: profile.name.clone(),
        server_url: profile.server.url.clone(),
        resolve_override: profile.server.resolve_override.clone(),
        is_active: active == Some(profile.id.as_str()),
        user_label: profile.user_label.clone(),
        mpv_config_path: profile.mpv_config_path(root).display().to_string(),
        directory: profile.directory(root).display().to_string(),
        preferences: PreferencesView {
            fullscreen_on_play: profile.preferences.fullscreen_on_play,
            confirm_transcode: profile.preferences.confirm_transcode,
            audio_language: profile.preferences.audio_language.clone(),
            subtitle_language: profile.preferences.subtitle_language.clone(),
        },
    }
}

#[tauri::command]
pub fn list_profiles(state: State<'_, AppState>) -> Result<Vec<ProfileView>, String> {
    let store = state.profiles.lock().unwrap();
    let active = store.active_id.clone();
    Ok(store
        .profiles
        .iter()
        .map(|p| view(p, &state.config_root, active.as_deref()))
        .collect())
}

#[tauri::command]
pub fn active_profile(state: State<'_, AppState>) -> Result<Option<ProfileView>, String> {
    let store = state.profiles.lock().unwrap();
    let active = store.active_id.clone();
    Ok(store
        .active()
        .map(|p| view(p, &state.config_root, active.as_deref())))
}

/// Creates or updates a profile.
///
/// `id` is optional: when absent one is derived from the name. The id is never taken
/// from the UI as a path — it is sanitised by the core crate, and an unsafe value is
/// rejected rather than repaired, so a traversal attempt fails loudly.
#[tauri::command]
#[allow(clippy::too_many_arguments)]
pub fn save_profile(
    state: State<'_, AppState>,
    id: Option<String>,
    name: String,
    server_url: String,
    resolve_override: Option<String>,
    fullscreen_on_play: Option<bool>,
    confirm_transcode: Option<bool>,
    audio_language: Option<String>,
    subtitle_language: Option<String>,
) -> Result<ProfileView, String> {
    let root = state.config_root.clone();
    let mut store = state.profiles.lock().unwrap();

    let id = match id {
        Some(id) => id,
        None => {
            // A name that yields an existing id gets a suffix rather than an error:
            // the user asked for a profile, not for a lesson about identifiers.
            let base = suggest_id(&name);
            let mut candidate = base.clone();
            let mut n = 2;
            while store.get(&candidate).is_some() {
                candidate = format!("{base}-{n}");
                n += 1;
            }
            candidate
        }
    };

    let mut server = ServerAddress::new(server_url);
    // An empty string from a text field means "no pin", not "a pin of nothing".
    server.resolve_override = resolve_override
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty());

    let existing = store.get(&id).cloned();
    let mut profile =
        existing.unwrap_or_else(|| Profile::new(id.clone(), name.clone(), server.clone()));
    profile.name = name;
    profile.server = server;
    if let Some(value) = fullscreen_on_play {
        profile.preferences.fullscreen_on_play = value;
    }
    if let Some(value) = confirm_transcode {
        profile.preferences.confirm_transcode = value;
    }
    if audio_language.is_some() {
        profile.preferences.audio_language = audio_language.filter(|s| !s.trim().is_empty());
    }
    if subtitle_language.is_some() {
        profile.preferences.subtitle_language = subtitle_language.filter(|s| !s.trim().is_empty());
    }
    profile.validate().map_err(|e| e.to_string())?;

    // Replace in place, or append.
    match store.profiles.iter_mut().find(|p| p.id == id) {
        Some(slot) => *slot = profile.clone(),
        None => store.add(profile.clone()).map_err(|e| e.to_string())?,
    }
    store.save(&root).map_err(|e| e.to_string())?;
    // The mpv.conf is created eagerly so the settings screen can offer to open it.
    store
        .ensure_profile_files(&root, &id)
        .map_err(|e| e.to_string())?;

    let active = store.active_id.clone();
    Ok(view(&profile, &root, active.as_deref()))
}

#[tauri::command]
pub fn set_active_profile(state: State<'_, AppState>, id: String) -> Result<(), String> {
    let root = state.config_root.clone();
    let mut store = state.profiles.lock().unwrap();
    store.set_active(&id).map_err(|e| e.to_string())?;
    store.save(&root).map_err(|e| e.to_string())?;
    drop(store);
    // A different server means different endpoints and different tokens.
    state.invalidate_api();
    Ok(())
}

#[tauri::command]
pub fn delete_profile(state: State<'_, AppState>, id: String) -> Result<(), String> {
    let root = state.config_root.clone();
    let mut store = state.profiles.lock().unwrap();
    let removed = store.remove(&id).map_err(|e| e.to_string())?;
    store.save(&root).map_err(|e| e.to_string())?;
    drop(store);
    // The profile directory is left on disk on purpose. It holds the user's
    // mpv.conf, and silently deleting a file the user may have written into would be
    // the kind of data loss that is impossible to undo.
    log::info!(
        "Profil `{}` entfernt; Verzeichnis bleibt erhalten: {}",
        removed.id,
        removed.directory(&root).display()
    );
    state.invalidate_api();
    Ok(())
}

/// Where a profile's files live, for the settings screen.
#[derive(Debug, Clone, Serialize)]
pub struct ProfilePaths {
    pub directory: String,
    pub mpv_config: String,
}

#[tauri::command]
pub fn profile_paths(state: State<'_, AppState>, id: String) -> Result<ProfilePaths, String> {
    let store = state.profiles.lock().unwrap();
    let profile = store.get(&id).ok_or("Profil nicht gefunden")?;
    Ok(ProfilePaths {
        directory: profile.directory(&state.config_root).display().to_string(),
        mpv_config: profile
            .mpv_config_path(&state.config_root)
            .display()
            .to_string(),
    })
}

/// Address details of the active server, for the login screen.
#[derive(Debug, Clone, Serialize)]
pub struct ServerInfoView {
    pub url: String,
    pub host: String,
    pub port: u16,
    pub resolve_override: Option<String>,
    /// Whether traffic is pinned to an IP instead of resolved.
    pub pinned: bool,
}

#[tauri::command]
pub fn server_info(state: State<'_, AppState>) -> Result<Option<ServerInfoView>, String> {
    let store = state.profiles.lock().unwrap();
    Ok(store.active().map(|profile| ServerInfoView {
        url: profile.server.base_url(),
        host: profile.server.host().unwrap_or_default().to_string(),
        port: profile.server.port().unwrap_or(443),
        resolve_override: profile.server.resolve_override.clone(),
        pinned: profile.server.resolve_override.is_some(),
    }))
}

#[cfg(test)]
mod tests {
    use streamarr_desktop_player::profile::{Profile, ProfileStore, ServerAddress};

    /// The view is built from the domain type and the root, and must never expose a
    /// path the caller supplied — only ones derived from the profile id.
    #[test]
    fn profile_paths_are_derived_from_the_root_and_id() {
        let root = std::path::Path::new("/config");
        let profile = Profile::new("home", "Zuhause", ServerAddress::new("https://host"));
        assert_eq!(
            profile.mpv_config_path(root),
            std::path::Path::new("/config/profiles/home/mpv.conf")
        );
    }

    /// An empty pin from a text field must mean "no pin", not an empty pin — the core
    /// crate rejects a malformed pin, so passing an empty string through would make
    /// the dialog refuse a valid address.
    #[test]
    fn an_empty_pin_is_treated_as_no_pin() {
        let mut store = ProfileStore::default();
        let mut profile = Profile::new("a", "A", ServerAddress::new("https://host"));
        profile.server.resolve_override = None;
        store.add(profile).unwrap();
        // The filtering happens in the command; this pins the rule it relies on.
        for empty in ["", "   "] {
            let filtered = Some(empty.to_string())
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty());
            assert_eq!(filtered, None, "`{empty}` muss als kein Pin gelten");
        }
    }

    #[test]
    fn a_name_that_collides_gets_a_suffix() {
        let mut store = ProfileStore::default();
        store
            .add(Profile::new("test", "Test", ServerAddress::default()))
            .unwrap();
        let base = streamarr_desktop_player::profile::suggest_id("Test");
        assert_eq!(base, "test");
        let mut candidate = base.clone();
        let mut n = 2;
        while store.get(&candidate).is_some() {
            candidate = format!("{base}-{n}");
            n += 1;
        }
        assert_eq!(candidate, "test-2");
    }
}
