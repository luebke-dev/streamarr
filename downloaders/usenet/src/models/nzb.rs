use serde::{Deserialize, Serialize};
use chrono::{DateTime, Utc};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NzbFile {
    pub filename: String,
    pub groups: Vec<String>,
    pub segments: Vec<NzbSegment>,
}

impl NzbFile {
    /// Check if this file is a PAR2 volume (not the base .par2 file).
    pub fn is_par2_volume(&self) -> bool {
        let lower = self.filename.to_lowercase();
        lower.contains(".vol") && lower.ends_with(".par2")
    }

    /// Check if this file is the base PAR2 file (not a volume).
    pub fn is_par2_base(&self) -> bool {
        let lower = self.filename.to_lowercase();
        lower.ends_with(".par2") && !lower.contains(".vol")
    }

    /// Check if this file is any PAR2 file.
    pub fn is_par2(&self) -> bool {
        self.filename.to_lowercase().ends_with(".par2")
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NzbSegment {
    pub message_id: String,
    pub number: u32,
    pub bytes: u64,
}

#[derive(Debug, Clone)]
pub struct ParsedNzb {
    pub files: Vec<NzbFile>,
    pub password: Option<String>,
    /// Earliest post date across all files in the NZB, parsed from the `date` attribute.
    pub publish_date: Option<DateTime<Utc>>,
}

impl ParsedNzb {
    pub fn total_bytes(&self) -> u64 {
        self.files
            .iter()
            .flat_map(|f| &f.segments)
            .map(|s| s.bytes)
            .sum()
    }

    pub fn total_segments(&self) -> usize {
        self.files.iter().map(|f| f.segments.len()).sum()
    }

    /// Split files into data files + base PAR2, and PAR2 volumes (for on-demand download).
    /// Returns (essential_files, par2_volumes).
    /// Essential = data files + base .par2 file.
    /// PAR2 volumes = .vol00+01.par2 etc. — only download if repair needed.
    pub fn split_par2_volumes(&self) -> (Vec<&NzbFile>, Vec<&NzbFile>) {
        let mut essential = Vec::new();
        let mut volumes = Vec::new();

        for file in &self.files {
            if file.is_par2_volume() {
                volumes.push(file);
            } else {
                essential.push(file);
            }
        }

        // Sort volumes by filename so smaller volumes come first
        volumes.sort_by(|a, b| a.filename.cmp(&b.filename));

        (essential, volumes)
    }

    /// Check if any file is a PAR2 file.
    pub fn has_par2(&self) -> bool {
        self.files.iter().any(|f| f.is_par2())
    }

    /// Get total bytes for data files only (excluding PAR2 volumes).
    pub fn data_bytes(&self) -> u64 {
        self.files
            .iter()
            .filter(|f| !f.is_par2_volume())
            .flat_map(|f| &f.segments)
            .map(|s| s.bytes)
            .sum()
    }
}
