//! Browser Gamepad API → RetroArch remote-gamepad translation.
//!
//! RetroArch is launched with `network_remote_enable`, which makes it listen
//! for UDP "remote gamepad" packets on `network_remote_base_port` (55400 by
//! default; one port per player, so player 1 = 55400, player 2 = 55401).

//! Why this transport instead of `/dev/uinput`: the retro container gets no
//! `/dev/input` and creating virtual devices needs `uinput`/`uhid` on the
//! host. Under an outer container runtime (LXC with a default AppArmor
//! profile) opening `/dev/uinput` fails with EPERM even in a `--privileged`
//! child, so a virtual-device approach is not portable. The remote-gamepad
//! path needs no device access at all and carries real analog values.
//!
//! Wire format (little-endian, matches RetroArch `struct remote_message`):
//!
//! ```text
//! offset  size  field
//!      0     4  port        (int32, ignored on receive; the UDP port picks the player)
//!      4     4  device      (int32, RETRO_DEVICE_JOYPAD=1 | RETRO_DEVICE_ANALOG=5)
//!      8     4  index       (int32, analog stick: 0=left, 1=right; unused for joypad)
//!     12     4  id          (int32, button id or analog axis: 0=X, 1=Y)
//!     16     2  state       (uint16, button bitmask or int16 analog value)
//!     18     2  padding     (unused, but MUST be sent)
//! ```
//!
//! The struct is 20 bytes, not 18: the trailing `uint16_t state` sits at offset
//! 16 and the compiler pads the struct to a 4-byte alignment, adding two dead
//! bytes. This matters more than it looks. RetroArch reads a packet with
//! `recvfrom(...)` and only parses it when `ret == sizeof(msg)`, i.e. exactly
//! 20. A short packet falls into the `else` branch, which zeroes the player's
//! buttons *and* all four analog axes, so an 18-byte packet would not merely be
//! ignored, it would actively cancel input every time one arrived.
//!
//! For `RETRO_DEVICE_ANALOG` the `state` field is reinterpreted as a signed
//! 16-bit axis value (RetroArch assigns it straight into an `int16_t`), so
//! negative values must be sent as the two's-complement bit pattern.
//!
//! The `port` field is not used to route input: RetroArch binds one UDP socket
//! per player (`network_remote_base_port + player`) and attributes each packet
//! to the socket it arrived on. Sending everything to 55400 always addresses
//! player 1.

use std::net::UdpSocket;

/// `RETRO_DEVICE_JOYPAD` (1) for digital buttons.
const RETRO_DEVICE_JOYPAD: i32 = 1;

/// `RETRO_DEVICE_ANALOG` (5) for analog sticks.
const RETRO_DEVICE_ANALOG: i32 = 5;

/// First UDP port RetroArch listens on for remote gamepads
/// (`DEFAULT_NETWORK_GAMEPAD_PORT`). Player N uses `base + N`.
pub const DEFAULT_REMOTE_GAMEPAD_PORT: u16 = 55400;

/// Size of RetroArch's `struct remote_message` on the wire, including the two
/// bytes of trailing struct padding. RetroArch compares the received length
/// against `sizeof(msg)` and ignores anything that is not an exact match, so
/// this must not be changed to the sum of the fields (18).
pub const REMOTE_MESSAGE_LEN: usize = 20;

/// RetroPad button ids, in RetroArch's `RETRO_DEVICE_ID_JOYPAD_*` order.
///
/// The numeric value is the bit position in the joypad state bitmask, so
/// `1 << id` sets that button. Keep in sync with `libretro.h`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(i32)]
pub enum RetroPadButton {
    B = 0,
    Y = 1,
    Select = 2,
    Start = 3,
    Up = 4,
    Down = 5,
    Left = 6,
    Right = 7,
    A = 8,
    X = 9,
    L = 10,
    R = 11,
    L2 = 12,
    R2 = 13,
    L3 = 14,
    R3 = 15,
}

impl RetroPadButton {
    /// Bit position of this button in the joypad state bitmask.
    pub fn bit(self) -> u16 {
        1u16 << (self as i32)
    }
}

/// A decoded gamepad message ready to be put on the wire.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum GamepadEvent {
    /// A digital button changed state.
    Button {
        button: RetroPadButton,
        pressed: bool,
    },
    /// An analog axis moved. `stick` is 0 for left, 1 for right; `axis` is
    /// 0 for X, 1 for Y. `value` is the raw axis value in `i16` range.
    Axis { stick: i32, axis: i32, value: i16 },
}

/// One player's remote-gamepad socket.
///
/// Sockets are created lazily on first use and then reused for the session;
/// a gamepad message is tiny (18 bytes) and sent fire-and-forget, so a
/// dropped packet only costs one frame of input.
pub struct RemoteGamepad {
    socket: Option<UdpSocket>,
    target: String,
    port: u16,
    /// Last sent state per button bit, so we only transmit real changes.
    buttons: u16,
    /// Last sent value per (stick, axis), to avoid spamming identical axes.
    axes: [[i16; 2]; 2],
}

impl RemoteGamepad {
    /// Create a gamepad channel for `player` (0-based) of a session whose
    /// RetroArch runs at `host`.
    pub fn new(host: &str, player: u8) -> Self {
        Self {
            socket: None,
            target: format!("{host}:{}", DEFAULT_REMOTE_GAMEPAD_PORT + player as u16),
            port: DEFAULT_REMOTE_GAMEPAD_PORT + player as u16,
            buttons: 0,
            axes: [[0; 2]; 2],
        }
    }

    /// Target UDP port this gamepad sends to (for logging/tests).
    pub fn port(&self) -> u16 {
        self.port
    }

    fn send_raw(&mut self, packet: &[u8]) {
        if self.socket.is_none() {
            // Bind an ephemeral local port; RetroArch replies to the source
            // address it last saw, so the socket has to stay alive.
            match UdpSocket::bind("0.0.0.0:0") {
                Ok(s) => {
                    // Non-blocking so a stalled receiver can never wedge a
                    // session's input thread.
                    let _ = s.set_nonblocking(true);
                    self.socket = Some(s);
                }
                Err(e) => {
                    log::warn!("Remote gamepad: could not bind UDP socket: {e}");
                    return;
                }
            }
        }
        if let Some(socket) = self.socket.as_ref() {
            if let Err(e) = socket.send_to(packet, &self.target) {
                // A full send buffer or an unreachable container is not
                // fatal: the next frame's event carries the same state.
                log::debug!("Remote gamepad send failed ({}): {e}", self.target);
            }
        }
    }

    /// Apply a decoded event, sending only when the state actually changed.
    pub fn apply(&mut self, event: GamepadEvent) {
        match event {
            GamepadEvent::Button { button, pressed } => {
                let bit = button.bit();
                let next = if pressed {
                    self.buttons | bit
                } else {
                    self.buttons & !bit
                };
                if next == self.buttons {
                    return;
                }
                self.buttons = next;
                self.send_button(button, pressed);
            }
            GamepadEvent::Axis { stick, axis, value } => {
                let (s, a) = (stick.clamp(0, 1) as usize, axis.clamp(0, 1) as usize);
                if self.axes[s][a] == value {
                    return;
                }
                self.axes[s][a] = value;
                self.send_axis(stick, axis, value);
            }
        }
    }

    /// Release every held button and recentre both sticks. Called when the
    /// client disconnects, so a dropped connection cannot leave a game with
    /// a stuck direction or a held button.
    pub fn release_all(&mut self) {
        if self.buttons != 0 {
            for id in 0..16 {
                if self.buttons & (1u16 << id) != 0 {
                    self.send_raw(&encode_joypad(0, id, false));
                }
            }
            self.buttons = 0;
        }
        for stick in 0..2i32 {
            for axis in 0..2i32 {
                if self.axes[stick as usize][axis as usize] != 0 {
                    self.send_axis(stick, axis, 0);
                    self.axes[stick as usize][axis as usize] = 0;
                }
            }
        }
    }

    fn send_button(&mut self, button: RetroPadButton, pressed: bool) {
        let packet = encode_joypad(0, button as i32, pressed);
        self.send_raw(&packet);
    }

    fn send_axis(&mut self, stick: i32, axis: i32, value: i16) {
        let packet = encode_analog(0, stick, axis, value);
        self.send_raw(&packet);
    }
}

/// Encode a digital joypad message: `struct remote_message` with
/// `device = RETRO_DEVICE_JOYPAD` and `state` carrying the press bit.
pub fn encode_joypad(port: i32, id: i32, pressed: bool) -> [u8; REMOTE_MESSAGE_LEN] {
    let state: u16 = if pressed { 1 } else { 0 };
    encode_message(port, RETRO_DEVICE_JOYPAD, 0, id, state)
}

/// Encode an analog axis message: `device = RETRO_DEVICE_ANALOG`, with the
/// stick in `index` and the axis in `id`; `value` goes into the 16-bit
/// `state` field as its two's-complement bit pattern.
pub fn encode_analog(
    port: i32,
    stick: i32,
    axis: i32,
    value: i16,
) -> [u8; REMOTE_MESSAGE_LEN] {
    encode_message(port, RETRO_DEVICE_ANALOG, stick, axis, value as u16)
}

/// Build the 20-byte little-endian `struct remote_message`.
///
/// The struct is `int port; int device; int index; int id; uint16_t state;`
/// which C lays out as 4+4+4+4+2 followed by two bytes of alignment padding,
/// giving `sizeof == 20`. RetroArch discards any packet whose length does not
/// match exactly, so the two trailing zero bytes are load-bearing, not
/// cosmetic (see the module docs).
fn encode_message(port: i32, device: i32, index: i32, id: i32, state: u16) -> [u8; REMOTE_MESSAGE_LEN] {
    let mut buf = [0u8; REMOTE_MESSAGE_LEN];
    buf[0..4].copy_from_slice(&port.to_le_bytes());
    buf[4..8].copy_from_slice(&device.to_le_bytes());
    buf[8..12].copy_from_slice(&index.to_le_bytes());
    buf[12..16].copy_from_slice(&id.to_le_bytes());
    buf[16..18].copy_from_slice(&state.to_le_bytes());
    // buf[18..20] stays zero: the struct's alignment padding.
    buf
}

/// Convert a browser `Gamepad` axis value (-1.0..=1.0) to the `i16` range
/// RetroArch expects, with a deadzone applied.
///
/// The deadzone is the user's `analog_deadzone` preference so the existing
/// setting finally has an effect: values inside the deadzone snap to 0, and
/// the remaining range is rescaled so control stays proportional instead of
/// jumping at the threshold.
pub fn axis_to_i16(value: f64, deadzone: f64) -> i16 {
    if !value.is_finite() {
        return 0;
    }
    let v = value.clamp(-1.0, 1.0);
    let dz = deadzone.clamp(0.0, 0.95);
    if v.abs() <= dz {
        return 0;
    }
    // Rescale [dz, 1] onto [0, 1] preserving sign.
    let sign = if v < 0.0 { -1.0 } else { 1.0 };
    let magnitude = (v.abs() - dz) / (1.0 - dz);
    let scaled = (magnitude * i16::MAX as f64).round();
    (sign * scaled).clamp(i16::MIN as f64, i16::MAX as f64) as i16
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn joypad_packet_layout_matches_retroarch_struct() {
        let p = encode_joypad(0, RetroPadButton::A as i32, true);
        // 20, not 18: `sizeof(struct remote_message)` includes two bytes of
        // trailing alignment padding, and RetroArch drops any packet whose
        // length differs from sizeof(msg).
        assert_eq!(p.len(), 20);
        assert_eq!(p.len(), REMOTE_MESSAGE_LEN);
        assert_eq!(i32::from_le_bytes(p[0..4].try_into().unwrap()), 0); // port
        assert_eq!(
            i32::from_le_bytes(p[4..8].try_into().unwrap()),
            RETRO_DEVICE_JOYPAD
        );
        assert_eq!(i32::from_le_bytes(p[8..12].try_into().unwrap()), 0); // index
        assert_eq!(
            i32::from_le_bytes(p[12..16].try_into().unwrap()),
            RetroPadButton::A as i32
        );
        assert_eq!(u16::from_le_bytes(p[16..18].try_into().unwrap()), 1);
    }

    #[test]
    fn trailing_padding_bytes_are_zero() {
        // The padding is unused by RetroArch but must be present and zeroed,
        // otherwise the struct would not match a C-allocated one byte for byte.
        let p = encode_analog(0, 1, 1, -1234);
        assert_eq!(&p[18..20], &[0u8, 0u8]);
    }

    #[test]
    fn field_offsets_match_the_c_struct() {
        // Mirrors the offsets `offsetof()` reports for the C struct, so a
        // future refactor cannot silently shift a field.
        let p = encode_joypad(7, 3, true);
        assert_eq!(i32::from_le_bytes(p[0..4].try_into().unwrap()), 7);
        assert_eq!(i32::from_le_bytes(p[8..12].try_into().unwrap()), 0);
        assert_eq!(i32::from_le_bytes(p[12..16].try_into().unwrap()), 3);
    }

    #[test]
    fn released_button_sends_zero_state() {
        let p = encode_joypad(0, RetroPadButton::Start as i32, false);
        assert_eq!(u16::from_le_bytes(p[16..18].try_into().unwrap()), 0);
    }

    #[test]
    fn analog_packet_uses_analog_device_and_axis_index() {
        let p = encode_analog(0, 1, 1, 1234);
        assert_eq!(
            i32::from_le_bytes(p[4..8].try_into().unwrap()),
            RETRO_DEVICE_ANALOG
        );
        assert_eq!(i32::from_le_bytes(p[8..12].try_into().unwrap()), 1); // right stick
        assert_eq!(i32::from_le_bytes(p[12..16].try_into().unwrap()), 1); // Y axis
        assert_eq!(u16::from_le_bytes(p[16..18].try_into().unwrap()), 1234);
    }

    #[test]
    fn analog_negative_values_round_trip_as_twos_complement() {
        let p = encode_analog(0, 0, 0, -32768);
        let raw = u16::from_le_bytes(p[16..18].try_into().unwrap());
        assert_eq!(raw as i16, -32768);
    }

    #[test]
    fn button_bits_follow_retropad_order() {
        assert_eq!(RetroPadButton::B.bit(), 1 << 0);
        assert_eq!(RetroPadButton::A.bit(), 1 << 8);
        assert_eq!(RetroPadButton::R3.bit(), 1 << 15);
    }

    #[test]
    fn port_advances_per_player() {
        assert_eq!(RemoteGamepad::new("10.0.0.1", 0).port(), 55400);
        assert_eq!(RemoteGamepad::new("10.0.0.1", 1).port(), 55401);
        assert_eq!(RemoteGamepad::new("10.0.0.1", 3).port(), 55403);
    }

    #[test]
    fn deadzone_snaps_small_values_to_zero() {
        assert_eq!(axis_to_i16(0.0, 0.15), 0);
        assert_eq!(axis_to_i16(0.1, 0.15), 0);
        assert_eq!(axis_to_i16(-0.1, 0.15), 0);
        assert_eq!(axis_to_i16(0.15, 0.15), 0);
    }

    #[test]
    fn deadzone_rescales_remaining_range() {
        // At full deflection the axis must still reach the maximum.
        assert_eq!(axis_to_i16(1.0, 0.15), i16::MAX);
        assert_eq!(axis_to_i16(-1.0, 0.15), -i16::MAX);
        // Just past the deadzone the output is small but non-zero.
        let just_past = axis_to_i16(0.16, 0.15);
        assert!(just_past > 0 && just_past < 2000, "got {just_past}");
    }

    #[test]
    fn deadzone_of_zero_is_a_passthrough() {
        assert_eq!(axis_to_i16(1.0, 0.0), i16::MAX);
        assert_eq!(axis_to_i16(-1.0, 0.0), -i16::MAX);
        assert_eq!(axis_to_i16(0.0, 0.0), 0);
    }

    #[test]
    fn non_finite_axis_values_are_rejected() {
        // Infinity and NaN are not real deflections. Clamping infinity to
        // full deflection would turn corrupt input into held-stick input,
        // so anything non-finite becomes centred (0) instead.
        assert_eq!(axis_to_i16(f64::NAN, 0.1), 0);
        assert_eq!(axis_to_i16(f64::INFINITY, 0.1), 0);
        assert_eq!(axis_to_i16(f64::NEG_INFINITY, 0.1), 0);
    }

    #[test]
    fn out_of_range_axis_values_are_clamped() {
        assert_eq!(axis_to_i16(5.0, 0.0), i16::MAX);
        assert_eq!(axis_to_i16(-5.0, 0.0), -i16::MAX);
    }

    #[test]
    fn repeated_identical_button_state_is_deduplicated() {
        let mut gp = RemoteGamepad::new("127.0.0.1", 0);
        // No socket is created until the first real change is sent.
        gp.apply(GamepadEvent::Button {
            button: RetroPadButton::A,
            pressed: false,
        });
        assert!(gp.socket.is_none(), "no-op must not open a socket");

        gp.apply(GamepadEvent::Button {
            button: RetroPadButton::A,
            pressed: true,
        });
        assert!(gp.socket.is_some(), "a real change must open the socket");

        // Second identical press is a no-op (state already held).
        let before = gp.buttons;
        gp.apply(GamepadEvent::Button {
            button: RetroPadButton::A,
            pressed: true,
        });
        assert_eq!(gp.buttons, before);
    }

    #[test]
    fn release_all_clears_held_state() {
        let mut gp = RemoteGamepad::new("127.0.0.1", 0);
        gp.apply(GamepadEvent::Button {
            button: RetroPadButton::Up,
            pressed: true,
        });
        gp.apply(GamepadEvent::Axis {
            stick: 0,
            axis: 0,
            value: 9000,
        });
        assert_ne!(gp.buttons, 0);

        gp.release_all();
        assert_eq!(gp.buttons, 0);
        assert_eq!(gp.axes, [[0; 2]; 2]);
    }

    #[test]
    fn repeated_identical_axis_is_deduplicated() {
        let mut gp = RemoteGamepad::new("127.0.0.1", 0);
        gp.apply(GamepadEvent::Axis {
            stick: 0,
            axis: 0,
            value: 500,
        });
        assert_eq!(gp.axes[0][0], 500);
        gp.apply(GamepadEvent::Axis {
            stick: 0,
            axis: 0,
            value: 500,
        });
        assert_eq!(gp.axes[0][0], 500);
    }

    #[test]
    fn out_of_range_stick_and_axis_indices_are_clamped() {
        let mut gp = RemoteGamepad::new("127.0.0.1", 0);
        gp.apply(GamepadEvent::Axis {
            stick: 9,
            axis: 9,
            value: 100,
        });
        // Clamped into the 2x2 array rather than panicking.
        assert_eq!(gp.axes[1][1], 100);
    }
}
