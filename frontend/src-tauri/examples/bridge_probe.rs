//! Beweist den Proxy-Pfad des WebViews gegen den echten Server — ohne GUI.
//!
//! Genau der Weg, den die eingebettete Oberfläche nimmt: Adresse und Pin kommen aus dem
//! Profil, die Anfrage führt die Shell aus.

use streamarr_desktop_player::profile::ServerAddress;
use streamarr_media_lib::api::{ApiClient, RawBody, RawRequest};

fn main() {
    let mut server = ServerAddress::new("https://streamarr.luebke.internal");
    // Der Pin aus dem Profil — ohne ihn hängt die Anfrage 20 Sekunden und scheitert.
    server.resolve_override = Some("10.10.60.30:443".to_string());

    let client = ApiClient::new(&server).expect("Client");
    let rt = tokio::runtime::Runtime::new().unwrap();

    let request = RawRequest {
        method: "GET".to_string(),
        path: "/api/auth/status".to_string(),
        base_url: None,
        headers: vec![("Accept".to_string(), "application/json".to_string())],
        body: None,
        timeout_ms: Some(15000),
    };

    let started = std::time::Instant::now();
    match rt.block_on(client.raw_request(&request)) {
        Ok(response) => {
            println!("Dauer:  {:.0?}", started.elapsed());
            println!("Status: {} {}", response.status, response.status_text);
            match response.body {
                RawBody::Text(text) => println!("Body:   {}", &text[..120.min(text.len())]),
                RawBody::Base64(data) => println!("Body:   <{} Bytes base64>", data.len()),
                RawBody::Empty => println!("Body:   <leer>"),
            }
        }
        Err(err) => println!("FEHLER: {err}"),
    }

    // Und die Gegenprobe: ein fremder Host muss abgelehnt werden, damit eine
    // kompromittierte Seite die Zugangsdaten nicht woandershin schicken kann.
    let foreign = RawRequest {
        base_url: Some("https://example.com".to_string()),
        ..request.clone()
    };
    match rt.block_on(client.raw_request(&foreign)) {
        Ok(response) => println!("FREMDER HOST AKZEPTIERT: {}", response.status),
        Err(err) => println!("Fremder Host abgelehnt: {err}"),
    }
}
