//! Golden tests for the wire contract with Lightrays.
//!
//! The plan (§7) calls for the input contract to be pinned so the desktop
//! client cannot drift away from the web client silently. Rather than
//! duplicating the server's expectations as hand-written fixtures — which
//! would drift too — these tests read the Lightrays sources and assert that
//! every field name we serialise is one the server actually reads.
//!
//! If the server renames a field, these tests fail here instead of producing a
//! silently dead input path at runtime. The tests skip (rather than fail) when
//! the `lightrays/` sources are not present, so the crate can be built from a
//! packaged source tree.

use std::path::{Path, PathBuf};

use streamarr_desktop_player::protocol::{ClientMessage, InputMessage, KeyCode, ServerMessage};

fn repo_root() -> Option<PathBuf> {
    // CARGO_MANIFEST_DIR is <repo>/desktop/player.
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()?
        .parent()?
        .to_path_buf();
    if root.join("lightrays/src").is_dir() {
        Some(root)
    } else {
        None
    }
}

fn read(relative: &str) -> Option<String> {
    let root = repo_root()?;
    std::fs::read_to_string(root.join(relative)).ok()
}

/// Render an integer the way Rust source writes large literals: `50_000`.
fn format_value_underscored(value: u32) -> String {
    let digits = value.to_string();
    let mut out = String::new();
    for (i, ch) in digits.chars().enumerate() {
        if i > 0 && (digits.len() - i) % 3 == 0 {
            out.push('_');
        }
        out.push(ch);
    }
    out
}

/// Assert that the server source mentions a field name. The server reads JSON
/// with `data.get("<field>")`, so the quoted name must appear literally.
fn assert_server_reads(source: &str, file: &str, field: &str) {
    assert!(
        source.contains(&format!("\"{field}\"")),
        "{file} no longer mentions the field {field:?} — the desktop client \
         would send a field the server ignores"
    );
}

#[test]
fn input_fields_are_read_by_the_server() {
    let Some(input_rs) = read("lightrays/src/input.rs") else {
        eprintln!("skipping: lightrays/src/input.rs not available");
        return;
    };

    // Keyboard: server reads "code" and "pressed".
    assert_server_reads(&input_rs, "input.rs", "code");
    assert_server_reads(&input_rs, "input.rs", "pressed");
    // Pointer: absolute sends x/y/w/h, relative sends dx/dy.
    for field in ["x", "y", "w", "h", "dx", "dy"] {
        assert_server_reads(&input_rs, "input.rs", field);
    }
    // Mouse button and wheel.
    assert_server_reads(&input_rs, "input.rs", "button");
    // Gamepad parsing lives in input.rs (`parse_gamepad_event`), not in
    // gamepad.rs — gamepad.rs only encodes RetroArch packets.
    for field in ["index", "pressed", "stick", "axis", "value"] {
        assert_server_reads(&input_rs, "input.rs", field);
    }

    // And every message type we emit must be one the server dispatches on.
    let emitted = [
        InputMessage::key(KeyCode::new("KeyA"), true),
        InputMessage::MouseAbs {
            x: 0.0,
            y: 0.0,
            w: 1.0,
            h: 1.0,
        },
        InputMessage::MouseMove { dx: 1.0, dy: 1.0 },
        InputMessage::MouseButton {
            button: 0,
            pressed: true,
        },
        InputMessage::Wheel { dx: 0.0, dy: 0.0 },
        InputMessage::gamepad_button(0, true),
        InputMessage::gamepad_axis(0, 0, 0.0),
    ];
    for message in emitted {
        let json = message.to_json();
        let kind = serde_json::from_str::<serde_json::Value>(&json)
            .expect("input message is valid JSON")
            .get("type")
            .and_then(|v| v.as_str())
            .expect("input message has a type")
            .to_string();

        assert!(
            input_rs.contains(&format!("\"{kind}\"")),
            "the server has no handler for the input message type {kind:?}"
        );
    }
}

#[test]
fn signalling_fields_match_the_server() {
    let Some(server_rs) = read("lightrays/src/server.rs") else {
        eprintln!("skipping: lightrays/src/server.rs not available");
        return;
    };

    // Client → server: the server reads "answer", "ice", "resize" plus the
    // candidate fields. `sdpMLineIndex` keeps its camelCase spelling.
    for field in [
        "answer",
        "ice",
        "resize",
        "sdp",
        "candidate",
        "sdpMLineIndex",
    ] {
        assert_server_reads(&server_rs, "server.rs", field);
    }
    for field in ["width", "height"] {
        assert_server_reads(&server_rs, "server.rs", field);
    }

    // Server → client: message types the server emits, and every one we parse.
    for kind in ["offer", "ice", "container_died", "pipeline_error"] {
        assert!(
            server_rs.contains(&format!("\"{kind}\"")),
            "server.rs no longer emits {kind:?}"
        );
    }

    // Round-trip the shapes we expect so a typo in our parser is caught even
    // when the source check above passes on an unrelated occurrence.
    let offer = ServerMessage::parse(r#"{"type":"offer","sdp":"v=0"}"#).expect("offer parses");
    assert_eq!(offer, ServerMessage::Offer { sdp: "v=0".into() });

    let ice = ClientMessage::Ice {
        candidate: "c".into(),
        mline_index: 2,
    };
    assert!(
        ice.to_json().contains("\"sdpMLineIndex\""),
        "ICE must use the server's camelCase field name"
    );
}

#[test]
fn input_channel_label_matches_the_server() {
    let Some(webrtc_rs) = read("lightrays/src/webrtc.rs") else {
        eprintln!("skipping: lightrays/src/webrtc.rs not available");
        return;
    };
    // The server creates/expects a data channel for input; the label is part of
    // the contract, so the native client must request the same one.
    assert!(
        webrtc_rs.contains(streamarr_desktop_player::protocol::INPUT_CHANNEL_LABEL),
        "webrtc.rs does not use the input data channel label we assume"
    );
}

#[test]
fn resize_limits_match_the_server() {
    let Some(launch_rs) = read("lightrays/src/launch.rs") else {
        eprintln!("skipping: lightrays/src/launch.rs not available");
        return;
    };
    use streamarr_desktop_player::protocol as p;

    // Each constant we mirror must still be the value the server enforces.
    // The source writes large literals with underscores (50_000), so compare
    // against the formatted value the server actually uses.
    for (name, value) in [
        ("MAX_WIDTH", p::MAX_WIDTH),
        ("MAX_HEIGHT", p::MAX_HEIGHT),
        ("MIN_FPS", p::MIN_FPS),
        ("MAX_FPS", p::MAX_FPS),
        ("MIN_BITRATE_KBPS", p::MIN_BITRATE_KBPS),
        ("MAX_BITRATE_KBPS", p::MAX_BITRATE_KBPS),
    ] {
        let plain = format!("const {name}: u32 = {value}");
        let underscored = format!("const {name}: u32 = {value}").replacen(
            &value.to_string(),
            &format_value_underscored(value),
            1,
        );
        assert!(
            launch_rs.contains(&plain) || launch_rs.contains(&underscored),
            "lightrays/src/launch.rs no longer defines {name} = {value} — the \
             client clamps against a stale limit"
        );
    }
}

// ---------------------------------------------------------------------------
// Client capabilities
// ---------------------------------------------------------------------------

/// The play endpoint takes query parameters, and its field names are what the
/// server reads. `client_max_resolution` in particular differs from the device
/// endpoint's `max_resolution`, so both are pinned separately.
#[test]
fn play_query_field_names_match_the_server() {
    let Some(params) = read("backend/src/streamarr/api/v1/playback_params.py") else {
        eprintln!("skipping: playback_params.py not available");
        return;
    };

    use streamarr_desktop_player::capabilities::Capabilities;
    let caps = Capabilities::detect(3840, true, true, true, "0.1.0");
    let query = caps.play_query();

    for (key, _) in &query {
        // The server declares each of these as a `Query(...)` parameter, so the
        // bare name must appear in the source.
        assert!(
            params.contains(key.as_str()),
            "playback_params.py no longer declares `{key}` — the client sends a \
             parameter the server ignores, and playback silently loses a \
             capability"
        );
    }

    // And the reverse direction: a parameter the server requires but the client
    // never sends would fall back to a default, which is how the needless
    // transcode in spike 0.3 happened.
    for required in [
        "supported_video_codecs",
        "supported_audio_codecs",
        "supported_containers",
        "client_max_resolution",
    ] {
        assert!(
            query.iter().any(|(k, _)| k == required),
            "the client no longer sends `{required}`, which playback_params.py \
             declares — the server would fall back to conservative defaults"
        );
    }
}

/// The device-capability endpoint uses a *different* name for the same concept.
/// Pinning both stops a well-meaning "unify the names" change from breaking one
/// of the two endpoints.
#[test]
fn device_payload_field_names_match_the_server_schema() {
    let Some(schema) = read("backend/src/streamarr/schemas/device.py") else {
        eprintln!("skipping: schemas/device.py not available");
        return;
    };

    use streamarr_desktop_player::capabilities::Capabilities;
    let payload = Capabilities::detect(3840, true, true, true, "0.1.0").device_payload();
    let object = payload.as_object().expect("payload is an object");

    for key in object.keys() {
        // Pydantic declares fields as `name: type = Field(...)`, so the bare
        // identifier followed by a colon is the declaration — not a quoted
        // string. (An earlier version of this test required quotes and failed on
        // a perfectly good schema.)
        let declared =
            schema.contains(&format!("{key}:")) || schema.contains(&format!("\"{key}\""));
        assert!(
            declared,
            "schemas/device.py no longer declares `{key}` — the device endpoint \
             would reject or ignore it"
        );
    }

    // The distinction that matters: this endpoint does NOT know the prefixed name.
    assert!(
        object.contains_key("max_resolution"),
        "the device endpoint expects `max_resolution`"
    );
    assert!(
        !object.contains_key("client_max_resolution"),
        "`client_max_resolution` belongs to the play endpoint, not this one"
    );
}

/// The codec names the client sends must be ones the server can match. The server
/// normalises aliases in `libraries/base.py`, so the canonical spellings have to
/// appear there.
#[test]
fn codec_names_are_known_to_the_server() {
    let Some(base) = read("backend/src/streamarr/libraries/base.py") else {
        eprintln!("skipping: libraries/base.py not available");
        return;
    };

    use streamarr_desktop_player::capabilities::{AudioCodec, Capabilities, VideoCodec};
    let caps = Capabilities::detect(3840, true, true, true, "0.1.0");

    for codec in &caps.video_codecs {
        assert!(
            base.contains(&format!("\"{}\"", codec.as_str())),
            "libraries/base.py no longer mentions video codec `{}`",
            codec.as_str()
        );
    }

    // H.264 and HEVC are the two libraries actually use, so they are required.
    assert!(caps.video_codecs.contains(&VideoCodec::H264));
    assert!(caps.video_codecs.contains(&VideoCodec::H265));
    assert!(caps.audio_codecs.contains(&AudioCodec::Ac3));
}
