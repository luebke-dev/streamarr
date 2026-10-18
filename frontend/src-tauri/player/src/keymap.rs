//! Translating native key events into the browser key codes the server expects.
//!
//! # Why a translation is needed at all
//!
//! `lightrays/src/input.rs` accepts key events only as **browser** codes — the
//! `KeyboardEvent.code` values, `KeyA`, `ArrowLeft`, `ShiftLeft` — and runs them
//! through `js_code_to_linux`. A native client sees *evdev* key codes instead
//! (`KEY_A` = 30, `KEY_ESC` = 1). Sending the evdev number where a browser code
//! is expected does not raise an error anywhere: `js_code_to_linux` returns
//! `None`, the event is dropped, and the game simply ignores the key. That
//! silence is what makes the mapping worth pinning down in one place.
//!
//! # The table is derived, not copied
//!
//! The mapping below is the exact inverse of the server's own table, and the
//! golden test in `tests/wire_contract.rs` re-derives it from
//! `lightrays/src/input.rs` on every run. If the server adds, removes or
//! reassigns a key, that test fails here rather than leaving one key dead in
//! play. There is no point in a mapping that is merely *believed* to match.
//!
//! # Key codes are not the same on X11 and Wayland
//!
//! This matters and is easy to get wrong:
//!
//! * **Wayland** (`wl_keyboard.key`) reports the **evdev key code directly** —
//!   the numbers in this table.
//! * **X11** (`XKeyEvent.keycode`) reports **evdev + 8**, an offset inherited
//!   from the historic X server layout.
//!
//! Using one convention on the other platform shifts every letter key by eight
//! positions, which produces a keyboard that types plausible-looking nonsense
//! rather than nothing at all. [`browser_code`] takes evdev, and
//! [`browser_code_for_x11`] applies the offset for callers that have an X11
//! key code.

/// The offset X11 adds to an evdev key code (`XKeyEvent.keycode = evdev + 8`).
///
/// Only for X11 callers. On Wayland the key *is* the evdev code and this offset
/// must not be applied.
pub const X11_KEYCODE_OFFSET: u32 = 8;

/// evdev key code → browser `KeyboardEvent.code`, sorted by key code.
///
/// Exactly the inverse of `lightrays/src/input.rs::js_code_to_linux`; the golden
/// test derives the server's table and compares against this one.
pub const EVDEV_TO_BROWSER_CODE: &[(u32, &str)] = &[
    (1, "Escape"),
    (2, "Digit1"),
    (3, "Digit2"),
    (4, "Digit3"),
    (5, "Digit4"),
    (6, "Digit5"),
    (7, "Digit6"),
    (8, "Digit7"),
    (9, "Digit8"),
    (10, "Digit9"),
    (11, "Digit0"),
    (12, "Minus"),
    (13, "Equal"),
    (14, "Backspace"),
    (15, "Tab"),
    (16, "KeyQ"),
    (17, "KeyW"),
    (18, "KeyE"),
    (19, "KeyR"),
    (20, "KeyT"),
    (21, "KeyY"),
    (22, "KeyU"),
    (23, "KeyI"),
    (24, "KeyO"),
    (25, "KeyP"),
    (26, "BracketLeft"),
    (27, "BracketRight"),
    (28, "Enter"),
    (29, "ControlLeft"),
    (30, "KeyA"),
    (31, "KeyS"),
    (32, "KeyD"),
    (33, "KeyF"),
    (34, "KeyG"),
    (35, "KeyH"),
    (36, "KeyJ"),
    (37, "KeyK"),
    (38, "KeyL"),
    (39, "Semicolon"),
    (40, "Quote"),
    (41, "Backquote"),
    (42, "ShiftLeft"),
    (43, "Backslash"),
    (44, "KeyZ"),
    (45, "KeyX"),
    (46, "KeyC"),
    (47, "KeyV"),
    (48, "KeyB"),
    (49, "KeyN"),
    (50, "KeyM"),
    (51, "Comma"),
    (52, "Period"),
    (53, "Slash"),
    (54, "ShiftRight"),
    (55, "NumpadMultiply"),
    (56, "AltLeft"),
    (57, "Space"),
    (58, "CapsLock"),
    (59, "F1"),
    (60, "F2"),
    (61, "F3"),
    (62, "F4"),
    (63, "F5"),
    (64, "F6"),
    (65, "F7"),
    (66, "F8"),
    (67, "F9"),
    (68, "F10"),
    (69, "NumLock"),
    (70, "ScrollLock"),
    (71, "Numpad7"),
    (72, "Numpad8"),
    (73, "Numpad9"),
    (74, "NumpadSubtract"),
    (75, "Numpad4"),
    (76, "Numpad5"),
    (77, "Numpad6"),
    (78, "NumpadAdd"),
    (79, "Numpad1"),
    (80, "Numpad2"),
    (81, "Numpad3"),
    (82, "Numpad0"),
    (83, "NumpadDecimal"),
    (86, "IntlBackslash"),
    (87, "F11"),
    (88, "F12"),
    (96, "NumpadEnter"),
    (97, "ControlRight"),
    (98, "NumpadDivide"),
    (99, "PrintScreen"),
    (100, "AltRight"),
    (102, "Home"),
    (103, "ArrowUp"),
    (104, "PageUp"),
    (105, "ArrowLeft"),
    (106, "ArrowRight"),
    (107, "End"),
    (108, "ArrowDown"),
    (109, "PageDown"),
    (110, "Insert"),
    (111, "Delete"),
    (119, "Pause"),
    (125, "MetaLeft"),
    (126, "MetaRight"),
    (127, "ContextMenu"),
];

/// The browser code for an evdev key code, or `None` if the server has no
/// mapping for it (media keys, for instance — a game does not receive them).
pub fn browser_code(evdev: u32) -> Option<&'static str> {
    EVDEV_TO_BROWSER_CODE
        .iter()
        .find_map(|(code, name)| (*code == evdev).then_some(*name))
}

/// The browser code for an **X11** key code, which is evdev plus 8.
///
/// A key code below the offset cannot come from X11 and yields `None` rather
/// than underflowing to a huge evdev code that might accidentally match.
pub fn browser_code_for_x11(x11_keycode: u32) -> Option<&'static str> {
    browser_code(x11_keycode.checked_sub(X11_KEYCODE_OFFSET)?)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn letters_map_to_their_evdev_codes() {
        // The four that catch an offset error immediately: on a QWERTY row the
        // evdev codes are consecutive, so a shift by one or eight lands on a
        // neighbouring letter instead of failing.
        assert_eq!(browser_code(30), Some("KeyA"));
        assert_eq!(browser_code(31), Some("KeyS"));
        assert_eq!(browser_code(44), Some("KeyZ"));
        assert_eq!(browser_code(57), Some("Space"));
    }

    #[test]
    fn arrows_and_modifiers_are_present() {
        assert_eq!(browser_code(103), Some("ArrowUp"));
        assert_eq!(browser_code(105), Some("ArrowLeft"));
        assert_eq!(browser_code(42), Some("ShiftLeft"));
        assert_eq!(browser_code(29), Some("ControlLeft"));
    }

    #[test]
    fn unknown_key_codes_return_none_instead_of_a_wrong_key() {
        // 84–85, 89–95, 101, 112–118, 120–124 are gaps in the server's table.
        for gap in [84u32, 85, 89, 90, 101, 112, 120] {
            assert_eq!(
                browser_code(gap),
                None,
                "Lücke {gap} darf nicht auf eine Taste abgebildet werden"
            );
        }
        assert_eq!(browser_code(0), None);
        assert_eq!(browser_code(9999), None);
    }

    #[test]
    fn the_table_is_sorted_and_free_of_duplicates() {
        // A linear scan hides an unsorted table; the golden test compares as a
        // set, so this is what keeps the file readable and diffable.
        for pair in EVDEV_TO_BROWSER_CODE.windows(2) {
            assert!(
                pair[0].0 < pair[1].0,
                "Tabelle ist nicht aufsteigend: {:?} vor {:?}",
                pair[0],
                pair[1]
            );
        }
    }

    #[test]
    fn x11_keycodes_are_offset_by_eight() {
        // X11 `KeyA` is 38, evdev `KEY_A` is 30.
        assert_eq!(browser_code_for_x11(38), Some("KeyA"));
        assert_eq!(browser_code_for_x11(105 + 8), Some("ArrowLeft"));
        // The same number means *different* keys under the two conventions —
        // the reason both functions exist rather than one with a flag.
        assert_eq!(browser_code(38), Some("KeyL"));
    }

    #[test]
    fn an_x11_keycode_below_the_offset_is_rejected() {
        // Would underflow to 4294967293 and match nothing; `None` says so
        // honestly. evdev 0 is not a key either, so X11 8 (= 0 + 8) is a
        // keycode with no key behind it.
        assert_eq!(browser_code_for_x11(0), None);
        assert_eq!(browser_code_for_x11(7), None);
        assert_eq!(browser_code_for_x11(8), None);
        // The first real key is Escape: evdev 1, hence X11 9. The offset
        // between the two conventions is exactly why this test exists — the
        // naive "X11 8 means the first key" guess is off by one.
        assert_eq!(browser_code_for_x11(9), Some("Escape"));
    }

    #[test]
    fn every_entry_is_reachable_and_non_empty() {
        for (code, name) in EVDEV_TO_BROWSER_CODE {
            assert_eq!(browser_code(*code), Some(*name));
            assert!(!name.is_empty());
        }
    }
}
