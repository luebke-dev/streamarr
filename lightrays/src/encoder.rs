//! Video encoder selection and pipeline-fragment construction.
//!
//! Pure logic that doesn't touch session state. Auto-detection probes
//! GStreamer for available encoder factories and prefers hardware
//! variants; pipeline assembly returns a string fragment ready to splice
//! into a `gst::parse::launch` call.
//!
//! H.265 is detected and exposed for completeness, but the live path
//! always picks H.264 — Firefox and Chrome only enable H.265 over WebRTC
//! behind flags. Frames wider than the H.264 hardware encoder limit are
//! scaled down by the caller before encoding.

use gstreamer as gst;

// ── H.264 encoders (max ~4096px width for VA-API) ──
const H264_ENCODERS: &[&str] = &["vah264enc", "vaapih264enc", "nvh264enc", "x264enc"];

// ── H.265/HEVC encoders (supports up to 8192px width) ──
const H265_ENCODERS: &[&str] = &["vah265enc", "vaapih265enc", "nvh265enc", "x265enc"];

/// Maximum width supported by H.264 hardware encoders (VA-API / NVENC).
pub const H264_MAX_WIDTH: u32 = 4096;

/// Detect the best available H.264 encoder element.
pub fn detect_h264_encoder() -> Option<String> {
    if gst::init().is_err() {
        return None;
    }
    for &name in H264_ENCODERS {
        if gst::ElementFactory::find(name).is_some() {
            log::info!("Detected H.264 encoder: {}", name);
            return Some(name.to_string());
        }
    }
    log::error!("No H.264 encoder found");
    None
}

/// Detect the best available H.265/HEVC encoder element.
pub fn detect_h265_encoder() -> Option<String> {
    if gst::init().is_err() {
        return None;
    }
    for &name in H265_ENCODERS {
        if gst::ElementFactory::find(name).is_some() {
            log::info!("Detected H.265 encoder: {}", name);
            return Some(name.to_string());
        }
    }
    None
}

/// Pick the best encoder for the given width.
/// Returns `(encoder_name, is_h265)`.
///
/// H.265 is not supported by most browsers via WebRTC (Firefox, Chrome
/// only behind flags), so we always use H.264 for maximum compatibility.
/// When the width exceeds the H.264 limit the video is scaled down by a
/// `videoscale` element added by the caller.
pub fn select_encoder(width: u32) -> (String, bool) {
    if width > H264_MAX_WIDTH {
        log::warn!(
            "Width {} exceeds H.264 limit ({}) — video will be scaled to {}px wide \
             (H.265 not used because browsers lack WebRTC support for it)",
            width,
            H264_MAX_WIDTH,
            H264_MAX_WIDTH
        );
    }
    let name = detect_h264_encoder().unwrap_or_else(|| "x264enc".to_string());
    (name, false)
}

/// Build the pre-processing + encoder GStreamer fragment.
pub fn build_encoder_pipeline(encoder: &str, bitrate: u32, fps: u32, is_h265: bool) -> String {
    if is_h265 {
        return build_h265_encoder_pipeline(encoder, bitrate, fps);
    }
    match encoder {
        "vah264enc" => format!(
            "vapostproc ! \
             vah264enc rate-control=cbr bitrate={bitrate} key-int-max={fps} \
             ref-frames=1 b-frames=0 target-usage=7 ! \
             video/x-h264,profile=constrained-baseline ! "
        ),
        "vaapih264enc" => format!(
            // Intel low-power H.264 encoder on UHD 770 only exposes CQP rate
            // control (no CBR/VBR). Without explicit QPs the encoder default
            // produces uncontrolled bitrate spikes at higher resolutions —
            // WebRTC backpressures the encoder, push_sample blocks, picture
            // goes black. With moderate CQP values the stream stays inside
            // ~10 Mbps for typical content at 4096x1152.
            "videoconvert n-threads=4 ! video/x-raw,format=NV12 ! \
             vapostproc ! \
             vah264lpenc rate-control=cqp qpi=26 qpp=28 \
                         key-int-max={fps} target-usage=7 \
                         b-frames=0 ref-frames=1 \
                         mbbrc=auto ! \
             video/x-h264,profile=constrained-baseline ! "
        ),
        "nvh264enc" => format!(
            "videoconvert ! video/x-raw,format=I420 ! \
             nvh264enc bitrate={bitrate} gop-size={fps} \
             preset=low-latency-hq rc-mode=cbr ! \
             video/x-h264,profile=constrained-baseline ! "
        ),
        _ => format!(
            "videoconvert ! video/x-raw,format=I420 ! \
             x264enc tune=zerolatency bitrate={bitrate} speed-preset=ultrafast \
             key-int-max={fps} bframes=0 threads=0 ! \
             video/x-h264,stream-format=byte-stream,profile=constrained-baseline ! "
        ),
    }
}

/// Build H.265/HEVC encoder pipeline fragment.
fn build_h265_encoder_pipeline(encoder: &str, bitrate: u32, fps: u32) -> String {
    match encoder {
        "vah265enc" => format!(
            "vapostproc ! \
             vah265enc rate-control=cbr bitrate={bitrate} key-int-max={fps} \
             ref-frames=1 b-frames=0 target-usage=7 ! \
             video/x-h265,profile=main ! "
        ),
        "vaapih265enc" => format!(
            "videoconvert n-threads=4 ! video/x-raw,format=NV12 ! \
             vapostproc ! \
             vaapih265enc keyframe-period={fps} \
             rate-control=cqp init-qp=26 quality-level=4 ! \
             video/x-h265,profile=main ! "
        ),
        "nvh265enc" => format!(
            "videoconvert ! video/x-raw,format=I420 ! \
             nvh265enc bitrate={bitrate} gop-size={fps} \
             preset=low-latency-hq rc-mode=cbr ! \
             video/x-h265,profile=main ! "
        ),
        _ => format!(
            "videoconvert ! video/x-raw,format=I420 ! \
             x265enc tune=zerolatency bitrate={bitrate} speed-preset=ultrafast \
             key-int-max={fps} option-string=\"bframes=0\" ! \
             video/x-h265,profile=main ! "
        ),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn x264enc_fragment_uses_constrained_baseline_and_bitrate() {
        let frag = build_encoder_pipeline("x264enc", 5000, 60, false);
        assert!(frag.contains("x264enc"));
        assert!(frag.contains("bitrate=5000"));
        assert!(frag.contains("key-int-max=60"));
        assert!(frag.contains("profile=constrained-baseline"));
    }

    #[test]
    fn vaapih264enc_fragment_drops_bitrate_for_cqp() {
        // The Intel low-power encoder uses CQP — passing a bitrate to it
        // would silently be ignored; the fragment must not include one.
        let frag = build_encoder_pipeline("vaapih264enc", 5000, 60, false);
        assert!(frag.contains("vah264lpenc"));
        assert!(frag.contains("rate-control=cqp"));
        assert!(!frag.contains("bitrate=5000"));
    }

    #[test]
    fn h265_branch_is_taken_when_requested() {
        let frag = build_encoder_pipeline("x265enc", 4000, 30, true);
        assert!(frag.contains("x265enc"));
        assert!(frag.contains("video/x-h265"));
    }

    #[test]
    fn select_encoder_falls_back_to_software_when_nothing_detected() {
        // In the test environment GStreamer factories aren't usually
        // registered; the function must still produce a usable name.
        let (name, is_h265) = select_encoder(1920);
        assert!(!name.is_empty());
        assert!(!is_h265);
    }
}
