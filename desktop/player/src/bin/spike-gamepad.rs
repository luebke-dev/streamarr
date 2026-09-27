//! Spike 0.4: reads gamepads through `gilrs` and prints wire messages.
//!
//! Verifies the half of gamepad support that cannot be unit-tested: whether
//! gilrs discovers a device, reports hot-plug, and delivers button and axis
//! values that translate into the messages the server accepts.
//!
//! Intended to run alongside `virtual-pad`, which creates a real uinput device:
//!
//!   cargo run --features gamepad --bin spike-gamepad &        # reader
//!   cargo run --features gamepad --bin virtual-pad -- press    # device
//!
//! Every emitted line is a real `InputMessage` serialised by `protocol.rs`, so
//! the output is exactly what would go on the data channel.

use std::time::{Duration, Instant};

use streamarr_desktop_player::input::{PadEvent, PadSource};

fn main() {
    let seconds: u64 = std::env::args()
        .nth(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(8);

    eprintln!("starting gilrs…");
    let mut source = match PadSource::new() {
        Ok(s) => s,
        Err(e) => {
            eprintln!("FAILED to start gilrs: {e}");
            eprintln!();
            eprintln!("gilrs needs a working udev/input stack. In a container this");
            eprintln!("usually means /dev/input and /run/udev are not mounted.");
            std::process::exit(1);
        }
    };

    if std::env::var("SPIKE_TRACE").is_ok() {
        source.trace_raw = true;
    }
    let pads = source.connected_pads();
    if pads.is_empty() {
        eprintln!("no pads connected at startup (this is fine if one is coming)");
    }
    for pad in &pads {
        println!(
            "PAD CONNECTED id={} name=\"{}\" layout={:?}",
            pad.id, pad.name, pad.layout
        );
    }

    let mut events = 0usize;
    let mut inputs = 0usize;
    let mut releases = 0usize;
    let deadline = Instant::now() + Duration::from_secs(seconds);
    while Instant::now() < deadline {
        for event in source.poll() {
            events += 1;
            match event {
                PadEvent::Connected(info) => println!(
                    "PAD CONNECTED id={} name=\"{}\" layout={:?}",
                    info.id, info.name, info.layout
                ),
                PadEvent::Disconnected { id, name } => {
                    println!("PAD DISCONNECTED id={id} name=\"{name}\"")
                }
                PadEvent::Raw { pad, event, input } => {
                    eprintln!("RAW pad={pad} {event:?} -> {input:?}");
                }
                PadEvent::SyntheticRelease { pad, message } => {
                    releases += 1;
                    println!("RELEASE pad={pad} {}", message.to_json());
                }
                PadEvent::Input { pad, message } => {
                    inputs += 1;
                    // Serialised by the real protocol module, so this is the
                    // exact bytes that would reach the server.
                    println!("INPUT pad={pad} {}", message.to_json());
                }
            }
        }
        std::thread::sleep(Duration::from_millis(15));
    }

    println!();
    println!();
    println!(
        "=== spike 0.4: {events} pad event(s), {inputs} input message(s), \
{releases} synthetic release(s) ==="
    );
}
