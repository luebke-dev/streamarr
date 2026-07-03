use crate::error::AppError;
use crate::models::nzb::{NzbFile, NzbSegment, ParsedNzb};
use chrono::{DateTime, TimeZone, Utc};
use quick_xml::events::Event;
use quick_xml::Reader;

pub fn parse_nzb(xml: &str) -> Result<ParsedNzb, AppError> {
    let mut reader = Reader::from_str(xml);
    let mut files = Vec::new();
    let mut password: Option<String> = None;
    let mut earliest_date: Option<DateTime<Utc>> = None;

    let mut current_file: Option<NzbFileBuilder> = None;
    let mut in_groups = false;
    let mut in_segments = false;
    let mut in_password_meta = false;
    let mut current_text = String::new();

    loop {
        match reader.read_event() {
            Ok(Event::Start(ref e)) | Ok(Event::Empty(ref e)) => {
                match e.name().as_ref() {
                    b"file" => {
                        let mut filename = String::new();
                        let mut file_date: Option<i64> = None;
                        for attr in e.attributes().flatten() {
                            match attr.key.as_ref() {
                                b"subject" => {
                                    filename = String::from_utf8_lossy(&attr.value).to_string();
                                }
                                b"date" => {
                                    if let Ok(ts) = String::from_utf8_lossy(&attr.value).parse::<i64>() {
                                        file_date = Some(ts);
                                    }
                                }
                                _ => {}
                            }
                        }
                        // Track the earliest post date across all files
                        if let Some(ts) = file_date {
                            if let Some(dt) = Utc.timestamp_opt(ts, 0).single() {
                                match earliest_date {
                                    None => earliest_date = Some(dt),
                                    Some(existing) if dt < existing => earliest_date = Some(dt),
                                    _ => {}
                                }
                            }
                        }
                        current_file = Some(NzbFileBuilder {
                            filename: extract_filename(&filename),
                            groups: Vec::new(),
                            segments: Vec::new(),
                        });
                    }
                    b"meta" => {
                        for attr in e.attributes().flatten() {
                            if attr.key.as_ref() == b"type"
                                && attr.value.as_ref() == b"password"
                            {
                                in_password_meta = true;
                            }
                        }
                    }
                    b"groups" => in_groups = true,
                    b"segments" => in_segments = true,
                    b"segment" => {
                        if in_segments {
                            let mut number = 0u32;
                            let mut bytes = 0u64;
                            for attr in e.attributes().flatten() {
                                match attr.key.as_ref() {
                                    b"number" => {
                                        number = String::from_utf8_lossy(&attr.value)
                                            .parse()
                                            .unwrap_or(0);
                                    }
                                    b"bytes" => {
                                        bytes = String::from_utf8_lossy(&attr.value)
                                            .parse()
                                            .unwrap_or(0);
                                    }
                                    _ => {}
                                }
                            }
                            // The message-id is the text content, read in Text event
                            if let Some(ref mut file) = current_file {
                                file.segments.push(NzbSegment {
                                    message_id: String::new(), // filled on End event
                                    number,
                                    bytes,
                                });
                            }
                        }
                    }
                    _ => {}
                }
                current_text.clear();
            }
            Ok(Event::Text(e)) => {
                current_text = e.unescape().unwrap_or_default().to_string();
            }
            Ok(Event::End(ref e)) => match e.name().as_ref() {
                b"file" => {
                    if let Some(file) = current_file.take() {
                        let mut nzb_file = NzbFile {
                            filename: file.filename,
                            groups: file.groups,
                            segments: file.segments,
                        };
                        nzb_file.segments.sort_by_key(|s| s.number);
                        files.push(nzb_file);
                    }
                }
                b"meta" => {
                    if in_password_meta {
                        let pw = current_text.trim().to_string();
                        if !pw.is_empty() {
                            password = Some(pw);
                        }
                        in_password_meta = false;
                    }
                }
                b"groups" => in_groups = false,
                b"segments" => in_segments = false,
                b"group" => {
                    if in_groups {
                        if let Some(ref mut file) = current_file {
                            file.groups.push(current_text.trim().to_string());
                        }
                    }
                }
                b"segment" => {
                    if let Some(ref mut file) = current_file {
                        if let Some(seg) = file.segments.last_mut() {
                            seg.message_id = current_text.trim().to_string();
                        }
                    }
                }
                _ => {}
            },
            Ok(Event::Eof) => break,
            Err(e) => {
                return Err(AppError::InvalidNzb(format!("XML parse error: {}", e)));
            }
            _ => {}
        }
    }

    if files.is_empty() {
        return Err(AppError::InvalidNzb("No files found in NZB".to_string()));
    }

    Ok(ParsedNzb { files, password, publish_date: earliest_date })
}

struct NzbFileBuilder {
    filename: String,
    groups: Vec<String>,
    segments: Vec<NzbSegment>,
}

/// Extract a usable filename from the NZB subject line.
/// Handles formats like:
///   "My.File.txt" yEnc (1/10)
///   My.File.txt (1/0)
///   [group] My.File.txt yEnc (1/10)
fn extract_filename(subject: &str) -> String {
    // Decode XML entities that quick-xml may not decode in attributes
    let subject = subject
        .replace("&quot;", "\"")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">");

    // Try to find a quoted filename
    if let Some(start) = subject.find('"') {
        if let Some(end) = subject[start + 1..].find('"') {
            let name = &subject[start + 1..start + 1 + end];
            if !name.is_empty() {
                return sanitize_filename(name);
            }
        }
    }

    // Strip trailing yEnc / (N/M) markers and leading brackets
    let mut s = subject.trim();

    // Remove trailing (N/M) pattern
    if let Some(paren_start) = s.rfind('(') {
        s = s[..paren_start].trim();
    }

    // Remove trailing "yEnc" marker
    if let Some(stripped) = s.strip_suffix("yEnc") {
        s = stripped.trim();
    }

    // Remove leading [group] pattern
    if s.starts_with('[') {
        if let Some(bracket_end) = s.find(']') {
            s = s[bracket_end + 1..].trim();
        }
    }

    if s.is_empty() {
        return sanitize_filename(&subject);
    }

    sanitize_filename(s)
}

/// Remove characters that are unsafe in filenames (especially / which creates subdirs)
fn sanitize_filename(name: &str) -> String {
    name.chars()
        .map(|c| match c {
            '/' | '\\' | ':' | '*' | '?' | '<' | '>' | '|' => '_',
            _ => c,
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_nzb() {
        let xml = r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE nzb PUBLIC "-//newzBin//DTD NZB 1.1//EN" "http://www.newzbin.com/DTD/nzb/nzb-1.1.dtd">
<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">
  <file poster="test@test.com" date="1234567890" subject="&quot;test.rar&quot; yEnc (1/2)">
    <groups>
      <group>alt.binaries.test</group>
    </groups>
    <segments>
      <segment bytes="100000" number="1">article1@test.com</segment>
      <segment bytes="50000" number="2">article2@test.com</segment>
    </segments>
  </file>
</nzb>"#;

        let nzb = parse_nzb(xml).unwrap();
        assert_eq!(nzb.files.len(), 1);
        assert_eq!(nzb.files[0].filename, "test.rar");
        assert_eq!(nzb.files[0].segments.len(), 2);
        assert_eq!(nzb.files[0].segments[0].message_id, "article1@test.com");
        assert_eq!(nzb.files[0].segments[1].number, 2);
        assert_eq!(nzb.total_bytes(), 150000);
    }
}
