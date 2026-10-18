//! Wire protocol shared with the Lightrays streaming server.
//!
//! Every message here is derived from the server implementation, not from
//! documentation, because there is no schema on the wire — it is ad-hoc JSON
//! on a WebSocket and a WebRTC data channel:
//!
//! * signalling (`offer`, `ice`, `container_died`, `pipeline_error`) and the
//!   client→server messages (`answer`, `ice`, `resize`) come from
//!   `lightrays/src/server.rs` (`handle_ws_upgrade`).
//! * `input` messages come from `lightrays/src/input.rs` (the `"key"`,
//!   `"mousemove"`, `"mouseabs"`, `"mousebutton"`, `"wheel"` arms) and
//!   `lightrays/src/gamepad.rs` (`"gamepadbutton"`, `"gamepadaxis"`).
//!
//! Keeping this module free of GStreamer and of any GUI shell means the
//! contract can be unit-tested in milliseconds and cannot drift silently: the
//! tests in `tests/wire_contract.rs` pin the exact field names the server
//! reads.

use serde::{Deserialize, Serialize};

/// Subprotocol name the client must request, plus the session ticket as the
/// second protocol. See `lightrays/src/server.rs`.
pub const WS_SUBPROTOCOL: &str = "lightrays";

/// Name of the WebRTC data channel that carries input.
pub const INPUT_CHANNEL_LABEL: &str = "input";

// ---------------------------------------------------------------------------
// Server → client
// ---------------------------------------------------------------------------

/// A message received from the Lightrays signalling WebSocket.
#[derive(Debug, Clone, PartialEq)]
pub enum ServerMessage {
    /// Initial SDP offer; the client answers it.
    Offer { sdp: String },
    /// Trickled ICE candidate.
    Ice { candidate: String, mline_index: u32 },
    /// The per-session container exited. The stream is over.
    ContainerDied { exit_code: Option<i64> },
    /// The GStreamer pipeline failed server-side.
    PipelineError,
    /// The server reported an error in a JSON field.
    Error { message: String },
}

impl ServerMessage {
    /// Parse a signalling frame. Unknown or malformed frames yield `None`
    /// rather than an error: the server may grow new message types, and a
    /// client that hard-fails on them would break on a server update.
    pub fn parse(raw: &str) -> Option<Self> {
        let value: serde_json::Value = serde_json::from_str(raw).ok()?;

        // An explicit `error` field is checked first: the server uses it for
        // failures that carry no `type` of their own.
        if let Some(message) = value.get("error").and_then(|v| v.as_str()) {
            return Some(Self::Error {
                message: message.to_string(),
            });
        }

        match value.get("type").and_then(|v| v.as_str())? {
            "offer" => Some(Self::Offer {
                sdp: value.get("sdp").and_then(|v| v.as_str())?.to_string(),
            }),
            "ice" => Some(Self::Ice {
                candidate: value
                    .get("candidate")
                    .and_then(|v| v.as_str())
                    .unwrap_or_default()
                    .to_string(),
                // The server emits `sdpMLineIndex` (camelCase) — see server.rs.
                mline_index: value
                    .get("sdpMLineIndex")
                    .and_then(|v| v.as_u64())
                    .unwrap_or(0) as u32,
            }),
            "container_died" => Some(Self::ContainerDied {
                exit_code: value.get("exit_code").and_then(|v| v.as_i64()),
            }),
            "pipeline_error" => Some(Self::PipelineError),
            _ => None,
        }
    }
}

// ---------------------------------------------------------------------------
// Client → server (signalling socket)
// ---------------------------------------------------------------------------

/// Messages sent over the signalling WebSocket.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum ClientMessage {
    /// SDP answer to the server's offer.
    Answer { sdp: String },
    /// Trickled ICE candidate. `sdpMLineIndex` must keep its camelCase name.
    Ice {
        candidate: String,
        #[serde(rename = "sdpMLineIndex")]
        mline_index: u32,
    },
    /// Request a server-side resize. Rebuilds the whole WebRTC pipeline, so
    /// callers debounce it.
    Resize { width: u32, height: u32 },
}

impl ClientMessage {
    pub fn to_json(&self) -> String {
        serde_json::to_string(self).expect("client message serialisation is infallible")
    }
}

// ---------------------------------------------------------------------------
// Input (sent over the WebRTC data channel, or fallback: signalling socket)
// ---------------------------------------------------------------------------

/// A browser-style key code, e.g. `KeyA`, `ArrowLeft`, `ShiftLeft`.
///
/// The server maps these through `js_code_to_linux`; sending a Linux scancode
/// instead would be silently dropped.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct KeyCode(pub String);

impl KeyCode {
    pub fn new(code: impl Into<String>) -> Self {
        Self(code.into())
    }
}

/// Input events, in exactly the shape `lightrays/src/input.rs` consumes.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum InputMessage {
    /// Absolute pointer position in *client* pixels; the server scales it to
    /// the compositor's coordinate space.
    MouseAbs {
        x: f64,
        y: f64,
        w: f64,
        h: f64,
    },
    /// Relative pointer movement, used while the pointer is locked.
    MouseMove {
        dx: f64,
        dy: f64,
    },
    MouseButton {
        button: u32,
        pressed: bool,
    },
    Wheel {
        dx: f64,
        dy: f64,
    },
    Key {
        code: String,
        pressed: bool,
    },
    GamepadButton {
        index: u32,
        pressed: bool,
    },
    GamepadAxis {
        stick: u32,
        axis: u32,
        value: f64,
    },
}

impl InputMessage {
    pub fn key(code: KeyCode, pressed: bool) -> Self {
        Self::Key {
            code: code.0,
            pressed,
        }
    }

    pub fn gamepad_button(index: u32, pressed: bool) -> Self {
        Self::GamepadButton { index, pressed }
    }

    pub fn gamepad_axis(stick: u32, axis: u32, value: f64) -> Self {
        Self::GamepadAxis { stick, axis, value }
    }

    pub fn to_json(&self) -> String {
        serde_json::to_string(self).expect("input message serialisation is infallible")
    }

    /// Reject values the server would have to defend against: non-finite
    /// floats poison the compositor's pointer state (`input.rs` checks this
    /// too, but a client should not send garbage in the first place).
    pub fn is_finite(&self) -> bool {
        match self {
            Self::MouseAbs { x, y, w, h } => {
                x.is_finite() && y.is_finite() && w.is_finite() && h.is_finite()
            }
            Self::MouseMove { dx, dy } => dx.is_finite() && dy.is_finite(),
            Self::Wheel { dx, dy } => dx.is_finite() && dy.is_finite(),
            Self::GamepadAxis { value, .. } => value.is_finite(),
            _ => true,
        }
    }
}

// ---------------------------------------------------------------------------
// Gamepad translation
// ---------------------------------------------------------------------------

/// Which gamepad API layout a pad reports.
///
/// Pads that do not report the W3C "standard" mapping expose their physical
/// layout directly, where indices 0/1 and 2/3 sit crosswise to the standard
/// A/B and X/Y. The web client swaps those indices to preserve physical button
/// positions (`useLightraysStreaming.js::gamepadButtonIndices`); the server
/// then translates browser indices to RetroPad ids in
/// `lightrays/src/input.rs::browser_gamepad_button`. The same adjustment has to
/// happen here so the native client behaves identically.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GamepadLayout {
    /// W3C "standard gamepad" mapping: indices are used as-is.
    Standard,
    /// Non-standard mapping: A/B and X/Y are crosswise and get swapped.
    NonStandard,
}

/// Number of buttons the web client forwards. Buttons beyond this are ignored.
pub const FORWARDED_BUTTON_COUNT: usize = 17;

impl GamepadLayout {
    pub fn from_mapping(mapping: &str) -> Self {
        if mapping == "standard" {
            Self::Standard
        } else {
            Self::NonStandard
        }
    }

    /// Map a raw button index from the pad to the index sent on the wire.
    pub fn button_index(self, raw: usize) -> usize {
        match self {
            Self::Standard => raw,
            Self::NonStandard => match raw {
                0 => 1,
                1 => 0,
                2 => 3,
                3 => 2,
                other => other,
            },
        }
    }
}

/// Threshold used by the web client to decide whether a trigger counts as
/// pressed (`pad.buttons[i].value > 0.5`).
pub const BUTTON_PRESS_THRESHOLD: f64 = 0.5;

/// Minimum change in an axis value before a new sample is sent. Suppresses
/// jitter without visible input lag (`GAMEPAD_AXIS_EPSILON` in the web client).
pub const GAMEPAD_AXIS_EPSILON: f64 = 0.01;

// ---------------------------------------------------------------------------
// Resize handling
// ---------------------------------------------------------------------------

/// Server-side limits, mirrored from `lightrays/src/launch.rs` so the client
/// clamps before sending instead of provoking a validation error.
pub const MIN_DIMENSION: u32 = 64;
pub const MAX_WIDTH: u32 = 7680;
pub const MAX_HEIGHT: u32 = 4320;
/// The server's own 8-pixel dead zone, applied client-side as well so a window
/// drag does not spam a pipeline rebuild.
pub const RESIZE_DEAD_ZONE: u32 = 8;

/// Prepare a requested resolution for the `resize` message.
///
/// Returns `None` when the request is unchanged relative to `last` (inside the
/// dead zone), or when it cannot produce a valid request at all.
pub fn clamp_resize(width: u32, height: u32, last: (u32, u32)) -> Option<(u32, u32)> {
    // H.264/H.265 encoders need even dimensions; the server rejects bad sizes.
    let even = |v: u32| v + (v % 2);
    let w = even(width).clamp(MIN_DIMENSION, MAX_WIDTH);
    let h = even(height).clamp(MIN_DIMENSION, MAX_HEIGHT);

    let (lw, lh) = last;
    let unchanged = w.abs_diff(lw) <= RESIZE_DEAD_ZONE && h.abs_diff(lh) <= RESIZE_DEAD_ZONE;
    if unchanged {
        return None;
    }
    Some((w, h))
}

/// Physical pixel size of a surface at a given scale factor, ready to be fed
/// to [`clamp_resize`].
pub fn surface_to_physical(
    logical_width: f64,
    logical_height: f64,
    scale_factor: f64,
) -> (u32, u32) {
    let w = (logical_width * scale_factor).round().max(0.0);
    let h = (logical_height * scale_factor).round().max(0.0);
    (w as u32, h as u32)
}

// ---------------------------------------------------------------------------
// Launch payload
// ---------------------------------------------------------------------------

/// Request body for `POST /api/lightrays/launch` (the backend forwards it to
/// Lightrays). Field names match `lightrays/src/launch.rs`.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct LaunchRequest {
    pub width: u32,
    pub height: u32,
    pub fps: u32,
    pub bitrate_kbps: u32,
    pub title: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub runtime_profile: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub app_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub keyboard_layout: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub start_virtual_compositor: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub start_audio_server: Option<bool>,
}

/// Server limits for a launch, mirrored from `lightrays/src/launch.rs`.
pub const MIN_FPS: u32 = 15;
pub const MAX_FPS: u32 = 120;
pub const MIN_BITRATE_KBPS: u32 = 500;
pub const MAX_BITRATE_KBPS: u32 = 50_000;

/// Clamp a launch request into the range the server accepts. Sending an
/// out-of-range value would be rejected with a validation error, so the client
/// clamps proactively.
pub fn clamp_launch(req: &mut LaunchRequest) {
    let even = |v: u32| v + (v % 2);
    req.width = even(req.width).clamp(MIN_DIMENSION, MAX_WIDTH);
    req.height = even(req.height).clamp(MIN_DIMENSION, MAX_HEIGHT);
    req.fps = req.fps.clamp(MIN_FPS, MAX_FPS);
    req.bitrate_kbps = req.bitrate_kbps.clamp(MIN_BITRATE_KBPS, MAX_BITRATE_KBPS);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_offer() {
        let msg = ServerMessage::parse(r#"{"type":"offer","sdp":"v=0..."}"#);
        assert_eq!(
            msg,
            Some(ServerMessage::Offer {
                sdp: "v=0...".into()
            })
        );
    }

    #[test]
    fn parses_ice_with_camel_case_field() {
        let msg = ServerMessage::parse(r#"{"type":"ice","candidate":"c","sdpMLineIndex":7}"#);
        assert_eq!(
            msg,
            Some(ServerMessage::Ice {
                candidate: "c".into(),
                mline_index: 7
            })
        );
    }

    #[test]
    fn parses_container_died_with_and_without_exit_code() {
        assert_eq!(
            ServerMessage::parse(r#"{"type":"container_died","exit_code":137}"#),
            Some(ServerMessage::ContainerDied {
                exit_code: Some(137)
            })
        );
        assert_eq!(
            ServerMessage::parse(r#"{"type":"container_died"}"#),
            Some(ServerMessage::ContainerDied { exit_code: None })
        );
    }

    #[test]
    fn parses_error_and_pipeline_error() {
        assert_eq!(
            ServerMessage::parse(r#"{"error":"no such session"}"#),
            Some(ServerMessage::Error {
                message: "no such session".into()
            })
        );
        assert_eq!(
            ServerMessage::parse(r#"{"type":"pipeline_error"}"#),
            Some(ServerMessage::PipelineError)
        );
    }

    #[test]
    fn unknown_and_malformed_frames_are_ignored() {
        assert_eq!(ServerMessage::parse(r#"{"type":"future_thing"}"#), None);
        assert_eq!(ServerMessage::parse("not json"), None);
        assert_eq!(ServerMessage::parse("{}"), None);
    }

    #[test]
    fn serialises_client_messages_with_server_field_names() {
        let ice = ClientMessage::Ice {
            candidate: "cand".into(),
            mline_index: 3,
        };
        assert_eq!(
            ice.to_json(),
            r#"{"type":"ice","candidate":"cand","sdpMLineIndex":3}"#
        );

        let resize = ClientMessage::Resize {
            width: 1920,
            height: 1080,
        };
        assert_eq!(
            resize.to_json(),
            r#"{"type":"resize","width":1920,"height":1080}"#
        );

        let answer = ClientMessage::Answer { sdp: "v=0".into() };
        assert_eq!(answer.to_json(), r#"{"type":"answer","sdp":"v=0"}"#);
    }

    #[test]
    fn serialises_input_messages_with_server_field_names() {
        assert_eq!(
            InputMessage::MouseAbs {
                x: 1.0,
                y: 2.0,
                w: 1920.0,
                h: 1080.0
            }
            .to_json(),
            r#"{"type":"mouseabs","x":1.0,"y":2.0,"w":1920.0,"h":1080.0}"#
        );
        assert_eq!(
            InputMessage::key(KeyCode::new("KeyA"), true).to_json(),
            r#"{"type":"key","code":"KeyA","pressed":true}"#
        );
        assert_eq!(
            InputMessage::gamepad_button(9, true).to_json(),
            r#"{"type":"gamepadbutton","index":9,"pressed":true}"#
        );
        assert_eq!(
            InputMessage::gamepad_axis(0, 1, -0.75).to_json(),
            r#"{"type":"gamepadaxis","stick":0,"axis":1,"value":-0.75}"#
        );
        assert_eq!(
            InputMessage::Wheel {
                dx: 0.0,
                dy: -120.0
            }
            .to_json(),
            r#"{"type":"wheel","dx":0.0,"dy":-120.0}"#
        );
    }

    #[test]
    fn rejects_non_finite_input() {
        assert!(!InputMessage::MouseAbs {
            x: f64::NAN,
            y: 0.0,
            w: 1.0,
            h: 1.0
        }
        .is_finite());
        assert!(!InputMessage::gamepad_axis(0, 0, f64::INFINITY).is_finite());
        assert!(InputMessage::key(KeyCode::new("KeyA"), true).is_finite());
    }

    #[test]
    fn standard_layout_keeps_indices() {
        let layout = GamepadLayout::from_mapping("standard");
        assert_eq!(layout.button_index(0), 0);
        assert_eq!(layout.button_index(3), 3);
        assert_eq!(layout.button_index(16), 16);
    }

    #[test]
    fn non_standard_layout_swaps_ab_and_xy() {
        let layout = GamepadLayout::from_mapping("");
        assert_eq!(layout.button_index(0), 1);
        assert_eq!(layout.button_index(1), 0);
        assert_eq!(layout.button_index(2), 3);
        assert_eq!(layout.button_index(3), 2);
        // Shoulder/trigger/face extras keep their position.
        assert_eq!(layout.button_index(4), 4);
        assert_eq!(layout.button_index(16), 16);
    }

    #[test]
    fn resize_is_clamped_to_even_server_limits() {
        // Odd sizes become even.
        assert_eq!(clamp_resize(1921, 1081, (0, 0)), Some((1922, 1082)));
        // Too small grows to the minimum.
        assert_eq!(
            clamp_resize(10, 10, (0, 0)),
            Some((MIN_DIMENSION, MIN_DIMENSION))
        );
        // Too large shrinks to the maximum.
        assert_eq!(
            clamp_resize(10_000, 10_000, (0, 0)),
            Some((MAX_WIDTH, MAX_HEIGHT))
        );
    }

    #[test]
    fn resize_inside_the_dead_zone_is_skipped() {
        // Exactly the same size.
        assert_eq!(clamp_resize(1920, 1080, (1920, 1080)), None);
        // Within the 8-pixel dead zone.
        assert_eq!(clamp_resize(1924, 1084, (1920, 1080)), None);
        // Outside the dead zone.
        assert_eq!(clamp_resize(1930, 1080, (1920, 1080)), Some((1930, 1080)));
    }

    #[test]
    fn surface_to_physical_applies_scale_factor() {
        assert_eq!(surface_to_physical(1280.0, 720.0, 1.0), (1280, 720));
        assert_eq!(surface_to_physical(1280.0, 720.0, 2.0), (2560, 1440));
        // Fractional scaling (e.g. 1.25) is rounded, not truncated.
        assert_eq!(surface_to_physical(1280.0, 720.0, 1.25), (1600, 900));
    }

    #[test]
    fn launch_request_round_trips_and_clamps() {
        let mut req = LaunchRequest {
            width: 1919,
            height: 1081,
            fps: 240,
            bitrate_kbps: 999_999,
            title: "Half-Life".into(),
            runtime_profile: Some("gow-steam".into()),
            app_id: Some("70".into()),
            keyboard_layout: None,
            start_virtual_compositor: None,
            start_audio_server: None,
        };
        clamp_launch(&mut req);

        assert_eq!(req.width, 1920);
        assert_eq!(req.height, 1082);
        assert_eq!(req.fps, MAX_FPS);
        assert_eq!(req.bitrate_kbps, MAX_BITRATE_KBPS);

        let json = serde_json::to_string(&req).unwrap();
        // Unset optional fields are omitted rather than sent as null.
        assert!(!json.contains("keyboard_layout"));
        assert!(json.contains(r#""runtime_profile":"gow-steam""#));
        assert_eq!(serde_json::from_str::<LaunchRequest>(&json).unwrap(), req);
    }
}

// ---------------------------------------------------------------------------
// Pointer input
// ---------------------------------------------------------------------------

/// The rectangle a video frame actually occupies inside a display surface.
///
/// A stream is almost never the aspect ratio of the window it is shown in, so
/// the picture is letter- or pillarboxed and part of the surface is black bars.
/// The server maps `mouseabs` coordinates onto the *compositor's* space, so
/// sending the raw window position would click somewhere the player cannot see
/// — with black bars the error scales with the bar width and is worst exactly
/// where a game's UI sits.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Letterbox {
    /// Width of the rendered picture, excluding bars.
    pub width: f64,
    /// Height of the rendered picture, excluding bars.
    pub height: f64,
    /// Distance from the surface's left edge to the picture.
    pub offset_x: f64,
    /// Distance from the surface's top edge to the picture.
    pub offset_y: f64,
}

impl Letterbox {
    /// Compute the box for a surface of `surface_w × surface_h` showing a
    /// `video_w × video_h` frame, fitted the way `object-fit: contain` does.
    ///
    /// Degenerate sizes (a zero-height window while a compositor is starting, a
    /// video whose size is not yet known) yield `None` rather than a box that
    /// would divide by zero. The caller then sends nothing, which is correct: a
    /// click that cannot be placed should not be sent at a guess.
    pub fn fit(surface_w: f64, surface_h: f64, video_w: f64, video_h: f64) -> Option<Self> {
        if !(surface_w > 0.0 && surface_h > 0.0 && video_w > 0.0 && video_h > 0.0) {
            return None;
        }
        let video_aspect = video_w / video_h;
        let surface_aspect = surface_w / surface_h;

        // Same branch as the web client: if the surface is *wider* than the
        // video, the video is limited by height and the leftover space becomes
        // left/right bars.
        let (width, height, offset_x, offset_y) = if surface_aspect > video_aspect {
            let height = surface_h;
            let width = surface_h * video_aspect;
            (width, height, (surface_w - width) / 2.0, 0.0)
        } else {
            let width = surface_w;
            let height = surface_w / video_aspect;
            (width, height, 0.0, (surface_h - height) / 2.0)
        };

        Some(Self {
            width,
            height,
            offset_x,
            offset_y,
        })
    }

    /// Translate a position in surface coordinates into the video's own pixel
    /// space, clamped to the picture.
    ///
    /// Clamping rather than rejecting: a drag that leaves the window should pin
    /// the pointer to the edge, which is what a browser does. Outside the
    /// picture the value would otherwise go negative or exceed the frame size,
    /// and the server would place the cursor somewhere surprising.
    pub fn to_video(
        &self,
        surface_x: f64,
        surface_y: f64,
        video_w: f64,
        video_h: f64,
    ) -> (f64, f64) {
        // A zero-size box cannot place anything; fall back to the surface
        // origin rather than dividing by zero.
        if self.width <= 0.0 || self.height <= 0.0 {
            return (0.0, 0.0);
        }
        let rel_x = surface_x - self.offset_x;
        let rel_y = surface_y - self.offset_y;
        let x = (rel_x / self.width) * video_w;
        let y = (rel_y / self.height) * video_h;
        (x.clamp(0.0, video_w), y.clamp(0.0, video_h))
    }
}

/// Builds the absolute-pointer message for a position on a display surface.
///
/// Returns `None` when the geometry is unusable, so the caller sends nothing
/// instead of a guessed coordinate.
pub fn mouse_abs(
    surface_w: f64,
    surface_h: f64,
    video_w: f64,
    video_h: f64,
    x: f64,
    y: f64,
) -> Option<InputMessage> {
    let box_ = Letterbox::fit(surface_w, surface_h, video_w, video_h)?;
    let (x, y) = box_.to_video(x, y, video_w, video_h);
    let message = InputMessage::MouseAbs {
        x: x.round(),
        y: y.round(),
        w: video_w,
        h: video_h,
    };
    // The server defends against non-finite floats; a client should not send
    // them in the first place.
    message.is_finite().then_some(message)
}

#[cfg(test)]
mod letterbox_tests {
    use super::*;

    /// A 16:9 video in a wider surface gets bars left and right.
    #[test]
    fn a_wide_surface_pillarboxes_the_picture() {
        let box_ = Letterbox::fit(2000.0, 1000.0, 1920.0, 1080.0).expect("Box");
        // Limited by height.
        assert!((box_.height - 1000.0).abs() < 1e-9);
        assert!((box_.width - (1000.0 * 16.0 / 9.0)).abs() < 1e-9);
        assert!((box_.offset_y).abs() < 1e-9);
        assert!(box_.offset_x > 0.0, "links und rechts müssen Balken sein");
    }

    /// A 16:9 video in a taller surface gets bars top and bottom.
    #[test]
    fn a_tall_surface_letterboxes_the_picture() {
        let box_ = Letterbox::fit(1000.0, 2000.0, 1920.0, 1080.0).expect("Box");
        assert!((box_.width - 1000.0).abs() < 1e-9);
        assert!((box_.height - (1000.0 * 9.0 / 16.0)).abs() < 1e-9);
        assert!((box_.offset_x).abs() < 1e-9);
        assert!(box_.offset_y > 0.0, "oben und unten müssen Balken sein");
    }

    /// Matching aspect ratios leave no bars at all.
    #[test]
    fn a_matching_aspect_ratio_has_no_bars() {
        let box_ = Letterbox::fit(1920.0, 1080.0, 1920.0, 1080.0).expect("Box");
        assert!((box_.width - 1920.0).abs() < 1e-9);
        assert!((box_.height - 1080.0).abs() < 1e-9);
        assert!((box_.offset_x).abs() < 1e-9);
        assert!((box_.offset_y).abs() < 1e-9);
    }

    /// The centre of the picture maps to the centre of the frame, whatever the
    /// bars are — this is what makes aiming correct in a game.
    #[test]
    fn the_centre_of_the_picture_is_the_centre_of_the_frame() {
        let box_ = Letterbox::fit(2000.0, 1000.0, 1920.0, 1080.0).expect("Box");
        let (x, y) = box_.to_video(1000.0, 500.0, 1920.0, 1080.0);
        assert!((x - 960.0).abs() < 1e-6, "x war {x}");
        assert!((y - 540.0).abs() < 1e-6, "y war {y}");
    }

    /// The corner of the *picture* is the corner of the frame — not the corner
    /// of the window, which is the mistake the bars cause.
    #[test]
    fn the_picture_corner_maps_to_the_frame_corner_not_the_window_corner() {
        let box_ = Letterbox::fit(2000.0, 1000.0, 1920.0, 1080.0).expect("Box");
        // The surface origin (0,0) is inside the left bar, so it clamps to 0.
        let (x0, y0) = box_.to_video(0.0, 0.0, 1920.0, 1080.0);
        assert!((x0 - 0.0).abs() < 1e-9);
        assert!((y0 - 0.0).abs() < 1e-9);
        // The picture's own top-left maps to the frame's top-left.
        let (x1, y1) = box_.to_video(box_.offset_x, 0.0, 1920.0, 1080.0);
        assert!((x1 - 0.0).abs() < 1e-9, "x war {x1}");
        assert!((y1 - 0.0).abs() < 1e-9, "y war {y1}");
    }

    /// Coordinates outside the picture are clamped, so a drag that leaves the
    /// window pins to the edge instead of producing a wild coordinate.
    #[test]
    fn positions_outside_the_picture_are_clamped() {
        let box_ = Letterbox::fit(2000.0, 1000.0, 1920.0, 1080.0).expect("Box");
        let (x, y) = box_.to_video(-500.0, -500.0, 1920.0, 1080.0);
        assert!((x - 0.0).abs() < 1e-9);
        assert!((y - 0.0).abs() < 1e-9);
        let (x, y) = box_.to_video(99999.0, 99999.0, 1920.0, 1080.0);
        assert!((x - 1920.0).abs() < 1e-9);
        assert!((y - 1080.0).abs() < 1e-9);
    }

    /// A degenerate surface yields no box — and therefore no message, rather
    /// than a coordinate that divides by zero.
    #[test]
    fn a_degenerate_surface_yields_no_box() {
        assert!(Letterbox::fit(0.0, 1000.0, 1920.0, 1080.0).is_none());
        assert!(Letterbox::fit(1000.0, 0.0, 1920.0, 1080.0).is_none());
        // A video whose size is not known yet (before the first frame).
        assert!(Letterbox::fit(1000.0, 1000.0, 0.0, 1080.0).is_none());
        assert!(Letterbox::fit(1000.0, 1000.0, 1920.0, 0.0).is_none());
        // Negative values can come from a compositor that reports a
        // not-yet-laid-out window.
        assert!(Letterbox::fit(-100.0, 1000.0, 1920.0, 1080.0).is_none());
        assert!(Letterbox::fit(1000.0, 1000.0, f64::NAN, 1080.0).is_none());
    }

    /// The message carries the *video* size, not the surface size: the server
    /// scales into the compositor's space, and a surface-sized `w` would squeeze
    /// the pointer into a fraction of the frame.
    #[test]
    fn the_message_reports_the_video_size() {
        let message = mouse_abs(2000.0, 1000.0, 1920.0, 1080.0, 1000.0, 500.0).expect("Meldung");
        match message {
            InputMessage::MouseAbs { x, y, w, h } => {
                assert!((w - 1920.0).abs() < 1e-9, "w war {w}");
                assert!((h - 1080.0).abs() < 1e-9, "h war {h}");
                assert!((x - 960.0).abs() < 1e-9, "x war {x}");
                assert!((y - 540.0).abs() < 1e-9, "y war {y}");
            }
            other => panic!("falscher Nachrichtentyp: {other:?}"),
        }
        assert!(message.is_finite());
    }

    /// A degenerate surface produces no message at all.
    #[test]
    fn a_degenerate_surface_produces_no_message() {
        assert!(mouse_abs(0.0, 0.0, 1920.0, 1080.0, 10.0, 10.0).is_none());
    }
}
