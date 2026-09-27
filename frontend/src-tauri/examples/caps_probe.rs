//! Live probe for the measured capability claim (plan tasks 2.2 and 2.9).
//!
//! Prints what the shell now reports to the server, built from a real EDID and a real mpv
//! rather than from constants. This is the value the server acts on when it decides
//! between direct play and transcode, and between sending HDR and tone-mapping it.
//!
//! Run from `frontend/src-tauri`:
//!
//! ```text
//! cargo run --example caps_probe
//! ```

use streamarr_media_lib::commands::session::detect_capabilities;

fn main() {
    println!("Gemessene Geräte-Capabilities (Aufgaben 2.2 / 2.9)");
    println!();

    // The width is passed so the resolution tier can be computed; the shell reads it from
    // the main window, which a probe has no access to.
    let detected = detect_capabilities(3840);
    let caps = &detected.capabilities;

    println!("Messgrundlage:");
    for note in &detected.notes {
        println!("  · {note}");
    }
    println!();

    println!("Gemeldete Fähigkeiten:");
    println!("  app_name          : {}", caps.app_name);
    println!("  app_version       : {}", caps.app_version);
    println!("  max_resolution    : {}", caps.max_resolution.as_str());
    println!(
        "  hardware_decode   : {}   ← gemessen, nicht angenommen",
        caps.hardware_decode
    );
    println!(
        "  supports_hdr      : {}   ← Display UND Renderer müssen beide können",
        caps.supports_hdr
    );
    println!();

    println!(
        "  Video-Codecs      : {}",
        caps.video_codecs
            .iter()
            .map(|c| c.as_str())
            .collect::<Vec<_>>()
            .join(", ")
    );
    println!(
        "  Audio-Codecs      : {}",
        caps.audio_codecs
            .iter()
            .map(|c| c.as_str())
            .collect::<Vec<_>>()
            .join(", ")
    );
    println!();

    println!("An den Server als Abfrageparameter:");
    for (key, value) in caps.play_query() {
        println!("  {key}={value}");
    }
}
