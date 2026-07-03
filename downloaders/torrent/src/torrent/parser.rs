use crate::error::AppError;
use hightorrent::{MagnetLink, TorrentFile};

pub struct ParsedMagnet {
    pub info_hash: String,
    pub display_name: Option<String>,
}

pub struct ParsedTorrent {
    pub info_hash: String,
    pub name: String,
}

pub fn parse_magnet(uri: &str) -> Result<ParsedMagnet, AppError> {
    let magnet = MagnetLink::new(uri)
        .map_err(|e| AppError::InvalidTorrent(format!("Invalid magnet link: {}", e)))?;

    let info_hash = magnet.hash().to_string();
    let name = magnet.name();
    let display_name = if name.is_empty() {
        None
    } else {
        Some(name.to_string())
    };

    Ok(ParsedMagnet {
        info_hash,
        display_name,
    })
}

pub fn parse_torrent_file(bytes: &[u8]) -> Result<ParsedTorrent, AppError> {
    let torrent = TorrentFile::from_slice(bytes)
        .map_err(|e| AppError::InvalidTorrent(format!("Invalid torrent file: {}", e)))?;

    let info_hash = torrent.hash().to_string();
    let name = torrent.name().to_string();

    Ok(ParsedTorrent { info_hash, name })
}
