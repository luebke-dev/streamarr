use std::env;
use std::path::PathBuf;

#[derive(Debug, Clone)]
pub struct Config {
    pub server: ServerConfig,
    pub usenet: UsenetConfig,
    pub backup_servers: Vec<UsenetConfig>,
    pub nntp: NntpConfig,
    pub webhooks: WebhookConfig,
    pub download: DownloadConfig,
    pub database_path: PathBuf,
}

#[derive(Debug, Clone)]
pub struct ServerConfig {
    pub host: String,
    pub port: u16,
}

#[derive(Debug, Clone)]
pub struct UsenetConfig {
    pub host: String,
    pub port: u16,
    pub tls: bool,
    pub username: String,
    pub password: String,
    pub connections: usize,
    /// Server retention in days. 0 = unlimited.
    pub retention_days: u64,
    /// Selection order: lower value = tried first. Primary defaults to 0,
    /// backups to their 1-based index (SABnzbd server "priority" levels).
    pub priority: u8,
    /// Optional servers auto-deactivate when too many connections go bad;
    /// required servers (the primary) are only temporarily blocked and
    /// auto-resume. Primary defaults to required, backups to optional.
    pub optional: bool,
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
    pub temp_directory: PathBuf,
    pub max_concurrent_jobs: usize,
    /// Seconds to wait before downloading a newly added NZB.
    /// Gives articles time to propagate across usenet servers.
    pub propagation_delay_secs: u64,
    /// If true, start unrar as soon as part01 arrives (in parallel with download).
    /// Off by default: a missing/corrupt volume crashes unrar before PAR2 can repair,
    /// turning a recoverable download into a failed one. Matches SABnzbd default.
    pub direct_unpack: bool,
    /// Global decoded-segment RAM budget in MiB. Fetch tasks block once this
    /// much undelivered data is buffered, so peak memory is bounded by this
    /// value regardless of release size (SABnzbd articlecache analog).
    pub article_cache_mb: usize,
    /// Global download speed cap in KiB/s. 0 = unlimited. Overridable at
    /// runtime via the API.
    pub speed_limit_kbps: u64,
}

#[derive(Debug, Clone)]
pub struct NntpConfig {
    /// Timeout for individual NNTP read/write operations in seconds.
    pub timeout_secs: u64,
    /// Number of pipelined BODY requests per connection.
    pub pipeline_requests: usize,
}

impl Config {
    pub fn from_env() -> Result<Self, String> {
        // Parse backup servers from BACKUP_SERVER_1_HOST, BACKUP_SERVER_1_PORT, etc.
        let mut backup_servers = Vec::new();
        for i in 1..=5 {
            let prefix = format!("BACKUP_SERVER_{}", i);
            if let Ok(host) = env::var(format!("{}_HOST", prefix)) {
                backup_servers.push(UsenetConfig {
                    host,
                    port: env_parse(&format!("{}_PORT", prefix), 563)?,
                    tls: env_parse(&format!("{}_TLS", prefix), true)?,
                    username: env_or(&format!("{}_USERNAME", prefix), ""),
                    password: env_or(&format!("{}_PASSWORD", prefix), ""),
                    connections: env_parse(&format!("{}_CONNECTIONS", prefix), 4)?,
                    retention_days: env_parse(&format!("{}_RETENTION_DAYS", prefix), 0)?,
                    priority: env_parse(&format!("{}_PRIORITY", prefix), i as u8)?,
                    optional: env_parse(&format!("{}_OPTIONAL", prefix), true)?,
                });
            }
        }

        Ok(Self {
            server: ServerConfig {
                host: env_or("SERVER_HOST", "0.0.0.0"),
                port: env_parse("SERVER_PORT", 3000)?,
            },
            usenet: UsenetConfig {
                host: env_required("USENET_HOST")?,
                port: env_parse("USENET_PORT", 563)?,
                tls: env_parse("USENET_TLS", true)?,
                username: env_required("USENET_USERNAME")?,
                password: env_required("USENET_PASSWORD")?,
                connections: env_parse("USENET_CONNECTIONS", 20)?,
                retention_days: env_parse("USENET_RETENTION_DAYS", 0)?,
                priority: env_parse("USENET_PRIORITY", 0)?,
                optional: env_parse("USENET_OPTIONAL", false)?,
            },
            backup_servers,
            nntp: NntpConfig {
                timeout_secs: env_parse("NNTP_TIMEOUT_SECS", 60)?,
                pipeline_requests: env_parse("NNTP_PIPELINE_REQUESTS", 2)?,
            },
            webhooks: WebhookConfig {
                url: env_or("WEBHOOK_URL", ""),
                secret: env_or("WEBHOOK_SECRET", ""),
                timeout_secs: env_parse("WEBHOOK_TIMEOUT_SECS", 10)?,
                max_retries: env_parse("WEBHOOK_MAX_RETRIES", 3)?,
            },
            download: DownloadConfig {
                directory: PathBuf::from(env_or("DOWNLOAD_DIR", "/downloads")),
                temp_directory: PathBuf::from(env_or("DOWNLOAD_TEMP_DIR", "/downloads/.tmp")),
                max_concurrent_jobs: env_parse("DOWNLOAD_MAX_CONCURRENT_JOBS", 3)?,
                propagation_delay_secs: env_parse("PROPAGATION_DELAY_SECS", 0)?,
                direct_unpack: env_parse("DIRECT_UNPACK", false)?,
                article_cache_mb: env_parse("ARTICLE_CACHE_MB", 500)?,
                speed_limit_kbps: env_parse("SPEED_LIMIT_KBPS", 0)?,
            },
            database_path: PathBuf::from(env_or("DATABASE_PATH", "/data/usenet.db")),
        })
    }
}

fn env_or(key: &str, default: &str) -> String {
    env::var(key).unwrap_or_else(|_| default.to_string())
}

fn env_required(key: &str) -> Result<String, String> {
    env::var(key).map_err(|_| format!("Required env var {} is not set", key))
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
