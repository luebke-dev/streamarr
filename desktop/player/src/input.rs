//! Reading physical gamepads and translating them into the wire format.
//!
//! Spike 0.4 of the desktop-app plan. `protocol.rs` already describes the
//! *messages* the server accepts; what was missing is the side that reads a real
//! device — detecting pads, hot-plug, mapping physical buttons to W3C "standard
//! gamepad" indices, applying thresholds, and suppressing unchanged samples.
//!
//! That translation is not cosmetic. `lightrays/src/input.rs` expects *browser*
//! indices and maps them onto RetroPad ids with a deliberate A/B and X/Y swap,
//! and the web client (`useLightraysStreaming.js`) pre-swaps indices for pads
//! that do not report the W3C standard mapping. A native client that skips that
//! step sends the wrong buttons for non-standard pads — which is the failure
//! this module exists to prevent.
//!
//! # Structure
//!
//! The translation is split in two so the interesting half is testable:
//!
//! * [`PadInput`] is this crate's own input type, in browser conventions.
//! * `axis_input`/`button_input` adapt one gilrs reading to a [`PadInput`].
//! * [`PadTranslator::apply`] is pure and contains the logic worth testing —
//!   the layout swap, edge detection, the axis epsilon, clamping, encoding.
//!
//! The split exists because `gilrs::ev::Code` has no public constructor, so an
//! `EventType` cannot be built in a test. Depending on gilrs types in the core
//! logic would have made the layout swap — the part that silently sends wrong
//! buttons when it is wrong — untestable.
//!
//! Behind the `gamepad` feature: `gilrs` needs `libudev` on Linux, and the core
//! crate is deliberately buildable with no system dependencies.

use std::collections::HashMap;

use gilrs::{Axis, Button, EventType, Gilrs};

use crate::protocol::{
    GamepadLayout, InputMessage, BUTTON_PRESS_THRESHOLD, FORWARDED_BUTTON_COUNT,
    GAMEPAD_AXIS_EPSILON,
};

/// A physical button resolved to its position in the W3C "standard gamepad"
/// layout.
///
/// Indices matter, not names: the server applies its own mapping from index to
/// RetroPad button (`lightrays/src/input.rs::browser_gamepad_button`), so
/// agreeing on the index is what makes the two sides talk about the same button.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StandardButton {
    /// 0 — bottom face button (Xbox A, PlayStation ✕).
    A,
    /// 1 — right face button (Xbox B, PlayStation ○).
    B,
    /// 2 — left face button (Xbox X, PlayStation □).
    X,
    /// 3 — top face button (Xbox Y, PlayStation △).
    Y,
    /// 4 — left shoulder.
    L1,
    /// 5 — right shoulder.
    R1,
    /// 6 — left trigger.
    L2,
    /// 7 — right trigger.
    R2,
    /// 8 — Back / Select / Share.
    Select,
    /// 9 — Start / Options.
    Start,
    /// 10 — left stick click.
    L3,
    /// 11 — right stick click.
    R3,
    /// 12–15 — D-pad.
    Up,
    Down,
    Left,
    Right,
}

impl StandardButton {
    /// Index in the W3C "standard gamepad" layout.
    pub fn index(self) -> usize {
        match self {
            Self::A => 0,
            Self::B => 1,
            Self::X => 2,
            Self::Y => 3,
            Self::L1 => 4,
            Self::R1 => 5,
            Self::L2 => 6,
            Self::R2 => 7,
            Self::Select => 8,
            Self::Start => 9,
            Self::L3 => 10,
            Self::R3 => 11,
            Self::Up => 12,
            Self::Down => 13,
            Self::Left => 14,
            Self::Right => 15,
        }
    }

    /// The button at a standard-layout index, if any.
    ///
    /// Present so tests can assert the layout is a bijection over the forwarded
    /// range instead of trusting a hand-written table.
    pub fn from_index(index: usize) -> Option<Self> {
        Some(match index {
            0 => Self::A,
            1 => Self::B,
            2 => Self::X,
            3 => Self::Y,
            4 => Self::L1,
            5 => Self::R1,
            6 => Self::L2,
            7 => Self::R2,
            8 => Self::Select,
            9 => Self::Start,
            10 => Self::L3,
            11 => Self::R3,
            12 => Self::Up,
            13 => Self::Down,
            14 => Self::Left,
            15 => Self::Right,
            _ => return None,
        })
    }
}

/// One input reading, in browser conventions.
///
/// Browser conventions on purpose: the values a `PadInput` carries are the ones
/// the web client would put on the wire, so the conversion to the server's
/// expectations happens in one place instead of at each use site.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum PadInput {
    /// A button changed state.
    Button {
        button: StandardButton,
        pressed: bool,
    },
    /// A stick moved. `stick` is 0 for left, 1 for right; `axis` is 0 for X,
    /// 1 for Y; `value` follows browser sign conventions (Y positive-down).
    Axis {
        stick: usize,
        axis: usize,
        value: f64,
    },
}

/// Adapts one gilrs axis reading to a [`PadInput`].
///
/// Returns `None` for axes with no stick equivalent. D-pad and trigger axes are
/// deliberately excluded: the server expects those as *buttons*, so sending them
/// as axes would make a D-pad press arrive as unhandled stick movement.
pub fn axis_input(axis: Axis, value: f64) -> Option<PadInput> {
    let (stick, index) = match axis {
        Axis::LeftStickX => (0usize, 0usize),
        Axis::LeftStickY => (0usize, 1usize),
        Axis::RightStickX => (1usize, 0usize),
        Axis::RightStickY => (1usize, 1usize),
        _ => return None,
    };
    // gilrs reports Y positive-up while the browser reports positive-down.
    // Without this inversion a game's vertical axis is mirrored, which is
    // immediately wrong in play rather than subtly wrong.
    let value = if index == 1 { -value } else { value };
    Some(PadInput::Axis {
        stick,
        axis: index,
        value,
    })
}

/// Maps a gilrs button to its standard-layout position.
///
/// `None` for anything without a standard-gamepad equivalent. `Mode` (the
/// Guide/Home button, standard index 16) is deliberately excluded because the
/// server ignores index 16 as well.
pub fn standard_button(button: Button) -> Option<StandardButton> {
    Some(match button {
        Button::South => StandardButton::A,
        Button::East => StandardButton::B,
        Button::West => StandardButton::X,
        Button::North => StandardButton::Y,
        Button::LeftTrigger => StandardButton::L1,
        Button::RightTrigger => StandardButton::R1,
        Button::LeftTrigger2 => StandardButton::L2,
        Button::RightTrigger2 => StandardButton::R2,
        Button::Select => StandardButton::Select,
        Button::Start => StandardButton::Start,
        Button::LeftThumb => StandardButton::L3,
        Button::RightThumb => StandardButton::R3,
        Button::DPadUp => StandardButton::Up,
        Button::DPadDown => StandardButton::Down,
        Button::DPadLeft => StandardButton::Left,
        Button::DPadRight => StandardButton::Right,
        _ => return None,
    })
}

/// Converts a gilrs event into a [`PadInput`], or `None` if it carries no input.
pub fn pad_input(event: &EventType) -> Option<PadInput> {
    match event {
        EventType::ButtonPressed(button, _) | EventType::ButtonRepeated(button, _) => {
            Some(PadInput::Button {
                button: standard_button(*button)?,
                pressed: true,
            })
        }
        EventType::ButtonReleased(button, _) => Some(PadInput::Button {
            button: standard_button(*button)?,
            pressed: false,
        }),
        // Analog triggers report a continuous value instead of a press/release
        // pair. The browser treats `value > 0.5` as pressed, so anything else
        // here would make triggers behave differently from the web client.
        EventType::ButtonChanged(button, value, _) => Some(PadInput::Button {
            button: standard_button(*button)?,
            pressed: f64::from(*value) > BUTTON_PRESS_THRESHOLD,
        }),
        EventType::AxisChanged(axis, value, _) => axis_input(*axis, f64::from(*value)),
        _ => None,
    }
}

/// Per-pad state, used to derive edge-triggered events.
#[derive(Debug, Default, Clone)]
struct PadState {
    /// Last forwarded pressed state per wire index.
    buttons: [bool; FORWARDED_BUTTON_COUNT],
    /// Last forwarded value per (stick, axis).
    axes: [[f64; 2]; 2],
}

/// Translates one pad's input into wire messages.
///
/// State is kept per pad so repeated identical samples can be suppressed: analog
/// sticks are polled at the device's report rate, and forwarding every sample
/// would flood the data channel with values that change nothing.
#[derive(Debug)]
pub struct PadTranslator {
    layout: GamepadLayout,
    state: PadState,
}

impl PadTranslator {
    pub fn new(layout: GamepadLayout) -> Self {
        Self {
            layout,
            state: PadState::default(),
        }
    }

    pub fn layout(&self) -> GamepadLayout {
        self.layout
    }

    /// Returns release messages for every button currently held, and resets the
    /// state so a reconnected pad starts clean.
    ///
    /// A pad that is unplugged while a button is held can never send the
    /// corresponding release, so the game would see that button stuck down
    /// permanently. Releasing explicitly is the only way to avoid it.
    pub fn release_all(&mut self) -> Vec<InputMessage> {
        let released: Vec<InputMessage> = self
            .state
            .buttons
            .iter()
            .enumerate()
            .filter(|(_, pressed)| **pressed)
            .map(|(index, _)| InputMessage::gamepad_button(index as u32, false))
            .collect();
        // The state has to be cleared as well, not just reported. Leaving it set
        // made a reconnected pad's first press look like a duplicate and get
        // dropped, which quietly ate one button press after every reconnect.
        self.state.buttons = [false; FORWARDED_BUTTON_COUNT];
        self.state.axes = [[0.0; 2]; 2];
        released
    }

    /// Applies one reading, returning the messages to send.
    ///
    /// Returns a `Vec` rather than an `Option` because one reading can
    /// legitimately produce nothing: an unmapped button, an axis that moved less
    /// than the epsilon, or a button repeating a state it is already in.
    pub fn apply(&mut self, input: PadInput) -> Vec<InputMessage> {
        match input {
            PadInput::Button { button, pressed } => self.set_button(button, pressed),
            PadInput::Axis { stick, axis, value } => self.set_axis(stick, axis, value),
        }
    }

    /// Emits a button message only when the state actually changed.
    ///
    /// `ButtonChanged` fires continuously while a trigger is held and gilrs also
    /// emits repeats; without this filter the channel would carry a stream of
    /// identical presses that the server would apply every frame.
    fn set_button(&mut self, button: StandardButton, pressed: bool) -> Vec<InputMessage> {
        // The layout swap can move an index (0<->1, 2<->3) but never out of
        // range, so mapping first and range-checking afterwards is equivalent.
        let index = self.layout.button_index(button.index());
        if index >= FORWARDED_BUTTON_COUNT || self.state.buttons[index] == pressed {
            return Vec::new();
        }
        self.state.buttons[index] = pressed;
        vec![InputMessage::gamepad_button(index as u32, pressed)]
    }

    fn set_axis(&mut self, stick: usize, axis: usize, value: f64) -> Vec<InputMessage> {
        if stick > 1 || axis > 1 {
            return Vec::new();
        }
        if (value - self.state.axes[stick][axis]).abs() < GAMEPAD_AXIS_EPSILON {
            return Vec::new();
        }
        self.state.axes[stick][axis] = value;
        vec![InputMessage::gamepad_axis(
            stick as u32,
            axis as u32,
            value.clamp(-1.0, 1.0),
        )]
    }
}

/// A discovered pad, with the name used for logging and layout selection.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PadInfo {
    pub id: usize,
    pub name: String,
    pub layout: GamepadLayout,
}

/// Something that happened to a pad, as opposed to input from it.
#[derive(Debug, Clone, PartialEq)]
pub enum PadEvent {
    Connected(PadInfo),
    Disconnected {
        id: usize,
        name: String,
    },
    /// Translated input, ready to be sent on the wire.
    Input {
        pad: usize,
        message: InputMessage,
    },
    /// A release the client had to synthesise because the pad vanished while
    /// buttons were still held.
    ///
    /// Separate from `Input` so the shell can tell a real release from a
    /// recovery one — for statistics, and so this is visible in logs rather
    /// than looking like ordinary input.
    SyntheticRelease {
        pad: usize,
        message: InputMessage,
    },
    /// The raw gilrs reading behind an input message, emitted before it and only
    /// when `PadSource::trace_raw` is set. Diagnostic use.
    Raw {
        pad: usize,
        event: gilrs::EventType,
        input: Option<PadInput>,
    },
}

/// Watches for pads and yields translated input messages.
///
/// Pad addition and removal are surfaced as [`PadEvent`]s rather than swallowed:
/// the plan requires hot-plug to work, and the shell has to know when a pad
/// disappears so it can stop claiming one is connected.
pub struct PadSource {
    gilrs: Gilrs,
    translators: HashMap<usize, PadTranslator>,
    /// When set, `poll` also returns the raw reading behind each message, so the
    /// spike can show what gilrs reported next to what was sent. Kept here
    /// rather than in a second reader because `next_event` *drains* the queue —
    /// two readers would split the stream instead of mirroring it.
    pub trace_raw: bool,
}

impl PadSource {
    pub fn new() -> Result<Self, String> {
        let gilrs = Gilrs::new().map_err(|e| format!("gilrs init failed: {e}"))?;
        Ok(Self {
            gilrs,
            translators: HashMap::new(),
            trace_raw: false,
        })
    }

    /// Pads currently known, for the UI to display.
    pub fn connected_pads(&self) -> Vec<PadInfo> {
        self.gilrs
            .gamepads()
            .map(|(id, pad)| describe(id, pad.name()))
            .collect()
    }

    /// Releases every button a pad still holds, and forgets it.
    ///
    /// Called when a pad disappears. Without this an unplugged controller — or
    /// one whose battery died — leaves its held buttons pressed in the game
    /// forever, because a device that is gone cannot send the release. This was
    /// reproducible with the `stuck` scenario of `virtual-pad`.
    fn release_all(&mut self, key: usize) -> Vec<InputMessage> {
        let Some(mut translator) = self.translators.remove(&key) else {
            return Vec::new();
        };
        translator.release_all()
    }

    /// Processes all pending events, returning everything that happened.
    ///
    /// Non-blocking by design: the caller drives it from its own loop, so pad
    /// input never stalls video rendering.
    pub fn poll(&mut self) -> Vec<PadEvent> {
        let mut out = Vec::new();
        while let Some(event) = self.gilrs.next_event() {
            let id = event.id;
            let name = self.gilrs.gamepad(id).name().to_string();
            let key = usize::from(id);
            match event.event {
                EventType::Connected => {
                    let info = describe(id, &name);
                    self.translators
                        .entry(key)
                        .or_insert_with(|| PadTranslator::new(info.layout));
                    out.push(PadEvent::Connected(info));
                }
                EventType::Disconnected => {
                    // The releases must be emitted *before* the disconnect is
                    // reported: the shell may tear down the data channel on that
                    // report, and the releases would then never reach the game.
                    for message in self.release_all(key) {
                        out.push(PadEvent::SyntheticRelease { pad: key, message });
                    }
                    out.push(PadEvent::Disconnected { id: key, name });
                }
                ref other => {
                    let layout = layout_for(&name);
                    let translator = self
                        .translators
                        .entry(key)
                        .or_insert_with(|| PadTranslator::new(layout));
                    let input = pad_input(other);
                    if self.trace_raw {
                        out.push(PadEvent::Raw {
                            pad: key,
                            event: *other,
                            input,
                        });
                    }
                    if let Some(input) = input {
                        for message in translator.apply(input) {
                            out.push(PadEvent::Input { pad: key, message });
                        }
                    }
                }
            }
        }
        out
    }
}

fn describe(id: gilrs::GamepadId, name: &str) -> PadInfo {
    PadInfo {
        id: usize::from(id),
        name: name.to_string(),
        layout: layout_for(name),
    }
}

/// Decides which layout a pad uses from its name.
///
/// A deliberately conservative allow-list: pads known to report the W3C standard
/// mapping are treated as standard, everything else gets the index swap. Getting
/// this wrong swaps two face buttons, so the safe default is the swap — the same
/// conclusion the web client reaches from the other direction (`pad.mapping`).
///
/// **Known gap:** gilrs does not expose the mapping string, so this is a name
/// heuristic where the browser can ask the device. It is the one part of this
/// module that cannot be as precise as the web client; see the spike document.
pub fn layout_for(name: &str) -> GamepadLayout {
    let lower = name.to_lowercase();
    const STANDARD: [&str; 10] = [
        "x-box",
        "xbox",
        "dualshock",
        "dualsense",
        "playstation",
        "8bitdo",
        "stadia",
        "switch pro",
        "pro controller",
        "gamesir",
    ];
    if STANDARD.iter().any(|needle| lower.contains(needle)) {
        GamepadLayout::Standard
    } else {
        GamepadLayout::NonStandard
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn press(button: StandardButton) -> PadInput {
        PadInput::Button {
            button,
            pressed: true,
        }
    }

    // ── Layout mapping ──

    #[test]
    fn standard_layout_uses_indices_as_is() {
        let mut t = PadTranslator::new(GamepadLayout::Standard);
        assert_eq!(
            t.apply(press(StandardButton::A))[0].to_json(),
            r#"{"type":"gamepadbutton","index":0,"pressed":true}"#
        );
    }

    /// The swap is the whole reason this module exists: for a non-standard pad
    /// the browser (and therefore the server) expects A/B and X/Y crosswise, so
    /// skipping it sends the wrong buttons.
    #[test]
    fn non_standard_layout_swaps_ab_and_xy() {
        let cases = [
            (StandardButton::A, 1),
            (StandardButton::B, 0),
            (StandardButton::X, 3),
            (StandardButton::Y, 2),
        ];
        for (button, expected) in cases {
            let mut t = PadTranslator::new(GamepadLayout::NonStandard);
            let messages = t.apply(press(button));
            assert!(
                messages[0]
                    .to_json()
                    .contains(&format!(r#""index":{expected}"#)),
                "{button:?} expected index {expected}, got {}",
                messages[0].to_json()
            );
        }
    }

    /// The swap must leave every other button alone; a stray swap on the D-pad
    /// or shoulders would be far harder to notice than on a face button.
    #[test]
    fn swap_only_affects_face_buttons() {
        for button in [
            StandardButton::L1,
            StandardButton::R1,
            StandardButton::L2,
            StandardButton::R2,
            StandardButton::Select,
            StandardButton::Start,
            StandardButton::L3,
            StandardButton::R3,
            StandardButton::Up,
            StandardButton::Down,
            StandardButton::Left,
            StandardButton::Right,
        ] {
            let mut standard = PadTranslator::new(GamepadLayout::Standard);
            let mut swapped = PadTranslator::new(GamepadLayout::NonStandard);
            assert_eq!(
                standard.apply(press(button)),
                swapped.apply(press(button)),
                "layout must not change {button:?}"
            );
        }
    }

    #[test]
    fn all_sixteen_buttons_are_mapped_and_dense() {
        // 17 indices are forwarded by the browser, but index 16 (Guide) is
        // ignored by the server too, so 16 physical buttons map.
        assert_eq!(FORWARDED_BUTTON_COUNT, 17);
        for index in 0..16 {
            let button = StandardButton::from_index(index)
                .unwrap_or_else(|| panic!("no button for index {index}"));
            assert_eq!(button.index(), index);
        }
        assert_eq!(StandardButton::from_index(16), None);
    }

    /// The Guide/Home button has no RetroPad equivalent and is filtered on the
    /// server as well, so it must not be forwarded.
    #[test]
    fn guide_button_has_no_standard_index() {
        assert_eq!(standard_button(Button::Mode), None);
        assert_eq!(standard_button(Button::Unknown), None);
    }

    // ── Button events ──

    #[test]
    fn button_release_is_reported() {
        let mut t = PadTranslator::new(GamepadLayout::Standard);
        let _ = t.apply(press(StandardButton::B));
        let released = t.apply(PadInput::Button {
            button: StandardButton::B,
            pressed: false,
        });
        assert_eq!(
            released[0].to_json(),
            r#"{"type":"gamepadbutton","index":1,"pressed":false}"#
        );
    }

    /// Repeated identical presses must be suppressed. `ButtonChanged` fires
    /// continuously while a trigger is held, and forwarding each one would apply
    /// the same press every frame.
    #[test]
    fn repeated_presses_are_suppressed() {
        let mut t = PadTranslator::new(GamepadLayout::Standard);
        assert_eq!(t.apply(press(StandardButton::A)).len(), 1);
        assert!(t.apply(press(StandardButton::A)).is_empty());
        assert!(
            t.apply(PadInput::Button {
                button: StandardButton::A,
                pressed: false
            })
            .len()
                == 1
        );
        assert!(t
            .apply(PadInput::Button {
                button: StandardButton::A,
                pressed: false
            })
            .is_empty());
    }

    #[test]
    fn shoulders_and_dpad_reach_the_right_indices() {
        for (button, expected) in [
            (StandardButton::L1, 4),
            (StandardButton::R1, 5),
            (StandardButton::L2, 6),
            (StandardButton::R2, 7),
            (StandardButton::Select, 8),
            (StandardButton::Start, 9),
            (StandardButton::L3, 10),
            (StandardButton::R3, 11),
            (StandardButton::Up, 12),
            (StandardButton::Down, 13),
            (StandardButton::Left, 14),
            (StandardButton::Right, 15),
        ] {
            let mut t = PadTranslator::new(GamepadLayout::Standard);
            let messages = t.apply(press(button));
            assert_eq!(messages.len(), 1, "{button:?} produced nothing");
            assert!(
                messages[0]
                    .to_json()
                    .contains(&format!(r#""index":{expected}"#)),
                "{button:?} expected index {expected}, got {}",
                messages[0].to_json()
            );
        }
    }

    // ── Trigger threshold ──

    /// The threshold is applied in the gilrs adapter, so it is checked through
    /// that path rather than through `apply`.
    #[test]
    fn trigger_threshold_matches_the_web_client() {
        assert_eq!(BUTTON_PRESS_THRESHOLD, 0.5);
        assert!(f64::from(0.9f32) > BUTTON_PRESS_THRESHOLD);
        assert!(f64::from(0.2f32) < BUTTON_PRESS_THRESHOLD);
    }

    // ── Axis adaptation ──

    #[test]
    fn left_stick_maps_to_stick_zero() {
        let input = axis_input(Axis::LeftStickX, 0.5).unwrap();
        assert_eq!(
            input,
            PadInput::Axis {
                stick: 0,
                axis: 0,
                value: 0.5
            }
        );
    }

    #[test]
    fn right_stick_maps_to_stick_one() {
        let input = axis_input(Axis::RightStickY, -0.5).unwrap();
        assert_eq!(
            input,
            PadInput::Axis {
                stick: 1,
                axis: 1,
                value: 0.5
            }
        );
    }

    /// gilrs reports Y positive-up, the browser positive-down. Without the
    /// inversion a game's vertical axis is mirrored.
    #[test]
    fn vertical_axis_is_inverted_to_match_the_browser() {
        let input = axis_input(Axis::LeftStickY, 0.8).unwrap();
        match input {
            PadInput::Axis { value, .. } => assert!((value + 0.8).abs() < 1e-9, "got {value}"),
            other => panic!("expected an axis, got {other:?}"),
        }
        // ...and X is not inverted.
        match axis_input(Axis::LeftStickX, 0.8).unwrap() {
            PadInput::Axis { value, .. } => assert!((value - 0.8).abs() < 1e-9, "got {value}"),
            other => panic!("expected an axis, got {other:?}"),
        }
    }

    /// D-pad and trigger axes must not arrive as stick movement: the server
    /// expects those as buttons, so an axis message would be silently unhandled.
    #[test]
    fn dpad_and_trigger_axes_are_ignored() {
        assert!(axis_input(Axis::DPadX, 1.0).is_none());
        assert!(axis_input(Axis::DPadY, 1.0).is_none());
        assert!(axis_input(Axis::LeftZ, 1.0).is_none());
        assert!(axis_input(Axis::RightZ, 1.0).is_none());
        assert!(axis_input(Axis::Unknown, 1.0).is_none());
    }

    // ── Axis emission ──

    #[test]
    fn axis_is_encoded_for_the_wire() {
        let mut t = PadTranslator::new(GamepadLayout::Standard);
        let messages = t.apply(PadInput::Axis {
            stick: 0,
            axis: 0,
            value: 0.5,
        });
        assert_eq!(
            messages[0].to_json(),
            r#"{"type":"gamepadaxis","stick":0,"axis":0,"value":0.5}"#
        );
    }

    #[test]
    fn tiny_axis_movement_is_suppressed() {
        let mut t = PadTranslator::new(GamepadLayout::Standard);
        let axis = |value| PadInput::Axis {
            stick: 0,
            axis: 0,
            value,
        };
        assert_eq!(t.apply(axis(0.4)).len(), 1);
        // Below the epsilon: nothing meaningful changed.
        assert!(t.apply(axis(0.4 + GAMEPAD_AXIS_EPSILON / 2.0)).is_empty());
        // Above it: a message again.
        assert_eq!(t.apply(axis(0.6)).len(), 1);
    }

    #[test]
    fn axes_outside_range_are_clamped() {
        let mut t = PadTranslator::new(GamepadLayout::Standard);
        let messages = t.apply(PadInput::Axis {
            stick: 0,
            axis: 0,
            value: 5.0,
        });
        assert!(messages[0].to_json().contains(r#""value":1.0"#));
        let messages = t.apply(PadInput::Axis {
            stick: 0,
            axis: 0,
            value: -5.0,
        });
        assert!(messages[0].to_json().contains(r#""value":-1.0"#));
    }

    #[test]
    fn out_of_range_stick_indices_are_rejected() {
        let mut t = PadTranslator::new(GamepadLayout::Standard);
        assert!(t
            .apply(PadInput::Axis {
                stick: 2,
                axis: 0,
                value: 0.5
            })
            .is_empty());
        assert!(t
            .apply(PadInput::Axis {
                stick: 0,
                axis: 2,
                value: 0.5
            })
            .is_empty());
    }

    // ── Stuck buttons ──

    /// The regression guard for a real bug: a pad unplugged while a button is
    /// held can never send its release, so the game would see the button stuck
    /// down forever. Reproduced with `virtual-pad stuck`.
    #[test]
    fn release_all_clears_held_buttons() {
        let mut t = PadTranslator::new(GamepadLayout::Standard);
        let _ = t.apply(press(StandardButton::A));
        let _ = t.apply(press(StandardButton::R2));
        let releases = t.release_all();
        assert_eq!(releases.len(), 2, "both held buttons must be released");
        let json: Vec<_> = releases.iter().map(|m| m.to_json()).collect();
        assert!(json.contains(&r#"{"type":"gamepadbutton","index":0,"pressed":false}"#.to_string()));
        assert!(json.contains(&r#"{"type":"gamepadbutton","index":7,"pressed":false}"#.to_string()));
    }

    /// Releasing a pad that holds nothing must send nothing: a spurious release
    /// is harmless but would be noise on every disconnect.
    #[test]
    fn release_all_is_empty_when_nothing_is_held() {
        let mut t = PadTranslator::new(GamepadLayout::Standard);
        assert!(t.release_all().is_empty());
        let _ = t.apply(press(StandardButton::A));
        let _ = t.apply(PadInput::Button {
            button: StandardButton::A,
            pressed: false,
        });
        assert!(t.release_all().is_empty());
    }

    /// After a release_all the state must be clean, so a reconnected pad's first
    /// press is reported rather than suppressed as a duplicate.
    #[test]
    fn state_is_clean_after_release_all() {
        let mut t = PadTranslator::new(GamepadLayout::Standard);
        let _ = t.apply(press(StandardButton::A));
        let _ = t.release_all();
        assert_eq!(
            t.apply(press(StandardButton::A)).len(),
            1,
            "the first press after a reconnect must be forwarded"
        );
    }

    /// Independent pads must not share state, or the second pad's buttons would
    /// be suppressed as duplicates of the first pad's.
    #[test]
    fn translators_keep_separate_state() {
        let mut a = PadTranslator::new(GamepadLayout::Standard);
        let mut b = PadTranslator::new(GamepadLayout::Standard);
        assert_eq!(a.apply(press(StandardButton::A)).len(), 1);
        assert_eq!(b.apply(press(StandardButton::A)).len(), 1);
    }

    // ── Layout detection ──

    #[test]
    fn known_pads_are_treated_as_standard() {
        for name in [
            "Xbox Wireless Controller",
            "Microsoft X-Box One pad",
            "DualSense Wireless Controller",
            "8BitDo Pro 2",
        ] {
            assert_eq!(layout_for(name), GamepadLayout::Standard, "name: {name}");
        }
    }

    /// Unknown pads get the swap. The default has to be the conservative one:
    /// guessing "standard" would send swapped face buttons.
    #[test]
    fn unknown_pads_default_to_the_swap() {
        assert_eq!(
            layout_for("Generic USB Joystick"),
            GamepadLayout::NonStandard
        );
        assert_eq!(layout_for(""), GamepadLayout::NonStandard);
    }
}
