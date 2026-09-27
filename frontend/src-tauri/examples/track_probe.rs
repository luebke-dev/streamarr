//! Live probe for track selection against a real mpv (plan task 2.6).
//!
//! A native client cannot ask the browser for its `TextTrack` list — there is no browser
//! here — and the browser's list would be of the *stream* the player was handed, not of
//! what mpv resolved after demuxing. For a container carrying several audio tracks those
//! are not the same thing, so the list has to come from mpv.
//!
//! This prints what mpv reports, which is exactly what `player_tracks` hands the
//! interface. Run from `frontend/src-tauri`:
//!
//! ```text
//! ./desktop/scripts/make_test_media.sh
//! cargo run --example track_probe -- /tmp/mpvt/test.mkv
//! cargo run --example track_probe -- /tmp/mpvt/sub.mkv
//! ```

use std::time::{Duration, Instant};

use streamarr_desktop_player::mpv::{Mpv, PlayerOptions, TrackKind};

fn main() {
    let path = std::env::args().nth(1).expect("Dateipfad");
    println!("Spurerkennung (Aufgabe 2.6) — {path}");
    println!();

    // Silent, so the probe runs on a machine with no audio device — and so a CI run does
    // not play anything.
    let opts = PlayerOptions {
        ao: "null".to_string(),
        ..Default::default()
    };
    let mut mpv = Mpv::start(&path, &opts).expect("mpv startet");

    // The track list does not exist before the file is loaded (defect 5 of spike 0.3), so
    // reading it earlier would report an empty list and look like "no tracks".
    let deadline = Instant::now() + Duration::from_secs(15);
    let mut loaded = false;
    while Instant::now() < deadline {
        if let Some(event) = mpv.next_event(Duration::from_millis(300)) {
            if event.get("event").and_then(|v| v.as_str()) == Some("file-loaded") {
                loaded = true;
                break;
            }
        }
    }
    println!("file-loaded: {loaded}");
    println!();

    let list = mpv.track_list();

    println!("Audiospuren: {}", list.audio().len());
    for track in list.audio() {
        println!(
            "  id={} label={:?} lang={:?} codec={:?} ausgewählt={}",
            track.id,
            track.label(),
            track.language,
            track.codec,
            track.selected
        );
    }

    println!("Untertitelspuren: {}", list.subtitles().len());
    for track in list.subtitles() {
        println!(
            "  id={} label={:?} lang={:?} extern={} leer={}",
            track.id,
            track.label(),
            track.language,
            track.external,
            track.is_default
        );
    }

    let selected_audio = list.selected(TrackKind::Audio).map(|t| t.id);
    let selected_subtitle = list.selected(TrackKind::Subtitle).map(|t| t.id);
    println!();
    println!("Ausgewählt: audio={selected_audio:?} sub={selected_subtitle:?}");

    // These are the ids the interface passes back to `player_set_property`.
    if let Some(first_other) = list.audio().iter().find(|t| !t.selected) {
        println!("Umschalten würde `aid={}` setzen.", first_other.id);
    }
}
