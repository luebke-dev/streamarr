//! IPC commands — the only surface the web UI may touch.
//!
//! Plan task 1.2: the main window gets **no** direct player or filesystem
//! permissions, only `invoke` commands. The commands here are therefore the complete
//! attack surface from the WebView's point of view, which is why each one takes
//! explicit arguments and returns data rather than accepting a path or a command to
//! run.
//!
//! Two rules are enforced by the signatures, not by discipline:
//!
//! * **No free-form filesystem access.** A command that needs a file takes a
//!   *profile id*, never a path, and resolves the path itself from the configured
//!   root. A path parameter would hand the WebView the whole filesystem.
//! * **No token leaves this process.** Tokens are stored and used here; the UI only
//!   ever learns *whether* a session exists. Sending a refresh token into the WebView
//!   would defeat the point of the keyring.

pub mod bridge;
pub mod profiles;
pub mod session;
