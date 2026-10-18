//! Creates a virtual gamepad and drives it, so the reader can be tested.
//!
//! Spike 0.4. There is no physical pad in this environment, and a test that only
//! exercises the pure translation logic would not prove the part most likely to
//! be wrong: whether `gilrs` actually *sees* the device, reports hot-plug, and
//! delivers sane button and axis values.
//!
//! `/dev/uinput` lets us create a real input device that the kernel and udev
//! treat like a physical one. `gilrs` cannot tell the difference, so everything
//! downstream of device discovery is genuinely under test.
//!
//! Gamepads use **absolute** axes (`ABS_X`/`ABS_Y`), not relative ones: a stick
//! has a position, not a delta. Using `REL_X` here would produce a device that
//! gilrs does not recognise as a gamepad at all.
//!
//! Run with: cargo run --features gamepad --bin virtual-pad -- <scenario> [name]
//! Scenarios: press | axes | hotplug

use std::thread::sleep;
use std::time::Duration;

use evdev::uinput::VirtualDevice;
use evdev::{
    AbsInfo, AbsoluteAxisCode, AttributeSet, BusType, EventType, InputEvent, InputId, KeyCode,
    UinputAbsSetup,
};

/// Axis range matching what a real pad reports. `gilrs` scales this into
/// [-1.0, 1.0], so a test that used a different range would not exercise the
/// same normalisation the app will see.
const AXIS_MIN: i32 = -32768;
const AXIS_MAX: i32 = 32767;

/// Builds a virtual pad that looks like a real controller.
///
/// The device name matters: `layout_for` decides the button layout from it, so
/// passing a name here is how both the standard and the non-standard path are
/// exercised against a device that reports standard codes.
fn build_pad(name: &str) -> std::io::Result<VirtualDevice> {
    let mut keys = AttributeSet::<KeyCode>::new();
    for code in [
        KeyCode::BTN_SOUTH,
        KeyCode::BTN_EAST,
        KeyCode::BTN_WEST,
        KeyCode::BTN_NORTH,
        KeyCode::BTN_TL,
        KeyCode::BTN_TR,
        KeyCode::BTN_SELECT,
        KeyCode::BTN_START,
        KeyCode::BTN_DPAD_UP,
        KeyCode::BTN_DPAD_DOWN,
        KeyCode::BTN_DPAD_LEFT,
        KeyCode::BTN_DPAD_RIGHT,
    ] {
        keys.insert(code);
    }

    let axis = |code: AbsoluteAxisCode| {
        UinputAbsSetup::new(code, AbsInfo::new(0, AXIS_MIN, AXIS_MAX, 0, 0, 0))
    };
    // A hat reports -1/0/+1, not the stick range.
    let hat = |code: AbsoluteAxisCode| UinputAbsSetup::new(code, AbsInfo::new(0, -1, 1, 0, 0, 0));

    // `with_absolute_axis` takes one axis at a time, so it is called per axis.
    // Bus 0x03 (USB) with the Microsoft vendor id, because some detection paths
    // key off the device id and an all-zero id is not representative.
    VirtualDevice::builder()?
        .name(name)
        .input_id(InputId::new(BusType::BUS_USB, 0x045e, 0x028e, 0x0114))
        .with_keys(&keys)?
        // Left stick
        .with_absolute_axis(&axis(AbsoluteAxisCode::ABS_X))?
        .with_absolute_axis(&axis(AbsoluteAxisCode::ABS_Y))?
        // Right stick
        .with_absolute_axis(&axis(AbsoluteAxisCode::ABS_RX))?
        .with_absolute_axis(&axis(AbsoluteAxisCode::ABS_RY))?
        // Triggers. gilrs maps ABS_Z to LeftZ and ABS_RZ to RightZ; leaving them
        // out makes the device not look like a real controller and shifts what
        // the remaining codes mean.
        .with_absolute_axis(&axis(AbsoluteAxisCode::ABS_Z))?
        .with_absolute_axis(&axis(AbsoluteAxisCode::ABS_RZ))?
        // D-pad as a hat, which is how a real pad reports it.
        .with_absolute_axis(&hat(AbsoluteAxisCode::ABS_HAT0X))?
        .with_absolute_axis(&hat(AbsoluteAxisCode::ABS_HAT0Y))?
        .build()
}

fn press(device: &mut VirtualDevice, code: KeyCode, down: bool) {
    let event = InputEvent::new(EventType::KEY.0, code.0, i32::from(down));
    let _ = device.emit(&[event]);
}

fn move_stick(device: &mut VirtualDevice, code: AbsoluteAxisCode, value: i32) {
    let event = InputEvent::new(EventType::ABSOLUTE.0, code.0, value);
    let _ = device.emit(&[event]);
}

fn main() {
    let scenario = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "press".to_string());
    let name = std::env::args()
        .nth(2)
        .unwrap_or_else(|| "Microsoft X-Box One pad".to_string());

    println!("scenario={scenario} device=\"{name}\"");
    println!("creating virtual pad…");

    let mut pad = match build_pad(&name) {
        Ok(p) => p,
        Err(e) => {
            eprintln!("failed to create virtual pad: {e}");
            eprintln!();
            eprintln!("/dev/uinput must exist and be writable. Check with:");
            eprintln!("  ls -l /dev/uinput && test -w /dev/uinput && echo writable");
            std::process::exit(1);
        }
    };
    println!("virtual pad created");

    match scenario.as_str() {
        "press" => {
            sleep(Duration::from_millis(800));
            for (label, code) in [
                ("A / South", KeyCode::BTN_SOUTH),
                ("B / East", KeyCode::BTN_EAST),
                ("X / West", KeyCode::BTN_WEST),
                ("Y / North", KeyCode::BTN_NORTH),
                ("L1 / TL", KeyCode::BTN_TL),
                ("Start", KeyCode::BTN_START),
                ("Select", KeyCode::BTN_SELECT),
                ("D-pad up", KeyCode::BTN_DPAD_UP),
            ] {
                // Releasing first makes each press an edge, which is what the
                // translator's duplicate suppression keys on.
                press(&mut pad, code, false);
                sleep(Duration::from_millis(80));
                println!("press {label}");
                press(&mut pad, code, true);
                sleep(Duration::from_millis(250));
                press(&mut pad, code, false);
                sleep(Duration::from_millis(150));
            }
        }
        "axes" => {
            sleep(Duration::from_millis(800));
            // Real sticks sweep; a single jump would not prove that repeated
            // samples are suppressed, which is the point of the epsilon.
            for (label, code, value) in [
                ("left stick X = 40%", AbsoluteAxisCode::ABS_X, AXIS_MAX / 3),
                (
                    "left stick X = 41% (below epsilon)",
                    AbsoluteAxisCode::ABS_X,
                    AXIS_MAX / 3 + 200,
                ),
                (
                    "left stick X = 80%",
                    AbsoluteAxisCode::ABS_X,
                    (AXIS_MAX as f64 * 0.8) as i32,
                ),
                (
                    "left stick Y = -60% (up)",
                    AbsoluteAxisCode::ABS_Y,
                    (AXIS_MIN as f64 * 0.6) as i32,
                ),
                ("right stick X = 100%", AbsoluteAxisCode::ABS_RX, AXIS_MAX),
                ("right stick Y = -100%", AbsoluteAxisCode::ABS_RY, AXIS_MIN),
                ("left stick back to centre", AbsoluteAxisCode::ABS_X, 0),
                // Triggers live on ABS_Z / ABS_RZ (LeftZ / RightZ in gilrs).
                (
                    "left trigger (LeftZ) = 80%",
                    AbsoluteAxisCode::ABS_Z,
                    (AXIS_MAX as f64 * 0.8) as i32,
                ),
                ("left trigger released", AbsoluteAxisCode::ABS_Z, 0),
                ("d-pad right (hat)", AbsoluteAxisCode::ABS_HAT0X, 1),
                ("d-pad centred", AbsoluteAxisCode::ABS_HAT0X, 0),
            ] {
                println!("{label}");
                move_stick(&mut pad, code, value);
                sleep(Duration::from_millis(400));
            }
        }
        "stuck" => {
            println!("holding A, then unplugging WITHOUT releasing");
            // Wait for the device to be fully registered before pressing:
            // gilrs needs a moment after uinput creation before it reads.
            sleep(Duration::from_millis(1500));
            press(&mut pad, KeyCode::BTN_SOUTH, true);
            sleep(Duration::from_millis(1200));
            drop(pad);
            println!("pad unplugged while A was held");
            sleep(Duration::from_millis(2000));
        }
        "hotplug" => {
            println!("pad is connected; unplugging in 1.5s");
            sleep(Duration::from_millis(1500));
            drop(pad);
            println!("pad removed");
            sleep(Duration::from_millis(2000));
            println!("reconnecting…");
            let mut pad = build_pad(&name).expect("recreate");
            println!("pad reconnected");
            sleep(Duration::from_millis(800));
            press(&mut pad, KeyCode::BTN_SOUTH, true);
            sleep(Duration::from_millis(300));
            press(&mut pad, KeyCode::BTN_SOUTH, false);
            sleep(Duration::from_millis(500));
        }
        other => {
            eprintln!("unknown scenario '{other}'; use press | axes | hotplug | stuck");
            std::process::exit(2);
        }
    }

    println!("done");
    sleep(Duration::from_millis(400));
}
