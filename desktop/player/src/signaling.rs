//! The signalling transport's decisions: headers, framing, and how a broken
//! connection is retried.
//!
//! Plan tasks 3.2 and 3.8. `spike-webrtc.rs` proved the transport works against
//! the real server; what lives here is the part worth testing without a socket —
//! the `Sec-WebSocket-Protocol` header the server authenticates against, the
//! mapping from wire messages onto the session's state machine, and the retry
//! policy that decides whether a drop is worth another attempt.
//!
//! # Why the retry policy is not a loop with a `sleep`
//!
//! A reconnect loop is easy to write and easy to get subtly wrong in ways that
//! only show up under load: retrying a container that has genuinely exited
//! starts a *second* game for a session the user believes is over, and retrying
//! without a bound turns a server outage into an infinite request storm. Both
//! are decidable from the session state and the attempt count, so they are
//! decided here, where a test can pin them.

use std::time::Duration;

use crate::game_session::{GameSession, SessionState};
use crate::protocol::{ServerMessage, WS_SUBPROTOCOL};

/// The `Sec-WebSocket-Protocol` header value: the protocol name, then the ticket.
///
/// `lightrays/src/auth.rs` reads the ticket out of this header, and the browser
/// sends it the same way — `new WebSocket(url, ['lightrays', ticket])`. The
/// order matters, and so does the separator: the header is a comma-separated
/// list, and sending the ticket alone makes the server reject the handshake
/// because it never sees the protocol name it expects.
pub fn subprotocol_header(ticket: &str) -> String {
    format!("{WS_SUBPROTOCOL}, {ticket}")
}

/// The `Authorization` header, sent alongside the subprotocol.
///
/// `lightrays/src/auth.rs` accepts the ticket as *either* the second subprotocol
/// value or a bearer token. Both are sent because the two are not equivalent on
/// the wire: some proxies rewrite `Sec-WebSocket-Protocol`, and the header is
/// the one a plain HTTP client can always set. The spike used both and connected;
/// sending only one leaves a deployment-specific failure mode with no upside.
pub fn authorization_header(ticket: &str) -> String {
    format!("Bearer {ticket}")
}

/// What to do after the connection dropped.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReconnectDecision {
    /// Wait this long, then dial again.
    Retry { after: Duration, attempt: u32 },
    /// Do not retry. The reason is what the user is told.
    GiveUp(GiveUpReason),
}

/// Why a reconnect is not attempted.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GiveUpReason {
    /// The container exited; there is nothing to reconnect to.
    ContainerGone,
    /// The user stopped the stream.
    StoppedByUser,
    /// The session failed in a way a retry cannot fix.
    Failed,
    /// Retried as often as allowed.
    AttemptsExhausted,
}

impl GiveUpReason {
    /// The message shown to the user.
    ///
    /// A generic "connection lost" for all four would be wrong in three of them:
    /// a stopped stream did not lose anything, and an exhausted retry is about
    /// patience rather than about the network.
    pub fn message(self) -> &'static str {
        match self {
            Self::ContainerGone => "Das Spiel wurde auf dem Server beendet.",
            Self::StoppedByUser => "Die Übertragung wurde beendet.",
            Self::Failed => "Die Übertragung ist fehlgeschlagen.",
            Self::AttemptsExhausted => "Keine Verbindung zum Server — Versuche aufgebraucht.",
        }
    }
}

/// How often and how long to retry.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ReconnectPolicy {
    /// Total attempts, including the first.
    pub max_attempts: u32,
    /// Delay before the first retry.
    pub base_delay: Duration,
    /// Upper bound for the delay, however many attempts have passed.
    pub max_delay: Duration,
}

impl Default for ReconnectPolicy {
    fn default() -> Self {
        Self {
            // Three attempts is about twenty seconds of patience: long enough to
            // ride out a Wi-Fi hiccup or a server restart, short enough that the
            // user is not left staring at a frozen frame wondering whether the
            // client is still trying.
            max_attempts: 3,
            base_delay: Duration::from_millis(500),
            // Without a ceiling, the tenth attempt would wait over four minutes,
            // by which time the user has long since given up on their own.
            max_delay: Duration::from_secs(8),
        }
    }
}

impl ReconnectPolicy {
    /// The delay before `attempt` (1-based), doubling and capped.
    ///
    /// A fixed delay would either hammer a server that is still starting or
    /// leave a brief hiccup waiting for a full second. Exponential with a cap is
    /// the usual answer, and the cap is what keeps it usable.
    pub fn delay_for(&self, attempt: u32) -> Duration {
        // `attempt - 1` doublings, saturating: a large attempt must not
        // overflow into a tiny delay.
        let doublings = attempt.saturating_sub(1).min(32);
        let scaled = self
            .base_delay
            .checked_mul(1u32 << doublings.min(31))
            .unwrap_or(self.max_delay);
        scaled.min(self.max_delay)
    }

    /// Decides what to do after a dropped connection.
    ///
    /// `attempt` is the number of connections already tried, so the first drop
    /// after one connection is attempt 2.
    pub fn decide(&self, session: &GameSession, attempt: u32, dropped: bool) -> ReconnectDecision {
        // The session's state is the authority on whether anything is left to
        // reconnect to. A container that exited, or a stream the user stopped,
        // is not coming back — and in the container case a retry would launch a
        // second game, which is worse than doing nothing.
        match session.state {
            SessionState::Ended { .. } => {
                return ReconnectDecision::GiveUp(GiveUpReason::ContainerGone)
            }
            SessionState::Stopped => return ReconnectDecision::GiveUp(GiveUpReason::StoppedByUser),
            SessionState::Failed { .. } => return ReconnectDecision::GiveUp(GiveUpReason::Failed),
            // Nothing dropped, nothing to do.
            _ if !dropped => return ReconnectDecision::GiveUp(GiveUpReason::StoppedByUser),
            _ => {}
        }

        if attempt >= self.max_attempts {
            return ReconnectDecision::GiveUp(GiveUpReason::AttemptsExhausted);
        }
        ReconnectDecision::Retry {
            after: self.delay_for(attempt),
            attempt: attempt + 1,
        }
    }
}

/// Routes one server frame to the session, returning what the transport must
/// send back.
///
/// A thin layer over `GameSession::on_message`, and it exists because the two
/// sides of the wire disagree about who speaks first: the server offers, the
/// client answers. A server frame that arrives *before* the session expects one
/// must not be answered — an answer to a stale offer is a protocol error that
/// the server reports as a failed session.
pub fn route(session: &mut GameSession, message: &ServerMessage) -> RouteOutcome {
    use crate::game_session::Reaction;

    let reaction = session.on_message(message);
    match reaction {
        Reaction::Answer { sdp } => {
            RouteOutcome::Send(crate::protocol::ClientMessage::Answer { sdp }.to_json())
        }
        Reaction::Ice {
            candidate,
            mline_index,
        } => RouteOutcome::Send(
            crate::protocol::ClientMessage::Ice {
                candidate,
                mline_index,
            }
            .to_json(),
        ),
        // The container is gone: the socket has nothing left to carry, and the
        // server has already torn its side down.
        Reaction::ContainerGone { .. } => RouteOutcome::Ended,
        // A failed pipeline ends the session; the socket is closed by the
        // caller, which also has the error text to show.
        Reaction::PipelineFailed => RouteOutcome::Ended,
        // Something worth showing the user that changes nothing on the wire.
        Reaction::Report { .. } => RouteOutcome::Nothing,
        Reaction::Ignore => RouteOutcome::Nothing,
    }
}

/// What the transport does with a routed frame.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RouteOutcome {
    /// Send this JSON text on the websocket.
    Send(String),
    /// The frame changed nothing on the wire.
    Nothing,
    /// The stream is over; the socket should be closed.
    Ended,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::game_session::LaunchResponse;

    fn launch() -> LaunchResponse {
        LaunchResponse {
            session_id: "sess-1".to_string(),
            websocket_url: "/api/lightrays-ws/sess-1".to_string(),
            ws_ticket: "ticket-abc".to_string(),
            ice_servers: vec![],
        }
    }

    fn session() -> GameSession {
        GameSession::from_launch("https://streamarr.example", &launch()).expect("Sitzung")
    }

    #[test]
    fn the_subprotocol_header_carries_the_name_and_the_ticket() {
        let header = subprotocol_header("ticket-abc");
        assert_eq!(header, "lightrays, ticket-abc");
        // The protocol name comes first: the server looks for it to recognise
        // its own protocol at all.
        assert!(header.starts_with(WS_SUBPROTOCOL));
        assert!(header.ends_with("ticket-abc"));
    }

    #[test]
    fn the_subprotocol_header_matches_the_browsers() {
        // `new WebSocket(url, ['lightrays', ticket])` in
        // useLightraysStreaming.js produces exactly this header.
        let ticket = "abc123";
        let expected = format!("lightrays, {ticket}");
        assert_eq!(subprotocol_header(ticket), expected);
    }

    #[test]
    fn the_authorization_header_is_a_bearer_token() {
        assert_eq!(authorization_header("t"), "Bearer t");
    }

    // ── Retry policy ──

    #[test]
    fn the_delay_doubles_and_then_stops_growing() {
        let policy = ReconnectPolicy {
            max_attempts: 10,
            base_delay: Duration::from_millis(500),
            max_delay: Duration::from_secs(8),
        };
        assert_eq!(policy.delay_for(1), Duration::from_millis(500));
        assert_eq!(policy.delay_for(2), Duration::from_secs(1));
        assert_eq!(policy.delay_for(3), Duration::from_secs(2));
        assert_eq!(policy.delay_for(4), Duration::from_secs(4));
        // Capped from here on, rather than doubling forever.
        assert_eq!(policy.delay_for(5), Duration::from_secs(8));
        assert_eq!(policy.delay_for(50), Duration::from_secs(8));
    }

    #[test]
    fn a_huge_attempt_number_does_not_overflow() {
        let policy = ReconnectPolicy::default();
        // Shifting a `u32` left by more than 31 is undefined behaviour in Rust
        // (a panic in debug builds); a long-running client must not die here.
        for attempt in [33u32, 100, 1_000, u32::MAX] {
            let delay = policy.delay_for(attempt);
            assert!(delay <= policy.max_delay, "Versuche {attempt} → {delay:?}");
            assert!(delay >= policy.base_delay);
        }
    }

    #[test]
    fn a_dropped_stream_is_retried_up_to_the_limit() {
        let policy = ReconnectPolicy::default();
        let session = session();
        // First drop, one connection tried.
        match policy.decide(&session, 1, true) {
            ReconnectDecision::Retry { attempt, after } => {
                assert_eq!(attempt, 2);
                assert_eq!(after, Duration::from_millis(500));
            }
            other => panic!("erwartet: Retry, war {other:?}"),
        }
        // Last allowed retry.
        assert!(matches!(
            policy.decide(&session, 2, true),
            ReconnectDecision::Retry { attempt: 3, .. }
        ));
        // Attempts exhausted at the limit.
        assert_eq!(
            policy.decide(&session, 3, true),
            ReconnectDecision::GiveUp(GiveUpReason::AttemptsExhausted)
        );
    }

    #[test]
    fn a_dead_container_is_never_retried() {
        // The important one: retrying would launch a *second* game while the
        // user is looking at the "ended" message.
        let policy = ReconnectPolicy::default();
        let mut session = session();
        session.on_message(&ServerMessage::ContainerDied { exit_code: Some(0) });
        assert_eq!(
            policy.decide(&session, 1, true),
            ReconnectDecision::GiveUp(GiveUpReason::ContainerGone)
        );
    }

    #[test]
    fn a_stream_the_user_stopped_is_never_retried() {
        let policy = ReconnectPolicy::default();
        let mut session = session();
        session.stopped();
        assert_eq!(
            policy.decide(&session, 1, true),
            ReconnectDecision::GiveUp(GiveUpReason::StoppedByUser)
        );
    }

    #[test]
    fn a_failed_session_is_never_retried() {
        let policy = ReconnectPolicy::default();
        let mut session = session();
        session.failed("kaputt");
        assert_eq!(
            policy.decide(&session, 1, true),
            ReconnectDecision::GiveUp(GiveUpReason::Failed)
        );
    }

    #[test]
    fn a_connection_that_did_not_drop_is_not_retried() {
        // The policy is also consulted on the normal path; a healthy session
        // must not spawn a retry.
        let policy = ReconnectPolicy::default();
        let session = session();
        assert!(matches!(
            policy.decide(&session, 1, false),
            ReconnectDecision::GiveUp(GiveUpReason::StoppedByUser)
        ));
    }

    #[test]
    fn every_give_up_reason_has_its_own_message() {
        let messages: Vec<&str> = [
            GiveUpReason::ContainerGone,
            GiveUpReason::StoppedByUser,
            GiveUpReason::Failed,
            GiveUpReason::AttemptsExhausted,
        ]
        .iter()
        .map(|r| r.message())
        .collect();
        // Three of the four are not "the network died", and a single generic
        // message would misdescribe them.
        let unique: std::collections::HashSet<&&str> = messages.iter().collect();
        assert_eq!(
            unique.len(),
            4,
            "die Gründe sind nicht unterscheidbar: {messages:?}"
        );
        for message in messages {
            assert!(!message.is_empty());
        }
    }

    // ── Routing ──

    #[test]
    fn an_offer_is_answered() {
        let mut session = session();
        let outcome = route(
            &mut session,
            &ServerMessage::Offer {
                sdp: "v=0\r\n".to_string(),
            },
        );
        match outcome {
            RouteOutcome::Send(json) => {
                assert!(json.contains("\"answer\""), "{json}");
                assert!(json.contains("v=0"), "{json}");
            }
            other => panic!("erwartet: Send, war {other:?}"),
        }
    }

    #[test]
    fn a_candidate_is_forwarded_as_ice() {
        let mut session = session();
        route(
            &mut session,
            &ServerMessage::Offer {
                sdp: "v=0".to_string(),
            },
        );
        let outcome = route(
            &mut session,
            &ServerMessage::Ice {
                candidate: "candidate:1 1 UDP 1 127.0.0.1 1 typ host".to_string(),
                mline_index: 0,
            },
        );
        match outcome {
            RouteOutcome::Send(json) => {
                assert!(json.contains("\"ice\""), "{json}");
                // The server reads `sdpMLineIndex` with that exact casing.
                assert!(json.contains("\"sdpMLineIndex\""), "{json}");
            }
            other => panic!("erwartet: Send, war {other:?}"),
        }
    }

    #[test]
    fn a_frame_after_the_end_sends_nothing() {
        let mut session = session();
        session.on_message(&ServerMessage::ContainerDied { exit_code: Some(0) });
        // A candidate still in flight when the container exits is normal, not a
        // protocol break; sending it would be pointless.
        let outcome = route(
            &mut session,
            &ServerMessage::Ice {
                candidate: "candidate:1".to_string(),
                mline_index: 0,
            },
        );
        assert_eq!(outcome, RouteOutcome::Nothing);
    }

    #[test]
    fn a_container_death_ends_the_transport() {
        let mut session = session();
        let outcome = route(
            &mut session,
            &ServerMessage::ContainerDied { exit_code: Some(1) },
        );
        assert_eq!(outcome, RouteOutcome::Ended);
    }
}
