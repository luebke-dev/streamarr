//! Browser keycode → Linux scancode mapping and GStreamer input dispatch.

use gstreamer as gst;
use gstreamer::prelude::*;

// ─────────────────────────────────────────────────────────────────────────────
// Keycode mapping: JavaScript KeyboardEvent.code → Linux input scancode
// ─────────────────────────────────────────────────────────────────────────────

pub fn js_code_to_linux(code: &str) -> Option<u32> {
    match code {
        "Escape" => Some(1),
        "Digit1" => Some(2),
        "Digit2" => Some(3),
        "Digit3" => Some(4),
        "Digit4" => Some(5),
        "Digit5" => Some(6),
        "Digit6" => Some(7),
        "Digit7" => Some(8),
        "Digit8" => Some(9),
        "Digit9" => Some(10),
        "Digit0" => Some(11),
        "Minus" => Some(12),
        "Equal" => Some(13),
        "Backspace" => Some(14),
        "Tab" => Some(15),
        "KeyQ" => Some(16),
        "KeyW" => Some(17),
        "KeyE" => Some(18),
        "KeyR" => Some(19),
        "KeyT" => Some(20),
        "KeyY" => Some(21),
        "KeyU" => Some(22),
        "KeyI" => Some(23),
        "KeyO" => Some(24),
        "KeyP" => Some(25),
        "BracketLeft" => Some(26),
        "BracketRight" => Some(27),
        "Enter" => Some(28),
        "ControlLeft" => Some(29),
        "KeyA" => Some(30),
        "KeyS" => Some(31),
        "KeyD" => Some(32),
        "KeyF" => Some(33),
        "KeyG" => Some(34),
        "KeyH" => Some(35),
        "KeyJ" => Some(36),
        "KeyK" => Some(37),
        "KeyL" => Some(38),
        "Semicolon" => Some(39),
        "Quote" => Some(40),
        "Backquote" => Some(41),
        "ShiftLeft" => Some(42),
        "Backslash" => Some(43),
        "KeyZ" => Some(44),
        "KeyX" => Some(45),
        "KeyC" => Some(46),
        "KeyV" => Some(47),
        "KeyB" => Some(48),
        "KeyN" => Some(49),
        "KeyM" => Some(50),
        "Comma" => Some(51),
        "Period" => Some(52),
        "Slash" => Some(53),
        "ShiftRight" => Some(54),
        "NumpadMultiply" => Some(55),
        "AltLeft" => Some(56),
        "Space" => Some(57),
        "CapsLock" => Some(58),
        "F1" => Some(59),
        "F2" => Some(60),
        "F3" => Some(61),
        "F4" => Some(62),
        "F5" => Some(63),
        "F6" => Some(64),
        "F7" => Some(65),
        "F8" => Some(66),
        "F9" => Some(67),
        "F10" => Some(68),
        "NumLock" => Some(69),
        "ScrollLock" => Some(70),
        "Numpad7" => Some(71),
        "Numpad8" => Some(72),
        "Numpad9" => Some(73),
        "NumpadSubtract" => Some(74),
        "Numpad4" => Some(75),
        "Numpad5" => Some(76),
        "Numpad6" => Some(77),
        "NumpadAdd" => Some(78),
        "Numpad1" => Some(79),
        "Numpad2" => Some(80),
        "Numpad3" => Some(81),
        "Numpad0" => Some(82),
        "NumpadDecimal" => Some(83),
        "IntlBackslash" => Some(86),
        "F11" => Some(87),
        "F12" => Some(88),
        "NumpadEnter" => Some(96),
        "ControlRight" => Some(97),
        "NumpadDivide" => Some(98),
        "PrintScreen" => Some(99),
        "AltRight" => Some(100),
        "Home" => Some(102),
        "ArrowUp" => Some(103),
        "PageUp" => Some(104),
        "ArrowLeft" => Some(105),
        "ArrowRight" => Some(106),
        "End" => Some(107),
        "ArrowDown" => Some(108),
        "PageDown" => Some(109),
        "Insert" => Some(110),
        "Delete" => Some(111),
        "Pause" => Some(119),
        "MetaLeft" => Some(125),
        "MetaRight" => Some(126),
        "ContextMenu" => Some(127),
        _ => None,
    }
}

pub fn browser_button_to_linux(button: u32) -> u32 {
    match button {
        0 => 0x110, // BTN_LEFT
        1 => 0x112, // BTN_MIDDLE
        2 => 0x111, // BTN_RIGHT
        3 => 0x113, // BTN_SIDE
        4 => 0x114, // BTN_EXTRA
        _ => 0x110,
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// GStreamer input dispatch
// ─────────────────────────────────────────────────────────────────────────────

fn send_gst_upstream(element: &gst::Element, structure: gst::Structure) -> bool {
    let event = gst::event::CustomUpstream::new(structure);
    element.send_event(event)
}

pub fn handle_input_json(
    compositor_element: &gst::Element,
    json_str: &str,
    screen_w: u32,
    screen_h: u32,
) {
    let data: serde_json::Value = match serde_json::from_str(json_str) {
        Ok(v) => v,
        Err(_) => return,
    };

    let msg_type = data.get("type").and_then(|v| v.as_str()).unwrap_or("");

    match msg_type {
        "key" => {
            let code = data.get("code").and_then(|v| v.as_str()).unwrap_or("");
            let pressed = data
                .get("pressed")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            if let Some(scancode) = js_code_to_linux(code) {
                let s = gst::Structure::builder("KeyboardKey")
                    .field("key", scancode)
                    .field("pressed", pressed)
                    .build();
                send_gst_upstream(compositor_element, s);
            }
        }
        "mousemove" => {
            let dx = data.get("dx").and_then(|v| v.as_f64()).unwrap_or(0.0);
            let dy = data.get("dy").and_then(|v| v.as_f64()).unwrap_or(0.0);
            let s = gst::Structure::builder("MouseMoveRelative")
                .field("pointer_x", dx)
                .field("pointer_y", dy)
                .build();
            send_gst_upstream(compositor_element, s);
        }
        "mouseabs" => {
            let x = data.get("x").and_then(|v| v.as_f64()).unwrap_or(0.0);
            let y = data.get("y").and_then(|v| v.as_f64()).unwrap_or(0.0);
            let client_w = data.get("w").and_then(|v| v.as_f64()).unwrap_or(1920.0);
            let client_h = data.get("h").and_then(|v| v.as_f64()).unwrap_or(1080.0);
            let target_x = if client_w > 0.0 {
                x * (screen_w as f64 / client_w)
            } else {
                x
            };
            let target_y = if client_h > 0.0 {
                y * (screen_h as f64 / client_h)
            } else {
                y
            };
            let s = gst::Structure::builder("MouseMoveAbsolute")
                .field("pointer_x", target_x)
                .field("pointer_y", target_y)
                .build();
            send_gst_upstream(compositor_element, s);
        }
        "mousebutton" => {
            let button = data.get("button").and_then(|v| v.as_u64()).unwrap_or(0) as u32;
            let pressed = data
                .get("pressed")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            let linux_btn = browser_button_to_linux(button);
            let s = gst::Structure::builder("MouseButton")
                .field("button", linux_btn)
                .field("pressed", pressed)
                .build();
            send_gst_upstream(compositor_element, s);
        }
        "wheel" => {
            let dx = data.get("dx").and_then(|v| v.as_f64()).unwrap_or(0.0);
            let dy = data.get("dy").and_then(|v| v.as_f64()).unwrap_or(0.0);
            let s = gst::Structure::builder("MouseAxis")
                .field("x", dx)
                .field("y", -dy) // Invert Y like browser convention
                .build();
            send_gst_upstream(compositor_element, s);
        }
        _ => {} // Unknown input type — silently ignore
    }
}
