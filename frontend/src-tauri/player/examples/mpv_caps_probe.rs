//! Live probe for the mpv capability detection (plan task 2.2).
//!
//! Answers, against the mpv actually installed on this machine, what the unit tests
//! cannot: what the capability set looks like in full, and whether the two HDR answers
//! come out as expected.
//!
//! Run from `frontend/src-tauri/player`:
//!
//! ```text
//! cargo run --example mpv_caps_probe
//! ```

use streamarr_desktop_player::mpv_caps::{binary, detect};

fn main() {
    let binary = binary();
    println!("mpv-Fähigkeitserkennung (Aufgabe 2.2)");
    println!("  Binary: {binary}");
    println!();

    let Some(caps) = detect() else {
        println!("Kein brauchbares mpv gefunden — die App würde das melden statt zu starten.");
        std::process::exit(1);
    };

    println!("{}", caps.describe());
    println!();
    println!(
        "  mpv-Version  : {}",
        caps.version.as_deref().unwrap_or("?")
    );
    println!(
        "  libplacebo   : {}",
        caps.libplacebo.as_deref().unwrap_or("?")
    );
    println!();

    println!("Videoausgänge ({}):", caps.video_outputs.len());
    for vo in &caps.video_outputs {
        println!("  {vo}");
    }
    println!();

    println!("Audiopässe ({}):", caps.audio_outputs.len());
    println!(
        "  {}",
        caps.audio_outputs
            .iter()
            .cloned()
            .collect::<Vec<_>>()
            .join(", ")
    );
    println!();

    println!("Hardware-Dekoder ({}):", caps.hwdec.len());
    println!(
        "  {}",
        caps.hwdec.iter().cloned().collect::<Vec<_>>().join(", ")
    );
    println!();

    println!("Optionen insgesamt: {}", caps.options.len());
    for wanted in [
        "target-colorspace-hint",
        "target-prim",
        "target-trc",
        "tone-mapping",
        "hdr-compute-peak",
    ] {
        println!(
            "  {wanted:<24} {}",
            if caps.has_option(wanted) {
                "ja"
            } else {
                "nein"
            }
        );
    }
    println!();

    // The three conclusions the app draws from this. Printed explicitly because they are
    // what the shell acts on, and a wrong "ja" here is a capability claimed to the server.
    println!("Schlussfolgerungen:");
    println!("  brauchbar (is_usable)          : {}", caps.is_usable());
    println!(
        "  Hardware-Dekodierung           : {}",
        caps.has_hardware_decode()
    );
    println!(
        "  HDR-Durchreichung (gpu-next)   : {}",
        caps.supports_hdr_passthrough()
    );
    println!("  Tone-Mapping nach SDR          : {}", caps.can_tone_map());
}
