//! Beweist den Auflösungs-Tunnel gegen einen echten Server.
//!
//! Genau der Weg, den die Wiedergabe nimmt: der Name bleibt in der URL (damit TLS
//! stimmt), die Verbindung geht über den lokalen Tunnel an die echte Adresse.
//!
//! Aufruf:
//!   SPIKE_URL=https://streamarr.luebke.internal/test.mkv \
//!   SPIKE_PIN=10.10.60.30 SPIKE_MPV=/usr/bin/mpv \
//!   cargo run --features mpv --bin spike-tunnel

use streamarr_desktop_player::resolve_tunnel::{tunnel_plan, ResolveTunnel};

fn main() {
    let url = std::env::var("SPIKE_URL").expect("SPIKE_URL");
    let pin = std::env::var("SPIKE_PIN").expect("SPIKE_PIN");
    let mpv_bin = std::env::var("SPIKE_MPV").unwrap_or_else(|_| "mpv".to_string());

    // Der Name und der Port, wie sie in der URL stehen.
    let rest = url.split("://").nth(1).expect("URL mit Schema");
    let authority = rest.split('/').next().unwrap();
    let (host, port) = match authority.rsplit_once(':') {
        Some((h, p)) => (h.to_string(), p.parse::<u16>().unwrap()),
        None => (authority.to_string(), 443),
    };

    let mapping = tunnel_plan(&host, port, Some(&pin)).expect("Der Pin muss eine IP-Adresse sein");
    println!("Name bleibt in der URL: {host}:{port}");
    println!("Verbindung geht an:     {}", mapping.target);

    let tunnel = ResolveTunnel::start(vec![mapping]).expect("Tunnel");
    println!("Tunnel:                 {}", tunnel.proxy_url());
    for line in tunnel.describe() {
        println!("Weiterleitung:          {line}");
    }

    // Nur den Tunnel bereitstellen und warten — damit lässt sich von außen prüfen,
    // ob die Verbindung wirklich beim echten Server landet (z. B. mit openssl s_client).
    if std::env::var("SPIKE_HOLD").is_ok() {
        println!("PROXY={}", tunnel.proxy_url());
        std::io::Write::flush(&mut std::io::stdout()).ok();
        std::thread::sleep(std::time::Duration::from_secs(
            std::env::var("SPIKE_HOLD_SECS")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(30),
        ));
        return;
    }

    let proxy_arg = format!("--http-proxy={}", tunnel.proxy_url());
    let mut mpv_args: Vec<String> = vec![
        "--no-config".into(),
        "--vo=null".into(),
        "--ao=null".into(),
        "--frames=30".into(),
        "--msg-level=all=info".into(),
        proxy_arg,
    ];
    // `SPIKE_CA` prüft die TLS-Kette durch den Tunnel hindurch. Für den echten Server
    // ist das unnötig (die Systemwurzeln greifen), für einen Testserver mit
    // selbstsigniertem Zertifikat ist es der Weg, TLS echt zu validieren statt es
    // abzuschalten — `--tls-verify=no` würde genau den Beweis zerstören.
    if let Ok(ca) = std::env::var("SPIKE_CA") {
        mpv_args.push(format!("--tls-ca-file={ca}"));
    }
    mpv_args.push(url.clone());

    let status = std::process::Command::new(&mpv_bin)
        .args(&mpv_args)
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .output()
        .expect("mpv");

    let log = String::from_utf8_lossy(&status.stderr);
    let decoded: Vec<&str> = log
        .lines()
        .filter(|l| l.contains("Video") || l.contains("AO:") || l.contains("TUNNEL"))
        .collect();

    println!("mpv-Ergebnis:           {}", status.status);
    for line in &decoded {
        println!("  {line}");
    }
    println!(
        "Angenommene Verbindungen: {}",
        tunnel.accepted_connections()
    );

    let ok = status.status.success() && tunnel.accepted_connections() > 0;
    println!(
        "ERGEBNIS: {}",
        if ok {
            "ueber den Tunnel abgespielt"
        } else {
            "FEHLGESCHLAGEN"
        }
    );
    std::process::exit(if ok { 0 } else { 1 });
}
