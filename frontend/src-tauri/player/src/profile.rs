//! Profiles: which server, which user, which local settings.
//!
//! Plan task 1.3. A profile is the unit a user switches between — "home server as
//! me", "test server as the test account" — and it owns everything that differs
//! between them: the server address, the display name, and local preferences such
//! as the mpv configuration file.
//!
//! # Why the storage root is a parameter
//!
//! This crate must not know about Tauri or GTK (ADR 001), and it must not guess
//! platform directories either: the shell owns that decision and passes a root in.
//! Everything here is then plain file I/O against that root, which is also what
//! makes it testable without a running app.
//!
//! # Why the server address is a first-class field
//!
//! Spike 0.1 found that `streamarr.luebke.internal` resolves to a Tailscale
//! address that does not answer, while the real endpoint is reachable on the
//! VLAN address — the reason `curl` needs `--resolve`. A desktop app cannot rely
//! on the system resolver being right, so the address is configurable and can be
//! pinned to an IP while still sending the correct `Host` and SNI.

use std::fmt;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

/// File name of the profile index inside the storage root.
pub const PROFILES_FILE: &str = "profiles.json";

/// Name of the per-profile mpv configuration file (plan task 1.3).
pub const MPV_CONFIG_FILE: &str = "mpv.conf";

/// The default server address, used when a profile has none.
pub const DEFAULT_SERVER_URL: &str = "https://streamarr.luebke.internal";

/// A server address, optionally pinned to an IP address.
///
/// The address is kept apart from the pin on purpose: a pin only changes where
/// the TCP connection goes. The hostname still goes into the `Host` header and
/// into TLS SNI, which is what makes the certificate validate. Collapsing the two
/// into one field would either break TLS or lose the name the server needs.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ServerAddress {
    /// Base URL including scheme, e.g. `https://streamarr.luebke.internal`.
    pub url: String,
    /// Optional `ip:port` override, mirroring `curl --resolve`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub resolve_override: Option<String>,
}

impl Default for ServerAddress {
    fn default() -> Self {
        Self {
            url: DEFAULT_SERVER_URL.to_string(),
            resolve_override: None,
        }
    }
}

impl ServerAddress {
    pub fn new(url: impl Into<String>) -> Self {
        Self {
            url: url.into(),
            resolve_override: None,
        }
    }

    /// Returns the hostname, or `None` if the URL has no host.
    pub fn host(&self) -> Option<&str> {
        split_url(&self.url).map(|parts| parts.host)
    }

    /// Returns the port, defaulting by scheme.
    pub fn port(&self) -> Option<u16> {
        split_url(&self.url).map(|parts| parts.port)
    }

    /// Whether the address is usable at all.
    ///
    /// Checked before saving so a typo surfaces in the settings dialog rather than
    /// as a failed login later. Deliberately permissive otherwise: a self-hosted
    /// server may use any host, port or subdomain.
    pub fn validate(&self) -> Result<(), ProfileError> {
        let Some(parts) = split_url(&self.url) else {
            return Err(ProfileError::InvalidServerUrl(self.url.clone()));
        };
        if parts.scheme != "http" && parts.scheme != "https" {
            return Err(ProfileError::InvalidServerUrl(self.url.clone()));
        }
        if parts.host.is_empty() {
            return Err(ProfileError::InvalidServerUrl(self.url.clone()));
        }
        if let Some(pin) = &self.resolve_override {
            if parse_pin(pin).is_none() {
                return Err(ProfileError::InvalidResolveOverride(pin.clone()));
            }
        }
        Ok(())
    }

    /// The normalised base URL, without a trailing slash.
    pub fn base_url(&self) -> String {
        self.url.trim_end_matches('/').to_string()
    }

    /// The `--resolve` pair as `host:port:ip`, for the HTTP and WebSocket layers.
    ///
    /// `None` when no pin is set, i.e. normal DNS is to be used.
    pub fn resolve_pair(&self) -> Option<String> {
        let pin = self.resolve_override.as_ref()?;
        let (ip, port) = parse_pin(pin)?;
        let host = self.host()?;
        Some(format!("{host}:{port}:{ip}"))
    }
}

/// Pieces of a base URL. Hand-parsed rather than pulled from a URL crate: the
/// accepted shape is tiny, and a dependency for this would be out of proportion
/// in a crate that is deliberately dependency-light.
struct UrlParts<'a> {
    scheme: &'a str,
    host: &'a str,
    port: u16,
}

fn split_url(url: &str) -> Option<UrlParts<'_>> {
    let (scheme, rest) = url.split_once("://")?;
    // Strip any path; a profile stores a base, not a route.
    let authority = rest.split('/').next()?;
    if authority.is_empty() {
        return None;
    }
    // Userinfo is not supported and must not be mistaken for a host.
    if authority.contains('@') {
        return None;
    }
    let default_port = match scheme {
        "https" => 443,
        "http" => 80,
        _ => return None,
    };
    // IPv6 literals are bracketed: [::1]:8443
    let (host, port) = if let Some(stripped) = authority.strip_prefix('[') {
        let (host, tail) = stripped.split_once(']')?;
        let port = match tail.strip_prefix(':') {
            Some(p) => p.parse().ok()?,
            None => default_port,
        };
        (host, port)
    } else {
        match authority.split_once(':') {
            Some((host, port)) => (host, port.parse().ok()?),
            None => (authority, default_port),
        }
    };
    Some(UrlParts { scheme, host, port })
}

/// Parses an `ip:port` pin, accepting a bare IP with an implied default port.
fn parse_pin(pin: &str) -> Option<(String, u16)> {
    let pin = pin.trim();
    let (ip, port) = match pin.rsplit_once(':') {
        Some((ip, port)) => (ip, port.parse().ok()?),
        None => (pin, 443),
    };
    if ip.is_empty() {
        return None;
    }
    Some((ip.to_string(), port))
}

/// One user's settings for one server.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Profile {
    /// Stable identifier, used as the directory name.
    pub id: String,
    /// Shown in the profile switcher.
    pub name: String,
    pub server: ServerAddress,
    /// Server-side user identifier once logged in.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub user_guid: Option<String>,
    /// Email or display name, for the UI only.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub user_label: Option<String>,
    /// Playback preferences that are not part of mpv.conf.
    #[serde(default)]
    pub preferences: Preferences,
}

/// Local playback preferences for a profile.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Preferences {
    /// Start playback in fullscreen. Default on, because the window integration
    /// from spike 0.2 uses fullscreen as the primary mode.
    pub fullscreen_on_play: bool,
    /// Ask before transcoding instead of direct-playing.
    ///
    /// Default on: a transcode costs the server a lot more than a direct play, and
    /// silently starting one is how a weak server gets into trouble.
    pub confirm_transcode: bool,
    /// Default audio language, as an ISO 639-1/2 code. `None` means "let mpv and
    /// the file decide".
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub audio_language: Option<String>,
    /// Default subtitle language. `None` means "no subtitles unless embedded".
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub subtitle_language: Option<String>,
}

impl Default for Preferences {
    fn default() -> Self {
        Self {
            fullscreen_on_play: true,
            confirm_transcode: true,
            audio_language: None,
            subtitle_language: None,
        }
    }
}

impl Profile {
    /// A new profile for a server.
    pub fn new(id: impl Into<String>, name: impl Into<String>, server: ServerAddress) -> Self {
        Self {
            id: id.into(),
            name: name.into(),
            server,
            user_guid: None,
            user_label: None,
            preferences: Preferences::default(),
        }
    }

    /// Directory-safe identifier check.
    ///
    /// The id becomes a path component, so anything that could escape the storage
    /// root — separators, `..`, absolute paths — has to be rejected. Checking here
    /// means the rest of the module can join paths without worrying.
    pub fn validate(&self) -> Result<(), ProfileError> {
        if !is_safe_id(&self.id) {
            return Err(ProfileError::UnsafeId(self.id.clone()));
        }
        if self.name.trim().is_empty() {
            return Err(ProfileError::EmptyName);
        }
        self.server.validate()
    }

    /// `<root>/profiles/<id>`
    pub fn directory(&self, root: &Path) -> PathBuf {
        root.join("profiles").join(&self.id)
    }

    /// `<root>/profiles/<id>/mpv.conf`, editable by the user (plan task 1.3).
    pub fn mpv_config_path(&self, root: &Path) -> PathBuf {
        self.directory(root).join(MPV_CONFIG_FILE)
    }
}

/// Identifiers that are safe to use as a single path component.
fn is_safe_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 64
        && id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
        // `.` and `..` are already excluded by the character rule, but being
        // explicit documents the intent and survives a future rule relaxation.
        && id != "."
        && id != ".."
}

/// Everything the app needs to know about the user's profiles.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ProfileStore {
    /// Schema version, so a future format change can be migrated rather than
    /// silently misinterpreted.
    pub version: u32,
    pub profiles: Vec<Profile>,
    /// Which profile is active.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub active_id: Option<String>,
}

/// Current on-disk schema version.
pub const STORE_VERSION: u32 = 1;

impl Default for ProfileStore {
    fn default() -> Self {
        Self {
            version: STORE_VERSION,
            profiles: Vec::new(),
            active_id: None,
        }
    }
}

/// What can go wrong with profiles.
#[derive(Debug, Clone, PartialEq)]
pub enum ProfileError {
    InvalidServerUrl(String),
    InvalidResolveOverride(String),
    UnsafeId(String),
    EmptyName,
    DuplicateId(String),
    NotFound(String),
    /// The file exists but cannot be understood.
    Corrupt(String),
    Io(String),
}

impl fmt::Display for ProfileError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidServerUrl(url) => {
                write!(f, "`{url}` ist keine gültige Server-Adresse")
            }
            Self::InvalidResolveOverride(pin) => {
                write!(f, "`{pin}` ist keine gültige IP-Angabe (erwartet ip:port)")
            }
            Self::UnsafeId(id) => write!(f, "`{id}` ist keine gültige Profil-Kennung"),
            Self::EmptyName => write!(f, "Der Profilname darf nicht leer sein"),
            Self::DuplicateId(id) => {
                write!(f, "Ein Profil mit der Kennung `{id}` existiert bereits")
            }
            Self::NotFound(id) => write!(f, "Profil `{id}` wurde nicht gefunden"),
            Self::Corrupt(detail) => write!(f, "Die Profildatei ist beschädigt: {detail}"),
            Self::Io(detail) => write!(f, "Dateifehler: {detail}"),
        }
    }
}

impl std::error::Error for ProfileError {}

impl ProfileStore {
    pub fn load(root: &Path) -> Result<Self, ProfileError> {
        let path = root.join(PROFILES_FILE);
        let raw = match std::fs::read_to_string(&path) {
            Ok(raw) => raw,
            // A missing file is the normal first-run case, not an error.
            Err(err) if err.kind() == std::io::ErrorKind::NotFound => return Ok(Self::default()),
            Err(err) => return Err(ProfileError::Io(err.to_string())),
        };
        let store: Self =
            serde_json::from_str(&raw).map_err(|err| ProfileError::Corrupt(err.to_string()))?;
        if store.version > STORE_VERSION {
            // Refusing beats guessing: a newer file may mean fields this build
            // would drop on the next save.
            return Err(ProfileError::Corrupt(format!(
                "Profilformat-Version {} ist neuer als die unterstützte ({STORE_VERSION})",
                store.version
            )));
        }
        Ok(store)
    }

    /// Writes the store, replacing the file atomically.
    ///
    /// Written to a temporary file and renamed, so an interrupted save cannot
    /// leave a half-written file that would then fail to parse — which would look
    /// like data loss to the user.
    pub fn save(&self, root: &Path) -> Result<(), ProfileError> {
        std::fs::create_dir_all(root).map_err(|e| ProfileError::Io(e.to_string()))?;
        let path = root.join(PROFILES_FILE);
        let tmp = root.join(format!("{PROFILES_FILE}.tmp"));
        let json =
            serde_json::to_string_pretty(self).map_err(|e| ProfileError::Corrupt(e.to_string()))?;
        std::fs::write(&tmp, json).map_err(|e| ProfileError::Io(e.to_string()))?;
        std::fs::rename(&tmp, &path).map_err(|e| ProfileError::Io(e.to_string()))?;
        Ok(())
    }

    /// Adds a profile, rejecting duplicates and invalid data.
    pub fn add(&mut self, profile: Profile) -> Result<(), ProfileError> {
        profile.validate()?;
        if self.profiles.iter().any(|p| p.id == profile.id) {
            return Err(ProfileError::DuplicateId(profile.id));
        }
        // The first profile becomes active, so a fresh install needs no extra step.
        if self.active_id.is_none() {
            self.active_id = Some(profile.id.clone());
        }
        self.profiles.push(profile);
        Ok(())
    }

    /// Removes a profile and repairs the active selection.
    pub fn remove(&mut self, id: &str) -> Result<Profile, ProfileError> {
        let index = self
            .profiles
            .iter()
            .position(|p| p.id == id)
            .ok_or_else(|| ProfileError::NotFound(id.to_string()))?;
        let removed = self.profiles.remove(index);
        if self.active_id.as_deref() == Some(id) {
            // Falling back to the first remaining profile beats leaving an active
            // id that points at nothing.
            self.active_id = self.profiles.first().map(|p| p.id.clone());
        }
        Ok(removed)
    }

    /// Selects a profile, if it exists.
    pub fn set_active(&mut self, id: &str) -> Result<(), ProfileError> {
        if !self.profiles.iter().any(|p| p.id == id) {
            return Err(ProfileError::NotFound(id.to_string()));
        }
        self.active_id = Some(id.to_string());
        Ok(())
    }

    pub fn active(&self) -> Option<&Profile> {
        let id = self.active_id.as_ref()?;
        self.profiles.iter().find(|p| &p.id == id)
    }

    pub fn get(&self, id: &str) -> Option<&Profile> {
        self.profiles.iter().find(|p| p.id == id)
    }

    /// The active profile, or an error explaining that none is selected.
    ///
    /// Callers that need a profile should not have to handle `None` by inventing a
    /// fallback server, which is how a request ends up at the wrong host.
    pub fn require_active(&self) -> Result<&Profile, ProfileError> {
        self.active().ok_or_else(|| {
            ProfileError::NotFound(self.active_id.clone().unwrap_or_else(|| "—".to_string()))
        })
    }

    /// Ensures the per-profile directory and mpv.conf exist.
    ///
    /// Creates an empty `mpv.conf` rather than a prefilled one: mpv reads it as the
    /// user's own configuration (plan task 1.3), and seeding options would make the
    /// app's defaults look like the user's choices.
    pub fn ensure_profile_files(&self, root: &Path, id: &str) -> Result<PathBuf, ProfileError> {
        let profile = self
            .get(id)
            .ok_or_else(|| ProfileError::NotFound(id.to_string()))?;
        let dir = profile.directory(root);
        std::fs::create_dir_all(&dir).map_err(|e| ProfileError::Io(e.to_string()))?;
        let config = dir.join(MPV_CONFIG_FILE);
        if !config.exists() {
            std::fs::write(&config, b"").map_err(|e| ProfileError::Io(e.to_string()))?;
        }
        Ok(config)
    }
}

/// Suggests a filesystem-safe profile id from a name.
///
/// Kept here rather than in the UI so both shells produce the same ids for the
/// same input — otherwise a profile created on Windows would not be found on
/// Linux.
pub fn suggest_id(name: &str) -> String {
    let mut out = String::with_capacity(name.len());
    let mut last_dash = false;
    for ch in name.chars() {
        if ch.is_ascii_alphanumeric() {
            out.push(ch.to_ascii_lowercase());
            last_dash = false;
        } else if !last_dash && !out.is_empty() {
            out.push('-');
            last_dash = true;
        }
    }
    let trimmed = out.trim_end_matches('-').to_string();
    if trimmed.is_empty() {
        "profil".to_string()
    } else {
        trimmed
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_root(tag: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!(
            "streamarr-profile-test-{tag}-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(&root).unwrap();
        root
    }

    // ── Server address parsing ──

    #[test]
    fn parses_a_plain_https_url() {
        let addr = ServerAddress::new("https://streamarr.luebke.internal");
        assert_eq!(addr.host(), Some("streamarr.luebke.internal"));
        assert_eq!(addr.port(), Some(443));
        assert!(addr.validate().is_ok());
    }

    #[test]
    fn https_defaults_to_443_and_http_to_80() {
        assert_eq!(ServerAddress::new("https://host").port(), Some(443));
        assert_eq!(ServerAddress::new("http://host").port(), Some(80));
    }

    #[test]
    fn explicit_ports_are_respected() {
        assert_eq!(ServerAddress::new("https://host:8443").port(), Some(8443));
        assert_eq!(ServerAddress::new("http://host:8080").port(), Some(8080));
    }

    #[test]
    fn paths_are_stripped_from_the_base_url() {
        let addr = ServerAddress::new("https://host/api/");
        assert_eq!(addr.host(), Some("host"));
        assert_eq!(addr.base_url(), "https://host/api");
    }

    #[test]
    fn ipv6_literals_are_parsed() {
        let addr = ServerAddress::new("https://[fd00::1]:8443");
        assert_eq!(addr.host(), Some("fd00::1"));
        assert_eq!(addr.port(), Some(8443));
        assert!(addr.validate().is_ok());
    }

    #[test]
    fn invalid_urls_are_rejected() {
        for bad in [
            "",
            "streamarr.luebke.internal", // no scheme
            "ftp://host",                // wrong scheme
            "https://",                  // no host
            "https://user:pw@host",      // userinfo is not supported
            "https://host:notaport",     // bad port
        ] {
            let addr = ServerAddress::new(bad);
            assert!(
                addr.validate().is_err(),
                "`{bad}` should be rejected, got {addr:?}"
            );
        }
    }

    // ── The resolve pin, which exists because of the split-DNS finding ──

    #[test]
    fn no_pin_means_normal_dns() {
        let addr = ServerAddress::new("https://streamarr.luebke.internal");
        assert_eq!(addr.resolve_pair(), None);
    }

    /// The whole point of the pin: connect to a specific IP while keeping the
    /// hostname, so `Host` and TLS SNI stay correct and the certificate validates.
    #[test]
    fn pin_produces_a_resolve_pair_with_the_original_host() {
        let mut addr = ServerAddress::new("https://streamarr.luebke.internal");
        addr.resolve_override = Some("10.10.60.30:443".to_string());
        assert_eq!(
            addr.resolve_pair(),
            Some("streamarr.luebke.internal:443:10.10.60.30".to_string())
        );
        assert_eq!(addr.host(), Some("streamarr.luebke.internal"));
    }

    #[test]
    fn pin_without_a_port_defaults_to_443() {
        let mut addr = ServerAddress::new("https://host");
        addr.resolve_override = Some("10.0.0.5".to_string());
        assert_eq!(addr.resolve_pair(), Some("host:443:10.0.0.5".to_string()));
    }

    #[test]
    fn malformed_pins_are_rejected() {
        for bad in ["", ":", "10.0.0.1:", ":443"] {
            let mut addr = ServerAddress::new("https://host");
            addr.resolve_override = Some(bad.to_string());
            assert!(addr.validate().is_err(), "`{bad}` should be rejected");
        }
    }

    // ── Profile ids ──

    #[test]
    fn suggested_ids_are_filesystem_safe() {
        assert_eq!(suggest_id("Mein Server"), "mein-server");
        assert_eq!(
            suggest_id("streamarr.luebke.internal"),
            "streamarr-luebke-internal"
        );
        assert_eq!(suggest_id("  Test  "), "test");
        assert_eq!(suggest_id("a/b\\c"), "a-b-c");
        assert_eq!(suggest_id(""), "profil");
        assert_eq!(suggest_id("///"), "profil");
    }

    #[test]
    fn suggested_ids_never_contain_separators_or_dots() {
        for name in ["../etc/passwd", "..", ".", "C:\\Windows", "a/../../b"] {
            let id = suggest_id(name);
            assert!(!id.contains('/'), "{id} contains a separator");
            assert!(!id.contains('\\'), "{id} contains a separator");
            assert_ne!(id, "..");
            assert!(!id.is_empty());
        }
    }

    /// The id becomes a path component, so traversal has to be rejected.
    #[test]
    fn unsafe_ids_are_rejected() {
        for bad in ["../escape", "a/b", "", "..", ".", "with space", "a\\b"] {
            let profile = Profile::new(bad, "Name", ServerAddress::default());
            assert!(
                profile.validate().is_err(),
                "`{bad}` should not be a valid id"
            );
        }
    }

    #[test]
    fn safe_ids_are_accepted() {
        for good in ["home", "test-server", "server_2", "A1"] {
            let profile = Profile::new(good, "Name", ServerAddress::default());
            assert!(profile.validate().is_ok(), "`{good}` should be valid");
        }
    }

    #[test]
    fn empty_names_are_rejected() {
        let mut profile = Profile::new("id", "Name", ServerAddress::default());
        profile.name = "   ".to_string();
        assert_eq!(profile.validate(), Err(ProfileError::EmptyName));
    }

    // ── Paths ──

    #[test]
    fn profile_paths_live_under_the_root() {
        let root = Path::new("/data");
        let profile = Profile::new("home", "Home", ServerAddress::default());
        assert_eq!(profile.directory(root), Path::new("/data/profiles/home"));
        assert_eq!(
            profile.mpv_config_path(root),
            Path::new("/data/profiles/home/mpv.conf")
        );
    }

    // ── Store behaviour ──

    #[test]
    fn a_missing_file_is_an_empty_store_not_an_error() {
        let root = temp_root("missing");
        let store = ProfileStore::load(&root).unwrap();
        assert!(store.profiles.is_empty());
        assert_eq!(store.active_id, None);
    }

    #[test]
    fn store_round_trips_through_a_file() {
        let root = temp_root("roundtrip");
        let mut store = ProfileStore::default();
        let mut profile =
            Profile::new("home", "Zuhause", ServerAddress::new("https://example.org"));
        profile.user_guid = Some("abc-123".to_string());
        profile.preferences.fullscreen_on_play = false;
        store.add(profile).unwrap();
        store.save(&root).unwrap();

        let loaded = ProfileStore::load(&root).unwrap();
        assert_eq!(loaded, store);
        assert_eq!(loaded.active_id.as_deref(), Some("home"));
        assert_eq!(loaded.active().unwrap().name, "Zuhause");
        assert_eq!(
            loaded.active().unwrap().user_guid.as_deref(),
            Some("abc-123")
        );
        assert!(!loaded.active().unwrap().preferences.fullscreen_on_play);
    }

    #[test]
    fn save_leaves_no_temporary_file_behind() {
        let root = temp_root("tmp-cleanup");
        let store = ProfileStore::default();
        store.save(&root).unwrap();
        assert!(!root.join(format!("{PROFILES_FILE}.tmp")).exists());
    }

    /// A corrupt file must be reported, not silently replaced: the user may have
    /// hand-edited it, and overwriting would destroy their profiles.
    #[test]
    fn a_corrupt_file_is_reported() {
        let root = temp_root("corrupt");
        std::fs::write(root.join(PROFILES_FILE), b"{ this is not json").unwrap();
        assert!(matches!(
            ProfileStore::load(&root),
            Err(ProfileError::Corrupt(_))
        ));
    }

    /// A file from a newer build may contain fields this build would drop on save.
    #[test]
    fn a_newer_schema_version_is_refused() {
        let root = temp_root("future");
        let json = format!(r#"{{"version":{},"profiles":[]}}"#, STORE_VERSION + 1);
        std::fs::write(root.join(PROFILES_FILE), json).unwrap();
        assert!(matches!(
            ProfileStore::load(&root),
            Err(ProfileError::Corrupt(_))
        ));
    }

    #[test]
    fn the_first_profile_becomes_active() {
        let mut store = ProfileStore::default();
        store
            .add(Profile::new("a", "A", ServerAddress::default()))
            .unwrap();
        assert_eq!(store.active_id.as_deref(), Some("a"));

        store
            .add(Profile::new("b", "B", ServerAddress::default()))
            .unwrap();
        assert_eq!(
            store.active_id.as_deref(),
            Some("a"),
            "adding must not steal the active selection"
        );
    }

    #[test]
    fn duplicate_ids_are_rejected() {
        let mut store = ProfileStore::default();
        store
            .add(Profile::new("a", "A", ServerAddress::default()))
            .unwrap();
        assert_eq!(
            store.add(Profile::new("a", "A2", ServerAddress::default())),
            Err(ProfileError::DuplicateId("a".to_string()))
        );
    }

    #[test]
    fn invalid_profiles_are_rejected_on_add() {
        let mut store = ProfileStore::default();
        assert!(store
            .add(Profile::new("../escape", "X", ServerAddress::default()))
            .is_err());
        assert!(store
            .add(Profile::new("ok", "X", ServerAddress::new("nonsense")))
            .is_err());
        assert!(store.profiles.is_empty());
    }

    /// Removing the active profile must not leave a dangling selection.
    #[test]
    fn removing_the_active_profile_selects_another() {
        let mut store = ProfileStore::default();
        store
            .add(Profile::new("a", "A", ServerAddress::default()))
            .unwrap();
        store
            .add(Profile::new("b", "B", ServerAddress::default()))
            .unwrap();
        store.set_active("b").unwrap();

        store.remove("b").unwrap();
        assert_eq!(store.active_id.as_deref(), Some("a"));

        store.remove("a").unwrap();
        assert_eq!(store.active_id, None, "no profiles left, no active id");
    }

    #[test]
    fn removing_a_missing_profile_is_an_error() {
        let mut store = ProfileStore::default();
        assert_eq!(
            store.remove("nope"),
            Err(ProfileError::NotFound("nope".to_string()))
        );
    }

    #[test]
    fn activating_a_missing_profile_is_an_error() {
        let mut store = ProfileStore::default();
        assert!(store.set_active("nope").is_err());
    }

    /// Callers that need a profile get an error rather than a default, so a
    /// request cannot silently go to the wrong server.
    #[test]
    fn require_active_fails_without_profiles() {
        let store = ProfileStore::default();
        assert!(matches!(
            store.require_active(),
            Err(ProfileError::NotFound(_))
        ));
    }

    // ── Files per profile ──

    #[test]
    fn ensure_profile_files_creates_an_empty_mpv_conf() {
        let root = temp_root("files");
        let mut store = ProfileStore::default();
        store
            .add(Profile::new("home", "Home", ServerAddress::default()))
            .unwrap();

        let config = store.ensure_profile_files(&root, "home").unwrap();
        assert!(config.exists());
        assert_eq!(
            std::fs::read_to_string(&config).unwrap(),
            "",
            "the file must be empty so its contents are the user's own choices"
        );

        // The user's edits must survive a second call.
        std::fs::write(&config, "vo=gpu-next\n").unwrap();
        store.ensure_profile_files(&root, "home").unwrap();
        assert_eq!(std::fs::read_to_string(&config).unwrap(), "vo=gpu-next\n");
    }

    #[test]
    fn ensure_profile_files_rejects_unknown_profiles() {
        let root = temp_root("files-unknown");
        let store = ProfileStore::default();
        assert!(store.ensure_profile_files(&root, "nope").is_err());
    }

    // ── Preferences defaults ──

    /// Fullscreen is the primary playback mode after spike 0.2, so it is on by
    /// default; and a transcode should be confirmed, because it costs the server
    /// far more than a direct play.
    #[test]
    fn sensible_defaults() {
        let prefs = Preferences::default();
        assert!(prefs.fullscreen_on_play);
        assert!(prefs.confirm_transcode);
        assert_eq!(prefs.audio_language, None);
        assert_eq!(prefs.subtitle_language, None);
    }

    #[test]
    fn preferences_default_is_used_when_the_file_omits_them() {
        let root = temp_root("prefs-default");
        // A file written by an older build, without the preferences block.
        let json = r#"{"version":1,"profiles":[{"id":"a","name":"A",
            "server":{"url":"https://host"}}],"active_id":"a"}"#;
        std::fs::write(root.join(PROFILES_FILE), json).unwrap();
        let store = ProfileStore::load(&root).unwrap();
        assert_eq!(store.active().unwrap().preferences, Preferences::default());
    }

    #[test]
    fn errors_are_explained_in_german() {
        for err in [
            ProfileError::InvalidServerUrl("x".into()),
            ProfileError::InvalidResolveOverride("y".into()),
            ProfileError::UnsafeId("z".into()),
            ProfileError::EmptyName,
            ProfileError::DuplicateId("d".into()),
            ProfileError::NotFound("n".into()),
            ProfileError::Corrupt("c".into()),
            ProfileError::Io("i".into()),
        ] {
            assert!(!err.to_string().is_empty());
            // The message must not leak the enum shape to the user.
            assert!(!err.to_string().contains("ProfileError"));
        }
    }
}
