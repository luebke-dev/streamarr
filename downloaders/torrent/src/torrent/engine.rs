use crate::config::TorrentConfig;
use crate::error::AppError;
use librqbit::{AddTorrent, AddTorrentOptions, AddTorrentResponse, Session, SessionOptions};
use std::path::PathBuf;
use std::sync::Arc;

pub struct TorrentEngine {
    session: Arc<Session>,
}

pub struct TorrentHandle {
    pub id: usize,
}

pub struct TorrentStatus {
    pub progress: f64,
    pub total_bytes: u64,
    pub downloaded_bytes: u64,
    pub uploaded_bytes: u64,
    pub download_speed: u64,
    pub upload_speed: u64,
    pub peers_connected: u32,
    pub seeds_connected: u32,
    pub finished: bool,
    pub error: Option<String>,
}

impl TorrentEngine {
    pub async fn new(
        download_dir: PathBuf,
        config: &TorrentConfig,
    ) -> Result<Self, AppError> {
        let port = config.listen_port;
        let opts = SessionOptions {
            disable_dht: !config.enable_dht,
            listen_port_range: Some(port..(port + 10)),
            ..Default::default()
        };

        let session = Session::new_with_opts(download_dir, opts)
            .await
            .map_err(|e| AppError::Engine(format!("Failed to create session: {}", e)))?;

        Ok(Self { session })
    }

    pub async fn add_magnet(
        &self,
        magnet_uri: &str,
        dest: Option<PathBuf>,
    ) -> Result<TorrentHandle, AppError> {
        let opts = dest.map(|d| AddTorrentOptions {
            output_folder: Some(d.to_string_lossy().to_string()),
            ..Default::default()
        });

        let response = self
            .session
            .add_torrent(AddTorrent::from_url(magnet_uri), opts)
            .await
            .map_err(|e| AppError::Engine(format!("Failed to add magnet: {}", e)))?;

        let id = match response {
            AddTorrentResponse::Added(id, _) => id,
            AddTorrentResponse::AlreadyManaged(id, _) => id,
            AddTorrentResponse::ListOnly(_) => {
                return Err(AppError::Engine("Torrent returned list-only response".to_string()));
            }
        };

        Ok(TorrentHandle { id })
    }

    pub async fn add_torrent_bytes(
        &self,
        bytes: &[u8],
        dest: Option<PathBuf>,
    ) -> Result<TorrentHandle, AppError> {
        let opts = dest.map(|d| AddTorrentOptions {
            output_folder: Some(d.to_string_lossy().to_string()),
            ..Default::default()
        });

        let response = self
            .session
            .add_torrent(AddTorrent::from_bytes(bytes.to_vec()), opts)
            .await
            .map_err(|e| AppError::Engine(format!("Failed to add torrent: {}", e)))?;

        let id = match response {
            AddTorrentResponse::Added(id, _) => id,
            AddTorrentResponse::AlreadyManaged(id, _) => id,
            AddTorrentResponse::ListOnly(_) => {
                return Err(AppError::Engine("Torrent returned list-only response".to_string()));
            }
        };

        Ok(TorrentHandle { id })
    }

    pub fn get_status(&self, handle: &TorrentHandle) -> Result<TorrentStatus, AppError> {
        let managed = self
            .session
            .get(handle.id.into())
            .ok_or_else(|| AppError::Engine("Torrent not found in session".to_string()))?;

        let stats = managed.stats();

        let (download_speed, upload_speed, peers, seeds) = stats
            .live
            .as_ref()
            .map(|live| {
                // Speed.mbps is f64 megabits per second -> convert to bytes/sec
                let dl = (live.download_speed.mbps * 125_000.0) as u64;
                let ul = (live.upload_speed.mbps * 125_000.0) as u64;
                let p = live.snapshot.peer_stats.live as u32;
                let s = live.snapshot.peer_stats.seen as u32;
                (dl, ul, p, s)
            })
            .unwrap_or((0, 0, 0, 0));

        let progress = if stats.total_bytes > 0 {
            (stats.progress_bytes as f64 / stats.total_bytes as f64) * 100.0
        } else {
            0.0
        };

        Ok(TorrentStatus {
            progress,
            total_bytes: stats.total_bytes,
            downloaded_bytes: stats.progress_bytes,
            uploaded_bytes: stats.uploaded_bytes,
            download_speed,
            upload_speed,
            peers_connected: peers,
            seeds_connected: seeds,
            finished: stats.finished,
            error: stats.error.clone(),
        })
    }

    pub async fn cancel(&self, handle: &TorrentHandle) -> Result<(), AppError> {
        self.session
            .delete(handle.id.into(), false)
            .await
            .map_err(|e| AppError::Engine(format!("Failed to cancel torrent: {}", e)))?;
        Ok(())
    }
}
