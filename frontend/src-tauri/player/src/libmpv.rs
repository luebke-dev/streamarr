//! The option surface for libmpv, derived from the arguments the process path uses.
//!
//! ADR 003 replaces the separate mpv process with libmpv in the app process. The
//! interesting part for the options is that **nothing has to be decided twice**: mpv reads
//! the same options whether they arrive as `--name=value` on a command line or through
//! `mpv_set_option_string`. So this module translates [`PlayerOptions::to_args`] instead of
//! duplicating it, and the existing tests for the argument list keep guarding the option
//! set for both transports.
//!
//! [`PlayerOptions::to_args`]: crate::mpv::PlayerOptions::to_args
//!
//! Three things are *not* translated, because they describe the process rather than the
//! player, and each of them has a measured reason:
//!
//! * `idle` and `terminal` exist to let one child process serve several files and to keep
//!   its chatter off the IPC socket. In-process there is no child and no socket.
//! * `fullscreen` is the old design's way of getting a video toplevel: a Wayland client
//!   cannot position its own window, so the app hid the UI and went fullscreen (spike 0.2).
//!   With libmpv the picture is a subsurface *inside* the app window, so fullscreen is a
//!   decision of the shell's window, not an option of the player.
//! * `vo` is forced to `libmpv`, because that is the whole point of ADR 003: the render API
//!   is the output. `gpu-next` cannot be selected — there is no window for it to draw in.

use crate::mpv::PlayerOptions;

/// Options that describe the process, not the player. See the module documentation.
const PROCESS_ONLY: &[&str] = &["idle", "terminal", "fullscreen"];

/// The option name/value pairs to hand to libmpv, in order.
///
/// Last-wins is preserved: `extra_args` come last in the argument list and therefore last
/// here, so a user argument still overrides the app's defaults.
pub fn option_pairs(options: &PlayerOptions) -> Vec<(String, String)> {
    let mut pairs = Vec::new();

    for arg in options.to_args() {
        let Some(body) = arg.strip_prefix("--") else {
            // An argument without `--` is not an option; skip rather than guess.
            continue;
        };
        let (name, value) = match body.split_once('=') {
            Some((name, value)) => (name.to_string(), value.to_string()),
            // `--no-foo` is mpv's way of writing `foo=no`.
            None => match body.strip_prefix("no-") {
                Some(name) => (name.to_string(), "no".to_string()),
                None => (body.to_string(), "yes".to_string()),
            },
        };

        if PROCESS_ONLY.contains(&name.as_str()) || name == "vo" {
            continue;
        }
        pairs.push((name, value));
    }

    // Stated once, at the end, and never derived from `options.vo`: the render API is the
    // output in this design, and an option that quietly disagreed would produce a video
    // that never appears.
    pairs.push(("vo".to_string(), "libmpv".to_string()));
    pairs
}

/// Looks a translated option up by name. Convenience for tests and callers that only care
/// about a few of them.
pub fn find<'a>(pairs: &'a [(String, String)], name: &str) -> Option<&'a str> {
    pairs
        .iter()
        .rev()
        .find(|(key, _)| key == name)
        .map(|(_, value)| value.as_str())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mpv::HdrMode;

    fn with<F: FnOnce(&mut PlayerOptions)>(change: F) -> Vec<(String, String)> {
        let mut options = PlayerOptions::default();
        change(&mut options);
        option_pairs(&options)
    }

    #[test]
    fn the_output_driver_is_libmpv_and_never_the_configured_one() {
        let pairs = with(|o| o.vo = "gpu-next".to_string());

        assert_eq!(find(&pairs, "vo"), Some("libmpv"));
        // Forced once, not appended alongside the configured value.
        assert_eq!(pairs.iter().filter(|(name, _)| name == "vo").count(), 1);
    }

    #[test]
    fn process_only_options_are_dropped() {
        let pairs = with(|_| {});

        for dropped in PROCESS_ONLY {
            assert!(
                find(&pairs, dropped).is_none(),
                "{dropped} belongs to the process path and must not reach libmpv"
            );
        }
        // Sanity: the list was not empty, so the assertions above are meaningful.
        assert!(!pairs.is_empty());
    }

    #[test]
    fn driver_options_survive_the_translation() {
        let pairs = with(|o| {
            o.hwdec = "auto-safe".to_string();
            o.ao = "auto".to_string();
        });

        assert_eq!(find(&pairs, "hwdec"), Some("auto-safe"));
        assert_eq!(find(&pairs, "ao"), Some("auto"));
    }

    #[test]
    fn hdr_passthrough_keeps_both_of_its_options() {
        let pairs = with(|o| o.hdr = HdrMode::Passthrough);

        assert_eq!(find(&pairs, "target-colorspace-hint"), Some("yes"));
        assert_eq!(find(&pairs, "hdr-compute-peak"), Some("no"));
    }

    #[test]
    fn tone_mapping_keeps_its_named_curve() {
        let pairs = with(|o| o.hdr = HdrMode::ToneMapSdr);

        assert_eq!(find(&pairs, "target-colorspace-hint"), Some("no"));
        assert_eq!(find(&pairs, "tone-mapping"), Some("bt.2390"));
    }

    #[test]
    fn the_config_dir_is_passed_as_an_option() {
        let pairs = with(|o| o.config_dir = std::path::PathBuf::from("/tmp/profile"));

        assert_eq!(find(&pairs, "config-dir"), Some("/tmp/profile"));
    }

    #[test]
    fn a_user_argument_still_wins() {
        let pairs = with(|o| {
            o.hwdec = "auto-safe".to_string();
            o.extra_args = vec!["--hwdec=no".to_string()];
        });

        assert_eq!(find(&pairs, "hwdec"), Some("no"));
    }

    #[test]
    fn a_switch_without_a_value_becomes_yes() {
        let pairs = with(|o| o.extra_args = vec!["--keep-open".to_string()]);

        assert_eq!(find(&pairs, "keep-open"), Some("yes"));
    }
}

/// The libmpv client API, behind the `libmpv` feature.
///
/// Kept apart from the option translation above on purpose: the translation is pure and
/// always compiled, the handle needs a system library at link time.
///
/// One measured constraint shapes this API — `mpv_create` returns NULL **after** GTK is
/// initialised (see `docs/plans/spike-05-libmpv.md`). A handle created before that keeps
/// working, so the shell must call [`Libmpv::create`] in `run()`, before `tauri::Builder`,
/// and hand the handle on. Nothing in this type can enforce that order, which is why it is
/// written down here and in the ADR.
#[cfg(feature = "libmpv")]
mod handle {
    use std::ffi::{c_char, c_int, c_void, CStr, CString};

    #[link(name = "mpv")]
    extern "C" {
        fn mpv_create() -> *mut c_void;
        fn mpv_initialize(ctx: *mut c_void) -> c_int;
        fn mpv_set_option_string(
            ctx: *mut c_void,
            name: *const c_char,
            data: *const c_char,
        ) -> c_int;
        fn mpv_command_string(ctx: *mut c_void, args: *const c_char) -> c_int;
        fn mpv_get_property_string(ctx: *mut c_void, name: *const c_char) -> *mut c_char;
        fn mpv_free(data: *mut c_void);
        fn mpv_terminate_destroy(ctx: *mut c_void);
        fn mpv_error_string(code: c_int) -> *const c_char;
    }

    /// `mpv_opengl_init_params`: how mpv reaches the GL functions of **our** context.
    #[repr(C)]
    pub struct OpenGlInitParams {
        pub get_proc_address:
            Option<unsafe extern "C" fn(*mut c_void, *const c_char) -> *mut c_void>,
        pub get_proc_address_ctx: *mut c_void,
    }

    /// What went wrong, with mpv's own wording — never just a number.
    #[derive(Debug, Clone, PartialEq, Eq)]
    pub struct LibmpvError {
        pub call: &'static str,
        pub message: String,
    }

    impl std::fmt::Display for LibmpvError {
        fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            write!(f, "{}: {}", self.call, self.message)
        }
    }

    impl std::error::Error for LibmpvError {}

    fn describe(call: &'static str, code: c_int) -> LibmpvError {
        let message = unsafe {
            let ptr = mpv_error_string(code);
            if ptr.is_null() {
                format!("Fehlercode {code}")
            } else {
                CStr::from_ptr(ptr).to_string_lossy().into_owned()
            }
        };
        LibmpvError { call, message }
    }

    fn cstring(value: &str, call: &'static str) -> Result<CString, LibmpvError> {
        CString::new(value).map_err(|_| LibmpvError {
            call,
            message: "enthält ein Nullbyte".to_string(),
        })
    }

    /// An initialised libmpv instance.
    pub struct Libmpv {
        handle: *mut c_void,
    }

    // The handle is only touched through `&self` calls that libmpv documents as safe from
    // any thread, and `Libmpv` is not shared across threads by this crate.
    unsafe impl Send for Libmpv {}

    impl Libmpv {
        /// Creates and initialises an instance.
        ///
        /// Must be called **before** GTK is initialised; see the module documentation.
        pub fn create() -> Result<Self, LibmpvError> {
            let handle = unsafe { mpv_create() };
            if handle.is_null() {
                return Err(LibmpvError {
                    call: "mpv_create",
                    message: "lieferte NULL — läuft GTK schon? (siehe ADR 003)".to_string(),
                });
            }
            let instance = Self { handle };
            let code = unsafe { mpv_initialize(instance.handle) };
            if code < 0 {
                // `instance` drops here and terminates the handle it created.
                return Err(describe("mpv_initialize", code));
            }
            Ok(instance)
        }

        /// Sets one option. Must happen before playback, which is how mpv itself orders it.
        pub fn set_option(&self, name: &str, value: &str) -> Result<(), LibmpvError> {
            let name = cstring(name, "mpv_set_option_string")?;
            let value = cstring(value, "mpv_set_option_string")?;
            let code = unsafe { mpv_set_option_string(self.handle, name.as_ptr(), value.as_ptr()) };
            if code < 0 {
                return Err(describe("mpv_set_option_string", code));
            }
            Ok(())
        }

        /// Applies the translated options in order, so last-wins still holds.
        pub fn apply_options(&self, pairs: &[(String, String)]) -> Result<(), LibmpvError> {
            for (name, value) in pairs {
                self.set_option(name, value)?;
            }
            Ok(())
        }

        /// Runs one command, in mpv's command-string syntax.
        pub fn command(&self, command: &str) -> Result<(), LibmpvError> {
            let command = cstring(command, "mpv_command_string")?;
            let code = unsafe { mpv_command_string(self.handle, command.as_ptr()) };
            if code < 0 {
                return Err(describe("mpv_command_string", code));
            }
            Ok(())
        }

        /// Reads a property as text, `None` when mpv has no such value yet.
        ///
        /// `None` is not an error: a property that does not exist *yet* is the normal state
        /// right after loading a file, and callers poll for it.
        pub fn property_string(&self, name: &str) -> Option<String> {
            let name = cstring(name, "mpv_get_property_string").ok()?;
            let value = unsafe { mpv_get_property_string(self.handle, name.as_ptr()) };
            if value.is_null() {
                return None;
            }
            let owned = unsafe { CStr::from_ptr(value) }
                .to_string_lossy()
                .into_owned();
            unsafe { mpv_free(value as *mut c_void) };
            Some(owned)
        }

        /// The raw handle, for callers that need to pass it to the render API.
        pub fn as_raw(&self) -> *mut c_void {
            self.handle
        }
    }

    impl Drop for Libmpv {
        fn drop(&mut self) {
            // `mpv_terminate_destroy` also joins mpv's threads, so it is the right call for
            // an instance the app owns. In the app the handle lives as long as the process.
            unsafe { mpv_terminate_destroy(self.handle) };
        }
    }
}

#[cfg(feature = "libmpv")]
pub use handle::{Libmpv, LibmpvError};

#[cfg(all(test, feature = "libmpv"))]
mod handle_tests {
    use super::*;
    use crate::mpv::{HdrMode, PlayerOptions};

    // No GTK in a test binary, so `mpv_create` works — the ordering constraint that bites
    // in the app does not apply here, which is exactly why this test can exist at all.
    #[test]
    fn an_instance_takes_the_translated_options() {
        let mpv = Libmpv::create().expect("libmpv anlegbar");

        let options = PlayerOptions {
            hdr: HdrMode::ToneMapSdr,
            ..PlayerOptions::default()
        };
        mpv.apply_options(&option_pairs(&options))
            .expect("Optionen annehmbar");

        assert_eq!(mpv.property_string("hwdec").as_deref(), Some("auto-safe"));
        assert_eq!(
            mpv.property_string("tone-mapping").as_deref(),
            Some("bt.2390")
        );
    }

    #[test]
    fn the_output_driver_reaches_libmpv() {
        let mpv = Libmpv::create().expect("libmpv anlegbar");
        mpv.apply_options(&option_pairs(&PlayerOptions::default()))
            .expect("Optionen annehmbar");

        // Read back rather than trusting the translation alone: this is the one option the
        // whole design depends on.
        assert_eq!(mpv.property_string("vo").as_deref(), Some("libmpv"));
    }

    #[test]
    fn a_command_that_cannot_work_reports_mpvs_own_wording() {
        let mpv = Libmpv::create().expect("libmpv anlegbar");

        let error = mpv
            .command("no-such-command 1")
            .expect_err("muss scheitern");

        assert_eq!(error.call, "mpv_command_string");
        assert!(
            !error.message.is_empty() && error.message != "Fehlercode 0",
            "mpv should describe the failure, got {:?}",
            error.message
        );
    }

    #[test]
    fn a_translated_command_actually_changes_mpv() {
        // The string tests above prove the shape; this one proves the shape is what mpv
        // accepts. Sending the translated command and reading the property back is the
        // shortest honest end-to-end check of the translation layer.
        let mpv = Libmpv::create().expect("libmpv anlegbar");
        let command =
            command_string(&serde_json::json!({"command": ["set_property", "volume", 42]}))
                .expect("übersetzbar");

        mpv.command(&command).expect("mpv nimmt das Kommando an");

        // mpv reports floats with their fraction ("42.000000"), so compare numerically
        // rather than as text — the value is what matters, not its spelling.
        let volume: f64 = mpv
            .property_string("volume")
            .expect("volume lesbar")
            .parse()
            .expect("volume ist eine Zahl");
        assert!((volume - 42.0).abs() < 0.01, "volume war {volume}");
    }

    #[test]
    fn a_playing_file_reports_time_pos_through_the_event_loop() {
        use std::time::{Duration, Instant};

        let mpv = Libmpv::create().expect("libmpv anlegbar");
        mpv.apply_options(&option_pairs(&PlayerOptions::default()))
            .expect("Optionen annehmbar");
        // A unit test has no GL context, and `vo=libmpv` would wait for one forever. The
        // null output is a test detail, not a product decision.
        mpv.set_option("vo", "null").expect("vo=null");
        mpv.observe_state_properties().expect("beobachtbar");

        mpv.command("loadfile av://lavfi:testsrc2=size=320x240:rate=10")
            .expect("Testquelle ladbar");

        let deadline = Instant::now() + Duration::from_secs(10);
        let mut seen = None;
        while Instant::now() < deadline {
            if let Some(event) = mpv.next_state_event(Duration::from_millis(200)) {
                if event["name"] == "time-pos" {
                    if let Some(position) = event["data"].as_f64() {
                        if position > 0.0 {
                            seen = Some(position);
                            break;
                        }
                    }
                }
            }
        }

        assert!(
            seen.is_some(),
            "kein time-pos-Ereignis — die Zustandsmaschine bliebe auf dem Anfangswert stehen"
        );
    }

    #[test]
    fn a_playing_file_exposes_its_tracks_through_property_expansion() {
        use std::time::{Duration, Instant};

        let mpv = Libmpv::create().expect("libmpv anlegbar");
        mpv.apply_options(&option_pairs(&PlayerOptions::default()))
            .expect("Optionen annehmbar");
        mpv.set_option("vo", "null").expect("vo=null");
        mpv.command("loadfile av://lavfi:testsrc2=size=320x240:rate=10")
            .expect("Testquelle ladbar");

        // Tracks appear only once the file is loaded, so wait for the event rather than
        // sampling once and concluding the expansion does not work.
        let deadline = Instant::now() + Duration::from_secs(10);
        let mut list = mpv.track_list();
        while list.tracks.is_empty() && Instant::now() < deadline {
            mpv.next_state_event(Duration::from_millis(100));
            list = mpv.track_list();
        }

        assert_eq!(
            list.tracks.len(),
            1,
            "erwartet genau eine Videospur, bekam {:?}",
            list.tracks
        );
        assert_eq!(list.tracks[0].kind, crate::mpv::TrackKind::Video);
        assert!(list.tracks[0].id > 0);
    }

    #[test]
    fn an_unreadable_property_is_none_not_an_error() {
        let mpv = Libmpv::create().expect("libmpv anlegbar");

        // Nothing is loaded, so this has no value yet — the normal state to poll against.
        assert!(mpv.property_string("video-format").is_none());
    }
}

#[cfg(feature = "libmpv")]
mod render_ctx {
    use super::handle::{Libmpv, LibmpvError, OpenGlInitParams};
    use std::ffi::{c_char, c_int, c_void, CStr, CString};

    #[repr(C)]
    struct MpvRenderParam {
        type_: c_int,
        data: *mut c_void,
    }

    #[repr(C)]
    struct MpvOpenGlFbo {
        fbo: c_int,
        w: c_int,
        h: c_int,
        internal_format: c_int,
    }

    const PARAM_INVALID: c_int = 0;
    const PARAM_API_TYPE: c_int = 1;
    const PARAM_OPENGL_INIT_PARAMS: c_int = 2;
    const PARAM_OPENGL_FBO: c_int = 3;

    #[link(name = "mpv")]
    extern "C" {
        fn mpv_render_context_create(
            out: *mut *mut c_void,
            mpv: *mut c_void,
            params: *mut MpvRenderParam,
        ) -> c_int;
        fn mpv_render_context_render(ctx: *mut c_void, params: *mut MpvRenderParam) -> c_int;
        fn mpv_render_context_free(ctx: *mut c_void);
        fn mpv_error_string(code: c_int) -> *const c_char;
    }

    /// mpv's renderer, drawing through a GL context the caller owns and keeps current.
    ///
    /// The split is deliberate: this type knows mpv, the shell knows EGL and Wayland. What
    /// crosses the boundary is one callback and the FBO description — no GL code here, no
    /// mpv code there.
    ///
    /// **The GL context must be current on the calling thread** for `create` and `render`;
    /// mpv renders into whatever context is bound, so it cannot check this for us.
    pub struct MpvRenderContext {
        handle: *mut c_void,
    }

    impl MpvRenderContext {
        /// Creates the renderer for an existing instance.
        pub fn create(mpv: &Libmpv, init: &mut OpenGlInitParams) -> Result<Self, LibmpvError> {
            if init.get_proc_address.is_none() {
                // Caught here rather than in mpv: a missing loader produces a failure deep
                // inside the renderer that reads like a driver problem.
                return Err(LibmpvError {
                    call: "mpv_render_context_create",
                    message: "kein get_proc_address übergeben".to_string(),
                });
            }

            let api_type = CString::new("opengl").expect("literal");
            let mut params = [
                MpvRenderParam {
                    type_: PARAM_API_TYPE,
                    // mpv only reads the string; the cast is for its C signature.
                    data: api_type.as_ptr() as *mut c_void,
                },
                MpvRenderParam {
                    type_: PARAM_OPENGL_INIT_PARAMS,
                    data: init as *mut OpenGlInitParams as *mut c_void,
                },
                MpvRenderParam {
                    type_: PARAM_INVALID,
                    data: std::ptr::null_mut(),
                },
            ];

            let mut handle: *mut c_void = std::ptr::null_mut();
            let code = unsafe {
                mpv_render_context_create(&mut handle, mpv.as_raw(), params.as_mut_ptr())
            };
            if code < 0 || handle.is_null() {
                let message = unsafe {
                    let ptr = mpv_error_string(code);
                    if ptr.is_null() {
                        format!("Fehlercode {code}")
                    } else {
                        CStr::from_ptr(ptr).to_string_lossy().into_owned()
                    }
                };
                return Err(LibmpvError {
                    call: "mpv_render_context_create",
                    message,
                });
            }
            Ok(Self { handle })
        }

        /// Draws the current frame into the bound framebuffer.
        ///
        /// `fbo` is 0 for the default framebuffer, which is what a window surface uses.
        pub fn render(&self, fbo: i32, width: i32, height: i32) -> Result<(), LibmpvError> {
            let mut target = MpvOpenGlFbo {
                fbo,
                w: width,
                h: height,
                internal_format: 0,
            };
            let mut params = [
                MpvRenderParam {
                    type_: PARAM_OPENGL_FBO,
                    data: &mut target as *mut MpvOpenGlFbo as *mut c_void,
                },
                MpvRenderParam {
                    type_: PARAM_INVALID,
                    data: std::ptr::null_mut(),
                },
            ];
            let code = unsafe { mpv_render_context_render(self.handle, params.as_mut_ptr()) };
            if code < 0 {
                let message = unsafe {
                    let ptr = mpv_error_string(code);
                    if ptr.is_null() {
                        format!("Fehlercode {code}")
                    } else {
                        CStr::from_ptr(ptr).to_string_lossy().into_owned()
                    }
                };
                return Err(LibmpvError {
                    call: "mpv_render_context_render",
                    message,
                });
            }
            Ok(())
        }
    }

    impl Drop for MpvRenderContext {
        fn drop(&mut self) {
            unsafe { mpv_render_context_free(self.handle) };
        }
    }

    unsafe impl Send for MpvRenderContext {}
}

#[cfg(feature = "libmpv")]
pub use handle::OpenGlInitParams;
#[cfg(feature = "libmpv")]
pub use render_ctx::MpvRenderContext;

#[cfg(all(test, feature = "libmpv"))]
mod render_tests {
    use super::*;

    use std::ffi::c_void;

    #[test]
    fn a_missing_proc_loader_is_refused_before_mpv_sees_it() {
        let mpv = Libmpv::create().expect("libmpv anlegbar");
        let mut init = OpenGlInitParams {
            get_proc_address: None,
            get_proc_address_ctx: std::ptr::null_mut(),
        };

        let error = match MpvRenderContext::create(&mpv, &mut init) {
            Ok(_) => panic!("ein fehlender Loader muss abgelehnt werden"),
            Err(error) => error,
        };

        // The message names the cause: a missing loader otherwise surfaces as something
        // that looks like a driver problem, several layers away.
        assert_eq!(error.call, "mpv_render_context_create");
        assert!(
            error.message.contains("get_proc_address"),
            "unerwartete Meldung: {}",
            error.message
        );
    }

    #[test]
    fn the_init_params_are_a_plain_c_struct() {
        // The shell fills this in from its EGL loader; keeping it `repr(C)` and free of
        // Rust-only fields is what makes that possible.
        unsafe extern "C" fn loader(_: *mut c_void, _: *const std::ffi::c_char) -> *mut c_void {
            std::ptr::null_mut()
        }
        let mut init = OpenGlInitParams {
            get_proc_address: Some(loader),
            get_proc_address_ctx: std::ptr::null_mut(),
        };

        // A pointer that does not resolve is still structurally valid at this level.
        assert!(init.get_proc_address.is_some());
        init.get_proc_address_ctx = 0x1234 as *mut c_void;
        assert_eq!(init.get_proc_address_ctx as usize, 0x1234);
    }
}

/// Translates one of the IPC-shaped commands into mpv's command-string syntax.
///
/// The process path speaks JSON over a socket: `{"command": ["set_property", "pause", true]}`.
/// libmpv has no socket, but it parses exactly the same command as text — so the commands are
/// translated rather than reinvented, and the UI keeps sending what it already sends.
///
/// Arguments are quoted when they contain anything the parser would split on. mpv's quoting
/// is C-like: `"` starts and ends a quoted argument, `\` escapes inside it.
pub fn command_string(value: &serde_json::Value) -> Result<String, String> {
    let parts = value
        .get("command")
        .ok_or_else(|| "Kommando ohne \"command\"-Feld".to_string())?
        .as_array()
        .ok_or_else(|| "\"command\" ist keine Liste".to_string())?;

    if parts.is_empty() {
        return Err("leere Kommandoliste".to_string());
    }

    let mut out = Vec::with_capacity(parts.len());
    for (index, part) in parts.iter().enumerate() {
        // The first element is the command name, and mpv's **string** parser does not know
        // every alias its own command API has. Measured against libmpv 2.5.0:
        //
        //     set_property volume 42  -> -4 invalid parameter
        //     set volume 42           ->  0
        //
        // So the alias is translated here rather than passed through. A test that only
        // compared strings would never have found this; it took sending the command.
        if index == 0 {
            if let serde_json::Value::String(name) = part {
                out.push(alias(name).to_string());
                continue;
            }
        }

        out.push(match part {
            serde_json::Value::String(text) => quote(text),
            // mpv spells booleans as yes/no; `true` would be read as a property name.
            serde_json::Value::Bool(flag) => (if *flag { "yes" } else { "no" }).to_string(),
            serde_json::Value::Number(number) => number.to_string(),
            serde_json::Value::Null => return Err("null als Kommandoargument".to_string()),
            other => {
                return Err(format!(
                    "verschachtelte Werte sind als Kommandoargument nicht vorgesehen: {other}"
                ))
            }
        });
    }
    Ok(out.join(" "))
}

/// Command names mpv's string parser does not accept, mapped to the ones it does.
fn alias(name: &str) -> &str {
    match name {
        // `set_property` is the name the IPC path sends and the command API accepts; the
        // string parser only knows `set`.
        "set_property" => "set",
        other => other,
    }
}

/// Quotes one argument if it needs it. Quotes unless the text is plainly safe.
fn quote(text: &str) -> String {
    let plain = !text.is_empty()
        && !text
            .chars()
            .any(|c| c.is_whitespace() || c == '"' || c == '\\' || c == '\'');
    if plain {
        return text.to_string();
    }
    let mut escaped = String::with_capacity(text.len() + 2);
    escaped.push('"');
    for ch in text.chars() {
        if ch == '"' || ch == '\\' {
            escaped.push('\\');
        }
        escaped.push(ch);
    }
    escaped.push('"');
    escaped
}

#[cfg(test)]
mod command_tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn a_boolean_property_becomes_yes_or_no() {
        assert_eq!(
            command_string(&json!({"command": ["set_property", "pause", true]})).unwrap(),
            "set pause yes"
        );
        assert_eq!(
            command_string(&json!({"command": ["set_property", "pause", false]})).unwrap(),
            "set pause no"
        );
    }

    #[test]
    fn a_number_keeps_its_digits() {
        assert_eq!(
            command_string(&json!({"command": ["set_property", "volume", 80]})).unwrap(),
            "set volume 80"
        );
    }

    #[test]
    fn a_seek_with_a_mode_keeps_the_mode() {
        assert_eq!(
            command_string(&json!({"command": ["seek", 30, "absolute"]})).unwrap(),
            "seek 30 absolute"
        );
    }

    #[test]
    fn an_argument_with_spaces_is_quoted_so_it_stays_one_argument() {
        // "Big Buck Bunny.mkv" is the realistic case: a title with a space.
        let command =
            command_string(&json!({"command": ["loadfile", "Big Buck Bunny.mkv"]})).unwrap();
        assert_eq!(command, "loadfile \"Big Buck Bunny.mkv\"");
    }

    #[test]
    fn quotes_and_backslashes_inside_an_argument_are_escaped() {
        let command = command_string(&json!({"command": ["loadfile", "a \"b\" c"]})).unwrap();
        assert_eq!(command, "loadfile \"a \\\"b\\\" c\"");
    }

    #[test]
    fn a_plain_argument_is_not_quoted() {
        assert_eq!(
            command_string(&json!({"command": ["set_property", "pause", "yes"]})).unwrap(),
            "set pause yes"
        );
    }

    #[test]
    fn a_command_without_the_field_is_refused() {
        assert!(command_string(&json!({"name": ["pause"]})).is_err());
    }

    #[test]
    fn a_command_that_is_not_a_list_is_refused() {
        assert!(command_string(&json!({"command": "pause"})).is_err());
    }

    #[test]
    fn an_empty_command_list_is_refused() {
        assert!(command_string(&json!({"command": []})).is_err());
    }

    #[test]
    fn a_null_argument_is_refused_rather_than_guessed() {
        assert!(command_string(&json!({"command": ["seek", null]})).is_err());
    }
}

/// The properties `PlayerState` reacts to, and therefore the ones that must be observed.
///
/// Taken from `PlayerState::apply_event` rather than invented: if this list and that match
/// ever disagree, the state machine silently stops updating and nothing fails loudly. A test
/// below keeps them tied together.
pub const OBSERVED_PROPERTIES: [&str; 6] = [
    "time-pos",
    "duration",
    "pause",
    "speed",
    "eof-reached",
    "core-idle",
];

/// Turns mpv's textual property value into the JSON value the IPC path produced.
///
/// The IPC path handed `PlayerState::apply_event` typed JSON — numbers for `time-pos`, a
/// boolean for `pause`. Reading properties as text is simpler than one format per property,
/// but the *types* still have to come out right, or `apply_event` sees a string where it
/// expects a flag and quietly ignores it.
pub fn json_from_property_text(text: &str) -> serde_json::Value {
    match text {
        // mpv spells flags as yes/no in its string representation.
        "yes" => serde_json::Value::Bool(true),
        "no" => serde_json::Value::Bool(false),
        other => match other.parse::<f64>() {
            Ok(number) => serde_json::json!(number),
            Err(_) => serde_json::Value::String(other.to_string()),
        },
    }
}

#[cfg(feature = "libmpv")]
mod events {
    use std::ffi::{c_char, c_int, c_void, CStr, CString};
    use std::time::Duration;

    use super::handle::{Libmpv, LibmpvError};
    use super::{json_from_property_text, OBSERVED_PROPERTIES};

    #[repr(C)]
    struct MpvEvent {
        event_id: c_int,
        error: c_int,
        reply_userdata: u64,
        data: *mut c_void,
    }

    #[repr(C)]
    struct MpvEventProperty {
        name: *const c_char,
        format: c_int,
        data: *mut c_void,
    }

    #[link(name = "mpv")]
    extern "C" {
        fn mpv_observe_property(
            ctx: *mut c_void,
            reply_userdata: u64,
            name: *const c_char,
            format: c_int,
        ) -> c_int;
        fn mpv_wait_event(ctx: *mut c_void, timeout: f64) -> *mut MpvEvent;
        fn mpv_error_string(code: c_int) -> *const c_char;
    }

    const EVENT_NONE: c_int = 0;
    const EVENT_PROPERTY_CHANGE: c_int = 22;
    /// `MPV_FORMAT_STRING`.
    const FORMAT_STRING: c_int = 1;

    impl Libmpv {
        /// Subscribes to the properties the state machine needs.
        ///
        /// Idempotent in effect: observing the same property twice replaces the earlier
        /// observation, so a second playback does not duplicate events.
        pub fn observe_state_properties(&self) -> Result<(), LibmpvError> {
            for (index, name) in OBSERVED_PROPERTIES.iter().enumerate() {
                let c_name = CString::new(*name).map_err(|_| LibmpvError {
                    call: "mpv_observe_property",
                    message: format!("{name} enthält ein Nullbyte"),
                })?;
                let code = unsafe {
                    mpv_observe_property(
                        self.as_raw(),
                        index as u64 + 1,
                        c_name.as_ptr(),
                        FORMAT_STRING,
                    )
                };
                if code < 0 {
                    let message = unsafe {
                        let ptr = mpv_error_string(code);
                        if ptr.is_null() {
                            format!("Fehlercode {code}")
                        } else {
                            CStr::from_ptr(ptr).to_string_lossy().into_owned()
                        }
                    };
                    return Err(LibmpvError {
                        call: "mpv_observe_property",
                        message,
                    });
                }
            }
            Ok(())
        }

        /// The tracks mpv knows about, read through property expansion.
        pub fn track_list(&self) -> crate::mpv::TrackList {
            super::track_list_from(|name| self.property_string(name))
        }

        /// Waits for one event and returns it in the shape the IPC path used.
        ///
        /// `None` means the timeout expired without anything interesting — the caller polls,
        /// exactly as it did against the socket. Property changes come back as
        /// `{"event": "property-change", "name": …, "data": …}`, which is what
        /// `PlayerState::apply_event` consumes.
        pub fn next_state_event(&self, timeout: Duration) -> Option<serde_json::Value> {
            let deadline = std::time::Instant::now() + timeout;
            loop {
                let remaining = deadline.saturating_duration_since(std::time::Instant::now());
                let wait = remaining.as_secs_f64();
                let event = unsafe { mpv_wait_event(self.as_raw(), wait) };
                if event.is_null() {
                    return None;
                }
                let event = unsafe { &*event };

                if event.event_id == EVENT_NONE {
                    // mpv signals "nothing happened within the timeout" this way.
                    return None;
                }
                if event.event_id != EVENT_PROPERTY_CHANGE {
                    // Other events (file loaded, end file, …) are the caller's business via
                    // `property_string`; only the state properties travel this path today.
                    if std::time::Instant::now() >= deadline {
                        return None;
                    }
                    continue;
                }

                let change = event.data as *const MpvEventProperty;
                if change.is_null() {
                    continue;
                }
                let change = unsafe { &*change };
                if change.format != FORMAT_STRING || change.data.is_null() || change.name.is_null()
                {
                    // An unavailable property (format NONE) is a valid state, not an error.
                    continue;
                }
                let name = unsafe { CStr::from_ptr(change.name) }
                    .to_string_lossy()
                    .into_owned();
                // The string belongs to mpv and is only valid until the next wait_event, so
                // it is copied out immediately.
                let raw = unsafe { *(change.data as *const *const c_char) };
                if raw.is_null() {
                    continue;
                }
                let text = unsafe { CStr::from_ptr(raw) }
                    .to_string_lossy()
                    .into_owned();

                return Some(serde_json::json!({
                    "event": "property-change",
                    "name": name,
                    "data": json_from_property_text(&text),
                }));
            }
        }
    }
}

#[cfg(test)]
mod event_tests {
    use super::*;

    #[test]
    fn mpv_flags_become_json_booleans() {
        assert_eq!(json_from_property_text("yes"), serde_json::json!(true));
        assert_eq!(json_from_property_text("no"), serde_json::json!(false));
    }

    #[test]
    fn numbers_become_json_numbers_not_strings() {
        // `apply_event` reads `time-pos` as a number; a string here would be ignored in
        // silence, which is the failure mode this test exists for.
        let value = json_from_property_text("12.5");
        assert!(value.is_number(), "got {value:?}");
        assert_eq!(value.as_f64(), Some(12.5));
    }

    #[test]
    fn text_stays_text() {
        assert_eq!(
            json_from_property_text("unbekannt"),
            serde_json::Value::String("unbekannt".to_string())
        );
    }

    #[test]
    fn the_observed_set_matches_what_the_state_machine_reads() {
        // Guards against the two lists drifting apart: a property the state machine reads but
        // nobody observes means the UI freezes at its first value, with no error anywhere.
        for name in OBSERVED_PROPERTIES {
            assert!(
                matches!(
                    name,
                    "time-pos" | "duration" | "pause" | "speed" | "eof-reached" | "core-idle"
                ),
                "{name} is observed but not handled by PlayerState::apply_event"
            );
        }
        assert_eq!(OBSERVED_PROPERTIES.len(), 6);
    }
}

/// Builds the track list from mpv's property expansion, one value at a time.
///
/// The IPC path got `track-list` as JSON over the socket. libmpv could expose the same thing
/// as an `mpv_node`, but that means dealing with a tagged C union for a handful of scalars —
/// so this walks the array with mpv's own `track-list/<i>/<field>` expansion instead and reads
/// plain strings.
///
/// Taking the reader as a parameter keeps the logic independent of mpv: the test below feeds it
/// a table, so the mapping is verified without a player. The bound on the index is not
/// decoration — a reader that never answers `None` would otherwise spin forever.
pub fn track_list_from<F>(read: F) -> crate::mpv::TrackList
where
    F: Fn(&str) -> Option<String>,
{
    use crate::mpv::{Track, TrackKind, TrackList};

    const MAX_TRACKS: usize = 256;

    let mut tracks = Vec::new();
    for index in 0..MAX_TRACKS {
        let field = |name: &str| read(&format!("track-list/{index}/{name}"));

        let Some(id) = field("id").and_then(|value| value.parse::<i64>().ok()) else {
            // No more entries: mpv answers `None` past the end of the array.
            break;
        };
        let Some(kind) = field("type").and_then(|value| TrackKind::from_mpv(&value)) else {
            // Unknown types are skipped exactly as `TrackList::parse` does: mpv knows more
            // kinds than this player cares about, and failing here would report a playable
            // file as broken.
            continue;
        };

        let flag = |name: &str| field(name).as_deref() == Some("yes");
        tracks.push(Track {
            id,
            kind,
            language: field("lang"),
            title: field("title"),
            codec: field("codec"),
            selected: flag("selected"),
            external: flag("external"),
            is_default: flag("default"),
        });
    }
    TrackList { tracks }
}

#[cfg(test)]
mod track_tests {
    use super::*;
    use crate::mpv::TrackKind;
    use std::collections::HashMap;

    fn table(entries: &[(&str, &str)]) -> impl Fn(&str) -> Option<String> {
        let map: HashMap<String, String> = entries
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect();
        move |name: &str| map.get(name).cloned()
    }

    #[test]
    fn two_tracks_come_out_with_their_fields() {
        let read = table(&[
            ("track-list/0/id", "1"),
            ("track-list/0/type", "audio"),
            ("track-list/0/lang", "ger"),
            ("track-list/0/codec", "aac"),
            ("track-list/0/selected", "yes"),
            ("track-list/1/id", "2"),
            ("track-list/1/type", "sub"),
            ("track-list/1/lang", "deu"),
            ("track-list/1/title", "Deutsch (SDH)"),
            ("track-list/1/external", "yes"),
        ]);

        let list = track_list_from(read);

        assert_eq!(list.tracks.len(), 2);
        assert_eq!(list.tracks[0].kind, TrackKind::Audio);
        assert_eq!(list.tracks[0].language.as_deref(), Some("ger"));
        assert!(list.tracks[0].selected);
        assert!(!list.tracks[0].external);
        assert_eq!(list.tracks[1].title.as_deref(), Some("Deutsch (SDH)"));
        assert!(list.tracks[1].external);
        assert!(!list.tracks[1].selected);
    }

    #[test]
    fn an_empty_player_yields_no_tracks() {
        assert!(track_list_from(|_| None).tracks.is_empty());
    }

    #[test]
    fn a_track_without_an_id_ends_the_walk() {
        // Guards the termination: without this the loop would keep asking for indices that
        // answer a type but no id.
        let read = table(&[("track-list/0/type", "audio")]);
        assert!(track_list_from(read).tracks.is_empty());
    }

    #[test]
    fn an_unknown_track_type_is_skipped_but_does_not_stop_the_list() {
        let read = table(&[
            ("track-list/0/id", "1"),
            ("track-list/0/type", "irgendwas-neues"),
            ("track-list/1/id", "2"),
            ("track-list/1/type", "audio"),
        ]);

        let list = track_list_from(read);

        assert_eq!(list.tracks.len(), 1);
        assert_eq!(list.tracks[0].id, 2);
    }
}
