//! Gamepad input types, free of any device library.
//!
//! Split out from [`crate::input`] because these types are pure data, while reading a
//! physical pad needs `gilrs` — and `gilrs` needs `libudev` on Linux. Keeping the types
//! here means the couch interface, which is entirely about *translated* input, can be
//! built and tested with no system dependencies at all. Before this split, `couch.rs`
//! could not compile without the `gamepad` feature, which would have made couch mode
//! untestable in the default build.

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
