//! A loopback tunnel that makes a pinned server address reachable by mpv.
//!
//! # The problem
//!
//! The app reaches the server through an address pin: the hostname stays in the URL,
//! because the certificate covers only `*.luebke.internal` (measured — entering the IP
//! directly fails TLS), but the TCP connection goes to the real address. For the app's
//! own HTTP client that is a field on the request. **mpv has no equivalent of curl's
//! `--resolve`** (checked against mpv 0.41), so a URL handed to mpv is resolved by the
//! system resolver, which for this deployment returns a dead address — and the stream
//! then never starts, with no error at all. Spike 0.3 worked around that by bind-mounting
//! a patched `/etc/hosts` into a mount namespace, which needs root.
//!
//! # The solution, and why it is this one
//!
//! mpv hands HTTP(S) URLs to FFmpeg, and FFmpeg's HTTP protocol **supports a proxy**
//! (`-http_proxy`), which mpv exposes as `--http-proxy`. Measured: with
//! `--http-proxy=http://127.0.0.1:8888` mpv connects, receives `Video --vid=1 (h264
//! 640x360 25 fps)` and exits 0, while the proxy log shows
//! `CONNECT streamarr.luebke.internal:443`.
//!
//! So a tiny loopback proxy does the job. It is chosen over the alternatives for
//! concrete reasons:
//!
//! * **Not `/etc/hosts`.** That is a system-wide change needing root, and it would
//!   affect every other program on the machine.
//! * **Not rewriting the URL to the IP.** That breaks TLS: the certificate has no IP
//!   subject alternative name (`SAN: DNS:*.luebke.internal, DNS:luebke.internal`).
//! * **Not disabling certificate verification.** That would turn a name-resolution
//!   problem into a security hole, and the stream would be unprotected.
//! * **Not a global proxy for the whole app.** Only mpv is pointed at it, only for the
//!   one host and port in question.
//!
//! A `CONNECT` tunnel forwards raw bytes, so TLS is negotiated end to end between mpv
//! and the server: the hostname in the URL is still what the certificate is validated
//! against. The proxy sees only ciphertext, and it is bound to `127.0.0.1`, so it is not
//! reachable from the network.
//!
//! # What it deliberately is not
//!
//! Not an open proxy. It forwards only to the `host:port` pairs it was created with and
//! answers everything else with `403`. A local program — or a page in the webview — that
//! finds the port cannot use it to reach arbitrary hosts, and it cannot be used as an
//! HTTP proxy for plain requests at all.

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::net::{IpAddr, SocketAddr, TcpListener, TcpStream};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

/// How long a single tunnel may sit idle before it is closed.
///
/// Generous, because a paused video holds its connection open without transferring
/// anything; a timeout that is too short would end playback during a pause. Its job is
/// only to stop a dead peer from leaking a thread and a socket forever.
const TUNNEL_IDLE_TIMEOUT: Duration = Duration::from_secs(30 * 60);

/// How long to wait for a client's `CONNECT` line.
const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(10);

/// One destination the proxy is allowed to reach.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct Mapping {
    pub host: String,
    pub port: u16,
    pub target: IpAddr,
}

impl Mapping {
    /// A mapping that keeps the port and only redirects the address.
    pub fn to_ip(host: impl Into<String>, port: u16, target: IpAddr) -> Self {
        Self {
            host: host.into().to_lowercase(),
            port,
            target,
        }
    }
}

/// Why a tunnel could not be established.
#[derive(Debug)]
pub enum ProxyError {
    /// The loopback port could not be bound.
    Bind(std::io::Error),
    /// No destination was given, so there is nothing to do.
    NoMappings,
    /// An address string could not be read as an IP.
    BadTarget(String),
}

impl std::fmt::Display for ProxyError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Bind(e) => write!(f, "Der lokale Hilfsdienst konnte nicht starten: {e}"),
            Self::NoMappings => write!(
                f,
                "Ohne Zieladresse wird kein lokaler Hilfsdienst gestartet."
            ),
            Self::BadTarget(t) => write!(f, "`{t}` ist keine gültige IP-Adresse."),
        }
    }
}

impl std::error::Error for ProxyError {}

/// A running tunnel. Dropping it stops the listener.
pub struct ResolveTunnel {
    port: u16,
    mappings: Arc<HashMap<(String, u16), IpAddr>>,
    shutdown: Arc<AtomicBool>,
    /// Number of connections accepted, for tests and for the log.
    accepted: Arc<AtomicUsize>,
}

impl ResolveTunnel {
    /// Starts the tunnel for the given destinations.
    ///
    /// The listener binds to an ephemeral port on loopback, so several profiles (or two
    /// runs of the test suite) never collide.
    pub fn start(mappings: Vec<Mapping>) -> Result<Self, ProxyError> {
        if mappings.is_empty() {
            return Err(ProxyError::NoMappings);
        }
        let table: HashMap<(String, u16), IpAddr> = mappings
            .into_iter()
            .map(|m| ((m.host.to_lowercase(), m.port), m.target))
            .collect();

        let listener = TcpListener::bind(("127.0.0.1", 0)).map_err(ProxyError::Bind)?;
        let port = listener.local_addr().map_err(ProxyError::Bind)?.port();

        let mappings = Arc::new(table);
        let shutdown = Arc::new(AtomicBool::new(false));
        let accepted = Arc::new(AtomicUsize::new(0));

        let thread_mappings = Arc::clone(&mappings);
        let thread_shutdown = Arc::clone(&shutdown);
        let thread_accepted = Arc::clone(&accepted);

        std::thread::Builder::new()
            .name("streamarr-resolve-tunnel".to_string())
            .spawn(move || {
                serve(listener, thread_mappings, thread_shutdown, thread_accepted);
            })
            .map_err(ProxyError::Bind)?;

        Ok(Self {
            port,
            mappings,
            shutdown,
            accepted,
        })
    }

    /// The `--http-proxy` value for mpv.
    pub fn proxy_url(&self) -> String {
        format!("http://127.0.0.1:{}", self.port)
    }

    pub fn port(&self) -> u16 {
        self.port
    }

    /// How many connections were accepted, for diagnostics.
    pub fn accepted_connections(&self) -> usize {
        self.accepted.load(Ordering::Relaxed)
    }

    /// The destinations this tunnel will forward to, for a log line that makes a
    /// misconfiguration visible.
    pub fn describe(&self) -> Vec<String> {
        let mut out: Vec<String> = self
            .mappings
            .iter()
            .map(|((host, port), ip)| format!("{host}:{port} → {ip}"))
            .collect();
        out.sort();
        out
    }
}

impl Drop for ResolveTunnel {
    fn drop(&mut self) {
        self.shutdown.store(true, Ordering::Relaxed);
        // Wakes the blocking `accept` so the thread can notice the flag.
        let _ = TcpStream::connect(("127.0.0.1", self.port));
    }
}

fn serve(
    listener: TcpListener,
    mappings: Arc<HashMap<(String, u16), IpAddr>>,
    shutdown: Arc<AtomicBool>,
    accepted: Arc<AtomicUsize>,
) {
    for incoming in listener.incoming() {
        if shutdown.load(Ordering::Relaxed) {
            return;
        }
        let Ok(client) = incoming else { continue };
        accepted.fetch_add(1, Ordering::Relaxed);
        // One thread per tunnel: a video stream is long-lived and mostly idle, and a
        // thread pool would add a dependency for no benefit at this scale.
        let thread_mappings = Arc::clone(&mappings);
        std::thread::spawn(move || {
            let _ = handle_client(client, &thread_mappings);
        });
    }
}

/// Answers one client: read the request line, tunnel or refuse.
fn handle_client(
    mut client: TcpStream,
    mappings: &HashMap<(String, u16), IpAddr>,
) -> std::io::Result<()> {
    client.set_read_timeout(Some(HANDSHAKE_TIMEOUT))?;
    let mut reader = BufReader::new(client.try_clone()?);

    let mut request_line = String::new();
    if reader.read_line(&mut request_line)? == 0 {
        return Ok(());
    }
    // Drain the rest of the request headers so nothing is left to confuse the tunnel.
    loop {
        let mut line = String::new();
        if reader.read_line(&mut line)? == 0 || line == "\r\n" || line == "\n" {
            break;
        }
    }

    let mut parts = request_line.split_whitespace();
    let method = parts.next().unwrap_or_default().to_ascii_uppercase();
    let target = parts.next().unwrap_or_default().to_string();

    if method != "CONNECT" {
        // FFmpeg may send a plain proxied GET for `http://` URLs. Answering that would
        // mean implementing a proxy for cleartext traffic, which is more surface than
        // this needs — the app only ever streams over TLS.
        let _ = client.write_all(
            b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
        );
        return Ok(());
    }

    let Some((host, port)) = split_host_port(&target) else {
        let _ = client.write_all(
            b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
        );
        return Ok(());
    };

    // The allow-list is the point: a local program that finds the port must not be able
    // to use it as a general-purpose proxy.
    let Some(ip) = mappings.get(&(host.to_lowercase(), port)) else {
        let _ = client
            .write_all(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
        return Ok(());
    };

    let upstream = match TcpStream::connect(SocketAddr::new(*ip, port)) {
        Ok(stream) => stream,
        Err(_) => {
            // 502 rather than a bare close, so the failure is visible in mpv's log as a
            // proxy error instead of looking like a broken stream.
            let _ = client.write_all(
                b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
            );
            return Ok(());
        }
    };

    // From here on the bytes are the client's own; the handshake timeout must go, or a
    // quiet stream would be cut off mid-film.
    client.set_read_timeout(Some(TUNNEL_IDLE_TIMEOUT))?;
    client.set_write_timeout(Some(TUNNEL_IDLE_TIMEOUT))?;
    let _ = upstream.set_read_timeout(Some(TUNNEL_IDLE_TIMEOUT));
    let _ = upstream.set_write_timeout(Some(TUNNEL_IDLE_TIMEOUT));

    client.write_all(b"HTTP/1.1 200 Connection Established\r\n\r\n")?;

    let mut upstream_reader = upstream.try_clone()?;
    let mut client_writer = client.try_clone()?;
    let up = std::thread::spawn(move || {
        let _ = std::io::copy(&mut upstream_reader, &mut client_writer);
        let _ = client_writer.shutdown(std::net::Shutdown::Write);
    });
    let _ = std::io::copy(&mut reader.into_inner(), &mut upstream.try_clone()?);
    let _ = upstream.shutdown(std::net::Shutdown::Write);
    let _ = up.join();
    Ok(())
}

/// Splits `host:port`, tolerating an IPv6 literal in brackets.
fn split_host_port(target: &str) -> Option<(String, u16)> {
    let (host, port) = if let Some(rest) = target.strip_prefix('[') {
        let (host, after) = rest.split_once(']')?;
        (host.to_string(), after.strip_prefix(':')?)
    } else {
        let (host, port) = target.rsplit_once(':')?;
        (host.to_string(), port)
    };
    if host.is_empty() {
        return None;
    }
    Some((host, port.parse::<u16>().ok()?))
}

/// Whether a proxy is needed at all, and what it must map.
///
/// Separated from the tunnel so the decision is testable without opening a socket.
pub fn tunnel_plan(host: &str, url_port: u16, pin: Option<&str>) -> Option<Mapping> {
    let pin = pin?.trim();
    if pin.is_empty() {
        return None;
    }
    // Try the whole value as an address first. Splitting on the last colon would turn
    // the bare IPv6 literal `::1` into host `::` and port `1` — a wrong destination
    // rather than a visible failure, which is the worst kind. Only if it is not an
    // address is it read as `ip:port`.
    let ip: IpAddr = match pin.parse() {
        Ok(ip) => ip,
        Err(_) => {
            // The pin may be `ip:port`; the port in the URL still wins, because that is
            // where mpv will send the CONNECT.
            let (ip_part, _) = split_host_port(pin)?;
            ip_part.parse().ok()?
        }
    };
    Some(Mapping::to_ip(host, url_port, ip))
}

#[cfg(test)]
mod tests {
    use super::*;
    // Only the tests read from a stream directly.
    use std::io::Read;
    use std::net::Ipv4Addr;

    /// A stand-in for the media server: it accepts, sends a greeting and echoes.
    fn spawn_upstream() -> (u16, std::thread::JoinHandle<()>) {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let port = listener.local_addr().unwrap().port();
        let handle = std::thread::spawn(move || {
            for stream in listener.incoming().take(4) {
                let Ok(mut stream) = stream else { continue };
                std::thread::spawn(move || {
                    let _ = stream.write_all(b"UPSTREAM-HELLO");
                    let mut buf = [0u8; 64];
                    if let Ok(n) = stream.read(&mut buf) {
                        let _ = stream.write_all(&buf[..n]);
                    }
                });
            }
        });
        (port, handle)
    }

    fn connect_through(proxy_port: u16, target: &str) -> std::io::Result<TcpStream> {
        let mut stream = TcpStream::connect(("127.0.0.1", proxy_port))?;
        stream.set_read_timeout(Some(Duration::from_secs(5)))?;
        write!(
            stream,
            "CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n"
        )?;
        let mut reader = BufReader::new(stream.try_clone()?);
        let mut status = String::new();
        reader.read_line(&mut status)?;
        // Headers until the blank line.
        loop {
            let mut line = String::new();
            if reader.read_line(&mut line)? == 0 || line == "\r\n" || line == "\n" {
                break;
            }
        }
        Ok(stream)
    }

    #[test]
    fn a_tunnel_carries_bytes_both_ways() {
        let (upstream_port, _up) = spawn_upstream();
        let tunnel = ResolveTunnel::start(vec![Mapping::to_ip(
            "streamarr.luebke.internal",
            upstream_port,
            IpAddr::V4(Ipv4Addr::LOCALHOST),
        )])
        .unwrap();

        let mut stream = connect_through(
            tunnel.port(),
            &format!("streamarr.luebke.internal:{upstream_port}"),
        )
        .unwrap();

        let mut greeting = [0u8; 14];
        stream.read_exact(&mut greeting).unwrap();
        assert_eq!(&greeting, b"UPSTREAM-HELLO");

        stream.write_all(b"ping").unwrap();
        let mut echo = [0u8; 4];
        stream.read_exact(&mut echo).unwrap();
        assert_eq!(&echo, b"ping");

        assert_eq!(tunnel.accepted_connections(), 1);
    }

    #[test]
    fn the_client_is_told_the_tunnel_is_established() {
        let (upstream_port, _up) = spawn_upstream();
        let tunnel = ResolveTunnel::start(vec![Mapping::to_ip(
            "host",
            upstream_port,
            IpAddr::V4(Ipv4Addr::LOCALHOST),
        )])
        .unwrap();

        let stream = TcpStream::connect(("127.0.0.1", tunnel.port())).unwrap();
        let mut reader = BufReader::new(stream.try_clone().unwrap());
        {
            let mut w = stream.try_clone().unwrap();
            write!(w, "CONNECT host:{upstream_port} HTTP/1.1\r\n\r\n").unwrap();
        }
        let mut status = String::new();
        reader.read_line(&mut status).unwrap();
        assert!(status.starts_with("HTTP/1.1 200"), "{status}");
        // The blank line must terminate the headers, or a client would read them as
        // tunnel payload.
        let mut line = String::new();
        reader.read_line(&mut line).unwrap();
        assert_eq!(line, "\r\n");
    }

    #[test]
    fn a_host_that_was_not_configured_is_refused() {
        let (upstream_port, _up) = spawn_upstream();
        let tunnel = ResolveTunnel::start(vec![Mapping::to_ip(
            "allowed",
            upstream_port,
            IpAddr::V4(Ipv4Addr::LOCALHOST),
        )])
        .unwrap();

        // Same port, different host: this is exactly the request a program abusing the
        // proxy would make.
        let mut stream = TcpStream::connect(("127.0.0.1", tunnel.port())).unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(5)))
            .unwrap();
        write!(
            stream,
            "CONNECT evil.example:{upstream_port} HTTP/1.1\r\n\r\n"
        )
        .unwrap();
        let mut reader = BufReader::new(stream);
        let mut status = String::new();
        reader.read_line(&mut status).unwrap();
        assert!(status.starts_with("HTTP/1.1 403"), "{status}");
    }

    #[test]
    fn the_same_host_on_another_port_is_refused() {
        let (upstream_port, _up) = spawn_upstream();
        let tunnel = ResolveTunnel::start(vec![Mapping::to_ip(
            "host",
            upstream_port,
            IpAddr::V4(Ipv4Addr::LOCALHOST),
        )])
        .unwrap();

        let other = if upstream_port == 9 { 10 } else { 9 };
        let mut stream = TcpStream::connect(("127.0.0.1", tunnel.port())).unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(5)))
            .unwrap();
        write!(stream, "CONNECT host:{other} HTTP/1.1\r\n\r\n").unwrap();
        let mut status = String::new();
        BufReader::new(stream).read_line(&mut status).unwrap();
        assert!(status.starts_with("HTTP/1.1 403"), "{status}");
    }

    #[test]
    fn a_plain_proxy_request_is_refused_rather_than_served() {
        let (upstream_port, _up) = spawn_upstream();
        let tunnel = ResolveTunnel::start(vec![Mapping::to_ip(
            "host",
            upstream_port,
            IpAddr::V4(Ipv4Addr::LOCALHOST),
        )])
        .unwrap();

        // An absolute-form GET is what a client sends to a normal HTTP proxy. Serving it
        // would mean also stripping and forwarding cleartext requests — more surface
        // than this needs.
        let mut stream = TcpStream::connect(("127.0.0.1", tunnel.port())).unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(5)))
            .unwrap();
        write!(
            stream,
            "GET http://host:{upstream_port}/ HTTP/1.1\r\nHost: host\r\n\r\n"
        )
        .unwrap();
        let mut status = String::new();
        BufReader::new(stream).read_line(&mut status).unwrap();
        assert!(status.starts_with("HTTP/1.1 405"), "{status}");
    }

    #[test]
    fn a_host_is_matched_case_insensitively() {
        let (upstream_port, _up) = spawn_upstream();
        // Hostnames are case-insensitive; a client may send either spelling.
        let tunnel = ResolveTunnel::start(vec![Mapping::to_ip(
            "Streamarr.Luebke.Internal",
            upstream_port,
            IpAddr::V4(Ipv4Addr::LOCALHOST),
        )])
        .unwrap();

        let stream = connect_through(
            tunnel.port(),
            &format!("streamarr.luebke.internal:{upstream_port}"),
        );
        assert!(stream.is_ok(), "the tunnel must be established");
    }

    #[test]
    fn a_missing_upstream_answers_502_instead_of_hanging() {
        // Nothing listening on this port.
        let tunnel = ResolveTunnel::start(vec![Mapping::to_ip(
            "host",
            1,
            IpAddr::V4(Ipv4Addr::LOCALHOST),
        )])
        .unwrap();

        let mut stream = TcpStream::connect(("127.0.0.1", tunnel.port())).unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(5)))
            .unwrap();
        write!(stream, "CONNECT host:1 HTTP/1.1\r\n\r\n").unwrap();
        let mut status = String::new();
        BufReader::new(stream).read_line(&mut status).unwrap();
        // A bare close would look like a broken stream in mpv's log; 502 names it.
        assert!(status.starts_with("HTTP/1.1 502"), "{status}");
    }

    #[test]
    fn the_proxy_url_points_at_loopback() {
        let tunnel = ResolveTunnel::start(vec![Mapping::to_ip(
            "host",
            443,
            IpAddr::V4(Ipv4Addr::LOCALHOST),
        )])
        .unwrap();
        assert!(tunnel.proxy_url().starts_with("http://127.0.0.1:"));
        assert!(tunnel.proxy_url().ends_with(&tunnel.port().to_string()));
        assert_ne!(tunnel.port(), 0, "an ephemeral port must be resolved");
    }

    #[test]
    fn starting_without_a_destination_is_an_error_not_an_open_proxy() {
        // An empty allow-list would be a proxy that refuses everything, i.e. useless —
        // and the honest thing is to say so rather than start it.
        let result = ResolveTunnel::start(vec![]);
        assert!(matches!(result, Err(ProxyError::NoMappings)));
    }

    #[test]
    fn the_destinations_are_described_for_the_log() {
        let tunnel = ResolveTunnel::start(vec![Mapping::to_ip(
            "streamarr.luebke.internal",
            443,
            "10.10.60.30".parse().unwrap(),
        )])
        .unwrap();
        let described = tunnel.describe();
        assert_eq!(
            described,
            vec!["streamarr.luebke.internal:443 → 10.10.60.30"]
        );
    }

    #[test]
    fn dropping_the_tunnel_stops_accepting() {
        let tunnel = ResolveTunnel::start(vec![Mapping::to_ip(
            "host",
            443,
            IpAddr::V4(Ipv4Addr::LOCALHOST),
        )])
        .unwrap();
        let port = tunnel.port();
        // Reachable while alive.
        assert!(TcpStream::connect(("127.0.0.1", port)).is_ok());
        drop(tunnel);
        // The listener is gone. Retried, because closing a socket is not instantaneous
        // and a single attempt is a flaky test.
        let mut refused = false;
        for _ in 0..40 {
            if TcpStream::connect(("127.0.0.1", port)).is_err() {
                refused = true;
                break;
            }
            std::thread::sleep(Duration::from_millis(25));
        }
        assert!(
            refused,
            "the port must stop answering after the tunnel is dropped"
        );
    }

    #[test]
    fn the_plan_only_exists_when_a_pin_is_set() {
        assert!(tunnel_plan("host", 443, None).is_none());
        assert!(tunnel_plan("host", 443, Some("")).is_none());
        assert!(tunnel_plan("host", 443, Some("   ")).is_none());
    }

    #[test]
    fn the_plan_reads_the_pin_with_and_without_a_port() {
        // A bare IP: the URL's port is the destination port.
        let mapping = tunnel_plan("host", 443, Some("10.10.60.30")).unwrap();
        assert_eq!(mapping.target, "10.10.60.30".parse::<IpAddr>().unwrap());
        assert_eq!(mapping.port, 443, "the URL's port wins");
        assert_eq!(mapping.host, "host");

        // `ip:port` is accepted too, because that is the shape the profile stores.
        let mapping = tunnel_plan("host", 443, Some("10.10.60.30:8443")).unwrap();
        assert_eq!(mapping.port, 443, "the URL's port still wins");
    }

    #[test]
    fn a_pin_that_is_not_an_address_is_ignored_rather_than_guessed() {
        // A hostname in the pin field would mean a second DNS lookup, which is exactly
        // what the pin exists to avoid. Refusing is better than resolving.
        assert!(tunnel_plan("host", 443, Some("other.example")).is_none());
        assert!(tunnel_plan("host", 443, Some("10.10.60.999")).is_none());
    }

    #[test]
    fn an_ipv6_target_is_accepted() {
        let mapping = tunnel_plan("host", 443, Some("::1")).unwrap();
        assert_eq!(mapping.target, "::1".parse::<IpAddr>().unwrap());
    }

    #[test]
    fn a_malformed_connect_target_is_a_bad_request() {
        assert!(split_host_port("nohost").is_none());
        assert!(split_host_port(":443").is_none());
        assert!(split_host_port("host:notaport").is_none());
        // A bracketed IPv6 literal, which is how CONNECT carries one.
        assert_eq!(split_host_port("[::1]:443"), Some(("::1".to_string(), 443)));
    }
}
