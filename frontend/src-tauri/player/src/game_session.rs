//! Game-session lifecycle: from a game id to a live stream, and back.
//!
//! This is the state machine around a Lightrays session. The wire frames themselves live in
//! [`crate::protocol`]; what is here is the *sequence*, and the rules about what may happen
//! when.
//!
//! # Why a state machine rather than a handful of flags
//!
//! A game session has one resource with a lifetime the client does not control: a container
//! on the server, holding a GPU and a game. Three things follow from that, and each is a
//! bug if handled ad hoc:
//!
//! **It must be given back.** If the client stops without telling the server, the container
//! keeps running — for a self-hosted server with one GPU, that is a session the user cannot
//! get rid of and a game somebody else cannot start. So every terminal path leads through
//! [`GameSession::stopped`], and the states distinguish "we asked it to stop" from "it died
//! on its own".
//!
//! **It can die without being asked.** The container may exit (a crash, an out-of-memory
//! kill) while the client believes the stream is fine. The server says so with
//! `container_died`; treating that as a network hiccup would leave the user staring at a
//! frozen picture and waiting for something that will never come.
//!
//! **An offer arrives before we can answer it.** The server is always the offerer
//! (spike 0.1). The client must not send an answer until the peer connection exists, and
//! must not treat a late offer as a protocol error — the ordering is the server's choice.
//!
//! # A resolved URL, not the raw one
//!
//! The server may return a *relative* websocket path (`/api/lightrays-ws/<id>`), which is
//! fine for a browser and useless for a native client (measured: `lightrays.py:501`,
//! `_browser_websocket_url`). Resolving it against the profile's server is
//! [`ResolvedEndpoint::from_launch`], and getting it wrong is invisible until a connection
//! fails against a host that means nothing — so it is done here, once, with tests, rather
//! than at the call site.

use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};

use crate::protocol::{ServerMessage, MIN_DIMENSION};

/// The launch response's payload, as the server sends it.
///
/// Field names checked against `LaunchResponse` in `backend/src/streamarr/api/v1/lightrays.py`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LaunchResponse {
    pub session_id: String,
    #[serde(default)]
    pub websocket_url: String,
    #[serde(default)]
    pub ws_ticket: String,
    #[serde(default)]
    pub ice_servers: Vec<serde_json::Value>,
}

/// A websocket endpoint resolved to an absolute URL.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResolvedEndpoint {
    /// Absolute `ws://` or `wss://` URL.
    pub url: String,
    /// The ticket, appended as a subprotocol rather than a query parameter — that is what
    /// the server's own client does, and a ticket in the URL would land in access logs.
    pub ticket: Option<String>,
}

impl ResolvedEndpoint {
    /// Resolves the server's answer against the server it came from.
    ///
    /// `base_url` is the profile's server (`https://streamarr.example`). The result keeps
    /// the hostname rather than any pinned IP: the pin exists so the *connection* can be
    /// redirected, and replacing the hostname here would break TLS verification — the
    /// certificate covers the name, not the address.
    pub fn from_launch(base_url: &str, launch: &LaunchResponse) -> Result<Self, SessionError> {
        let raw = launch.websocket_url.trim();
        if raw.is_empty() {
            return Err(SessionError::NoEndpoint);
        }

        let base = base_url.trim().trim_end_matches('/');
        if base.is_empty() {
            return Err(SessionError::NoEndpoint);
        }

        let url = if raw.starts_with("ws://") || raw.starts_with("wss://") {
            // Already absolute. Left exactly as it is: the server may deliberately point at
            // a different host (a relay), and "correcting" that would break it.
            raw.to_string()
        } else if raw.starts_with("http://") || raw.starts_with("https://") {
            // An `http(s)` URL where a websocket one belongs. The scheme is upgraded rather
            // than rejected: the host is right, and only the transport differs.
            upgrade_scheme(raw)
        } else {
            // Relative. Resolved against the server, keeping the path intact.
            let (scheme, host) = split_origin(base).ok_or(SessionError::NoEndpoint)?;
            let path = if raw.starts_with('/') {
                raw.to_string()
            } else {
                format!("/{raw}")
            };
            format!("{scheme}://{host}{path}")
        };

        Ok(Self {
            url,
            ticket: {
                let ticket = launch.ws_ticket.trim();
                if ticket.is_empty() {
                    None
                } else {
                    Some(ticket.to_string())
                }
            },
        })
    }
}

/// Turns an `http(s)` URL into its websocket equivalent.
fn upgrade_scheme(url: &str) -> String {
    if let Some(rest) = url.strip_prefix("https://") {
        format!("wss://{rest}")
    } else if let Some(rest) = url.strip_prefix("http://") {
        format!("ws://{rest}")
    } else {
        url.to_string()
    }
}

/// Splits an origin into its websocket scheme and authority.
fn split_origin(base: &str) -> Option<(&'static str, &str)> {
    if let Some(rest) = base.strip_prefix("https://") {
        Some(("wss", rest))
    } else if let Some(rest) = base.strip_prefix("http://") {
        Some(("ws", rest))
    } else {
        None
    }
}

/// Where a session is in its life.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", tag = "state")]
pub enum SessionState {
    /// The launch request is in flight.
    Launching,
    /// Launched; the websocket is being opened.
    Connecting,
    /// The offer arrived and was answered; media may flow once ICE completes.
    Negotiating,
    /// The stream is running.
    Streaming,
    /// A resize is in flight; the server rebuilds its pipeline, so the picture stops briefly.
    Resizing,
    /// The server said the container exited. Terminal.
    Ended { exit_code: Option<i64> },
    /// The client stopped it. Terminal.
    Stopped,
    /// Something failed. Terminal.
    Failed { reason: String },
}

impl SessionState {
    /// Whether the session has reached an end and will do nothing more.
    pub fn is_terminal(&self) -> bool {
        matches!(
            self,
            Self::Ended { .. } | Self::Stopped | Self::Failed { .. }
        )
    }

    /// Whether the server still holds a container for this session.
    ///
    /// Exactly the states in which a `stop` request must be sent. Sending one for a session
    /// that already ended is noise; *not* sending one for a session in `Streaming` leaks a
    /// container holding a GPU.
    pub fn holds_server_session(&self) -> bool {
        matches!(
            self,
            Self::Connecting | Self::Negotiating | Self::Streaming | Self::Resizing
        )
    }
}

/// Why a session could not be started or continued.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SessionError {
    /// The launch response carried no usable websocket URL.
    NoEndpoint,
    /// A message arrived that cannot happen in this state.
    Unexpected { expected: &'static str, got: String },
    /// The session already ended.
    AlreadyFinished,
    /// A resize was asked for with dimensions the server rejects.
    BadDimensions { width: u32, height: u32 },
}

impl std::fmt::Display for SessionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NoEndpoint => write!(
                f,
                "Der Server hat keine WebSocket-Adresse für die Sitzung geliefert."
            ),
            Self::Unexpected { expected, got } => write!(
                f,
                "Unerwartete Nachricht im laufenden Zustand: {expected} erwartet, `{got}` erhalten."
            ),
            Self::AlreadyFinished => write!(f, "Die Sitzung ist bereits beendet."),
            Self::BadDimensions { width, height } => write!(
                f,
                "Die Auflösung {width}×{height} wird vom Server nicht angenommen."
            ),
        }
    }
}

impl std::error::Error for SessionError {}

/// What the caller should do in response to a server message.
///
/// Returned rather than acted on, so the state transitions are testable without a network
/// and the caller stays in charge of the transport.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Reaction {
    /// Send this answer back over the signalling socket.
    Answer { sdp: String },
    /// Add this ICE candidate to the peer connection.
    Ice { candidate: String, mline_index: u32 },
    /// The container is gone; tell the user and clean up. No `stop` is needed — the server
    /// has already done it.
    ContainerGone { exit_code: Option<i64> },
    /// The server's pipeline failed; report the reason and clean up.
    PipelineFailed,
    /// A message that changes nothing here but may matter to the caller (e.g. a server-side
    /// error string to display).
    Report { message: String },
    /// Nothing to do. Unknown frames land here deliberately.
    Ignore,
}

/// A game session and its state.
#[derive(Debug, Clone)]
pub struct GameSession {
    pub session_id: String,
    pub endpoint: ResolvedEndpoint,
    pub state: SessionState,
    /// The stream size last asked for, so a repeat resize can be skipped.
    pub requested_size: Option<(u32, u32)>,
    pub started_at: Instant,
    /// How long the session has run, for the stats overlay.
    pub elapsed: Duration,
}

impl GameSession {
    /// Begins a session from the server's launch answer.
    pub fn from_launch(base_url: &str, launch: &LaunchResponse) -> Result<Self, SessionError> {
        if launch.session_id.trim().is_empty() {
            return Err(SessionError::NoEndpoint);
        }
        let endpoint = ResolvedEndpoint::from_launch(base_url, launch)?;
        Ok(Self {
            session_id: launch.session_id.clone(),
            endpoint,
            state: SessionState::Connecting,
            requested_size: None,
            started_at: Instant::now(),
            elapsed: Duration::ZERO,
        })
    }

    /// Handles one server frame.
    ///
    /// The state is updated *before* the reaction is returned, so a caller that fails to
    /// act on the reaction cannot leave the session in a state that promises something it is
    /// not doing.
    pub fn on_message(&mut self, message: &ServerMessage) -> Reaction {
        match message {
            ServerMessage::Offer { sdp } => {
                // An offer may arrive in `Connecting` (the normal case) or again after a
                // resize, when the server rebuilds its pipeline and renegotiates. Answering
                // is right both times; refusing the second would break resizing.
                match self.state {
                    SessionState::Connecting
                    | SessionState::Negotiating
                    | SessionState::Resizing
                    | SessionState::Streaming => {
                        self.state = SessionState::Negotiating;
                        Reaction::Answer { sdp: sdp.clone() }
                    }
                    _ => Reaction::Ignore,
                }
            }
            ServerMessage::Ice {
                candidate,
                mline_index,
            } => {
                // Ignored in a terminal state rather than treated as an error: a candidate
                // already in flight when the session ended is normal, not a protocol break.
                if self.state.is_terminal() {
                    return Reaction::Ignore;
                }
                Reaction::Ice {
                    candidate: candidate.clone(),
                    mline_index: *mline_index,
                }
            }
            ServerMessage::ContainerDied { exit_code } => {
                if self.state.is_terminal() {
                    return Reaction::Ignore;
                }
                self.state = SessionState::Ended {
                    exit_code: *exit_code,
                };
                Reaction::ContainerGone {
                    exit_code: *exit_code,
                }
            }
            ServerMessage::PipelineError => {
                if self.state.is_terminal() {
                    return Reaction::Ignore;
                }
                self.state = SessionState::Failed {
                    reason: "Die Server-Pipeline ist fehlgeschlagen.".to_string(),
                };
                Reaction::PipelineFailed
            }
            ServerMessage::Error { message } => Reaction::Report {
                message: message.clone(),
            },
        }
    }

    /// Marks the peer connection as established.
    pub fn on_connected(&mut self) {
        if !self.state.is_terminal() {
            self.state = SessionState::Streaming;
        }
    }

    /// Requests a resize, or refuses it.
    ///
    /// Refused, rather than clamped, when the dimensions are outside the server's limits:
    /// the server rejects the whole message, so sending a clamped one would move the picture
    /// to a size nobody asked for.
    pub fn request_resize(
        &mut self,
        width: u32,
        height: u32,
    ) -> Result<Option<(u32, u32)>, SessionError> {
        if self.state.is_terminal() {
            return Err(SessionError::AlreadyFinished);
        }
        if width < MIN_DIMENSION || height < MIN_DIMENSION {
            return Err(SessionError::BadDimensions { width, height });
        }
        // Repeating the same size is skipped: each resize rebuilds the server's pipeline and
        // interrupts the picture, so a no-op one costs a visible stutter for nothing.
        if self.requested_size == Some((width, height)) {
            return Ok(None);
        }
        self.requested_size = Some((width, height));
        self.state = SessionState::Resizing;
        Ok(Some((width, height)))
    }

    /// Clears the resizing state after the server answered with a fresh offer.
    pub fn on_resize_settled(&mut self) {
        if self.state == SessionState::Resizing {
            self.state = SessionState::Negotiating;
        }
    }

    /// Records that enough time has passed for a progress report.
    pub fn tick(&mut self, now: Instant) {
        self.elapsed = now.saturating_duration_since(self.started_at);
    }

    /// Ends the session locally.
    ///
    /// Returns whether the server should still be told to stop, which is the only thing a
    /// caller needs to get right here — and the one thing whose omission leaks a container.
    pub fn stopped(&mut self) -> bool {
        let needed = self.state.holds_server_session();
        self.state = SessionState::Stopped;
        needed
    }

    /// Records a failure.
    ///
    /// Returns whether the server must be told to stop, on the same reasoning as
    /// [`Self::stopped`]: a session that failed *after* the connection was up still holds a
    /// container, and dropping it silently would leave the game running for nobody.
    pub fn failed(&mut self, reason: impl Into<String>) -> bool {
        let needed = self.state.holds_server_session();
        self.state = SessionState::Failed {
            reason: reason.into(),
        };
        needed
    }

    /// Whether a reconnect should be attempted.
    ///
    /// A container that died is not coming back, and neither is a stopped one: retrying
    /// would start a *second* game for a session the user believes is over. Only a
    /// transport-level failure before the end is worth another attempt.
    pub fn is_recoverable(&self) -> bool {
        matches!(
            self.state,
            SessionState::Connecting | SessionState::Negotiating | SessionState::Streaming
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn launch(url: &str) -> LaunchResponse {
        LaunchResponse {
            session_id: "sess-1".to_string(),
            websocket_url: url.to_string(),
            ws_ticket: "ticket-abc".to_string(),
            ice_servers: vec![],
        }
    }

    fn session() -> GameSession {
        GameSession::from_launch(
            "https://streamarr.example",
            &launch("/api/lightrays-ws/sess-1"),
        )
        .expect("a relative path must resolve")
    }

    // ── Endpoint resolution ──

    #[test]
    fn a_relative_websocket_path_is_resolved_against_the_server() {
        // Measured: the server returns a bare path when it has no public URL configured
        // (`lightrays.py:501`). A browser resolves it against the page's origin; a native
        // client that passes it to a websocket library unchanged fails with "relative URL
        // without a base", which is at least loud — worse is a wrong host that connects.
        let resolved = ResolvedEndpoint::from_launch(
            "https://streamarr.example",
            &launch("/api/lightrays-ws/sess-1"),
        )
        .unwrap();
        assert_eq!(
            resolved.url,
            "wss://streamarr.example/api/lightrays-ws/sess-1"
        );
    }

    #[test]
    fn a_relative_path_without_a_leading_slash_is_still_resolved() {
        let resolved =
            ResolvedEndpoint::from_launch("https://host.test", &launch("api/ws/1")).unwrap();
        assert_eq!(resolved.url, "wss://host.test/api/ws/1");
    }

    #[test]
    fn a_trailing_slash_on_the_base_does_not_double_up() {
        let resolved =
            ResolvedEndpoint::from_launch("https://host.test/", &launch("/api/lightrays-ws/x"))
                .unwrap();
        assert_eq!(resolved.url, "wss://host.test/api/lightrays-ws/x");
    }

    #[test]
    fn http_becomes_ws_and_https_becomes_wss() {
        // A plaintext server must not be upgraded to `wss`: there is no certificate, and
        // the handshake would fail with a confusing TLS error.
        let plain = ResolvedEndpoint::from_launch("http://host.test", &launch("/ws")).unwrap();
        assert_eq!(plain.url, "ws://host.test/ws");

        let secure = ResolvedEndpoint::from_launch("https://host.test", &launch("/ws")).unwrap();
        assert_eq!(secure.url, "wss://host.test/ws");
    }

    #[test]
    fn an_absolute_websocket_url_is_left_exactly_as_it_is() {
        // The server may deliberately point at another host — a relay, a separate streaming
        // node. Rewriting it "for consistency" would break that, and the failure would look
        // like a network problem.
        let resolved = ResolvedEndpoint::from_launch(
            "https://streamarr.example",
            &launch("wss://relay.other.test/session/42"),
        )
        .unwrap();
        assert_eq!(resolved.url, "wss://relay.other.test/session/42");
    }

    #[test]
    fn an_http_url_in_the_websocket_field_is_upgraded_not_rejected() {
        // The host is right; only the transport name differs. Rejecting it would fail a
        // session for a server that is merely sloppy about the scheme.
        let resolved = ResolvedEndpoint::from_launch(
            "https://streamarr.example",
            &launch("https://streamarr.example/ws/1"),
        )
        .unwrap();
        assert_eq!(resolved.url, "wss://streamarr.example/ws/1");
    }

    #[test]
    fn the_hostname_is_kept_rather_than_any_pinned_address() {
        // The profile may pin an IP to get around broken DNS, but the pin belongs to the
        // connection. Replacing the hostname here would break TLS verification: the
        // certificate covers `streamarr.example`, not the address.
        let resolved =
            ResolvedEndpoint::from_launch("https://streamarr.example", &launch("/ws")).unwrap();
        assert!(resolved.url.contains("streamarr.example"));
        assert!(!resolved.url.contains("10."));
    }

    #[test]
    fn a_missing_endpoint_is_an_error_worth_naming() {
        assert_eq!(
            ResolvedEndpoint::from_launch("https://h.test", &launch("")),
            Err(SessionError::NoEndpoint)
        );
        // A base that is not an origin at all cannot resolve anything.
        assert_eq!(
            ResolvedEndpoint::from_launch("streamarr.example", &launch("/ws")),
            Err(SessionError::NoEndpoint)
        );
    }

    #[test]
    fn the_ticket_travels_as_a_subprotocol_not_in_the_url() {
        // A ticket in the query string lands in access logs and in the `Referer` of
        // anything the page loads. Kept separate so the connector can pass it the way the
        // server's own client does.
        let resolved = ResolvedEndpoint::from_launch("https://host.test", &launch("/ws")).unwrap();
        assert_eq!(resolved.ticket.as_deref(), Some("ticket-abc"));
        assert!(!resolved.url.contains("ticket"));
    }

    #[test]
    fn an_empty_ticket_becomes_none_rather_than_an_empty_string() {
        let mut response = launch("/ws");
        response.ws_ticket = "   ".to_string();
        let resolved = ResolvedEndpoint::from_launch("https://host.test", &response).unwrap();
        assert_eq!(resolved.ticket, None);
    }

    // ── Lifecycle ──

    #[test]
    fn a_launch_without_a_session_id_is_refused() {
        let mut response = launch("/ws");
        response.session_id = "  ".to_string();
        assert!(GameSession::from_launch("https://h.test", &response).is_err());
    }

    #[test]
    fn an_offer_in_the_connecting_state_is_answered() {
        let mut s = session();
        assert_eq!(s.state, SessionState::Connecting);
        let reaction = s.on_message(&ServerMessage::Offer {
            sdp: "v=0".to_string(),
        });
        assert_eq!(
            reaction,
            Reaction::Answer {
                sdp: "v=0".to_string()
            }
        );
        assert_eq!(s.state, SessionState::Negotiating);
    }

    #[test]
    fn a_second_offer_after_a_resize_is_answered_too() {
        // The server rebuilds its whole pipeline for a resize and sends a fresh offer.
        // Refusing the second one would make "match resolution" silently do nothing.
        let mut s = session();
        s.on_message(&ServerMessage::Offer {
            sdp: "first".to_string(),
        });
        s.on_connected();
        s.request_resize(2560, 1440).unwrap();

        assert_eq!(s.state, SessionState::Resizing);
        let reaction = s.on_message(&ServerMessage::Offer {
            sdp: "second".to_string(),
        });
        assert_eq!(
            reaction,
            Reaction::Answer {
                sdp: "second".to_string()
            }
        );
    }

    #[test]
    fn an_offer_after_the_end_is_ignored() {
        let mut s = session();
        s.on_message(&ServerMessage::ContainerDied { exit_code: Some(1) });
        assert_eq!(
            s.on_message(&ServerMessage::Offer {
                sdp: "late".to_string()
            }),
            Reaction::Ignore
        );
    }

    #[test]
    fn ice_candidates_are_forwarded_while_running() {
        let mut s = session();
        assert_eq!(
            s.on_message(&ServerMessage::Ice {
                candidate: "candidate:1".to_string(),
                mline_index: 0,
            }),
            Reaction::Ice {
                candidate: "candidate:1".to_string(),
                mline_index: 0,
            }
        );
    }

    #[test]
    fn ice_arriving_after_the_end_is_ignored_not_an_error() {
        // A candidate already in flight when the session ended is normal. Treating it as a
        // protocol violation would show the user an error for something that does not
        // matter.
        let mut s = session();
        s.stopped();
        assert_eq!(
            s.on_message(&ServerMessage::Ice {
                candidate: "late".to_string(),
                mline_index: 0,
            }),
            Reaction::Ignore
        );
    }

    #[test]
    fn a_container_death_ends_the_session_and_names_the_exit_code() {
        let mut s = session();
        s.on_connected();
        assert_eq!(
            s.on_message(&ServerMessage::ContainerDied {
                exit_code: Some(137)
            }),
            Reaction::ContainerGone {
                exit_code: Some(137)
            }
        );
        assert_eq!(
            s.state,
            SessionState::Ended {
                exit_code: Some(137)
            }
        );
        assert!(s.state.is_terminal());
    }

    #[test]
    fn a_container_death_needs_no_stop_request() {
        // The server has already cleaned up; sending `stop` would be noise, and worse, it
        // could stop a *new* session that reused the id.
        let mut s = session();
        s.on_connected();
        s.on_message(&ServerMessage::ContainerDied { exit_code: None });
        assert!(!s.state.holds_server_session());
    }

    #[test]
    fn a_pipeline_error_fails_the_session() {
        let mut s = session();
        s.on_connected();
        assert_eq!(
            s.on_message(&ServerMessage::PipelineError),
            Reaction::PipelineFailed
        );
        assert!(matches!(s.state, SessionState::Failed { .. }));
    }

    #[test]
    fn a_server_error_string_is_reported_without_changing_the_state() {
        // The server sends `error` for conditions that do not necessarily end the session;
        // ending it on their behalf would kill a stream that is still fine.
        let mut s = session();
        s.on_connected();
        assert_eq!(
            s.on_message(&ServerMessage::Error {
                message: "Ticket läuft ab".to_string()
            }),
            Reaction::Report {
                message: "Ticket läuft ab".to_string()
            }
        );
        assert_eq!(s.state, SessionState::Streaming);
    }

    #[test]
    fn stopping_a_running_session_asks_the_server_to_stop() {
        let mut s = session();
        s.on_connected();
        assert!(
            s.stopped(),
            "a running session holds a container that must be released"
        );
        assert_eq!(s.state, SessionState::Stopped);
    }

    #[test]
    fn stopping_an_ended_session_does_not_ask_the_server_to_stop() {
        let mut s = session();
        s.on_connected();
        s.on_message(&ServerMessage::ContainerDied { exit_code: Some(0) });
        assert!(!s.stopped());
    }

    #[test]
    fn stopping_a_session_that_never_connected_does_not_ask_the_server_either() {
        // Launching, then failing before the socket came up: there is no session on the
        // server to release. Sending `stop` anyway is what causes "session not found" noise.
        let mut s = session();
        s.state = SessionState::Launching;
        assert!(!s.stopped());
    }

    #[test]
    fn a_failure_while_streaming_still_asks_the_server_to_stop() {
        // The trap this guards: the client sees a transport failure, concludes "we are
        // done", and drops a container that keeps running — holding the GPU and blocking
        // the next game.
        let mut s = session();
        s.on_connected();
        assert!(s.failed("Netzwerk weg"));
        assert!(matches!(s.state, SessionState::Failed { .. }));
    }

    #[test]
    fn a_resize_to_the_same_size_is_skipped() {
        // Each resize rebuilds the server's pipeline and interrupts the picture, so a
        // no-op one costs a visible stutter for nothing.
        let mut s = session();
        s.on_connected();
        assert_eq!(s.request_resize(1920, 1080).unwrap(), Some((1920, 1080)));
        s.on_resize_settled();
        assert_eq!(s.request_resize(1920, 1080).unwrap(), None);
    }

    #[test]
    fn a_resize_to_a_different_size_is_allowed() {
        let mut s = session();
        s.on_connected();
        s.request_resize(1920, 1080).unwrap();
        s.on_resize_settled();
        assert_eq!(s.request_resize(2560, 1440).unwrap(), Some((2560, 1440)));
    }

    #[test]
    fn a_resize_below_the_server_limit_is_refused_not_clamped() {
        // The server rejects the whole message, so sending a clamped size would move the
        // picture to dimensions nobody asked for — worse than doing nothing.
        let mut s = session();
        s.on_connected();
        assert_eq!(
            s.request_resize(32, 1080),
            Err(SessionError::BadDimensions {
                width: 32,
                height: 1080
            })
        );
        // And nothing was recorded, so a later valid resize is not mistaken for a repeat.
        assert!(s.requested_size.is_none());
        assert_eq!(s.state, SessionState::Streaming);
    }

    #[test]
    fn a_resize_after_the_end_is_refused() {
        let mut s = session();
        s.on_connected();
        s.on_message(&ServerMessage::ContainerDied { exit_code: Some(1) });
        assert_eq!(
            s.request_resize(1920, 1080),
            Err(SessionError::AlreadyFinished)
        );
    }

    #[test]
    fn a_resize_settles_back_into_negotiating() {
        let mut s = session();
        s.on_connected();
        s.request_resize(1280, 720).unwrap();
        s.on_resize_settled();
        assert_eq!(s.state, SessionState::Negotiating);
    }

    #[test]
    fn only_a_session_before_its_end_is_worth_reconnecting() {
        let mut s = session();
        assert!(s.is_recoverable());

        s.on_connected();
        assert!(s.is_recoverable());

        // A dead container is not coming back, and "reconnecting" would start a second game
        // for a session the user believes is over.
        s.on_message(&ServerMessage::ContainerDied { exit_code: Some(1) });
        assert!(!s.is_recoverable());

        let mut t = session();
        t.stopped();
        assert!(!t.is_recoverable());

        let mut u = session();
        u.failed("kaputt");
        assert!(!u.is_recoverable());
    }

    #[test]
    fn the_elapsed_time_advances_with_the_clock_it_is_given() {
        // Driven by an injected instant rather than `Instant::now()`, so the stats overlay
        // can be tested without sleeping.
        let mut s = session();
        let later = s.started_at + Duration::from_secs(90);
        s.tick(later);
        assert_eq!(s.elapsed, Duration::from_secs(90));
    }

    #[test]
    fn connecting_after_the_end_does_not_resurrect_the_session() {
        // A late "connected" event from a peer connection that was already torn down must
        // not move a terminal session back to streaming — the UI would then show a live
        // stream for something that is over.
        let mut s = session();
        s.on_message(&ServerMessage::ContainerDied { exit_code: Some(1) });
        s.on_connected();
        assert!(s.state.is_terminal());
    }

    #[test]
    fn a_launch_response_is_read_from_the_servers_json() {
        // Field names checked against `LaunchResponse` in lightrays.py.
        let json = r#"{
            "session_id": "abc",
            "websocket_url": "/api/lightrays-ws/abc",
            "ws_ticket": "t",
            "ice_servers": [{"urls": "stun:stun.example:3478"}]
        }"#;
        let parsed: LaunchResponse = serde_json::from_str(json).expect("the server's shape");
        assert_eq!(parsed.session_id, "abc");
        assert_eq!(parsed.ice_servers.len(), 1);

        let session = GameSession::from_launch("https://h.test", &parsed).unwrap();
        assert_eq!(session.endpoint.url, "wss://h.test/api/lightrays-ws/abc");
    }

    #[test]
    fn a_launch_response_without_the_optional_fields_still_parses() {
        // The server declares `ws_ticket` and `ice_servers` with defaults, so a response
        // omitting them is valid and must not fail the whole parse.
        let parsed: LaunchResponse =
            serde_json::from_str(r#"{"session_id":"x","websocket_url":"/ws"}"#)
                .expect("defaults cover the optional fields");
        assert!(parsed.ws_ticket.is_empty());
        assert!(parsed.ice_servers.is_empty());
    }

    #[test]
    fn every_terminal_state_is_reported_as_terminal() {
        // Exhaustive, so a future variant cannot be added without being classified.
        let terminal = [
            SessionState::Ended { exit_code: None },
            SessionState::Stopped,
            SessionState::Failed {
                reason: "x".to_string(),
            },
        ];
        for state in terminal {
            assert!(state.is_terminal(), "{state:?}");
            assert!(!state.holds_server_session(), "{state:?}");
        }

        let running = [
            SessionState::Connecting,
            SessionState::Negotiating,
            SessionState::Streaming,
            SessionState::Resizing,
        ];
        for state in running {
            assert!(!state.is_terminal(), "{state:?}");
            assert!(state.holds_server_session(), "{state:?}");
        }

        // `Launching` is the one state that is neither: no session exists yet, so there is
        // nothing to release, and it is not an end either.
        assert!(!SessionState::Launching.is_terminal());
        assert!(!SessionState::Launching.holds_server_session());
    }
}
