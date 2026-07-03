use crate::error::AppError;

/// Result of yEnc decoding with optional CRC verification.
pub struct YencResult {
    pub data: Vec<u8>,
    pub crc_valid: bool,
}

/// Check if raw article data looks like a DMCA takedown or content removal notice.
/// SABnzbd checks for these keywords to immediately skip to another server.
pub fn is_dmca_content(data: &[u8]) -> bool {
    let check = if data.len() > 2048 { &data[..2048] } else { data };
    let lower = String::from_utf8_lossy(check).to_lowercase();
    lower.contains("dmca")
        || lower.contains("removed")
        || lower.contains("cancel")
        || lower.contains("blocked")
        || lower.contains("takedown")
        || lower.contains("this article has been")
        || lower.contains("article not available")
}

/// Decode yEnc encoded data from raw article body bytes.
/// Returns the decoded binary data and CRC32 validation result.
pub fn decode_yenc(data: &[u8]) -> Result<YencResult, AppError> {
    // Check for DMCA replacement content before trying to decode
    if is_dmca_content(data) {
        return Err(AppError::Download(
            "DMCA/takedown: article content has been removed".to_string(),
        ));
    }

    let mut output = Vec::new();
    let mut in_body = false;
    let mut escape_next = false;
    let mut expected_crc: Option<u32> = None;

    for line in data.split(|&b| b == b'\n') {
        let line = if line.last() == Some(&b'\r') {
            &line[..line.len() - 1]
        } else {
            line
        };

        if line.starts_with(b"=ybegin") {
            in_body = true;
            continue;
        }
        if line.starts_with(b"=ypart") {
            continue;
        }
        if line.starts_with(b"=yend") {
            // Parse CRC32 from =yend line
            expected_crc = parse_yend_crc(line);
            break;
        }

        if !in_body {
            continue;
        }

        for &byte in line {
            if escape_next {
                output.push(byte.wrapping_sub(64).wrapping_sub(42));
                escape_next = false;
            } else if byte == b'=' {
                escape_next = true;
            } else {
                output.push(byte.wrapping_sub(42));
            }
        }
    }

    if !in_body {
        return Err(AppError::Download(
            "No yEnc header found in article".to_string(),
        ));
    }

    // Verify CRC32 if present in =yend trailer
    let crc_valid = if let Some(expected) = expected_crc {
        let actual = crc32fast::hash(&output);
        if actual != expected {
            tracing::warn!(
                "yEnc CRC32 mismatch: expected {:08x}, got {:08x} ({} bytes)",
                expected, actual, output.len()
            );
            false
        } else {
            true
        }
    } else {
        // No CRC in trailer — assume valid (some servers omit it)
        true
    };

    Ok(YencResult {
        data: output,
        crc_valid,
    })
}

/// Parse the CRC32 value from a =yend line.
/// Looks for pcrc32= (part CRC) first, then crc32= (full CRC).
fn parse_yend_crc(line: &[u8]) -> Option<u32> {
    let line_str = std::str::from_utf8(line).ok()?;

    // Prefer pcrc32 (part CRC) for multi-part articles
    for prefix in &["pcrc32=", "crc32="] {
        if let Some(pos) = line_str.find(prefix) {
            let start = pos + prefix.len();
            let hex: String = line_str[start..]
                .chars()
                .take_while(|c| c.is_ascii_hexdigit())
                .collect();
            if !hex.is_empty() {
                return u32::from_str_radix(&hex, 16).ok();
            }
        }
    }

    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_decode_yenc_simple() {
        // "Hello" encoded in yEnc: each byte + 42, wrapped at 256
        let hello = b"Hello";
        let mut encoded = Vec::new();
        encoded.extend_from_slice(b"=ybegin line=128 size=5 name=test.txt\r\n");
        for &b in hello {
            encoded.push(b.wrapping_add(42));
        }
        encoded.extend_from_slice(b"\r\n=yend size=5\r\n");

        let result = decode_yenc(&encoded).unwrap();
        assert_eq!(result.data, hello);
    }

    #[test]
    fn test_parse_yend_crc() {
        let line = b"=yend size=1234 pcrc32=DEADBEEF";
        assert_eq!(parse_yend_crc(line), Some(0xDEADBEEF));

        let line = b"=yend size=1234 crc32=12345678";
        assert_eq!(parse_yend_crc(line), Some(0x12345678));

        let line = b"=yend size=1234";
        assert_eq!(parse_yend_crc(line), None);
    }

    #[test]
    fn test_dmca_detection() {
        assert!(is_dmca_content(b"This article has been removed due to DMCA"));
        assert!(is_dmca_content(b"Article blocked by content filter"));
        assert!(!is_dmca_content(b"=ybegin line=128 size=5 name=test.txt\r\n"));
    }
}
