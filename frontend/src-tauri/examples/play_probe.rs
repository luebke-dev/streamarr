//! Beweist die native Wiedergabekette ohne GUI und ohne echten Server.
//!
//! Der Weg ist genau der der App: Wiedergabe-Antwort holen -> Plan bauen -> Tunnel
//! starten -> mpv mit `--http-proxy` starten -> Position beobachten.
//!
//! Aufruf:
//!   PLAY_BASE=https://streamarr.luebke.internal:8443 PLAY_PIN=127.0.0.1 \
//!   PLAY_CA=/tmp/rt/c.pem cargo run --example play_probe

use streamarr_desktop_player::mpv::{HdrMode, Mpv, PlayerState};
use streamarr_desktop_player::plan::{notices_for, plan_playback};
use streamarr_desktop_player::playback::PlayResponse;
use streamarr_desktop_player::profile::{Profile, ServerAddress};
use streamarr_desktop_player::resolve_tunnel::{tunnel_plan, ResolveTunnel};

fn main() {
    let base = std::env::var("PLAY_BASE").expect("PLAY_BASE");
    let pin = std::env::var("PLAY_PIN").expect("PLAY_PIN");
    let ca = std::env::var("PLAY_CA").ok();

    let mut server = ServerAddress::new(&base);
    server.resolve_override = Some(format!("{pin}:8443"));
    let profile = Profile::new("standard", "Standard", server.clone());

    // 1. Wiedergabe-Antwort holen — über den Client der App, also mit Pin.
    let client = streamarr_media_lib::api::ApiClient::new(&server).expect("Client");
    let rt = tokio::runtime::Runtime::new().unwrap();
    let request = streamarr_media_lib::api::RawRequest {
        method: "POST".to_string(),
        path: "/api/play/9b0308f3-9426-4e92-b765-1b05d87ed656".to_string(),
        base_url: None,
        headers: vec![("Accept".to_string(), "application/json".to_string())],
        body: Some("{}".to_string()),
        timeout_ms: Some(15000),
    };
    let response = rt.block_on(client.raw_request(&request)).expect("play");
    let text = match response.body {
        streamarr_media_lib::api::RawBody::Text(t) => t,
        _ => panic!("kein Text"),
    };
    let body: serde_json::Value = serde_json::from_str(&text).unwrap();
    let play = PlayResponse::parse(&body).expect("Antwort");
    println!(
        "1. Wiedergabe: {:?}, direct_play={}",
        play.method,
        play.is_direct_play()
    );

    // 2. Plan bauen — mit gespeicherter Position (der Stellvertreter meldet 4 s
    //    bei 10 s Laenge, passend zum echten Testmedium).
    let plan = plan_playback(
        &play,
        &server,
        &profile,
        std::path::Path::new("/tmp/rt/playerconf"),
        300.0,
        Some(600.0),
        false,
        HdrMode::Auto,
    )
    .expect("Plan");
    println!("2. Plan: {} -> {}", plan.url, plan.start_position);
    println!("   Hinweise: {:?}", notices_for(&plan));

    // 3. Tunnel starten — Name bleibt, Verbindung geht an den Pin.
    let mapping = tunnel_plan(&plan.stream_host, 8443, Some(&pin)).expect("Mapping");
    let tunnel = ResolveTunnel::start(vec![mapping]).expect("Tunnel");
    println!(
        "3. Tunnel: {} ({:?})",
        tunnel.proxy_url(),
        tunnel.describe()
    );

    // 4. mpv starten — ueber `Mpv::start`, also den getesteten Pfad der App.
    let mut options = plan.options.clone();
    options
        .extra_args
        .push(format!("--start={:.3}", plan.start_position));
    options
        .extra_args
        .push(format!("--http-proxy={}", tunnel.proxy_url()));
    if let Some(ca) = &ca {
        options.extra_args.push(format!("--tls-ca-file={ca}"));
    }
    options.ao = "null".to_string();
    options.vo = "null".to_string();

    let mut mpv = Mpv::start(&plan.url, &options).expect("mpv");
    println!("4. mpv gestartet: {}", mpv.ipc_endpoint());

    // 5. Ereignisse beobachten — genau die Schleife der Shell.
    let mut state = PlayerState {
        idle: false,
        ..Default::default()
    };
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(25);
    let mut saw_position = false;
    while std::time::Instant::now() < deadline {
        if let Some(event) = mpv.next_event(std::time::Duration::from_millis(200)) {
            let name = event.get("event").and_then(|v| v.as_str()).unwrap_or("");
            if name == "property-change" {
                let prop = event.get("name").and_then(|v| v.as_str()).unwrap_or("");
                let data = event
                    .get("data")
                    .cloned()
                    .unwrap_or(serde_json::Value::Null);
                if state.apply_event(prop, &data) && prop == "time-pos" {
                    println!(
                        "   Position: {:.2}s / {:.2}s",
                        state.position, state.duration
                    );
                    if state.position >= 298.0 && !saw_position {
                        saw_position = true;
                        println!("   -> bei der gespeicherten Position angekommen");
                        break;
                    }
                }
            } else if name == "file-loaded" {
                println!("   Datei geladen");
            }
        }
        if mpv.has_exited() {
            break;
        }
    }
    mpv.stop();

    let ok = saw_position && tunnel.accepted_connections() > 0;
    println!(
        "5. Verbindungen durch den Tunnel: {}",
        tunnel.accepted_connections()
    );
    println!(
        "ERGEBNIS: {}",
        if ok {
            "Wiedergabe ueber den Tunnel, bei der gespeicherten Position"
        } else {
            "FEHLGESCHLAGEN"
        }
    );
    std::process::exit(if ok { 0 } else { 1 });
}
