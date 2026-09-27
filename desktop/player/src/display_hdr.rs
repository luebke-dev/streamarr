//! Detecting whether the connected display can actually show HDR (plan task 2.9).
//!
//! The app must decide between two ways of handling an HDR source, and the decision is
//! only correct if it knows what the *screen* can do:
//!
//!   * **Passthrough** — send the HDR signal through untouched. Right when the panel
//!     accepts HDR10 (PQ / SMPTE ST2084), so the display does the tone mapping it was
//!     built for.
//!   * **Tone-map to SDR** — convert in the player. Right when the panel cannot show HDR,
//!     because an unconverted HDR signal on an SDR screen looks washed out and grey rather
//!     than merely suboptimal.
//!
//! Guessing either way is wrong in a way the user sees: claim HDR without a probe and the
//! picture is wrong on every SDR screen; refuse it without a probe and HDR never works on
//! the screens that were bought for it.
//!
//! # Where the answer comes from
//!
//! The display's **EDID**, read from `/sys/class/drm/*/edid`. It is the only source that
//! answers the question about the hardware rather than about a setting, and it is readable
//! without privileges (verified: mode `-r--r--r--`).
//!
//! Within the EDID, the answer is in the **CTA-861 extension block** — the HDR Static
//! Metadata Data Block (extended tag `0x06`). Its second payload byte is a bitmap of
//! electro-optical transfer functions, and the bit that matters is **bit 1: SMPTE ST2084**,
//! which is PQ and is what "HDR10" means in practice. Bit 0 is traditional gamma (the SDR
//! range) and proves nothing.
//!
//! Measured on this machine's `card1-DP-2`: an HDR block with `SMPTE ST2084`, static
//! metadata type 1, and even an HDR10+ vendor block — so the probe has a positive case to
//! test against, not only a negative one.
//!
//! # Deliberately not included
//!
//! The DRM write-side interfaces (`hdr_output_metadata`) are *not* read. They exist on some
//! connectors and not others — measured: absent on the connected displays here — and they
//! describe what the compositor was last asked to output, not what the panel supports. A
//! probe that depended on them would be unavailable exactly where it is needed.
//!
//! Nothing here is feature-gated: it reads a few hundred bytes from sysfs and must be
//! testable anywhere, including on a CI runner with no display.

use std::path::{Path, PathBuf};

/// EDID header, the first eight bytes of every block.
const EDID_HEADER: [u8; 8] = [0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00];

/// One EDID block is 128 bytes.
const BLOCK_SIZE: usize = 128;

/// CTA-861 extension blocks carry the HDR metadata.
const CTA_EXTENSION_TAG: u8 = 0x02;

/// The extended tag of the HDR Static Metadata Data Block.
const HDR_STATIC_METADATA_TAG: u8 = 0x06;

/// What a display reports about HDR.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct DisplayHdr {
    /// The display supports **SMPTE ST2084** (PQ) — i.e. HDR10.
    ///
    /// The bit the decision turns on. `Traditional gamma - SDR luminance range` is
    /// deliberately not enough: every display has it, so it distinguishes nothing.
    pub supports_pq: bool,
    /// The display supports **hybrid log-gamma** (HLG). Broadcast HDR; not HDR10, and not
    /// what a film library uses.
    pub supports_hlg: bool,
    /// The display advertises **static metadata type 1**, which HDR10 streams carry.
    pub static_metadata_type1: bool,
    /// The display advertised an **HDR10+** vendor block (`OUI 90-84-8B`).
    ///
    /// Recorded for diagnostics only. Nothing acts on it: HDR10+ dynamic metadata cannot
    /// survive the server's current pipeline (plan §10), so it is a fact worth logging and
    /// not a capability worth claiming.
    pub hdr10_plus_advertised: bool,
    /// Which DRM connector this came from, e.g. `card1-DP-2`.
    pub connector: Option<String>,
}

impl DisplayHdr {
    /// Whether the app may pass an HDR signal through to this display.
    ///
    /// Requires PQ *and* static metadata type 1: HDR10 is defined as PQ with static
    /// metadata, and a panel advertising PQ without the metadata would be sent something
    /// it cannot interpret.
    pub fn can_show_hdr10(&self) -> bool {
        self.supports_pq && self.static_metadata_type1
    }

    /// A one-line summary for the log.
    pub fn describe(&self) -> String {
        let connector = self.connector.as_deref().unwrap_or("unbekannt");
        if !self.supports_pq && !self.supports_hlg && !self.static_metadata_type1 {
            return format!("{connector}: kein HDR gemeldet — es wird nach SDR gewandelt.");
        }
        format!(
            "{connector}: HDR10 (PQ): {}, statische Metadaten Typ 1: {}, HLG: {}, HDR10+: {}",
            yes_no(self.supports_pq),
            yes_no(self.static_metadata_type1),
            yes_no(self.supports_hlg),
            yes_no(self.hdr10_plus_advertised)
        )
    }
}

fn yes_no(value: bool) -> &'static str {
    if value {
        "ja"
    } else {
        "nein"
    }
}

/// Parses an EDID and reports its HDR capabilities.
///
/// Returns `None` when the data is not an EDID at all (wrong header, or too short). A
/// malformed *extension* yields `Some` with everything false rather than `None`: the
/// display is still a display, and "no HDR information found" is the honest answer.
pub fn parse_edid(data: &[u8]) -> Option<DisplayHdr> {
    if data.len() < BLOCK_SIZE || data[..8] != EDID_HEADER {
        return None;
    }

    let mut hdr = DisplayHdr {
        connector: None,
        ..Default::default()
    };

    // Byte 126 of the base block is the number of extension blocks that follow.
    let extensions = data[126] as usize;
    for index in 1..=extensions {
        let start = index * BLOCK_SIZE;
        let Some(block) = data.get(start..start + BLOCK_SIZE) else {
            // The count promised more blocks than are present. Truncated data is a reason
            // to stop looking, not to fail: an unreadable tail must not turn a working
            // display into "no HDR support" silently, so what was found is kept.
            break;
        };

        // Only CTA-861 extensions are searched.
        if block[0] != CTA_EXTENSION_TAG {
            continue;
        }

        // Byte 2 is the offset of the first data block; the collection runs up to byte 127
        // or to the padding byte 0x00 that ends it.
        let dtd_offset = block[2] as usize;
        // Byte 3 carries flags, including the "underscans" and audio bits that are not
        // data blocks. The walk starts at 4.
        let mut cursor = 4usize;
        let limit = if (4..BLOCK_SIZE).contains(&dtd_offset) {
            dtd_offset
        } else {
            BLOCK_SIZE
        };

        while cursor < limit {
            let header = block[cursor];
            // A tag of 0 with length 0 is the padding that ends the collection.
            if header == 0 {
                break;
            }
            let tag = header >> 5;
            let length = (header & 0x1F) as usize;
            let payload_start = cursor + 1;
            let payload_end = payload_start + length;
            if payload_end > BLOCK_SIZE {
                break;
            }
            let payload = &block[payload_start..payload_end];

            if tag == 7 {
                // Extended tag: the first payload byte says what kind of block this is.
                if let Some(&extended) = payload.first() {
                    if extended == HDR_STATIC_METADATA_TAG {
                        apply_hdr_block(&mut hdr, payload);
                    }
                }
            } else if tag == 3 {
                // A vendor-specific block; checked for the HDR10+ OUI.
                if payload.len() >= 3 && payload[..3] == [0x90, 0x84, 0x8B] {
                    hdr.hdr10_plus_advertised = true;
                }
            }

            cursor = payload_end;
        }
    }

    Some(hdr)
}

/// Reads the HDR Static Metadata Data Block.
///
/// Layout: `[extended tag, eotf bitmap, static metadata bitmap, ...]`. Per CTA-861, the
/// EOTF bitmap is:
///
/// | Bit | Meaning |
/// |---|---|
/// | 0 | Traditional gamma — SDR luminance range |
/// | 1 | Traditional gamma — HDR luminance range |
/// | 2 | **SMPTE ST 2084** (PQ — this is HDR10) |
/// | 3 | **HLG** |
///
/// The bit numbers are written out because getting them wrong is invisible and produces a
/// *confident wrong answer*: a first version of this function read PQ as bit 1 and
/// therefore reported **no HDR** for a monitor that plainly advertised it. The live test
/// against a real EDID caught it — the unit tests had been written to match the same wrong
/// assumption, so they agreed with the bug.
fn apply_hdr_block(hdr: &mut DisplayHdr, payload: &[u8]) {
    let Some(&eotf) = payload.get(1) else {
        return;
    };
    hdr.supports_pq = eotf & 0b0000_0100 != 0;
    hdr.supports_hlg = eotf & 0b0000_1000 != 0;

    // Static metadata descriptors: bit 0 is "static metadata type 1" — the metadata that
    // HDR10 streams carry.
    if let Some(&metadata) = payload.get(2) {
        hdr.static_metadata_type1 = metadata & 0b0000_0001 != 0;
    }
}

/// The DRM connectors present on this machine, as `(name, path to its EDID)`.
pub fn connectors() -> Vec<(String, PathBuf)> {
    let root = Path::new("/sys/class/drm");
    let Ok(entries) = std::fs::read_dir(root) else {
        return Vec::new();
    };

    let mut found: Vec<(String, PathBuf)> = entries
        .flatten()
        .filter_map(|entry| {
            let name = entry.file_name().to_string_lossy().to_string();
            // Connector directories look like `card1-DP-2`; `card1` itself and
            // `card1-Writeback-1` are not connectors with a display.
            let is_connector =
                name.contains('-') && name.starts_with("card") && !name.contains("Writeback");
            if !is_connector {
                return None;
            }
            let edid = entry.path().join("edid");
            edid.exists().then_some((name, edid))
        })
        .collect();

    found.sort();
    found
}

/// Whether a connector currently has a display attached.
///
/// Read separately from the EDID because a disconnected connector has an empty EDID file,
/// and reporting "this display has no HDR" for a socket with nothing plugged into it would
/// be a confusing answer.
pub fn is_connected(connector: &str) -> bool {
    std::fs::read_to_string(format!("/sys/class/drm/{connector}/status"))
        .map(|status| status.trim() == "connected")
        .unwrap_or(false)
}

/// The HDR capabilities of every connected display.
///
/// Empty when there is no DRM at all (headless CI, a container without `/dev/dri`).
pub fn detect_displays() -> Vec<DisplayHdr> {
    connectors()
        .into_iter()
        .filter(|(name, _)| is_connected(name))
        .filter_map(|(name, path)| {
            let data = std::fs::read(&path).ok()?;
            let mut hdr = parse_edid(&data)?;
            hdr.connector = Some(name);
            Some(hdr)
        })
        .collect()
}

/// Whether **any** connected display can show HDR10.
///
/// The question the playback decision asks. "Any" rather than "the current one" because a
/// window can be moved to the HDR screen, and refusing HDR for a session that may end up
/// there would make the mode depend on window placement.
///
/// `false` when no display could be identified, which is the safe direction: it means
/// tone-map to SDR, so the picture is merely not HDR rather than wrong.
pub fn any_display_supports_hdr10() -> bool {
    detect_displays().iter().any(DisplayHdr::can_show_hdr10)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Builds a minimal EDID with one CTA block whose payload blocks are given.
    fn edid_with_cta(blocks: &[Vec<u8>]) -> Vec<u8> {
        let mut base = vec![0u8; BLOCK_SIZE];
        base[..8].copy_from_slice(&EDID_HEADER);
        base[126] = 1; // one extension

        let mut cta = vec![0u8; BLOCK_SIZE];
        cta[0] = CTA_EXTENSION_TAG;
        cta[1] = 3; // revision
                    // The data block collection starts at byte 4; the offset points past it.
        let mut cursor = 4usize;
        for block in blocks {
            cta[cursor] = block[0];
            let length = (block[0] & 0x1F) as usize;
            cta[cursor + 1..cursor + 1 + length].copy_from_slice(&block[1..=length]);
            cursor += 1 + length;
        }
        cta[2] = cursor as u8;

        let mut edid = base;
        edid.extend_from_slice(&cta);
        edid
    }

    /// An HDR static metadata block with the given EOTF and metadata bitmaps.
    fn hdr_block(eotf: u8, metadata: u8) -> Vec<u8> {
        // Header: extended tag (7) << 5 | length 3
        vec![(7 << 5) | 3, HDR_STATIC_METADATA_TAG, eotf, metadata]
    }

    /// The EOTF bitmap a real HDR10 monitor sends: traditional SDR gamma (bit 0) plus
    /// **ST2084** (bit 2). Measured on this machine's `card1-DP-2`.
    const EOTF_HDR10: u8 = 0b0000_0101;

    #[test]
    fn a_panel_with_pq_and_static_metadata_can_show_hdr10() {
        // The positive case, matching what this machine's monitor reports.
        let edid = edid_with_cta(&[hdr_block(EOTF_HDR10, 0b0000_0001)]);
        let hdr = parse_edid(&edid).expect("gültiges EDID");
        assert!(hdr.supports_pq);
        assert!(hdr.static_metadata_type1);
        assert!(hdr.can_show_hdr10());
        // This panel reports SDR gamma + PQ, but *not* HLG — which is what the measured
        // bytes say, and asserting otherwise would re-introduce the wrong bit mapping.
        assert!(!hdr.supports_hlg);
    }

    #[test]
    fn the_eotf_bits_are_the_ones_cta_861_defines() {
        // Guards the defect the live test found: PQ is bit **2**, not bit 1. Written as a
        // direct assertion on each bit so the mapping cannot drift silently again — a
        // wrong answer here is confident and invisible.
        for (bit, expect_pq, expect_hlg) in [
            (0u8, false, false), // traditional gamma, SDR range
            (1, false, false),   // traditional gamma, HDR range — NOT PQ
            (2, true, false),    // SMPTE ST 2084
            (3, false, true),    // HLG
        ] {
            let edid = edid_with_cta(&[hdr_block(1 << bit, 0b0000_0001)]);
            let hdr = parse_edid(&edid).unwrap();
            assert_eq!(
                hdr.supports_pq, expect_pq,
                "Bit {bit}: PQ sollte {expect_pq} sein"
            );
            assert_eq!(
                hdr.supports_hlg, expect_hlg,
                "Bit {bit}: HLG sollte {expect_hlg} sein"
            );
        }
    }

    #[test]
    fn traditional_gamma_alone_is_not_hdr() {
        // Every display has bit 0. Treating it as HDR would make the app claim HDR on
        // every screen in existence, including the ones that would then show a grey,
        // washed-out picture.
        let edid = edid_with_cta(&[hdr_block(0b0000_0001, 0b0000_0001)]);
        let hdr = parse_edid(&edid).unwrap();
        assert!(!hdr.supports_pq);
        assert!(!hdr.can_show_hdr10());
    }

    #[test]
    fn pq_without_static_metadata_is_not_enough() {
        // HDR10 is *defined* as PQ with static metadata. A panel advertising PQ alone
        // would be sent something it cannot interpret.
        let edid = edid_with_cta(&[hdr_block(0b0000_0100, 0b0000_0000)]);
        let hdr = parse_edid(&edid).unwrap();
        assert!(hdr.supports_pq);
        assert!(!hdr.static_metadata_type1);
        assert!(!hdr.can_show_hdr10());
    }

    #[test]
    fn hlg_is_recognised_but_is_not_hdr10() {
        // Broadcast HDR. Recorded so the log is accurate, but it must not make the app
        // pass an HDR10 stream through unchanged.
        let edid = edid_with_cta(&[hdr_block(0b0000_1000, 0b0000_0001)]);
        let hdr = parse_edid(&edid).unwrap();
        assert!(hdr.supports_hlg);
        assert!(!hdr.supports_pq);
        assert!(!hdr.can_show_hdr10());
    }

    #[test]
    fn an_edid_without_any_hdr_block_reports_no_hdr() {
        // The negative case: a plain SDR monitor. This is the one where wrongly claiming
        // HDR would be visible on every single viewing.
        let mut base = vec![0u8; BLOCK_SIZE];
        base[..8].copy_from_slice(&EDID_HEADER);
        base[126] = 0;

        let hdr = parse_edid(&base).expect("das Basis-EDID ist gültig");
        assert!(!hdr.can_show_hdr10());
        assert!(!hdr.supports_pq);
        assert!(hdr.describe().contains("kein HDR"));
    }

    #[test]
    fn something_that_is_not_an_edid_is_refused() {
        // A wrong header means the file is not what it claims; parsing it would produce a
        // confident answer from noise.
        assert!(parse_edid(&[0u8; 128]).is_none());
        assert!(parse_edid(b"not an edid at all").is_none());
        // Too short to contain a header and a block.
        assert!(parse_edid(&EDID_HEADER).is_none());
    }

    #[test]
    fn a_truncated_extension_does_not_lose_what_was_found() {
        // The count promises two blocks but only one is present. Failing outright would
        // turn a working display into "no HDR"; stopping keeps the answer that was found.
        let mut edid = edid_with_cta(&[hdr_block(EOTF_HDR10, 0b0000_0001)]);
        edid[126] = 2; // claims a second block that is not there
        let hdr = parse_edid(&edid).expect("das Basis-EDID bleibt gültig");
        assert!(
            hdr.supports_pq,
            "der gefundene Block darf nicht verloren gehen"
        );
    }

    #[test]
    fn a_non_cta_extension_is_skipped() {
        // A VTB-EXT or block map extension must not be searched for CTA structures.
        let mut edid = edid_with_cta(&[]);
        edid[BLOCK_SIZE] = 0x10; // some other extension tag
        let hdr = parse_edid(&edid).unwrap();
        assert!(!hdr.can_show_hdr10());
    }

    #[test]
    fn a_padding_byte_ends_the_data_block_collection() {
        // Real EDIDs pad with 0x00. Walking past it would read padding as blocks and could
        // invent HDR support from zeros — or, worse, from whatever byte happened to follow.
        let mut block = vec![
            (7 << 5) | 3,
            HDR_STATIC_METADATA_TAG,
            EOTF_HDR10,
            0b0000_0001,
        ];
        // Header 0 with length 0 ends the collection, then a bogus HDR-looking header.
        block.push(0x00);
        block.push((7 << 5) | 3);
        let edid = edid_with_cta(&[block]);
        let hdr = parse_edid(&edid).unwrap();
        assert!(hdr.supports_pq);
        // The point is simply that this terminates rather than running off the block.
    }

    #[test]
    fn an_hdr10_plus_vendor_block_is_recorded_but_not_acted_on() {
        // Measured on this machine's monitor: the OUI is present. Nothing acts on it —
        // HDR10+ dynamic metadata cannot survive the server's pipeline (plan §10) — so it
        // must not influence `can_show_hdr10`.
        let vendor = vec![(3 << 5) | 5, 0x90, 0x84, 0x8B, 0x01, 0x00];
        let edid = edid_with_cta(&[hdr_block(0b0000_0001, 0b0000_0001), vendor]);
        let hdr = parse_edid(&edid).unwrap();
        assert!(hdr.hdr10_plus_advertised);
        assert!(
            !hdr.can_show_hdr10(),
            "HDR10+ anzukündigen ist keine HDR10-Fähigkeit"
        );
    }

    #[test]
    fn a_block_with_a_length_beyond_the_block_is_refused() {
        // A corrupt length would otherwise index outside the block.
        let mut cta = vec![0u8; BLOCK_SIZE];
        cta[0] = CTA_EXTENSION_TAG;
        cta[2] = BLOCK_SIZE as u8;
        cta[4] = 0b1110_0000 | 0x1F; // tag 7, length 31 — runs past the end
        let mut edid = {
            let mut base = vec![0u8; BLOCK_SIZE];
            base[..8].copy_from_slice(&EDID_HEADER);
            base[126] = 1;
            base
        };
        edid.extend_from_slice(&cta);
        // Must not panic.
        let hdr = parse_edid(&edid).expect("das Basis-EDID bleibt gültig");
        assert!(!hdr.can_show_hdr10());
    }

    #[test]
    fn the_description_names_the_connector_and_each_capability() {
        let hdr = DisplayHdr {
            supports_pq: true,
            static_metadata_type1: true,
            supports_hlg: false,
            hdr10_plus_advertised: true,
            connector: Some("card1-DP-2".to_string()),
        };
        let text = hdr.describe();
        assert!(text.contains("card1-DP-2"), "{text}");
        assert!(text.contains("HDR10 (PQ): ja"), "{text}");
        assert!(text.contains("HLG: nein"), "{text}");
        assert!(text.contains("HDR10+: ja"), "{text}");
    }

    #[test]
    fn an_unknown_connector_still_produces_a_readable_line() {
        let text = DisplayHdr::default().describe();
        assert!(text.contains("unbekannt"), "{text}");
        assert!(!text.trim().is_empty());
    }

    // ── Against this machine, when there is a display ──

    #[test]
    fn the_connector_list_is_plausible() {
        // Skipped rather than failed when there is no DRM (CI runner, container without
        // `/dev/dri`): there is nothing to detect, and pretending otherwise would produce
        // a test that passes for the wrong reason.
        let connectors = connectors();
        if connectors.is_empty() {
            eprintln!("übersprungen: kein /sys/class/drm vorhanden");
            return;
        }
        // Names must be connector-shaped, and the writeback pseudo-connector excluded.
        for (name, path) in &connectors {
            assert!(name.starts_with("card"), "{name}");
            assert!(name.contains('-'), "{name}");
            assert!(!name.contains("Writeback"), "{name}");
            assert!(path.ends_with("edid"), "{path:?}");
        }
    }

    #[test]
    fn a_real_connected_display_is_parsed() {
        // The measurement that gives this module its meaning. Skipped when nothing is
        // attached, because there is no display to make a claim about.
        let displays = detect_displays();
        if displays.is_empty() {
            eprintln!("übersprungen: kein angeschlossenes Display mit lesbarem EDID");
            return;
        }

        for display in &displays {
            let connector = display.connector.as_deref().unwrap_or("?");
            // A parsed EDID must at least produce a sentence, and the connector must be
            // recorded — otherwise the log cannot say which screen the answer is about.
            assert!(!display.describe().trim().is_empty());
            assert!(connector.starts_with("card"), "{connector}");

            eprintln!("{}", display.describe());
        }
    }
}
