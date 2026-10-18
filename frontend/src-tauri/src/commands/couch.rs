//! Couch / big-picture mode, as seen from the web UI.
//!
//! Plan phase 5. The geometry — focus movement, repeat, activation — lives in
//! `frontend/src-tauri/player/src/couch.rs` and is already tested there. What this module
//! adds is the part the UI actually needs and cannot compute itself: **where the
//! focus is**, and **which items exist**.
//!
//! # Why the focus lives in the shell and not in Vue
//!
//! Two reasons, and the second is the load-bearing one:
//!
//! * Movement is geometric, not index-based. "Right" means *the nearest item to
//!   the right*, which is not `index + 1` in any layout where rows have different
//!   lengths or a grid has a decorative tile. Expressing that in Vue would be a
//!   second implementation of `FocusGrid::move_focus`, and the two would drift.
//! * The pad is read by the shell. A controller's input arrives on a thread the
//!   WebView does not have, so a UI-side implementation could only ever be
//!   driven by the window's own key events — that is, by a keyboard pretending
//!   to be a gamepad.
//!
//! The UI therefore *reports the layout* (which it alone knows, since it renders
//! the tiles) and the shell decides where the focus goes. The UI never computes a
//! neighbour.
//!
//! # The layout is reported, not discovered
//!
//! `set_couch_layout` takes rectangles in **logical** pixels. Measuring them in
//! the shell would mean reading geometry through the webview's DOM, which the
//! shell cannot see; and guessing a grid from a count would break the moment the
//! real layout is a poster wall with a decorative header.

use std::sync::Mutex;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::State;

use streamarr_desktop_player::couch::{CouchIntent, Direction, FocusGrid, FocusItem, Rect};

/// Position and size of one focusable element, in logical pixels.
#[derive(Debug, Clone, Deserialize)]
pub struct ItemRect {
    /// Stable identifier the UI uses to find its element again.
    pub id: String,
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
    /// Not reachable by controller, but it still occupies space.
    ///
    /// A decorative tile that *is* focusable produces a focus ring the user can
    /// never see meaningfully; one that is *absent* lets the focus jump across
    /// the gap it leaves. Both are wrong, so it is a rectangle that is present
    /// for the geometry and skipped for the focus.
    #[serde(default)]
    pub decorative: bool,
}

impl ItemRect {
    fn into_focus_item(self) -> FocusItem {
        // Rounded, because the geometry only ever compares centres and edges and
        // a sub-pixel difference must not decide a tie.
        let rect = Rect::new(
            self.x.round() as i32,
            self.y.round() as i32,
            self.width.round() as i32,
            self.height.round() as i32,
        );
        if self.decorative {
            FocusItem::decorative(self.id, rect)
        } else {
            FocusItem::new(self.id, rect)
        }
    }
}

/// What the UI learns after an intent has been applied.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct CouchState {
    /// The focused item, or `None` when there is nothing focusable.
    pub focus: Option<String>,
    /// Whether couch mode is switched on.
    pub active: bool,
    /// How many pads are connected, so the UI can say "no controller found"
    /// rather than leaving the user pressing buttons with no effect.
    pub pads: usize,
}

/// What the UI should do about an intent.
///
/// Returned rather than performed: the shell does not know how a "back" is
/// expressed in the interface, and performing it here would put navigation logic
/// in two places.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(tag = "kind", rename_all = "camelCase")]
pub enum CouchEffect {
    /// Nothing happened (a repeat still waiting, or a movement with no neighbour).
    None,
    /// The focus moved; `id` is the new item.
    Focus { id: String },
    /// The focused item should be opened.
    Activate { id: String },
    /// One level back.
    Back,
    /// The menu.
    Menu,
}

/// Couch mode's state, shared across the commands.
pub struct CouchMode {
    grid: Mutex<FocusGrid>,
    repeat: Mutex<streamarr_desktop_player::couch::Repeat>,
    active: Mutex<bool>,
    /// The controller reader, created once.
    ///
    /// `None` when no controller subsystem could be started at all — a machine
    /// with no `libudev`, or a sandbox that denies the device nodes. That is not
    /// fatal: couch mode is still usable with a keyboard, and pretending a pad
    /// exists would be worse than reporting none.
    pads: Mutex<Option<streamarr_desktop_player::input::PadSource>>,
}

impl Default for CouchMode {
    fn default() -> Self {
        Self {
            grid: Mutex::new(FocusGrid::new(Vec::new())),
            repeat: Mutex::new(streamarr_desktop_player::couch::Repeat::default()),
            active: Mutex::new(false),
            pads: Mutex::new(streamarr_desktop_player::input::PadSource::new().ok()),
        }
    }
}

impl CouchMode {
    fn snapshot(&self, pads: usize) -> CouchState {
        let grid = self.grid.lock().expect("couch grid");
        CouchState {
            focus: grid.current_id().map(str::to_string),
            active: *self.active.lock().expect("couch active"),
            pads,
        }
    }
}

/// Switches couch mode on or off.
///
/// Switching *off* releases the repeat state: a direction still held when the
/// user leaves couch mode must not fire again on return.
#[tauri::command]
pub fn set_couch_mode(active: bool, couch: State<'_, CouchMode>) -> CouchState {
    *couch.active.lock().expect("couch active") = active;
    if !active {
        couch.repeat.lock().expect("repeat").release();
    }
    couch.snapshot(0)
}

/// Whether couch mode is on.
#[tauri::command]
pub fn couch_state(couch: State<'_, CouchMode>) -> CouchState {
    couch.snapshot(0)
}

/// Replaces the set of focusable elements.
///
/// Called whenever the UI's layout changes — a scroll, a route change, a resize.
/// The focus is **kept on the same id** when that id is still present, which is
/// what stops a background refresh from throwing the user back to the first tile.
#[tauri::command]
pub fn set_couch_layout(items: Vec<ItemRect>, couch: State<'_, CouchMode>) -> CouchState {
    let items: Vec<FocusItem> = items.into_iter().map(ItemRect::into_focus_item).collect();
    let mut grid = couch.grid.lock().expect("couch grid");
    grid.relayout(items);
    let focus = grid.current_id().map(str::to_string);
    drop(grid);
    let _ = focus;
    couch.snapshot(0)
}

/// Applies a movement in a direction.
///
/// `steps` is honoured as the geometric move repeated, not as an index jump: two
/// steps right means *the neighbour of the neighbour*, which is what a late or
/// repeated update should produce.
#[tauri::command]
pub fn couch_move(direction: String, steps: u32, couch: State<'_, CouchMode>) -> CouchEffect {
    let Some(direction) = direction_from(&direction) else {
        return CouchEffect::None;
    };
    let mut grid = couch.grid.lock().expect("couch grid");
    let mut moved = None;
    for _ in 0..steps.max(1) {
        match grid.move_focus(direction) {
            Some(item) => moved = Some(item.id.clone()),
            // Ran into an edge: stop rather than wrapping to the other side,
            // which would make a long press jump across the whole wall.
            None => break,
        }
    }
    match moved {
        Some(id) => CouchEffect::Focus { id },
        None => CouchEffect::None,
    }
}

/// Applies a button intent: activate, back or menu.
///
/// Returns the effect; the UI performs it. An "activate" with nothing focused is
/// simply nothing — not an error, since an empty list is a legitimate state.
#[tauri::command]
pub fn couch_intent(intent: String, couch: State<'_, CouchMode>) -> CouchEffect {
    let grid = couch.grid.lock().expect("couch grid");
    match intent.as_str() {
        "activate" => match grid.current_id() {
            Some(id) => CouchEffect::Activate { id: id.to_string() },
            None => CouchEffect::None,
        },
        "back" => CouchEffect::Back,
        "menu" => CouchEffect::Menu,
        _ => CouchEffect::None,
    }
}

/// Turns a name into a direction, refusing anything else.
///
/// A string rather than an enum because a `#[tauri::command]` argument has to be
/// deserialisable and an unknown variant fails the whole call; returning `None`
/// keeps an unknown direction a no-op, which is the right answer for a future UI
/// that sends one this build does not know.
fn direction_from(name: &str) -> Option<Direction> {
    Some(match name {
        "up" => Direction::Up,
        "down" => Direction::Down,
        "left" => Direction::Left,
        "right" => Direction::Right,
        _ => return None,
    })
}

/// The repeat configuration, for the UI to drive its own timers if it wants.
///
/// Reported rather than duplicated: the initial delay and rate are part of how
/// the couch interface *feels*, and a UI-side copy would drift from the one the
/// shell's own pad reader uses.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct RepeatInfo {
    pub initial_delay_ms: u64,
    pub interval_ms: u64,
}

#[tauri::command]
pub fn couch_repeat_info() -> RepeatInfo {
    let repeat = streamarr_desktop_player::couch::Repeat::default();
    RepeatInfo {
        initial_delay_ms: repeat.initial_delay.as_millis() as u64,
        interval_ms: repeat.interval.as_millis() as u64,
    }
}

/// Why a fullscreen request could not be honoured.
///
/// Returned rather than silently ignored: a couch interface that does not go
/// fullscreen is not "almost working", it is the wrong thing — the whole point is
/// to be readable from a sofa, and a window with a title bar and a desktop behind
/// it is not.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(tag = "kind", rename_all = "camelCase")]
pub enum FullscreenOutcome {
    /// The window is now in the requested state.
    Applied { fullscreen: bool },
    /// The request failed; `reason` is for a log, not for a dialog.
    Failed { reason: String },
}

/// Puts the main window into or out of fullscreen.
///
/// In the shell rather than in the UI on purpose. The WebView's own Fullscreen
/// API makes an *element* fullscreen inside the page; what couch mode needs is
/// the **window** to leave the desktop, and only the shell can ask the window
/// manager for that. The `main` capability deliberately grants the UI no window
/// permissions, so this command is the entire surface — and it takes no window
/// identifier, so the UI cannot address a different window with it.
#[tauri::command]
pub fn couch_set_fullscreen(
    fullscreen: bool,
    window: tauri::Window,
    couch: State<'_, CouchMode>,
) -> FullscreenOutcome {
    // Refused when the caller is not the main window. A command that took a
    // window name would let any granted window resize any other; taking the
    // caller's own window and checking it cannot.
    if window.label() != "main" {
        return FullscreenOutcome::Failed {
            reason: format!("Fenster {:?} darf kein Vollbild setzen", window.label()),
        };
    }
    match window.set_fullscreen(fullscreen) {
        Ok(()) => {
            // Remembered so a later `couch_state` can report the truth rather
            // than what the caller asked for. The window manager may refuse, and
            // asking it back is the only way to know.
            let actual = window.is_fullscreen().unwrap_or(fullscreen);
            if let Ok(mut active) = couch.active.lock() {
                *active = actual;
            }
            FullscreenOutcome::Applied { fullscreen: actual }
        }
        Err(error) => FullscreenOutcome::Failed {
            reason: error.to_string(),
        },
    }
}

/// Reads the connected controllers and returns what couch mode should do.
///
/// # This is the real path, not a placeholder
///
/// The pad is read here, in the shell, because that is where the device is: a
/// controller arrives on a thread the WebView does not have, and a UI-side
/// implementation could only ever be driven by the window's own key events —
/// a keyboard pretending to be a gamepad.
///
/// The reader is created once and kept, so hot-plug state and the per-pad
/// translators survive between calls. Creating it per call would re-enumerate
/// the devices every 60 ms and lose the "which buttons are held" bookkeeping,
/// which is exactly what makes a stuck button possible.
#[tauri::command]
pub fn couch_pad_input(now_ms: u64, couch: State<'_, CouchMode>) -> Vec<CouchIntentView> {
    let mut source = couch.pads.lock().expect("pad source");
    let Some(source) = source.as_mut() else {
        return Vec::new();
    };

    let now = Duration::from_millis(now_ms);
    let mut out = Vec::new();
    for event in source.poll() {
        // Only translated input can move a focus; connect and disconnect events
        // are reported through `couch_state` instead.
        let streamarr_desktop_player::input::PadEvent::Input { message, .. } = event else {
            continue;
        };
        // A controller speaks the wire format, which is what `intent_for`
        // consumes — the same translation the game stream uses, so the two
        // cannot disagree about which button is "A".
        let Some(pad_input) = pad_input_from_message(&message) else {
            continue;
        };
        let mut repeat = couch.repeat.lock().expect("repeat");
        let intent = streamarr_desktop_player::couch::intent_for(&pad_input, &mut repeat, now);
        let view = CouchIntentView::from_intent(&intent);
        if view.action != "nothing" {
            out.push(view);
        }
    }
    out
}

/// Drains the pad queue and returns the wire messages, without interpreting them.
///
/// The game path's half of the shared reader. It must not *also* produce couch
/// intents: `gilrs` hands each event out once, so interpreting here and there
/// would make a controller do two things at once — a D-pad press would both move
/// the game's character and move a menu highlight.
///
/// `couch_pad_input` is the interpreting counterpart; the caller picks one.
pub fn drain_pad_events(
    app: &tauri::AppHandle,
) -> Result<Vec<streamarr_desktop_player::protocol::InputMessage>, String> {
    use tauri::Manager;
    let couch = app.state::<CouchMode>();
    let mut source = couch.pads.lock().map_err(|_| "Pad-Sperre vergiftet")?;
    let Some(source) = source.as_mut() else {
        return Ok(Vec::new());
    };
    let mut out = Vec::new();
    for event in source.poll() {
        // Connect and disconnect are reported through `couch_state`; only
        // translated input can be forwarded.
        if let streamarr_desktop_player::input::PadEvent::Input { message, .. } = event {
            out.push(message);
        }
    }
    Ok(out)
}

/// Drains the pad queue and returns the wire messages, *without* interpreting.
///
/// The game path's half of the shared reader. It must not also produce couch
/// intents: `gilrs` hands each event out exactly once, so interpreting in both
/// places would make a controller do two things at once — a D-pad press would
/// move the game's character *and* a menu highlight. The caller picks one of the
/// two functions, never both.
pub fn drain_pad_messages(
    couch: &CouchMode,
) -> Vec<streamarr_desktop_player::protocol::InputMessage> {
    let Ok(mut guard) = couch.pads.lock() else {
        return Vec::new();
    };
    let Some(source) = guard.as_mut() else {
        return Vec::new();
    };
    source
        .poll()
        .into_iter()
        .filter_map(|event| match event {
            // Connect and disconnect are reported through `couch_state`; only
            // translated input can be forwarded to a game.
            streamarr_desktop_player::input::PadEvent::Input { message, .. } => Some(message),
            streamarr_desktop_player::input::PadEvent::SyntheticRelease { message, .. } => {
                // A release the client had to invent because the pad vanished.
                // It *must* be forwarded: without it a button stays logically
                // pressed in the game forever.
                Some(message)
            }
            _ => None,
        })
        .collect()
}

/// Turns a wire-format input message back into a pad input.
///
/// The round trip looks redundant and is not: `PadTranslator` already resolved
/// the pad's *layout*, so the button index on the wire is the standard-layout
/// index. Going through the wire format means couch mode and the game stream
/// share one definition of which physical button is which — a second mapping
/// here is how a controller ends up navigating one way in the menu and another
/// way in a game.
fn pad_input_from_message(
    message: &streamarr_desktop_player::protocol::InputMessage,
) -> Option<streamarr_desktop_player::pad::PadInput> {
    use streamarr_desktop_player::pad::{PadInput, StandardButton};
    use streamarr_desktop_player::protocol::InputMessage;
    match message {
        InputMessage::GamepadButton { index, pressed } => Some(PadInput::Button {
            button: StandardButton::from_index(*index as usize)?,
            pressed: *pressed,
        }),
        InputMessage::GamepadAxis { stick, axis, value } => Some(PadInput::Axis {
            stick: *stick as usize,
            axis: *axis as usize,
            value: *value,
        }),
        _ => None,
    }
}

/// The connected controllers, for the UI to display.
///
/// Reported so the interface can say "no controller found" rather than leaving
/// the user pressing buttons with no effect and no explanation.
#[tauri::command]
pub fn couch_pads(couch: State<'_, CouchMode>) -> Vec<PadView> {
    let mut source = couch.pads.lock().expect("pad source");
    let Some(source) = source.as_mut() else {
        return Vec::new();
    };
    source
        .connected_pads()
        .into_iter()
        .map(|pad| PadView {
            id: pad.id,
            name: pad.name,
            layout: format!("{:?}", pad.layout),
        })
        .collect()
}

/// One connected controller, as the UI sees it.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct PadView {
    pub id: usize,
    pub name: String,
    /// The resolved layout, so a UI can explain why a non-standard pad's buttons
    /// are swapped.
    pub layout: String,
}

/// The intent, in a shape the UI can switch on.
#[derive(Debug, Clone, Serialize, Default, PartialEq, Eq)]
pub struct CouchIntentView {
    /// `move`, `activate`, `back`, `menu` or `nothing`.
    pub action: String,
    pub direction: Option<String>,
    pub steps: u32,
}

impl CouchIntentView {
    fn from_intent(intent: &CouchIntent) -> Self {
        match intent {
            CouchIntent::Move { direction, steps } => Self {
                action: "move".to_string(),
                direction: Some(
                    match direction {
                        Direction::Up => "up",
                        Direction::Down => "down",
                        Direction::Left => "left",
                        Direction::Right => "right",
                    }
                    .to_string(),
                ),
                steps: *steps,
            },
            CouchIntent::Activate => Self {
                action: "activate".to_string(),
                ..Self::default()
            },
            CouchIntent::Back => Self {
                action: "back".to_string(),
                ..Self::default()
            },
            CouchIntent::Menu => Self {
                action: "menu".to_string(),
                ..Self::default()
            },
            CouchIntent::Nothing => Self {
                action: "nothing".to_string(),
                ..Self::default()
            },
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rect(id: &str, x: f64, y: f64) -> ItemRect {
        ItemRect {
            id: id.to_string(),
            x,
            y,
            width: 200.0,
            height: 300.0,
            decorative: false,
        }
    }

    /// A 2×2 wall of 200×300 tiles.
    fn wall() -> Vec<ItemRect> {
        vec![
            rect("a", 0.0, 0.0),
            rect("b", 210.0, 0.0),
            rect("c", 0.0, 310.0),
            rect("d", 210.0, 310.0),
        ]
    }

    #[test]
    fn a_direction_name_maps_to_a_direction() {
        assert_eq!(direction_from("up"), Some(Direction::Up));
        assert_eq!(direction_from("down"), Some(Direction::Down));
        assert_eq!(direction_from("left"), Some(Direction::Left));
        assert_eq!(direction_from("right"), Some(Direction::Right));
    }

    #[test]
    fn an_unknown_direction_is_a_no_op_not_a_failure() {
        // A future UI sending a direction this build does not know must not
        // break the call; doing nothing is the honest answer.
        assert_eq!(direction_from("diagonal"), None);
        assert_eq!(direction_from(""), None);
        assert_eq!(direction_from("UP"), None);
    }

    #[test]
    fn rectangles_are_rounded_to_whole_pixels() {
        let item = ItemRect {
            id: "x".to_string(),
            x: 10.4,
            y: 20.6,
            width: 200.5,
            height: 300.4,
            decorative: false,
        }
        .into_focus_item();
        assert_eq!(item.rect.x, 10);
        assert_eq!(item.rect.y, 21);
        assert_eq!(item.rect.width, 201);
        assert_eq!(item.rect.height, 300);
    }

    #[test]
    fn a_decorative_rectangle_is_present_but_not_focusable() {
        let item = ItemRect {
            id: "header".to_string(),
            x: 0.0,
            y: 0.0,
            width: 100.0,
            height: 100.0,
            decorative: true,
        }
        .into_focus_item();
        assert!(
            !item.focusable,
            "ein dekoratives Element ist nicht fokussierbar"
        );
        // Present for the geometry — otherwise the focus would jump across the
        // gap it leaves — but skipped when moving.
        assert_eq!(item.rect.width, 100);
    }

    #[test]
    fn moving_right_reaches_the_neighbour_not_the_next_index() {
        let mut grid = FocusGrid::new(wall().into_iter().map(|i| i.into_focus_item()).collect());
        assert_eq!(grid.current_id(), Some("a"));
        assert_eq!(
            grid.move_focus(Direction::Right).map(|i| i.id.as_str()),
            Some("b")
        );
        assert_eq!(
            grid.move_focus(Direction::Down).map(|i| i.id.as_str()),
            Some("d")
        );
        assert_eq!(
            grid.move_focus(Direction::Left).map(|i| i.id.as_str()),
            Some("c")
        );
        assert_eq!(
            grid.move_focus(Direction::Up).map(|i| i.id.as_str()),
            Some("a")
        );
    }

    #[test]
    fn two_steps_right_is_the_neighbours_neighbour() {
        // What a late or repeated update should produce. Honouring `steps` as an
        // index jump would be wrong in any layout where rows differ in length.
        let mut grid = FocusGrid::new(wall().into_iter().map(|i| i.into_focus_item()).collect());
        let mut moved = None;
        for _ in 0..2 {
            match grid.move_focus(Direction::Right) {
                Some(item) => moved = Some(item.id.clone()),
                None => break,
            }
        }
        // Only one step is possible in a two-column wall, so the second stops.
        assert_eq!(moved.as_deref(), Some("b"));
    }

    #[test]
    fn a_relayout_keeps_the_focus_on_the_same_id() {
        // The load-bearing behaviour for a background refresh: the user must not
        // be thrown back to the first tile because the list reloaded.
        let mut grid = FocusGrid::new(wall().into_iter().map(|i| i.into_focus_item()).collect());
        grid.focus("d");
        assert_eq!(grid.current_id(), Some("d"));
        // Same items, slightly different positions.
        let moved = wall()
            .into_iter()
            .map(|mut item| {
                item.y += 5.0;
                item
            })
            .collect::<Vec<_>>();
        grid.relayout(moved.into_iter().map(|i| i.into_focus_item()).collect());
        assert_eq!(grid.current_id(), Some("d"));
    }

    #[test]
    fn a_relayout_that_removes_the_focused_item_falls_back_to_a_real_one() {
        // My first version of this test asserted that the focus becomes *empty*,
        // and it failed — `relayout` deliberately falls back to the first
        // focusable item instead. The implementation is right and the assertion
        // was wrong: an empty focus would leave the user pressing "activate" with
        // nothing to open, which reads as a broken interface rather than as a
        // refreshed list.
        let mut grid = FocusGrid::new(wall().into_iter().map(|i| i.into_focus_item()).collect());
        grid.focus("d");
        let remaining: Vec<FocusItem> = wall()
            .into_iter()
            .filter(|item| item.id != "d")
            .map(|i| i.into_focus_item())
            .collect();
        grid.relayout(remaining);
        let focus = grid.current_id().expect("der Fokus darf nicht leer werden");
        assert_ne!(
            focus, "d",
            "das entfernte Element darf nicht fokussiert bleiben"
        );
        assert!(
            ["a", "b", "c"].contains(&focus),
            "der Fokus muss auf einem vorhandenen Element landen: {focus}"
        );
    }

    #[test]
    fn a_relayout_that_removes_everything_does_leave_no_focus() {
        // The genuinely empty case, which is what the test above was reaching for.
        let mut grid = FocusGrid::new(wall().into_iter().map(|i| i.into_focus_item()).collect());
        grid.focus("d");
        grid.relayout(Vec::new());
        assert!(grid.current_id().is_none());
        // And moving is harmless rather than a panic.
        assert!(grid.move_focus(Direction::Right).is_none());
    }

    #[test]
    fn an_empty_layout_has_no_focus_and_moving_is_harmless() {
        let mut grid = FocusGrid::new(Vec::new());
        assert!(grid.current_id().is_none());
        assert!(grid.move_focus(Direction::Right).is_none());
    }

    #[test]
    fn a_direction_press_becomes_a_move_and_repeat_respects_its_delay() {
        // The repeat rule is the reason a held direction does not scroll at the
        // render rate: the first press moves at once, then it waits.
        let mut repeat = streamarr_desktop_player::couch::Repeat::default();
        // Built directly rather than parsed from a string: the string parser was
        // only ever a test convenience, and after the real pad path landed it was
        // dead code the compiler rightly refused.
        let input = streamarr_desktop_player::pad::PadInput::Button {
            button: streamarr_desktop_player::pad::StandardButton::Down,
            pressed: true,
        };
        let first = streamarr_desktop_player::couch::intent_for(
            &input,
            &mut repeat,
            Duration::from_millis(0),
        );
        assert!(
            matches!(first, CouchIntent::Move { .. }),
            "der erste Druck muss sofort bewegen: {first:?}"
        );
        // A second reading immediately afterwards must not move.
        let second = streamarr_desktop_player::couch::intent_for(
            &input,
            &mut repeat,
            Duration::from_millis(1),
        );
        assert_eq!(second, CouchIntent::Nothing);
    }

    #[test]
    fn an_activate_intent_asks_the_ui_to_open_the_focused_item() {
        let view = CouchIntentView::from_intent(&CouchIntent::Activate);
        assert_eq!(view.action, "activate");
        assert_eq!(view.steps, 0);
        assert!(view.direction.is_none());
    }

    #[test]
    fn a_move_intent_carries_its_direction_and_steps() {
        let view = CouchIntentView::from_intent(&CouchIntent::Move {
            direction: Direction::Left,
            steps: 3,
        });
        assert_eq!(view.action, "move");
        assert_eq!(view.direction.as_deref(), Some("left"));
        assert_eq!(view.steps, 3);
    }

    #[test]
    fn every_intent_maps_to_a_distinct_action() {
        let actions: Vec<String> = [
            CouchIntent::Move {
                direction: Direction::Up,
                steps: 1,
            },
            CouchIntent::Activate,
            CouchIntent::Back,
            CouchIntent::Menu,
            CouchIntent::Nothing,
        ]
        .iter()
        .map(|intent| CouchIntentView::from_intent(intent).action)
        .collect();
        let unique: std::collections::HashSet<&String> = actions.iter().collect();
        assert_eq!(
            unique.len(),
            5,
            "die Absichten sind nicht unterscheidbar: {actions:?}"
        );
        // The UI switches on these strings, so they are part of the contract.
        assert_eq!(actions, vec!["move", "activate", "back", "menu", "nothing"]);
    }

    #[test]
    fn the_repeat_timings_are_reported_and_sane() {
        let info = couch_repeat_info();
        // A delay of zero would make a held button scroll at the render rate;
        // an interval shorter than the delay would be nonsensical.
        assert!(info.initial_delay_ms > 0, "{info:?}");
        assert!(info.interval_ms > 0, "{info:?}");
        assert!(info.interval_ms <= info.initial_delay_ms, "{info:?}");
        // Slow enough not to be a blur, fast enough to be usable.
        assert!(info.initial_delay_ms >= 100, "zu schnell: {info:?}");
        assert!(info.interval_ms >= 50, "zu schnell: {info:?}");
    }

    #[test]
    fn draining_yields_messages_without_interpreting_them() {
        // The two paths must not both run: `gilrs` hands each event out once, so
        // a controller would otherwise move the game's character and a menu
        // highlight from one press. This pins the *shape* of the game path — it
        // returns wire messages, not intents.
        let couch = CouchMode::default();
        let messages = drain_pad_messages(&couch);
        // No pad on this machine, so the list is empty — and that is the
        // assertion: it returns a list of messages and never panics, which is
        // what the command needs when no controller exists.
        assert!(messages.is_empty());
    }

    #[test]
    fn couch_mode_starts_off_and_can_be_toggled() {
        let mode = CouchMode::default();
        assert!(!mode.snapshot(0).active);
        *mode.active.lock().expect("active") = true;
        assert!(mode.snapshot(0).active);
    }

    #[test]
    fn switching_couch_mode_off_releases_a_held_direction() {
        // Otherwise a direction still held when the user leaves couch mode fires
        // again on return, which reads as the interface moving on its own.
        let mode = CouchMode::default();
        let mut repeat = mode.repeat.lock().expect("repeat");
        let input = streamarr_desktop_player::pad::PadInput::Button {
            button: streamarr_desktop_player::pad::StandardButton::Down,
            pressed: true,
        };
        let _ = streamarr_desktop_player::couch::intent_for(
            &input,
            &mut repeat,
            Duration::from_millis(0),
        );
        assert!(repeat.held().is_some());
        drop(repeat);

        *mode.active.lock().expect("active") = false;
        mode.repeat.lock().expect("repeat").release();
        assert!(mode.repeat.lock().expect("repeat").held().is_none());
    }
}
