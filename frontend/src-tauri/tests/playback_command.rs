//! The playback command, from the outside.
//!
//! Why this file exists, given that the core crate already proves the plan and the
//! integration tests already prove mpv: **neither proves the command layer.** The
//! mistakes that cost real time in this project were all wiring — a capability sent as a
//! body instead of a query (so the server transcoded silently), a resume position that
//! never reached mpv, a property pass-through that would let a page change how mpv runs.
//! Those are mistakes in the join, not in the parts.
//!
//! The server is a stand-in (`desktop/scripts/fake_playback_server.py`), because the test
//! server's database was down while this was written. It answers with the *measured*
//! response shapes and serves the real test medium with range support.

use streamarr_desktop_player::capabilities::Capabilities;
use streamarr_media_lib::commands::playback::{play_path, property_is_allowed, PlaybackService};

/// The query parameter names in a path, without the values.
fn parameter_names(path: &str) -> Vec<String> {
    path.split_once('?')
        .map(|(_, query)| {
            query
                .split('&')
                .filter_map(|pair| pair.split('=').next())
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default()
}

#[test]
fn the_play_path_carries_the_capabilities_as_query_parameters() {
    let path = play_path(
        "abc-123",
        &Capabilities::detect(3840, false, false, true, "1.0"),
    );

    // The guid is the path segment; everything else is the query.
    assert!(path.starts_with("/api/play/abc-123?"), "{path}");

    // The names the server actually reads (`api/v1/playback_params.py`). A wrong name
    // means the parameter is ignored, and the server falls back to conservative defaults
    // — i.e. it transcodes a file the client could have played directly, with nothing in
    // any log to say why.
    for expected in [
        "supported_video_codecs=",
        "supported_audio_codecs=",
        "supported_containers=",
    ] {
        assert!(
            path.contains(expected),
            "`{expected}` is missing from {path}"
        );
    }

    // Note the name: play takes `client_max_resolution`, the device endpoint takes
    // `max_resolution`. Using the wrong one here is silent — the server simply does not
    // read it and applies its own default.
    assert!(path.contains("client_max_resolution="), "{path}");
    // Checked as a parameter name, not a substring: `client_max_resolution` *contains*
    // `max_resolution`, so a naive `contains` would reject the correct path. (It did.)
    assert!(
        !parameter_names(&path).contains(&"max_resolution".to_string()),
        "the device endpoint's name must not appear here: {path}"
    );
}

#[test]
fn a_codec_list_arrives_as_one_parameter() {
    let path = play_path(
        "abc",
        &Capabilities::detect(3840, false, false, true, "1.0"),
    );
    // Split the query off the path first: the first parameter is preceded by the guid
    // and the `?`, so splitting on `&` alone misses it. (It did.)
    let codec_part = path
        .split_once('?')
        .expect("a query string")
        .1
        .split('&')
        .find(|p| p.starts_with("supported_video_codecs="))
        .expect("the codec parameter");

    // A comma-separated list must not be split into several parameters, so the separator
    // has to be encoded.
    assert!(
        codec_part.contains("%2C"),
        "the list must be encoded: {codec_part}"
    );
    assert!(
        !codec_part.contains(','),
        "an unencoded comma splits the list: {codec_part}"
    );
    assert!(codec_part.contains("h264"), "{codec_part}");
}

#[test]
fn hdr_is_not_claimed_by_this_shell() {
    // The backend's transcode path is HDR-blind (plan §10.2) and this shell has no display
    // probe yet, so claiming HDR would produce a washed-out picture rather than a better
    // one. Stated as a test so claiming it becomes a deliberate act.
    let capabilities = Capabilities::detect(3840, false, false, true, "1.0");
    assert!(!capabilities.supports_hdr);
}

#[test]
fn only_the_named_properties_may_be_set_from_the_page() {
    for allowed in ["aid", "sid", "volume", "mute", "speed", "sub-visibility"] {
        assert!(
            property_is_allowed(allowed),
            "`{allowed}` should be settable"
        );
    }
    for forbidden in [
        // Would change how mpv runs rather than what it plays.
        "options/vo",
        "options/ao",
        "config-dir",
        "script",
        "input-conf",
        "screenshot-directory",
        // Not a property at all.
        "",
        // mpv's names are lowercase; a second spelling would stop the list describing
        // what is allowed.
        "AID",
    ] {
        assert!(
            !property_is_allowed(forbidden),
            "`{forbidden}` must not be settable from the page"
        );
    }
}

#[test]
fn the_playback_service_starts_idle_and_stays_usable() {
    // What a user meets first — pressing play twice, or stopping nothing — must produce a
    // readable error rather than a panic.
    let service = PlaybackService::new();
    assert!(service.snapshot().is_none());
    assert!(service.summary().is_none());
    assert!(service.stop().is_none());

    let error = service
        .send(streamarr_media_lib::commands::playback::PlayerCommand::SetPaused(true))
        .unwrap_err();
    assert!(error.contains("keine Wiedergabe"), "{error}");
}

/// Wiring that is worth pinning because a mistake in it is silent.
///
/// These read the source. That is a weaker instrument than calling the code, and it is
/// used only where the alternative is a full GUI test: `play_media` needs a Tauri runtime,
/// a profile, a token and a server. The behaviour of every function it calls is tested
/// where it lives; what is checked here is that the command *calls* them.
mod wiring {
    const SOURCE: &str = include_str!("../src/commands/playback.rs");

    #[test]
    fn the_command_builds_its_path_through_the_tested_function() {
        // Without this it could regress to a JSON body, and nothing would fail.
        assert!(
            SOURCE.contains("play_path(&item_guid, &capabilities)"),
            "the command must build its path through the tested function"
        );
    }

    #[test]
    fn the_resume_position_reaches_mpv_as_an_argument() {
        // A property set after loading would work too, but a *missing* argument restarts
        // the film silently — which presents as "resume sometimes doesn't work".
        assert!(
            SOURCE.contains("--start="),
            "the resume position must reach mpv"
        );
    }

    #[test]
    fn the_tunnel_is_started_only_when_the_profile_pins_an_address() {
        assert!(
            SOURCE.contains("plan.resolve_target"),
            "the tunnel must depend on the plan's resolve target"
        );
        assert!(
            SOURCE.contains("--http-proxy="),
            "mpv must be pointed at the tunnel"
        );
    }

    #[test]
    fn the_shell_does_not_run_two_players_at_once() {
        // Two mpv processes would fight over the audio device, and the winner is a coin
        // toss the user experiences as "the wrong film is playing".
        assert!(
            SOURCE.contains("fn replace("),
            "starting a playback must replace the previous one"
        );
    }

    #[test]
    fn the_playback_service_is_the_one_slot_holder() {
        assert!(
            SOURCE.contains("current: Mutex<Option<Running>>"),
            "one playback at a time"
        );
    }
}
