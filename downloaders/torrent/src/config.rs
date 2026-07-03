use std::env;
use std::path::PathBuf;

#[derive(Debug, Clone)]
pub struct Config {
    pub server: ServerConfig,
    pub torrent: TorrentConfig,
    pub webhooks: WebhookConfig,
    pub download: DownloadConfig,
}

#[derive(Debug, Clone)]
pub struct ServerConfig {
    pub host: String,
    pub port: u16,
}

#[derive(Debug, Clone)]
pub struct TorrentConfig {
    pub enable_dht: bool,
    pub listen_port: u16,
    pub seed_ratio: f64,
}

#[derive(Debug, Clone)]
pub struct WebhookConfig {
    pub url: String,
    /// Shared secret sent as the `X-Webhook-Secret` header so the backend can
    /// reject forged callbacks. Empty string disables the header (dev parity).
    pub secret: String,
    pub timeout_secs: u64,
    pub max_retries: u32,
}

#[derive(Debug, Clone)]
pub struct DownloadConfig {
    pub directory: PathBuf,
    pub db_path: PathBuf,
    pub max_concurrent_jobs: usize,
}

impl Config {
    pub fn from_env() -> Result<Self, String> {
        Ok(Self {
            server: ServerConfig {
                host: env_or("SERVER_HOST", "0.0.0.0"),
                port: env_parse("SERVER_PORT", 3000)?,
            },
            torrent: TorrentConfig {
                enable_dht: env_parse("ENABLE_DHT", true)?,
                listen_port: env_parse("LISTEN_PORT", 6881)?,
                seed_ratio: env_parse("SEED_RATIO", 0.0)?,
            },
            webhooks: WebhookConfig {
                url: env_or("WEBHOOK_URL", ""),
                secret: env_or("WEBHOOK_SECRET", ""),
                timeout_secs: env_parse("WEBHOOK_TIMEOUT_SECS", 10)?,
                max_retries: env_parse("WEBHOOK_MAX_RETRIES", 3)?,
            },
            download: DownloadConfig {
                directory: PathBuf::from(env_or("DOWNLOAD_DIR", "/downloads")),
                db_path: PathBuf::from(env_or("DATABASE_PATH", "/data/torrent-downloader.db")),
                max_concurrent_jobs: env_parse("MAX_CONCURRENT_DOWNLOADS", 5)?,
            },
        })
    }
}

fn env_or(key: &str, default: &str) -> String {
    env::var(key).unwrap_or_else(|_| default.to_string())
}

fn env_parse<T: std::str::FromStr>(key: &str, default: T) -> Result<T, String>
where
    T::Err: std::fmt::Display,
{
    match env::var(key) {
        Ok(val) => val
            .parse()
            .map_err(|e| format!("Invalid value for {}: {}", key, e)),
        Err(_) => Ok(default),
    }
}
