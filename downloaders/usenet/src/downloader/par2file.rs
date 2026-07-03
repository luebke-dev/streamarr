//! PAR2 filename + tool-output parsing for *selective* volume download.
//!
//! The old worker downloaded **every** `.vol` PAR2 file whenever any segment
//! failed — often hundreds of MB of recovery data that was never needed.
//! SABnzbd instead asks the par2 tool how many recovery blocks are missing
//! and fetches only enough volumes to cover that deficit (`postproc.py`
//! re-add loop). par2cmdline encodes the block count of each volume in its
//! filename (`name.volSTART+COUNT.par2`), and prints the shortfall as
//! "You need N more recovery blocks to be able to repair." — both are stable
//! across par2cmdline versions, so no binary PAR2 packet parsing is needed.

/// Number of recovery blocks a `.volSTART+COUNT.par2` volume provides.
/// e.g. `Show.S01.vol012+10.par2` → 10. Returns `None` for the base
/// `name.par2` (no `.vol` segment) or an unrecognized name.
pub fn recovery_blocks_in_volume(filename: &str) -> Option<u32> {
    let lower = filename.to_lowercase();
    if !lower.ends_with(".par2") {
        return None;
    }
    // Isolate the "volSTART+COUNT" token.
    let vol_pos = lower.rfind(".vol")?;
    let after = &lower[vol_pos + 4..];
    let token = after.strip_suffix(".par2").unwrap_or(after);
    let plus = token.find('+')?;
    let count: String = token[plus + 1..]
        .chars()
        .take_while(|c| c.is_ascii_digit())
        .collect();
    count.parse().ok().filter(|&n| n > 0)
}

/// Outcome of a single par2 verify/repair attempt, parsed from tool output.
#[derive(Debug, PartialEq, Eq)]
pub enum Par2Outcome {
    /// Files already correct — nothing to do.
    NotNeeded,
    /// Repair succeeded (or was possible and completed).
    Repaired,
    /// Repair needs this many more recovery blocks than are present.
    NeedMoreBlocks(u32),
    /// par2 failed for a reason extra blocks won't fix.
    Failed,
}

/// Classify par2cmdline stdout (status code passed in separately by the
/// caller). Matched case-insensitively against par2cmdline's stable phrases.
pub fn classify_par2_output(stdout: &str, success: bool) -> Par2Outcome {
    let s = stdout.to_lowercase();

    if s.contains("repair is not required") || s.contains("all files are correct") {
        return Par2Outcome::NotNeeded;
    }
    if s.contains("repair complete")
        || s.contains("repaired successfully")
        || s.contains("repair is possible") && success
    {
        return Par2Outcome::Repaired;
    }
    if let Some(n) = parse_blocks_needed(stdout) {
        return Par2Outcome::NeedMoreBlocks(n);
    }
    if success {
        // Exit 0 with none of the known phrases: nothing was broken.
        return Par2Outcome::NotNeeded;
    }
    Par2Outcome::Failed
}

/// Extract N from "You need N more recovery blocks to be able to repair."
fn parse_blocks_needed(stdout: &str) -> Option<u32> {
    for line in stdout.lines() {
        let l = line.to_lowercase();
        if let Some(rest) = l.split_once("you need") {
            if rest.1.contains("more recovery block") {
                let n: String = rest
                    .1
                    .chars()
                    .skip_while(|c| !c.is_ascii_digit())
                    .take_while(|c| c.is_ascii_digit())
                    .collect();
                if let Ok(v) = n.parse::<u32>() {
                    return Some(v);
                }
            }
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_recovery_block_count_from_volume_name() {
        assert_eq!(recovery_blocks_in_volume("Show.S01E01.vol000+001.PAR2"), Some(1));
        assert_eq!(recovery_blocks_in_volume("Show.S01E01.vol001+002.par2"), Some(2));
        assert_eq!(recovery_blocks_in_volume("rls.vol12+100.par2"), Some(100));
        // Base par2 file has no .vol segment.
        assert_eq!(recovery_blocks_in_volume("rls.par2"), None);
        assert_eq!(recovery_blocks_in_volume("movie.mkv"), None);
    }

    #[test]
    fn classifies_par2_tool_output() {
        assert_eq!(
            classify_par2_output("All files are correct, repair is not required.", true),
            Par2Outcome::NotNeeded
        );
        assert_eq!(
            classify_par2_output("Repair is required.\nRepair complete.", true),
            Par2Outcome::Repaired
        );
        assert_eq!(
            classify_par2_output(
                "Repair is required.\nYou need 17 more recovery blocks to be able to repair.",
                false
            ),
            Par2Outcome::NeedMoreBlocks(17)
        );
        assert_eq!(
            classify_par2_output("Segmentation fault", false),
            Par2Outcome::Failed
        );
        // Exit 0, no recognized phrase → assume nothing was wrong.
        assert_eq!(classify_par2_output("", true), Par2Outcome::NotNeeded);
    }
}
