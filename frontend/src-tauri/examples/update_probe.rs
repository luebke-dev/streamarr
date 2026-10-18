//! Live probe for the update check (plan task 1.6).
//!
//! Answers, against the real release feed, the questions a unit test cannot:
//!
//!   1. Is the feed reachable from this machine at all, without any Streamarr instance,
//!      any profile and any token?
//!   2. What does the app decide for *this* build, with the configuration as it is?
//!
//! Run from `frontend/src-tauri`:
//!
//! ```text
//! cargo run --example update_probe
//! ```
//!
//! Nothing is installed. The command under test deliberately only reports.

use streamarr_desktop_player::updater::{is_configured, Channel, Release};
use streamarr_media_lib::commands::update::{
    channel_for_version, evaluate, fetch_release, parse_feed,
};

const DEFAULT_ENDPOINT: &str =
    "https://github.com/luebke-dev/streamarr/releases/latest/download/latest.json";

// `tokio` is available without the `macros` feature, so the runtime is built explicitly
// rather than with `#[tokio::main]`. Tauri owns the runtime in the real app; a probe has to
// make its own.
fn main() {
    tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .expect("Laufzeit")
        .block_on(run())
}

async fn run() {
    let endpoint = std::env::args()
        .nth(1)
        .unwrap_or_else(|| DEFAULT_ENDPOINT.to_string());
    // The real key lives only in release builds; a placeholder is what a developer build has.
    let pubkey = std::env::var("STREAMARR_UPDATE_PUBKEY")
        .unwrap_or_else(|_| streamarr_desktop_player::updater::PUBKEY_PLACEHOLDER.to_string());
    let current = env!("CARGO_PKG_VERSION");
    let channel = channel_for_version(current);

    println!("Update-Probe (Aufgabe 1.6)");
    println!("  Build-Version : {current}");
    println!("  Kanal         : {}", channel.as_str());
    println!("  Endpunkt      : {endpoint}");
    println!(
        "  Signierschlüssel: {}",
        if is_configured(Some(&endpoint), Some(&pubkey)) {
            "gesetzt"
        } else {
            "Platzhalter (Build ohne Updates)"
        }
    );
    println!();

    // Point 1: reachability, with no profile and no credentials anywhere in the call.
    let release: Option<Release> = match fetch_release(&endpoint).await {
        Ok(release) => {
            println!("Abruf: erfolgreich.");
            release
        }
        Err(e) => {
            println!("Abruf: fehlgeschlagen — {e}");
            None
        }
    };
    if let Some(release) = &release {
        println!(
            "  Version aus dem Feed: {} (Kanal {:?})",
            release.version, release.channel
        );
    }
    println!();

    // Point 2: what this build decides, using the same pure function the command uses.
    let outcome = evaluate(
        current,
        channel,
        Some(&endpoint),
        Some(&pubkey),
        release.as_ref(),
    );
    println!("Entscheidung : {}", outcome.describe());
    println!("  konfiguriert : {}", outcome.is_configured());
    println!("  für Nutzer   : {}", outcome.is_user_visible());

    // And once more with a key that looks real, so the *decision* is exercised rather than
    // the unconfigured short-circuit. This is the path a release build takes.
    let with_real_key = evaluate(
        current,
        channel,
        Some(&endpoint),
        Some("RWQexampleRealLookingPublicKey"),
        release.as_ref(),
    );
    println!();
    println!("Mit gesetztem Schlüssel (so verhält sich ein Release-Build):");
    println!("  {}", with_real_key.describe());
    println!("  für Nutzer : {}", with_real_key.is_user_visible());

    // A feed without any release is the normal state before the first one — make that
    // visible rather than leaving it as an untested branch.
    let empty = parse_feed("{}");
    println!();
    println!(
        "Feed ohne Angabe einer Version -> {:?} (kein Fehler, kein Update)",
        empty
    );

    let _ = Channel::Stable;
}
