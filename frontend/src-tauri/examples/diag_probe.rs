// Beweist die Diagnose gegen den ECHTEN Server, ohne GUI.
use streamarr_desktop_player::profile::ServerAddress;
fn main() {
    let server = ServerAddress::new("https://streamarr.luebke.internal");
    let client = streamarr_media_lib::api::ApiClient::new(&server).unwrap();
    let rt = tokio::runtime::Runtime::new().unwrap();
    let started = std::time::Instant::now();
    let result = rt.block_on(client.auth_status());
    let elapsed = started.elapsed();
    println!("Dauer: {:.1?}", elapsed);
    match result {
        Ok(v) => println!("ERFOLG: {}", &v.to_string()[..60.min(v.to_string().len())]),
        Err(e) => {
            let (kind, detail) = e.failure();
            println!("Detail:  {detail}");
            let d = streamarr_media_lib::api::diagnose(&server, kind, &detail);
            println!("Art:     {kind:?}");
            println!("Problem: {}", d.problem);
            println!("Rat:     {}", d.advice.unwrap_or_else(|| "-".into()));
            println!("Pin?     {}", d.suggests_pin);
        }
    }
}
