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
use streamarr_desktop_player::session::{
    APP_NAME, CLIENT_PLATFORM_HEADER, CLIENT_PLATFORM_VALUE, REFRESH_MARGIN,
};

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

// ── Session and auth contract (plan tasks 1.4/1.5) ──

/// The platform header is what makes the server hand a native client the refresh
/// token in the body instead of an httpOnly cookie. `auth/cookies.py` decides this
/// by comparing the header to the literal `web`, so both the header name and the
/// fact that our value is not `web` have to hold against the server source.
#[test]
fn the_platform_header_matches_the_server() {
    let Some(source) = read("backend/src/streamarr/auth/cookies.py") else {
        return;
    };
    assert!(
        source.contains("x-client-platform"),
        "der Server liest den Header nicht mehr als `x-client-platform`"
    );
    assert!(
        source.contains(r#".strip().lower() == "web""#),
        "die Serverlogik für Cookie- vs. Body-Token hat sich geändert — \
         die Annahme `nur web bekommt ein Cookie` muss neu geprüft werden"
    );
    assert_ne!(
        CLIENT_PLATFORM_VALUE, "web",
        "mit dem Wert `web` bekäme die App kein Refresh-Token im Body"
    );
    assert_eq!(CLIENT_PLATFORM_HEADER.to_lowercase(), "x-client-platform");
}

/// The login request must carry the device fields under the names the schema uses,
/// otherwise the device record is created without an identity.
#[test]
fn the_login_body_matches_the_server_schema() {
    let Some(source) = read("backend/src/streamarr/schemas/user.py") else {
        return;
    };
    for field in ["email", "password", "device_id", "device_info"] {
        assert!(
            source.contains(&format!("{field}:")),
            "LocalLoginRequest kennt das Feld {field:?} nicht mehr"
        );
    }
}

/// `TokenResponse.refresh_token` is optional precisely because web clients get a
/// cookie instead. The client treats its absence as a configuration error, so the
/// field name has to keep matching.
#[test]
fn the_token_response_fields_match_the_server() {
    let Some(source) = read("backend/src/streamarr/schemas/auth.py") else {
        return;
    };
    for field in ["access_token", "refresh_token", "token_type", "expires_in"] {
        assert!(
            source.contains(&format!("{field}:")),
            "TokenResponse kennt das Feld {field:?} nicht mehr"
        );
    }
    assert!(
        source.contains("refresh_token: str | None"),
        "das Refresh-Token ist nicht mehr optional — die Native-Client-Annahme \
         (`None` bedeutet: Header fehlt) muss neu bewertet werden"
    );
}

/// Device capabilities are stored under `device_info["capabilities"]`, and the
/// update schema must keep accepting our payload's field names.
#[test]
fn device_capabilities_are_stored_where_expected() {
    let Some(source) = read("backend/src/streamarr/api/v1/devices.py") else {
        return;
    };
    assert!(
        source.contains(r#"device_info["capabilities"]"#),
        "die Capabilities werden nicht mehr unter device_info[\"capabilities\"] abgelegt"
    );
    assert!(
        source.contains("capabilities.model_dump()"),
        "der Server speichert die Capabilities nicht mehr als Modell-Dump — \
         die Feldnamen des Payloads müssen neu geprüft werden"
    );
}

/// The refresh endpoint rotates the token on every call. If that ever stopped being
/// true, the client's single-use assumption would be needlessly strict; if a second
/// call were still accepted after rotation, it would be the opposite. Either way it
/// is worth knowing, so the behaviour is pinned.
#[test]
fn refresh_rotates_the_token_on_the_server() {
    let Some(source) = read("backend/src/streamarr/api/v1/auth.py") else {
        return;
    };
    assert!(
        source.contains("mark_refresh_rotated"),
        "der Refresh-Endpunkt rotiert das Token nicht mehr — die Einmal-Annahme \
         des Clients ist dann unnötig streng"
    );
    assert!(
        source.contains("new_refresh_token"),
        "es wird kein neues Refresh-Token mehr ausgegeben; der Client würde sein \
         gespeichertes Token weiterverwenden und beim nächsten Mal 401 bekommen"
    );
}

/// The 503 branch is the reason the client distinguishes "dead token" from "could
/// not check". If the server ever failed open instead, keeping the session would be
/// wrong.
#[test]
fn a_missing_revocation_store_still_fails_closed() {
    let Some(source) = read("backend/src/streamarr/auth/token_revocation.py") else {
        return;
    };
    assert!(
        source.contains("HTTP_503_SERVICE_UNAVAILABLE"),
        "der Revocation-Store antwortet nicht mehr mit 503 — die Unterscheidung \
         zwischen endgültigem und vorübergehendem Fehler muss neu geprüft werden"
    );
    assert!(
        source.to_lowercase().contains("fail-closed"),
        "die Fail-Closed-Eigenschaft ist nicht mehr dokumentiert"
    );
}

/// Access and refresh lifetimes drive `needs_refresh`. A refresh margin larger than
/// the access-token lifetime would mean refreshing on every single call.
#[test]
fn token_lifetimes_leave_room_for_the_refresh_margin() {
    let Some(source) = read("backend/src/streamarr/config.py") else {
        return;
    };
    let line = source
        .lines()
        .find(|l| l.contains("jwt_access_token_expire_minutes"))
        .expect("die Access-Token-Lebensdauer ist konfigurierbar");
    let minutes: u64 = line
        .rsplit(':')
        .next()
        .and_then(|tail| tail.split_whitespace().next())
        .and_then(|value| value.parse().ok())
        .unwrap_or(30);
    let lifetime = std::time::Duration::from_secs(minutes * 60);
    assert!(
        lifetime > REFRESH_MARGIN * 4,
        "die Access-Token-Lebensdauer ({minutes} min) ist zu kurz für eine \
         Refresh-Marge von {:?}",
        REFRESH_MARGIN
    );
}

/// The app name is what the server shows in the device list (plan task 1.5), and
/// the field has to fit the schema's length limit.
#[test]
fn the_device_app_name_fits_the_schema() {
    let Some(source) = read("backend/src/streamarr/schemas/device.py") else {
        return;
    };
    assert!(
        source.contains("app_name: str | None"),
        "die Device-Schemata kennen `app_name` nicht mehr"
    );
    // The limit is declared as `max_length=100`; assert the plan's name fits.
    if let Some(index) = source.find("app_name: str | None") {
        let tail = &source[index..];
        if let Some(limit_start) = tail.find("max_length=") {
            let digits: String = tail[limit_start + "max_length=".len()..]
                .chars()
                .take_while(|c| c.is_ascii_digit())
                .collect();
            if let Ok(limit) = digits.parse::<usize>() {
                assert!(
                    APP_NAME.len() <= limit,
                    "der App-Name ist länger als die erlaubten {limit} Zeichen"
                );
            }
        }
    }
}

/// Guards against the whole suite silently skipping.
///
/// Every test here is written to *skip* when the server sources are absent, so the
/// crate stays buildable from a packaged source tree. The risk of that design is
/// obvious once stated: a typo in a path turns a suite of golden tests into a suite
/// of no-ops that report success. This test fails loudly in the repository instead,
/// while still skipping in a packaged tree.
#[test]
fn the_server_sources_are_readable_in_this_repository() {
    if repo_root().is_none() {
        // Packaged tree: nothing to check, and the other tests skip too.
        return;
    }
    let required = [
        "lightrays/src/input.rs",
        "lightrays/src/stream.rs",
        "lightrays/src/webrtc.rs",
        "lightrays/src/encoder.rs",
        "lightrays/src/gamepad.rs",
        "backend/src/streamarr/auth/cookies.py",
        "backend/src/streamarr/auth/token_revocation.py",
        "backend/src/streamarr/api/v1/auth.py",
        "backend/src/streamarr/api/v1/devices.py",
        "backend/src/streamarr/schemas/auth.py",
        "backend/src/streamarr/schemas/user.py",
        "backend/src/streamarr/schemas/device.py",
        "backend/src/streamarr/config.py",
        "backend/src/streamarr/libraries/base.py",
    ];
    let mut missing = Vec::new();
    for path in required {
        match read(path) {
            Some(content) if !content.is_empty() => {}
            _ => missing.push(path),
        }
    }
    assert!(
        missing.is_empty(),
        "Diese Serverquellen sind nicht lesbar: {missing:?}. Damit würden die \
         Golden-Tests still überspringen und Erfolg melden, ohne etwas zu prüfen."
    );
}

/// The app name is what the server lists in its device view (plan task 1.5); a
/// change here should be a conscious one, not a silent rename.
#[test]
fn the_app_name_is_what_the_plan_specifies() {
    assert_eq!(APP_NAME, "Streamarr Desktop");
}

/// The refresh margin must stay well below the access-token lifetime, otherwise
/// every call would trigger a refresh — and every refresh rotates the token, so the
/// client would burn through its session for nothing.
#[test]
fn the_refresh_margin_is_far_below_a_typical_token_lifetime() {
    use std::time::Duration;
    assert!(
        REFRESH_MARGIN < Duration::from_secs(5 * 60),
        "die Refresh-Marge ({REFRESH_MARGIN:?}) ist zu großzügig"
    );
    assert!(
        REFRESH_MARGIN >= Duration::from_secs(5),
        "die Refresh-Marge ({REFRESH_MARGIN:?}) ist zu klein, um einen Ablauf \
         mitten im Request zu verhindern"
    );
}
