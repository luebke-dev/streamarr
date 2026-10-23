//! The option surface for libmpv, derived from the arguments the process path uses.
//!
//! ADR 003 replaces the separate mpv process with libmpv in the app process. The
//! interesting part for the options is that **nothing has to be decided twice**: mpv reads
//! the same options whether they arrive as `--name=value` on a command line or through
//! `mpv_set_option_string`. So this module translates [`PlayerOptions::to_args`] instead of
//! duplicating it, and the existing tests for the argument list keep guarding the option
//! set for both transports.
//!
//! [`PlayerOptions::to_args`]: crate::mpv::PlayerOptions::to_args
//!
//! Three things are *not* translated, because they describe the process rather than the
//! player, and each of them has a measured reason:
//!
//! * `idle` and `terminal` exist to let one child process serve several files and to keep
//!   its chatter off the IPC socket. In-process there is no child and no socket.
//! * `fullscreen` is the old design's way of getting a video toplevel: a Wayland client
//!   cannot position its own window, so the app hid the UI and went fullscreen (spike 0.2).
//!   With libmpv the picture is a subsurface *inside* the app window, so fullscreen is a
//!   decision of the shell's window, not an option of the player.
//! * `vo` is forced to `libmpv`, because that is the whole point of ADR 003: the render API
//!   is the output. `gpu-next` cannot be selected — there is no window for it to draw in.

use crate::mpv::PlayerOptions;

/// Options that describe the process, not the player. See the module documentation.
const PROCESS_ONLY: &[&str] = &["idle", "terminal", "fullscreen"];

/// The option name/value pairs to hand to libmpv, in order.
///
/// Last-wins is preserved: `extra_args` come last in the argument list and therefore last
/// here, so a user argument still overrides the app's defaults.
pub fn option_pairs(options: &PlayerOptions) -> Vec<(String, String)> {
    let mut pairs = Vec::new();

    for arg in options.to_args() {
        let Some(body) = arg.strip_prefix("--") else {
            // An argument without `--` is not an option; skip rather than guess.
            continue;
        };
        let (name, value) = match body.split_once('=') {
            Some((name, value)) => (name.to_string(), value.to_string()),
            // `--no-foo` is mpv's way of writing `foo=no`.
            None => match body.strip_prefix("no-") {
                Some(name) => (name.to_string(), "no".to_string()),
                None => (body.to_string(), "yes".to_string()),
            },
        };

        if PROCESS_ONLY.contains(&name.as_str()) || name == "vo" {
            continue;
        }
        pairs.push((name, value));
    }

    // Stated once, at the end, and never derived from `options.vo`: the render API is the
    // output in this design, and an option that quietly disagreed would produce a video
    // that never appears.
    pairs.push(("vo".to_string(), "libmpv".to_string()));
    pairs
}

/// Looks a translated option up by name. Convenience for tests and callers that only care
/// about a few of them.
pub fn find<'a>(pairs: &'a [(String, String)], name: &str) -> Option<&'a str> {
    pairs
        .iter()
        .rev()
        .find(|(key, _)| key == name)
        .map(|(_, value)| value.as_str())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mpv::HdrMode;

    fn with<F: FnOnce(&mut PlayerOptions)>(change: F) -> Vec<(String, String)> {
        let mut options = PlayerOptions::default();
        change(&mut options);
        option_pairs(&options)
    }

    #[test]
    fn the_output_driver_is_libmpv_and_never_the_configured_one() {
        let pairs = with(|o| o.vo = "gpu-next".to_string());

        assert_eq!(find(&pairs, "vo"), Some("libmpv"));
        // Forced once, not appended alongside the configured value.
        assert_eq!(pairs.iter().filter(|(name, _)| name == "vo").count(), 1);
    }

    #[test]
    fn process_only_options_are_dropped() {
        let pairs = with(|_| {});

        for dropped in PROCESS_ONLY {
            assert!(
                find(&pairs, dropped).is_none(),
                "{dropped} belongs to the process path and must not reach libmpv"
            );
        }
        // Sanity: the list was not empty, so the assertions above are meaningful.
        assert!(!pairs.is_empty());
    }

    #[test]
    fn driver_options_survive_the_translation() {
        let pairs = with(|o| {
            o.hwdec = "auto-safe".to_string();
            o.ao = "auto".to_string();
        });

        assert_eq!(find(&pairs, "hwdec"), Some("auto-safe"));
        assert_eq!(find(&pairs, "ao"), Some("auto"));
    }

    #[test]
    fn hdr_passthrough_keeps_both_of_its_options() {
        let pairs = with(|o| o.hdr = HdrMode::Passthrough);

        assert_eq!(find(&pairs, "target-colorspace-hint"), Some("yes"));
        assert_eq!(find(&pairs, "hdr-compute-peak"), Some("no"));
    }

    #[test]
    fn tone_mapping_keeps_its_named_curve() {
        let pairs = with(|o| o.hdr = HdrMode::ToneMapSdr);

        assert_eq!(find(&pairs, "target-colorspace-hint"), Some("no"));
        assert_eq!(find(&pairs, "tone-mapping"), Some("bt.2390"));
    }

    #[test]
    fn the_config_dir_is_passed_as_an_option() {
        let pairs = with(|o| o.config_dir = std::path::PathBuf::from("/tmp/profile"));

        assert_eq!(find(&pairs, "config-dir"), Some("/tmp/profile"));
    }

    #[test]
    fn a_user_argument_still_wins() {
        let pairs = with(|o| {
            o.hwdec = "auto-safe".to_string();
            o.extra_args = vec!["--hwdec=no".to_string()];
        });

        assert_eq!(find(&pairs, "hwdec"), Some("no"));
    }

    #[test]
    fn a_switch_without_a_value_becomes_yes() {
        let pairs = with(|o| o.extra_args = vec!["--keep-open".to_string()]);

        assert_eq!(find(&pairs, "keep-open"), Some("yes"));
    }
}
