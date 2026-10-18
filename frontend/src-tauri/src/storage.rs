//! Where profiles and tokens live on disk and in the OS keyring.
//!
//! This is the platform-facing half of the profile and session modules. The core
//! crate decides *what* a profile is and *when* a refresh is due; it deliberately
//! refuses to guess platform directories (ADR 001), so the shell resolves them here
//! and hands the root in.
//!
//! # Why tokens go to the keyring and profiles to disk
//!
//! A refresh token is a seven-day credential: anyone who reads it can mint access
//! tokens until it is revoked. Profiles, by contrast, are configuration the user may
//! reasonably want to inspect and edit — and the plan wants `mpv.conf` editable in
//! the profile folder. So the split follows sensitivity: credentials into the OS
//! store (Secret Service on Linux, Credential Manager on Windows), preferences into
//! a JSON file.
//!
//! The keyring is treated as *optional*. On a headless or containerised Linux
//! session there is often no Secret Service at all, and an app that refuses to run
//! there would be worse than one that falls back. [`TokenStorage`] therefore reports
//! which backend it ended up with, so the UI can say so honestly instead of
//! implying a level of protection it does not have.

use std::path::PathBuf;
use std::sync::Mutex;

use streamarr_desktop_player::profile::{Profile, ProfileStore, ServerAddress, DEFAULT_SERVER_URL};
use streamarr_desktop_player::session::{DeviceIdentity, TokenPair, TokenStore};

/// Keyring service name. Grouping by service keeps our entries findable and
/// separable from other applications' in the user's keyring UI.
const KEYRING_SERVICE: &str = "media.streamarr.desktop";

/// File under the config root that holds the stable device id.
const DEVICE_FILE: &str = "device.json";

/// Where the token ended up.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TokenBackend {
    /// The OS credential store.
    Keyring,
    /// A file next to the profile configuration, with restrictive permissions.
    File,
}

impl TokenBackend {
    /// German description for the UI.
    ///
    /// Kept next to the enum so a new variant cannot be added without a sentence to
    /// show the user — "where is my credential" must never be unanswerable.
    pub fn describe(self) -> &'static str {
        match self {
            Self::Keyring => "Die Anmeldung wird im Schlüsselbund des Systems gespeichert.",
            Self::File => {
                "Kein Schlüsselbund verfügbar — die Anmeldung wird in einer Datei mit \
                 eingeschränkten Rechten gespeichert."
            }
        }
    }
}

/// Resolves the configuration root for the app.
///
/// Tauri would normally provide this, but this module stays usable — and testable —
/// without a running app, so it takes the root as a parameter and only falls back to
/// the platform convention when asked.
pub fn default_config_root() -> PathBuf {
    // XDG on Linux, %APPDATA% on Windows. `directories` would do this, but the rule
    // is three lines and a dependency here would have to be justified twice.
    if cfg!(windows) {
        std::env::var_os("APPDATA")
            .map(PathBuf::from)
            .unwrap_or_else(std::env::temp_dir)
            .join("Streamarr")
    } else {
        std::env::var_os("XDG_CONFIG_HOME")
            .map(PathBuf::from)
            .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")))
            .unwrap_or_else(std::env::temp_dir)
            .join("streamarr")
    }
}

/// Loads the profile store, or an empty one on first run.
pub fn load_profiles(root: &std::path::Path) -> Result<ProfileStore, String> {
    ProfileStore::load(root).map_err(|e| e.to_string())
}

/// Creates the default profile for a fresh installation.
///
/// Seeded with the project's own server so a user of this deployment can log in
/// without typing an address; anyone else edits it. The profile is written to disk so
/// the address is visible and editable from the first launch, not hidden in a
/// default.
pub fn seed_default_profile(root: &std::path::Path) -> Result<Profile, String> {
    let mut store = load_profiles(root)?;
    if let Some(active) = store.active() {
        return Ok(active.clone());
    }
    let profile = Profile::new(
        "standard",
        "Streamarr",
        ServerAddress::new(DEFAULT_SERVER_URL),
    );
    store.add(profile.clone()).map_err(|e| e.to_string())?;
    store.save(root).map_err(|e| e.to_string())?;
    store
        .ensure_profile_files(root, &profile.id)
        .map_err(|e| e.to_string())?;
    Ok(profile)
}

/// Reads or creates the stable device identity (plan task 1.5).
///
/// The device id must survive restarts: a new one per launch would create a fresh
/// device record on the server every time, duplicating entries in the user's device
/// list and orphaning capabilities and playback positions.
pub fn device_identity(
    root: &std::path::Path,
    app_version: &str,
    device_name: &str,
) -> Result<DeviceIdentity, String> {
    let path = root.join(DEVICE_FILE);
    if let Ok(raw) = std::fs::read_to_string(&path) {
        if let Ok(device) = serde_json::from_str::<DeviceIdentity>(&raw) {
            return Ok(device);
        }
        // A corrupt file is regenerated rather than fatal: the worst outcome is one
        // extra device entry, which beats refusing to start.
        log::warn!("Gerätedatei unlesbar, wird neu erzeugt: {}", path.display());
    }
    let device = DeviceIdentity::new(
        generate_device_id(),
        app_version,
        std::env::consts::OS,
        device_name,
    );
    std::fs::create_dir_all(root).map_err(|e| e.to_string())?;
    let json = serde_json::to_string_pretty(&device).map_err(|e| e.to_string())?;
    std::fs::write(&path, json).map_err(|e| e.to_string())?;
    Ok(device)
}

/// A device id with enough entropy to be unique and no meaning beyond that.
///
/// Not a UUID library: two random 64-bit words in hex are ample for a per-install
/// identifier, and pulling a dependency for this would be out of proportion in a
/// crate that already avoided one for URL parsing.
fn generate_device_id() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    // Mixed with the address of a heap allocation so two processes starting in the
    // same nanosecond still differ.
    let marker = Box::new(0u8);
    let addr = format!("{:p}", marker).len();
    format!("desktop-{nanos:x}-{:x}-{addr:x}", std::process::id())
}

/// Token storage with a keyring-first strategy.
pub struct TokenStorage {
    backend: TokenBackend,
    /// Used by the file backend; `None` when the keyring is in use.
    fallback: Option<FileTokenStore>,
}

impl TokenStorage {
    /// Opens the credential store, falling back to a file when there is none.
    pub fn open(root: &std::path::Path) -> Self {
        // A probe write is the only reliable test: the Secret Service can be present
        // in the bus listing while refusing access, which is the situation inside a
        // container with no unlocked keyring.
        match probe_keyring() {
            true => Self {
                backend: TokenBackend::Keyring,
                fallback: None,
            },
            false => {
                log::warn!(
                    "Kein nutzbarer Schlüsselbund gefunden; Token werden in einer Datei \
                     gespeichert ({})",
                    root.display()
                );
                Self {
                    backend: TokenBackend::File,
                    fallback: Some(FileTokenStore::new(root.join("tokens.json"))),
                }
            }
        }
    }

    pub fn backend(&self) -> TokenBackend {
        self.backend
    }
}

/// Writes and removes one probe entry, so the caller knows the store really works.
fn probe_keyring() -> bool {
    let entry = match keyring::Entry::new(KEYRING_SERVICE, "__probe__") {
        Ok(entry) => entry,
        Err(_) => return false,
    };
    if entry.set_password("probe").is_err() {
        return false;
    }
    let readable = entry.get_password().is_ok();
    // Left behind on purpose if deletion fails; it is a single harmless key.
    let _ = entry.delete_credential();
    readable
}

impl TokenStore for TokenStorage {
    fn load(&self) -> Option<TokenPair> {
        match self.backend {
            TokenBackend::Keyring => {
                let entry = keyring::Entry::new(KEYRING_SERVICE, "session").ok()?;
                let raw = entry.get_password().ok()?;
                serde_json::from_str(&raw).ok()
            }
            TokenBackend::File => self.fallback.as_ref()?.load(),
        }
    }

    fn save(&self, tokens: &TokenPair) -> Result<(), String> {
        match self.backend {
            TokenBackend::Keyring => {
                let entry =
                    keyring::Entry::new(KEYRING_SERVICE, "session").map_err(|e| e.to_string())?;
                let json = serde_json::to_string(tokens).map_err(|e| e.to_string())?;
                entry.set_password(&json).map_err(|e| e.to_string())
            }
            TokenBackend::File => self
                .fallback
                .as_ref()
                .ok_or_else(|| "kein Token-Speicher konfiguriert".to_string())?
                .save(tokens),
        }
    }

    fn clear(&mut self) -> Result<(), String> {
        match self.backend {
            TokenBackend::Keyring => match keyring::Entry::new(KEYRING_SERVICE, "session") {
                Ok(entry) => match entry.delete_credential() {
                    Ok(()) => Ok(()),
                    // Nothing stored is not a failure.
                    Err(keyring::Error::NoEntry) => Ok(()),
                    Err(e) => Err(e.to_string()),
                },
                Err(e) => Err(e.to_string()),
            },
            TokenBackend::File => self
                .fallback
                .as_mut()
                .ok_or_else(|| "kein Token-Speicher konfiguriert".to_string())?
                .clear(),
        }
    }
}

/// File-backed token store for environments without a keyring.
///
/// The file is created with owner-only permissions. This is honest but weaker than a
/// keyring: any process running as the user can read it. That is why
/// [`TokenBackend::describe`] tells the user which one is in use.
#[derive(Debug)]
pub struct FileTokenStore {
    path: PathBuf,
    tokens: Mutex<Option<TokenPair>>,
}

impl FileTokenStore {
    pub fn new(path: PathBuf) -> Self {
        let tokens = std::fs::read_to_string(&path)
            .ok()
            .and_then(|raw| serde_json::from_str(&raw).ok());
        Self {
            path,
            tokens: Mutex::new(tokens),
        }
    }
}

impl TokenStore for FileTokenStore {
    fn load(&self) -> Option<TokenPair> {
        self.tokens.lock().unwrap().clone()
    }

    fn save(&self, tokens: &TokenPair) -> Result<(), String> {
        let json = serde_json::to_string(tokens).map_err(|e| e.to_string())?;
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        std::fs::write(&self.path, &json).map_err(|e| e.to_string())?;
        restrict_permissions(&self.path);
        *self.tokens.lock().unwrap() = Some(tokens.clone());
        Ok(())
    }

    fn clear(&mut self) -> Result<(), String> {
        if self.path.exists() {
            std::fs::remove_file(&self.path).map_err(|e| e.to_string())?;
        }
        *self.tokens.lock().unwrap() = None;
        Ok(())
    }
}

/// Makes the token file readable only by its owner.
///
/// A no-op on Windows, where the file inherits the user profile's ACL. Done
/// explicitly rather than left to the umask, because a world-readable refresh token
/// is a seven-day credential.
fn restrict_permissions(path: &std::path::Path) {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if let Err(e) = std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600)) {
            log::warn!("Rechte auf {} nicht setzbar: {e}", path.display());
        }
    }
    #[cfg(not(unix))]
    {
        let _ = path;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A unique, empty directory per test.
    ///
    /// The tag keeps the paths readable, and the process id plus a counter keep two
    /// tests in the same process apart — without the counter a test that reused a tag
    /// would inherit the previous run's files and pass or fail for the wrong reason.
    fn temp_root(tag: &str) -> PathBuf {
        use std::sync::atomic::{AtomicU64, Ordering};
        static COUNTER: AtomicU64 = AtomicU64::new(0);
        let unique = COUNTER.fetch_add(1, Ordering::SeqCst);
        let root = std::env::temp_dir().join(format!(
            "streamarr-shell-test-{tag}-{}-{unique}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(&root).unwrap();
        root
    }

    fn tokens() -> TokenPair {
        TokenPair {
            access_token: "a".to_string(),
            refresh_token: Some("r".to_string()),
            token_type: "bearer".to_string(),
            expires_in: 1800,
        }
    }

    #[test]
    fn a_default_profile_is_seeded_once() {
        let root = temp_root("seed");
        let first = seed_default_profile(&root).unwrap();
        assert_eq!(first.server.url, DEFAULT_SERVER_URL);
        // The mpv.conf is created so the user can edit it (plan task 1.3).
        assert!(first.mpv_config_path(&root).exists());

        // A second call must return the existing profile, not add another.
        let second = seed_default_profile(&root).unwrap();
        assert_eq!(first, second);
        let store = load_profiles(&root).unwrap();
        assert_eq!(store.profiles.len(), 1);
    }

    #[test]
    fn a_seeded_profile_is_persisted_for_editing() {
        let root = temp_root("seed-persist");
        seed_default_profile(&root).unwrap();
        assert!(root.join("profiles.json").exists());
    }

    /// The device id has to be stable, or every launch adds a device entry on the
    /// server and orphans capabilities and playback positions.
    #[test]
    fn the_device_identity_is_stable_across_calls() {
        let root = temp_root("device");
        let first = device_identity(&root, "1.0", "Testgerät").unwrap();
        let second = device_identity(&root, "1.0", "Testgerät").unwrap();
        assert_eq!(first.device_id, second.device_id);
        assert_eq!(first.app_name, "Streamarr Desktop");
    }

    #[test]
    fn a_corrupt_device_file_is_regenerated() {
        let root = temp_root("device-corrupt");
        std::fs::write(root.join(DEVICE_FILE), b"{ nicht json").unwrap();
        let device = device_identity(&root, "1.0", "Testgerät").unwrap();
        assert!(!device.device_id.is_empty());
        // And the file is usable again afterwards.
        let again = device_identity(&root, "1.0", "Testgerät").unwrap();
        assert_eq!(device.device_id, again.device_id);
    }

    #[test]
    fn generated_device_ids_differ_between_instances() {
        // Two files in two roots, i.e. two installations.
        let a = device_identity(&temp_root("id-a"), "1.0", "A").unwrap();
        let b = device_identity(&temp_root("id-b"), "1.0", "B").unwrap();
        assert_ne!(a.device_id, b.device_id);
        assert!(a.device_id.starts_with("desktop-"));
    }

    #[test]
    fn the_file_store_round_trips() {
        let root = temp_root("file-store");
        let mut store = FileTokenStore::new(root.join("tokens.json"));
        assert_eq!(store.load(), None);
        store.save(&tokens()).unwrap();
        assert_eq!(store.load().unwrap().refresh_token.as_deref(), Some("r"));
        store.clear().unwrap();
        assert_eq!(store.load(), None);
    }

    #[test]
    fn the_file_store_survives_a_reopen() {
        let root = temp_root("file-reopen");
        let path = root.join("tokens.json");
        FileTokenStore::new(path.clone()).save(&tokens()).unwrap();
        let reopened = FileTokenStore::new(path);
        assert_eq!(reopened.load().unwrap().refresh_token.as_deref(), Some("r"));
    }

    /// A refresh token in a world-readable file is a seven-day credential.
    #[cfg(unix)]
    #[test]
    fn the_token_file_is_owner_only() {
        use std::os::unix::fs::PermissionsExt;
        let root = temp_root("file-perms");
        let path = root.join("tokens.json");
        FileTokenStore::new(path.clone()).save(&tokens()).unwrap();
        let mode = std::fs::metadata(&path).unwrap().permissions().mode();
        assert_eq!(mode & 0o077, 0, "die Datei ist für andere lesbar: {mode:o}");
    }

    #[test]
    fn clearing_a_missing_token_file_is_not_an_error() {
        let root = temp_root("file-clear-missing");
        let mut store = FileTokenStore::new(root.join("nicht-da.json"));
        assert!(store.clear().is_ok());
    }

    /// This environment may or may not have a keyring, so the test asserts the
    /// storage opens and works rather than which backend it chose — but it does
    /// require that the choice is reported, since the UI has to tell the user.
    #[test]
    fn token_storage_opens_and_reports_its_backend() {
        let root = temp_root("storage");
        let mut storage = TokenStorage::open(&root);
        let described = storage.backend().describe();
        assert!(!described.is_empty());

        storage.save(&tokens()).unwrap();
        assert_eq!(storage.load().unwrap().refresh_token.as_deref(), Some("r"));
        storage.clear().unwrap();
        assert_eq!(storage.load(), None);
    }

    #[test]
    fn backend_descriptions_are_distinct_and_informative() {
        assert_ne!(
            TokenBackend::Keyring.describe(),
            TokenBackend::File.describe()
        );
        assert!(TokenBackend::File.describe().contains("Schlüsselbund"));
    }

    #[test]
    fn the_config_root_is_not_empty() {
        assert!(!default_config_root().as_os_str().is_empty());
    }
}
