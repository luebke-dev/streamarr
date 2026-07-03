use librespot_playback::config::Bitrate;
use std::env;
use std::path::PathBuf;

#[derive(Debug, Clone)]
pub struct Config {
    pub server: ServerConfig,
    pub spotify: SpotifyConfig,
    pub webhooks: WebhookConfig,
    pub database_path: PathBuf,
    pub download_dir: PathBuf,
    pub enable_webui: bool,
}

#[derive(Debug, Clone)]
pub struct ServerConfig {
    pub host: String,
    pub port: u16,
}

#[derive(Debug, Clone)]
pub struct SpotifyConfig {
    pub config_dir: String,
    pub bitrate: Bitrate,
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

impl Config {
    pub fn from_env() -> Result<Self, String> {
        Ok(Self {
            server: ServerConfig {
                host: env_or("SERVER_HOST", "0.0.0.0"),
                port: env_parse("SERVER_PORT", 3000)?,
            },
            spotify: SpotifyConfig {
                config_dir: env_or("CONFIG_DIR", "/data/config"),
                bitrate: parse_bitrate(&env_or("BITRATE", "320")),
            },
            webhooks: WebhookConfig {
                url: env_or("WEBHOOK_URL", ""),
                secret: env_or("WEBHOOK_SECRET", ""),
                timeout_secs: env_parse("WEBHOOK_TIMEOUT_SECS", 10)?,
                max_retries: env_parse("WEBHOOK_MAX_RETRIES", 3)?,
            },
            database_path: PathBuf::from(env_or("DATABASE_PATH", "/data/spotify.db")),
            download_dir: PathBuf::from(env_or("DOWNLOAD_DIR", "/data/downloads")),
            enable_webui: env::var("ENABLE_WEBUI").is_ok(),
        })
    }
}

fn parse_bitrate(s: &str) -> Bitrate {
    match s {
        "96" => Bitrate::Bitrate96,
        "160" => Bitrate::Bitrate160,
        _ => Bitrate::Bitrate320,
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
