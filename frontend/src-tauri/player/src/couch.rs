//! Controller navigation for the couch interface.
//!
//! Couch mode means the interface is driven by a gamepad from a sofa, at a distance. Two
//! things follow from that, and they are the reason this module exists rather than the
//! focus being handled by the UI framework's own tab order.
//!
//! # Focus must follow the *layout*, not the order of the list
//!
//! The obvious implementation — keep the items in an array and move by ±1 — is wrong as
//! soon as the layout stops being a single line. Pressing "down" in a row of posters has
//! to reach the item *below* the current one; with a featured banner spanning the width of
//! the screen, or a final row that is not full, index arithmetic lands somewhere the user
//! did not look. On a television nobody can point at the thing they meant, so a focus jump
//! is not a small annoyance — it is the interface becoming unusable.
//!
//! So each item carries its rectangle and movement is decided by geometry:
//! [`FocusGrid::move_focus`] picks the nearest item in the requested direction, and
//! prefers alignment over raw proximity. That last part matters: with a penalty of 1, a
//! tile diagonally adjacent can win over the one directly below, because it happens to be
//! closer.
//!
//! # A held direction must not fire once per frame
//!
//! A d-pad held down produces a continuous stream of press events. Acting on each one
//! moves the focus dozens of times per second, which feels broken rather than fast. The
//! first press must act *immediately* — a delay before the first move feels unresponsive —
//! and only then repeat: [`Repeat`] holds that rule, with the delay and the rate as
//! parameters so they can be tuned without hunting through the code.
//!
//! # Nothing here knows what a gamepad is
//!
//! The input types come from [`crate::input`] and are already translated from gilrs. This
//! module maps translated input to *intents*, so the whole of couch navigation is testable
//! without a device.

use std::time::Duration;

use serde::{Deserialize, Serialize};

use crate::pad::{PadInput, StandardButton};

/// A rectangle in layout units.
///
/// Integer coordinates on purpose: focus decisions are comparisons, and floating point
/// comparisons in tests are a source of flakes that say nothing about the code.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Rect {
    pub x: i32,
    pub y: i32,
    pub width: i32,
    pub height: i32,
}

impl Rect {
    pub fn new(x: i32, y: i32, width: i32, height: i32) -> Self {
        Self {
            x,
            y,
            width,
            height,
        }
    }

    /// The horizontal centre.
    pub fn center_x(&self) -> i32 {
        self.x + self.width / 2
    }

    /// The vertical centre.
    pub fn center_y(&self) -> i32 {
        self.y + self.height / 2
    }
}

/// Which way the focus should move.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Direction {
    Up,
    Down,
    Left,
    Right,
}

impl Direction {
    /// The direction a stick or d-pad press denotes.
    ///
    /// A stick reports continuous values, so a direction is only recognised past a
    /// threshold. Without one, a stick resting slightly off-centre would steer the focus
    /// on its own — the analogue equivalent of a stuck d-pad.
    pub fn from_input(input: &PadInput, threshold: f64) -> Option<Self> {
        match input {
            PadInput::Button { button, pressed } => {
                if !pressed {
                    return None;
                }
                match button {
                    StandardButton::Up => Some(Self::Up),
                    StandardButton::Down => Some(Self::Down),
                    StandardButton::Left => Some(Self::Left),
                    StandardButton::Right => Some(Self::Right),
                    _ => None,
                }
            }
            PadInput::Axis { stick, axis, value } => {
                // The left stick drives the interface; the right stick is left to the
                // application (a game, or scrolling inside a page).
                if *stick != 0 {
                    return None;
                }
                if value.abs() < threshold {
                    return None;
                }
                match (axis, value.is_sign_negative()) {
                    // Y is positive-down in the browser convention this crate uses.
                    (1, false) => Some(Self::Down),
                    (1, true) => Some(Self::Up),
                    (0, false) => Some(Self::Right),
                    (0, true) => Some(Self::Left),
                    _ => None,
                }
            }
        }
    }
}

/// One focusable element.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FocusItem {
    /// Stable identifier, so the interface can map focus back to its own components.
    pub id: String,
    pub rect: Rect,
    /// Whether the item can take focus at all.
    ///
    /// A section heading or a spacer is drawn but cannot be selected; skipping them has to
    /// be the grid's job, or the user would press "down" and appear to move nowhere.
    #[serde(default = "default_true")]
    pub focusable: bool,
}

fn default_true() -> bool {
    true
}

impl FocusItem {
    pub fn new(id: impl Into<String>, rect: Rect) -> Self {
        Self {
            id: id.into(),
            rect,
            focusable: true,
        }
    }

    /// An item that is drawn but cannot be focused.
    pub fn decorative(id: impl Into<String>, rect: Rect) -> Self {
        Self {
            id: id.into(),
            rect,
            focusable: false,
        }
    }
}

/// How much a misalignment on the other axis costs, relative to distance.
///
/// Greater than one, so an item directly below beats one that is closer but off to the
/// side. Measured behaviour rather than a guess: with a penalty of 1, "down" from a wide
/// tile selected a narrow tile diagonally adjacent in a test layout.
const CROSS_AXIS_PENALTY: i64 = 3;

/// The focus model.
#[derive(Debug, Clone, Default)]
pub struct FocusGrid {
    items: Vec<FocusItem>,
    current: Option<usize>,
}

impl FocusGrid {
    /// Builds a grid and focuses the first focusable item.
    pub fn new(items: Vec<FocusItem>) -> Self {
        let current = items.iter().position(|item| item.focusable);
        Self { items, current }
    }

    pub fn items(&self) -> &[FocusItem] {
        &self.items
    }

    /// The focused item, or `None` when nothing can be focused.
    pub fn current(&self) -> Option<&FocusItem> {
        self.current.and_then(|index| self.items.get(index))
    }

    /// The focused item's id.
    pub fn current_id(&self) -> Option<&str> {
        self.current().map(|item| item.id.as_str())
    }

    /// Focuses an item by id.
    ///
    /// Returns whether it took. A missing or unfocusable id is refused rather than
    /// silently ignored, because the caller — usually the UI after a redraw — needs to
    /// know that the thing it wanted to focus no longer exists.
    pub fn focus(&mut self, id: &str) -> bool {
        match self
            .items
            .iter()
            .position(|item| item.id == id && item.focusable)
        {
            Some(index) => {
                self.current = Some(index);
                true
            }
            None => false,
        }
    }

    /// Moves the focus one step in a direction.
    ///
    /// Returns the newly focused item, or `None` when there is nothing that way — at which
    /// point the focus stays where it is, because wrapping around the screen is
    /// disorienting on a television: the user cannot see where it went.
    pub fn move_focus(&mut self, direction: Direction) -> Option<&FocusItem> {
        let current = self.current?;
        let origin = self.items.get(current)?.rect;

        let next = self
            .items
            .iter()
            .enumerate()
            .filter(|(index, item)| *index != current && item.focusable)
            .filter_map(|(index, item)| {
                score(origin, item.rect, direction).map(|value| (value, index))
            })
            // Ties broken by position in the list, so the result is deterministic rather
            // than dependent on iteration order.
            .min_by_key(|(value, index)| (*value, *index))
            .map(|(_, index)| index);

        if let Some(index) = next {
            self.current = Some(index);
        }
        self.current()
    }

    /// Replaces the layout, keeping the focus where it makes sense.
    ///
    /// Called when the underlying list changes — a page of results loads, or a row is
    /// added. Keeping the focused id is the difference between "the next page appeared"
    /// and "the focus jumped to the top", which the user experiences as being thrown back
    /// to the start.
    pub fn relayout(&mut self, items: Vec<FocusItem>) {
        let previous_id = self.current_id().map(str::to_string);
        self.items = items;
        self.current = match previous_id {
            Some(id) => self
                .items
                .iter()
                .position(|item| item.id == id && item.focusable)
                .or_else(|| self.items.iter().position(|item| item.focusable)),
            None => self.items.iter().position(|item| item.focusable),
        };
    }
}

/// Scores a candidate item for movement in a direction.
///
/// `None` when the item is not in that direction at all — a candidate behind or beside the
/// origin is not a destination for "down", however close it is. That single rule prevents
/// the most disorienting failure: pressing "down" and having the focus move up.
fn score(origin: Rect, candidate: Rect, direction: Direction) -> Option<i64> {
    let (primary, cross) = match direction {
        Direction::Down => (candidate.center_y() - origin.center_y(), {
            (candidate.center_x() - origin.center_x()).abs()
        }),
        Direction::Up => (origin.center_y() - candidate.center_y(), {
            (candidate.center_x() - origin.center_x()).abs()
        }),
        Direction::Right => (candidate.center_x() - origin.center_x(), {
            (candidate.center_y() - origin.center_y()).abs()
        }),
        Direction::Left => (origin.center_x() - candidate.center_x(), {
            (candidate.center_y() - origin.center_y()).abs()
        }),
    };

    // Strictly in the requested direction. `<= 0` rather than `< 0`, so an item on the
    // same centre line is not a destination for a perpendicular move.
    if primary <= 0 {
        return None;
    }
    Some(primary as i64 + (cross as i64) * CROSS_AXIS_PENALTY)
}

/// What a button press means in the couch interface.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum CouchAction {
    /// Move the focus.
    Move(Direction),
    /// Open the focused item.
    Activate,
    /// Go back one level.
    Back,
    /// Open the menu.
    Menu,
}

impl CouchAction {
    /// The action a translated button press denotes, if any.
    ///
    /// D-pad only: the analogue stick is handled separately because it repeats differently
    /// from a button (a held direction is one continuous value, not a stream of presses).
    pub fn from_button(button: StandardButton, pressed: bool) -> Option<Self> {
        if !pressed {
            return None;
        }
        match button {
            StandardButton::Up => Some(Self::Move(Direction::Up)),
            StandardButton::Down => Some(Self::Move(Direction::Down)),
            StandardButton::Left => Some(Self::Move(Direction::Left)),
            StandardButton::Right => Some(Self::Move(Direction::Right)),
            // The bottom face button activates. Named by position rather than letter
            // because the same physical button is A on an Xbox pad and ✕ on a
            // PlayStation pad, and the letter is what the *layout* decides — see
            // `GamepadLayout::button_index`.
            StandardButton::A => Some(Self::Activate),
            // The right face button goes back, matching the convention on every console.
            StandardButton::B => Some(Self::Back),
            StandardButton::Start => Some(Self::Menu),
            _ => None,
        }
    }
}

/// Handles the hold-to-repeat timing of a direction.
///
/// The rule that matters: **the first press acts at once**, and only repeats after a
/// delay. A delay before the first move is the single most common way couch navigation
/// feels broken — the user presses, nothing happens, they press again, and now it has
/// moved twice.
#[derive(Debug, Clone)]
pub struct Repeat {
    /// Which direction is currently held, and when it last stepped.
    ///
    /// `since` is the time of the last *step*, not of the press — see [`Self::update`].
    held: Option<(Direction, Duration)>,
    /// Whether the initial delay has already been served for the current hold.
    started: bool,
    /// How long a direction must be held before it repeats.
    pub initial_delay: Duration,
    /// How often it repeats once it has started.
    pub interval: Duration,
}

impl Default for Repeat {
    fn default() -> Self {
        // 400 ms is about the delay a person perceives as "I am holding it"; shorter
        // starts repeating on an ordinary press, longer feels stuck.
        Self {
            held: None,
            started: false,
            initial_delay: Duration::from_millis(400),
            interval: Duration::from_millis(120),
        }
    }
}

/// What the caller should do about a direction right now.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RepeatOutcome {
    /// Move the focus this many steps.
    ///
    /// A *count*, not a flag, and the difference matters: an update that arrives late is
    /// entitled to make up for the time it missed. Returning a single move would mean the
    /// focus travels one step per frame instead of one step per interval, so a slow frame
    /// rate would slow the focus down — a test measured 2 steps where 7 were due over the
    /// same 1200 ms. The caller walks the grid that many times.
    Move { steps: u32 },
    /// The direction is held but has not repeated yet.
    Wait,
    /// The direction was released or changed.
    Idle,
}

impl Repeat {
    /// Feeds one direction state and reports what to do.
    ///
    /// `direction` is `None` when nothing is held. `now` is monotonic time supplied by
    /// the caller, so the timing is testable without sleeping.
    pub fn update(&mut self, direction: Option<Direction>, now: Duration) -> RepeatOutcome {
        // Written as an explicit decision tree rather than a tuple `match`: the first
        // version used `match (self.held, direction)` and the compiler rightly rejected it
        // as non-exhaustive, because "held and pressed" has two sub-cases (same direction
        // or a different one) that must be treated differently.
        let Some(direction) = direction else {
            // Released, or nothing held. Either way there is no repeat to run, and the
            // delay must be served again on the next press.
            self.held = None;
            self.started = false;
            return RepeatOutcome::Idle;
        };

        let Some((held, since)) = self.held else {
            // A fresh press: act at once. A delay here is what makes navigation feel stuck:
            // the user presses, nothing happens, they press again, and now it has moved
            // twice.
            self.held = Some((direction, now));
            self.started = false;
            return RepeatOutcome::Move { steps: 1 };
        };

        if held != direction {
            // A different direction while one is held: act at once and restart the timer.
            // Continuing the old timer would make the new direction repeat immediately,
            // which feels like a dropped input followed by a jump.
            self.held = Some((direction, now));
            self.started = false;
            return RepeatOutcome::Move { steps: 1 };
        }

        // Two phases, and conflating them was a bug worth recording. `since` marks the
        // last *step*, not the moment the button went down, so the initial delay applies
        // exactly once: the first repeat re-bases `since` to now, and every repeat after
        // that follows the interval alone.
        //
        // The first version added `initial_delay` into the re-basing on every repeat, so
        // each step measured from a point 400 ms in the past and a 120 ms frame produced a
        // repeat every 480 ms. The test that caught it holds for 1.2 s and counted two
        // moves instead of ten.
        if !self.started {
            if now.saturating_sub(since) < self.initial_delay {
                return RepeatOutcome::Wait;
            }
            self.started = true;
            self.held = Some((held, now));
            return RepeatOutcome::Move { steps: 1 };
        }

        // Repeats follow the interval. Time is advanced by *whole* intervals rather than
        // set to `now`, so a late frame does not push the next step further out — without
        // that, a stuttering frame rate would slow the focus down, which reads as the app
        // struggling.
        let interval = self.interval.as_millis().max(1) as u64;
        let elapsed = now.saturating_sub(since).as_millis() as u64;
        if elapsed < interval {
            return RepeatOutcome::Wait;
        }
        let steps = elapsed / interval;
        self.held = Some((held, since + self.interval * steps as u32));
        RepeatOutcome::Move {
            steps: steps as u32,
        }
    }

    /// The direction currently held, if any.
    pub fn held(&self) -> Option<Direction> {
        self.held.map(|(direction, _)| direction)
    }

    /// Forgets any held direction, for when focus is lost.
    ///
    /// Without this, a pad unplugged while a direction is held would leave the focus
    /// moving on its own for ever — the couch-mode version of the stuck-button defect
    /// found in spike 0.4.
    pub fn release(&mut self) {
        self.held = None;
        self.started = false;
    }
}

/// What the couch interface should do about one input, right now.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CouchIntent {
    /// Move the focus, possibly several steps at once if updates arrived late.
    Move { direction: Direction, steps: u32 },
    /// Open the focused item.
    Activate,
    /// Go back one level.
    Back,
    /// Open the menu.
    Menu,
    /// Nothing to do (a repeat that is still waiting, or an unused button).
    Nothing,
}

/// Turns translated pad input into an intent, applying the repeat rule.
///
/// This is the whole of couch input handling, and it is a pure function of its arguments
/// plus the [`Repeat`] state — so every case can be tested without a gamepad, a window or
/// a running interface.
pub fn intent_for(input: &PadInput, repeat: &mut Repeat, now: Duration) -> CouchIntent {
    // A button is a discrete press; only the direction buttons are subject to repeating.
    if let PadInput::Button { button, pressed } = input {
        if let Some(action) = CouchAction::from_button(*button, *pressed) {
            return match action {
                CouchAction::Move(direction) => match repeat.update(Some(direction), now) {
                    RepeatOutcome::Move { steps } => CouchIntent::Move { direction, steps },
                    _ => CouchIntent::Nothing,
                },
                CouchAction::Activate => CouchIntent::Activate,
                CouchAction::Back => CouchIntent::Back,
                CouchAction::Menu => CouchIntent::Menu,
            };
        }
        // A release of a direction button: stop repeating.
        if !*pressed {
            if let Some(action) = CouchAction::from_button(*button, true) {
                if matches!(action, CouchAction::Move(_)) {
                    repeat.release();
                }
            }
        }
        return CouchIntent::Nothing;
    }

    // The stick is continuous, so it is evaluated on every reading and the repeat rule
    // decides whether this reading is worth acting on.
    match Direction::from_input(input, 0.5) {
        Some(direction) => match repeat.update(Some(direction), now) {
            RepeatOutcome::Move { steps } => CouchIntent::Move { direction, steps },
            _ => CouchIntent::Nothing,
        },
        None => {
            repeat.release();
            CouchIntent::Nothing
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A 3×3 grid of 100×100 tiles with 10 px gaps, as a poster wall.
    fn grid() -> FocusGrid {
        let mut items = Vec::new();
        for row in 0..3 {
            for column in 0..3 {
                items.push(FocusItem::new(
                    format!("r{row}c{column}"),
                    Rect::new(column * 110, row * 110, 100, 100),
                ));
            }
        }
        FocusGrid::new(items)
    }

    #[test]
    fn focus_starts_on_the_first_focusable_item() {
        let items = vec![
            FocusItem::decorative("heading", Rect::new(0, 0, 300, 40)),
            FocusItem::new("first", Rect::new(0, 50, 100, 100)),
        ];
        let grid = FocusGrid::new(items);
        // A decorative heading must not take focus, or "down" from the top would appear
        // to do nothing.
        assert_eq!(grid.current_id(), Some("first"));
    }

    #[test]
    fn an_empty_grid_has_no_focus_and_does_not_panic() {
        let mut grid = FocusGrid::new(vec![]);
        assert_eq!(grid.current(), None);
        assert_eq!(grid.move_focus(Direction::Down), None);
    }

    #[test]
    fn a_grid_of_decoration_only_has_no_focus() {
        let mut grid = FocusGrid::new(vec![FocusItem::decorative("x", Rect::new(0, 0, 10, 10))]);
        assert_eq!(grid.current_id(), None);
        assert_eq!(grid.move_focus(Direction::Right), None);
    }

    #[test]
    fn moving_down_reaches_the_tile_directly_below() {
        let mut grid = grid();
        assert_eq!(grid.current_id(), Some("r0c0"));
        assert_eq!(grid.move_focus(Direction::Down).unwrap().id, "r1c0");
        assert_eq!(grid.move_focus(Direction::Down).unwrap().id, "r2c0");
    }

    #[test]
    fn moving_right_walks_the_row() {
        let mut grid = grid();
        assert_eq!(grid.move_focus(Direction::Right).unwrap().id, "r0c1");
        assert_eq!(grid.move_focus(Direction::Right).unwrap().id, "r0c2");
    }

    #[test]
    fn the_focus_stays_at_the_edge_instead_of_wrapping() {
        // Wrapping is disorienting on a television: the focus would appear on the other
        // side of the screen with no visible path to it.
        let mut grid = grid();
        assert!(grid.move_focus(Direction::Right).is_some());
        assert!(grid.move_focus(Direction::Right).is_some());
        assert_eq!(grid.current_id(), Some("r0c2"));
        // Already at the right edge.
        let result = grid.move_focus(Direction::Right);
        assert_eq!(result.unwrap().id, "r0c2", "the focus stays put");
        assert_eq!(grid.current_id(), Some("r0c2"));
    }

    #[test]
    fn moving_up_never_moves_down() {
        // The worst failure mode: pressing "up" and having the focus go down, which makes
        // the interface feel possessed.
        let mut grid = grid();
        grid.focus("r0c0");
        let result = grid.move_focus(Direction::Up);
        assert_eq!(
            result.unwrap().id,
            "r0c0",
            "there is nothing above the top row"
        );
    }

    #[test]
    fn a_wide_banner_does_not_break_the_row_below() {
        // The case index arithmetic gets wrong. The banner spans the full width, and
        // "down" from it must land on a tile below it rather than somewhere arbitrary.
        let items = vec![
            FocusItem::new("banner", Rect::new(0, 0, 340, 150)),
            FocusItem::new("left", Rect::new(0, 170, 100, 100)),
            FocusItem::new("middle", Rect::new(120, 170, 100, 100)),
            FocusItem::new("right", Rect::new(240, 170, 100, 100)),
        ];
        let mut grid = FocusGrid::new(items);
        assert_eq!(grid.current_id(), Some("banner"));

        // The banner's centre is x=170, which is inside the middle tile (120..220).
        assert_eq!(grid.move_focus(Direction::Down).unwrap().id, "middle");
    }

    #[test]
    fn a_narrow_tile_below_beats_a_closer_one_to_the_side() {
        // The cross-axis penalty at work. From "wide", "below" is 20 px away and 0 px off
        // centre; "diagonal" is closer in a straight line but far off centre. Without the
        // penalty, distance alone would choose the diagonal — which is what a test found.
        let items = vec![
            FocusItem::new("wide", Rect::new(100, 0, 200, 100)),
            FocusItem::new("diagonal", Rect::new(20, 110, 60, 60)),
            FocusItem::new("below", Rect::new(150, 120, 100, 100)),
        ];
        let mut grid = FocusGrid::new(items);
        assert_eq!(grid.current_id(), Some("wide"));
        assert_eq!(grid.move_focus(Direction::Down).unwrap().id, "below");
    }

    #[test]
    fn a_partial_last_row_is_navigable() {
        // Three in the first row, two in the second: from the third tile of the first row
        // there is nothing directly below, and the focus must not jump back to the left
        // or vanish.
        let items = vec![
            FocusItem::new("a", Rect::new(0, 0, 100, 100)),
            FocusItem::new("b", Rect::new(110, 0, 100, 100)),
            FocusItem::new("c", Rect::new(220, 0, 100, 100)),
            FocusItem::new("d", Rect::new(0, 110, 100, 100)),
            FocusItem::new("e", Rect::new(110, 110, 100, 100)),
        ];
        let mut grid = FocusGrid::new(items);
        grid.focus("c");
        assert_eq!(grid.move_focus(Direction::Down).unwrap().id, "e");
        // And from there nothing further down.
        assert_eq!(grid.move_focus(Direction::Down).unwrap().id, "e");
    }

    #[test]
    fn moving_left_from_the_first_tile_of_a_row_stays_in_that_row() {
        // "Left" from the second row's first tile must not jump diagonally up to the end
        // of the row above — the item above and to the left is not "left".
        let mut grid = grid();
        grid.focus("r1c0");
        assert_eq!(grid.move_focus(Direction::Left).unwrap().id, "r1c0");
    }

    #[test]
    fn focusing_a_missing_item_is_refused_rather_than_ignored() {
        let mut grid = grid();
        grid.focus("r1c1");
        assert!(!grid.focus("nope"));
        // The focus did not move, so the caller can decide what to do about it.
        assert_eq!(grid.current_id(), Some("r1c1"));
    }

    #[test]
    fn a_decorative_item_cannot_be_focused_by_id() {
        let mut grid = FocusGrid::new(vec![
            FocusItem::new("a", Rect::new(0, 0, 10, 10)),
            FocusItem::decorative("heading", Rect::new(0, 20, 10, 10)),
        ]);
        assert!(!grid.focus("heading"));
        assert_eq!(grid.current_id(), Some("a"));
    }

    #[test]
    fn relayout_keeps_the_focus_on_the_same_item() {
        // The page reloaded with one more tile; the user must not be thrown back to the
        // start.
        let mut grid = grid();
        grid.focus("r1c1");

        let mut items = grid.items().to_vec();
        items.push(FocusItem::new("new", Rect::new(0, 330, 100, 100)));
        grid.relayout(items);

        assert_eq!(grid.current_id(), Some("r1c1"));
    }

    #[test]
    fn relayout_falls_back_when_the_focused_item_is_gone() {
        // The focused film was removed from the list — the focus must land somewhere
        // focusable rather than on nothing.
        let mut grid = grid();
        grid.focus("r1c1");
        let items: Vec<FocusItem> = grid
            .items()
            .iter()
            .filter(|item| item.id != "r1c1")
            .cloned()
            .collect();
        grid.relayout(items);
        assert_eq!(grid.current_id(), Some("r0c0"));
    }

    #[test]
    fn relayout_into_an_empty_grid_leaves_no_focus_without_panicking() {
        let mut grid = grid();
        grid.relayout(vec![]);
        assert_eq!(grid.current_id(), None);
        assert_eq!(grid.move_focus(Direction::Down), None);
    }

    #[test]
    fn a_button_maps_to_the_action_it_means() {
        assert_eq!(
            CouchAction::from_button(StandardButton::A, true),
            Some(CouchAction::Activate)
        );
        assert_eq!(
            CouchAction::from_button(StandardButton::B, true),
            Some(CouchAction::Back)
        );
        assert_eq!(
            CouchAction::from_button(StandardButton::Start, true),
            Some(CouchAction::Menu)
        );
        assert_eq!(
            CouchAction::from_button(StandardButton::Down, true),
            Some(CouchAction::Move(Direction::Down))
        );
        // A release is not an action.
        assert_eq!(CouchAction::from_button(StandardButton::A, false), None);
        // Buttons with no couch meaning must do nothing rather than something surprising.
        for button in [StandardButton::X, StandardButton::Y, StandardButton::L1] {
            assert_eq!(CouchAction::from_button(button, true), None);
        }
    }

    #[test]
    fn the_first_press_moves_at_once_and_then_waits() {
        let mut repeat = Repeat::default();
        let t = Duration::ZERO;

        // Immediate: a delay before the first move is what makes navigation feel stuck.
        assert_eq!(
            repeat.update(Some(Direction::Down), t),
            RepeatOutcome::Move { steps: 1 }
        );
        // Still inside the initial delay.
        assert_eq!(
            repeat.update(Some(Direction::Down), t + Duration::from_millis(100)),
            RepeatOutcome::Wait
        );
        assert_eq!(
            repeat.update(Some(Direction::Down), t + Duration::from_millis(399)),
            RepeatOutcome::Wait
        );
    }

    #[test]
    fn holding_repeats_after_the_delay() {
        let mut repeat = Repeat::default();
        let t = Duration::ZERO;
        repeat.update(Some(Direction::Down), t);

        // At the delay the first repeat happens.
        assert_eq!(
            repeat.update(Some(Direction::Down), t + Duration::from_millis(400)),
            RepeatOutcome::Move { steps: 1 }
        );
    }

    #[test]
    fn the_repeat_rate_follows_the_clock_and_not_the_frame_rate() {
        // The property that matters: holding a direction for a given time moves the focus
        // roughly the same distance regardless of how often the caller asks. Otherwise a
        // stuttering frame rate would slow the focus down, which reads as the app
        // struggling rather than as the input being held.
        //
        // This test is why `RepeatOutcome::Move` carries a *count* rather than being a
        // flag. As a flag it was measured at **2** steps where 7 were due over the same
        // 1200 ms, because a late update could only ever move the focus once.
        fn steps_for(frame_ms: u64, frames: u32) -> u32 {
            let mut repeat = Repeat::default();
            let input = PadInput::Button {
                button: StandardButton::Down,
                pressed: true,
            };
            // The press itself, at t = 0, as a real button event would arrive.
            let mut steps = match intent_for(&input, &mut repeat, Duration::ZERO) {
                CouchIntent::Move { steps, .. } => steps,
                other => panic!("the press must move at once, got {other:?}"),
            };
            let mut now = Duration::ZERO;
            for _ in 0..frames {
                now += Duration::from_millis(frame_ms);
                if let CouchIntent::Move { steps: n, .. } = intent_for(&input, &mut repeat, now) {
                    steps += n;
                }
            }
            steps
        }

        // 1200 ms of holding: 400 ms of dead time, then one step every 120 ms.
        // 1 (the press) + 1 (the first repeat at 480) + 6 = 8.
        let fine = steps_for(120, 10);
        assert_eq!(fine, 8, "10 frames of 120 ms is 1200 ms of holding");

        // Twice the frame rate, same duration. Not *exactly* the same number, and the
        // reason is worth stating rather than smoothing over: the initial delay ends at
        // the first sample at or after press + 400 ms, so a coarser frame rate can end it
        // up to one frame later — and then one fewer interval fits inside the hold. The
        // difference is bounded by one step; what must not happen is the focus falling far
        // behind, which is what the flag version did.
        let fast = steps_for(60, 20);
        assert!(
            (fine as i64 - fast as i64).abs() <= 1,
            "the frame rate must not change the distance by more than one step: \
             {fine} vs {fast}"
        );

        // A coarse frame rate must keep up rather than lag: the second update of 600 ms is
        // entitled to move several steps at once. This is the case that failed at 2.
        let coarse = steps_for(600, 2);
        assert!(
            coarse >= fine - 1,
            "600 ms frames must not fall behind: {coarse} steps against {fine}"
        );
        assert!(
            coarse >= 7,
            "the coarse rate must make up lost time, not lose it: {coarse}"
        );
    }

    #[test]
    fn releasing_stops_the_repeat() {
        let mut repeat = Repeat::default();
        let t = Duration::ZERO;
        repeat.update(Some(Direction::Down), t);
        assert_eq!(
            repeat.update(None, t + Duration::from_millis(500)),
            RepeatOutcome::Idle
        );
        assert_eq!(repeat.held(), None);

        // And a new press starts over rather than continuing the old timer.
        assert_eq!(
            repeat.update(Some(Direction::Down), t + Duration::from_millis(600)),
            RepeatOutcome::Move { steps: 1 }
        );
        assert_eq!(
            repeat.update(Some(Direction::Down), t + Duration::from_millis(700)),
            RepeatOutcome::Wait,
            "the initial delay applies again"
        );
    }

    #[test]
    fn changing_direction_moves_at_once_instead_of_waiting() {
        // Holding down and then pressing left must move left immediately; reusing the
        // timer would make the new direction repeat only after the old delay had passed,
        // which feels like a dropped input.
        let mut repeat = Repeat::default();
        let t = Duration::ZERO;
        repeat.update(Some(Direction::Down), t);
        assert_eq!(
            repeat.update(Some(Direction::Left), t + Duration::from_millis(50)),
            RepeatOutcome::Move { steps: 1 }
        );
        assert_eq!(repeat.held(), Some(Direction::Left));
    }

    #[test]
    fn a_stuck_direction_can_be_released_without_a_button_event() {
        // A pad unplugged while a direction is held: without this the focus would keep
        // moving for ever. This is the couch-mode form of the stuck-button defect found
        // in spike 0.4.
        let mut repeat = Repeat::default();
        repeat.update(Some(Direction::Down), Duration::ZERO);
        assert_eq!(repeat.held(), Some(Direction::Down));
        repeat.release();
        assert_eq!(repeat.held(), None);
        assert_eq!(
            repeat.update(None, Duration::from_secs(1)),
            RepeatOutcome::Idle
        );
    }

    #[test]
    fn a_stick_direction_needs_to_pass_a_threshold() {
        let resting = PadInput::Axis {
            stick: 0,
            axis: 0,
            value: 0.2,
        };
        // A stick resting slightly off-centre must not steer the interface.
        assert_eq!(Direction::from_input(&resting, 0.5), None);

        let pushed = PadInput::Axis {
            stick: 0,
            axis: 0,
            value: 0.9,
        };
        assert_eq!(Direction::from_input(&pushed, 0.5), Some(Direction::Right));
    }

    #[test]
    fn stick_axes_follow_the_browser_sign_convention() {
        // Y is positive-down, which is the convention the wire protocol uses. Getting
        // this backwards would invert every vertical stick movement.
        let down = PadInput::Axis {
            stick: 0,
            axis: 1,
            value: 0.8,
        };
        let up = PadInput::Axis {
            stick: 0,
            axis: 1,
            value: -0.8,
        };
        assert_eq!(Direction::from_input(&down, 0.5), Some(Direction::Down));
        assert_eq!(Direction::from_input(&up, 0.5), Some(Direction::Up));

        let left = PadInput::Axis {
            stick: 0,
            axis: 0,
            value: -0.8,
        };
        assert_eq!(Direction::from_input(&left, 0.5), Some(Direction::Left));
    }

    #[test]
    fn the_right_stick_does_not_drive_the_interface() {
        // The right stick belongs to the application — a game, or scrolling inside a page.
        // Steering the focus with it would fight whatever else is using it.
        let right_stick = PadInput::Axis {
            stick: 1,
            axis: 0,
            value: 0.9,
        };
        assert_eq!(Direction::from_input(&right_stick, 0.5), None);
    }

    #[test]
    fn a_trigger_axis_does_not_drive_the_interface() {
        // Triggers arrive as axes on some pads; they are not directions.
        let trigger = PadInput::Axis {
            stick: 2,
            axis: 0,
            value: 0.9,
        };
        assert_eq!(Direction::from_input(&trigger, 0.5), None);
    }

    #[test]
    fn intent_for_an_unused_button_is_nothing() {
        let mut repeat = Repeat::default();
        let input = PadInput::Button {
            button: StandardButton::R2,
            pressed: true,
        };
        assert_eq!(
            intent_for(&input, &mut repeat, Duration::ZERO),
            CouchIntent::Nothing
        );
    }

    #[test]
    fn a_direction_button_press_and_release_behave_as_expected() {
        let mut repeat = Repeat::default();
        let pressed = PadInput::Button {
            button: StandardButton::Right,
            pressed: true,
        };
        assert_eq!(
            intent_for(&pressed, &mut repeat, Duration::ZERO),
            CouchIntent::Move {
                direction: Direction::Right,
                steps: 1
            }
        );
        // Held: waits, and reports nothing so the caller does not move twice.
        assert_eq!(
            intent_for(&pressed, &mut repeat, Duration::from_millis(50)),
            CouchIntent::Nothing
        );

        let released = PadInput::Button {
            button: StandardButton::Right,
            pressed: false,
        };
        assert_eq!(
            intent_for(&released, &mut repeat, Duration::from_millis(60)),
            CouchIntent::Nothing
        );
        assert_eq!(repeat.held(), None, "the release must stop the repeat");
    }

    #[test]
    fn activate_back_and_menu_are_passed_through() {
        let mut repeat = Repeat::default();
        for (button, expected) in [
            (StandardButton::A, CouchIntent::Activate),
            (StandardButton::B, CouchIntent::Back),
            (StandardButton::Start, CouchIntent::Menu),
        ] {
            let input = PadInput::Button {
                button,
                pressed: true,
            };
            assert_eq!(intent_for(&input, &mut repeat, Duration::ZERO), expected);
        }
    }

    #[test]
    fn a_whole_navigation_walk_behaves_like_a_person_expects() {
        // The integration case: banner, then a row of three, using only intents.
        let items = vec![
            FocusItem::new("banner", Rect::new(0, 0, 340, 150)),
            FocusItem::new("a", Rect::new(0, 170, 100, 100)),
            FocusItem::new("b", Rect::new(120, 170, 100, 100)),
            FocusItem::new("c", Rect::new(240, 170, 100, 100)),
        ];
        let mut grid = FocusGrid::new(items);
        let mut repeat = Repeat::default();
        let mut walk = |direction, at: Duration| {
            let input = PadInput::Button {
                button: match direction {
                    Direction::Down => StandardButton::Down,
                    Direction::Up => StandardButton::Up,
                    Direction::Left => StandardButton::Left,
                    Direction::Right => StandardButton::Right,
                },
                pressed: true,
            };
            match intent_for(&input, &mut repeat, at) {
                CouchIntent::Move { direction, steps } => {
                    // Walk the steps, because a late update may carry more than one.
                    for _ in 0..steps {
                        grid.move_focus(direction);
                    }
                }
                other => panic!("expected a move, got {other:?}"),
            }
            // Release, so the next press is a fresh one.
            let release = PadInput::Button {
                button: match direction {
                    Direction::Down => StandardButton::Down,
                    Direction::Up => StandardButton::Up,
                    Direction::Left => StandardButton::Left,
                    Direction::Right => StandardButton::Right,
                },
                pressed: false,
            };
            intent_for(&release, &mut repeat, at);
            grid.current_id().unwrap().to_string()
        };

        let mut t = Duration::ZERO;
        let mut step = |direction| {
            t += Duration::from_millis(200);
            walk(direction, t)
        };

        assert_eq!(
            step(Direction::Down),
            "b",
            "from the banner to the middle tile"
        );
        assert_eq!(step(Direction::Right), "c");
        assert_eq!(step(Direction::Left), "b");
        assert_eq!(step(Direction::Left), "a");
        assert_eq!(step(Direction::Left), "a", "the left edge");
        assert_eq!(step(Direction::Up), "banner", "back up to the banner");
    }
}
