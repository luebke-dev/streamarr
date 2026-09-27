//! Native media and game-streaming core for the Streamarr desktop app.
//!
//! This crate is intentionally shell-agnostic: it must not depend on Tauri,
//! GTK, Electron or any other UI toolkit. A shell (see
//! `docs/plans/adr-001-desktop-shell.md`) owns the window and the web UI; this
//! crate owns the native playback paths behind a narrow command surface.
//!
//! Two playback paths exist, mirroring the two references chosen for the
//! desktop app:
//!
//! * **Games** — WebRTC against the Lightrays server, decoded locally through
//!   GStreamer. Modelled on moonlight-qt's approach of decoding on the client
//!   instead of leaving it to a webview.
//! * **Media** — mpv, either as a child process or through libmpv. Modelled on
//!   Jellyfin Desktop, which wraps standalone mpv rather than using the
//!   restricted libmpv render API.
//!
//! The wire protocol shared with Lightrays lives in [`protocol`] and is tested
//! without any of those dependencies. Reading physical gamepads lives in
//! [`input`], behind the `gamepad` feature because it needs `libudev`.

pub mod capabilities;
pub mod mpv;
pub mod playback;
pub mod profile;
pub mod protocol;
pub mod session;

/// Reading physical gamepads and translating them into the wire format.
///
/// Feature-gated: `gilrs` needs `libudev` on Linux, and this crate must stay
/// buildable with no system dependencies so the wire-contract golden tests can
/// run anywhere.
#[cfg(feature = "gamepad")]
pub mod input;

/// Version of the player core, reported to the shell and to the server as the
/// client `app_version`.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");
