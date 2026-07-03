//! Runtime download controls: global pause and an adjustable global speed
//! limit (SABnzbd's pause + bandwidth limit, `downloader.py:815-823`).
//!
//! Per-job pause is expressed through `JobStatus::Paused` and checked by the
//! worker; this module holds only process-wide state shared across jobs.

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tokio::sync::Notify;

pub struct DownloadControl {
    paused: AtomicBool,
    /// Wakes parked workers when the global pause is lifted.
    resume: Notify,
    /// Speed cap in bytes/sec; 0 = unlimited.
    limit_bps: AtomicU64,
    bucket: Mutex<TokenBucket>,
}

struct TokenBucket {
    tokens: f64,
    last: Instant,
}

impl DownloadControl {
    pub fn new(speed_limit_kbps: u64) -> Self {
        Self {
            paused: AtomicBool::new(false),
            resume: Notify::new(),
            limit_bps: AtomicU64::new(speed_limit_kbps.saturating_mul(1024)),
            bucket: Mutex::new(TokenBucket {
                tokens: 0.0,
                last: Instant::now(),
            }),
        }
    }

    pub fn is_paused(&self) -> bool {
        self.paused.load(Ordering::Acquire)
    }

    pub fn set_paused(&self, paused: bool) {
        self.paused.store(paused, Ordering::Release);
        if !paused {
            self.resume.notify_waiters();
        }
    }

    /// Park until the global pause is lifted (returns immediately if not
    /// paused). Workers also re-check job-level pause after this.
    pub async fn wait_if_paused(&self) {
        while self.is_paused() {
            self.resume.notified().await;
        }
    }

    /// KiB/s, 0 = unlimited.
    pub fn speed_limit_kbps(&self) -> u64 {
        self.limit_bps.load(Ordering::Relaxed) / 1024
    }

    pub fn set_speed_limit_kbps(&self, kbps: u64) {
        self.limit_bps
            .store(kbps.saturating_mul(1024), Ordering::Relaxed);
    }

    /// Block long enough to keep the average throughput at or below the
    /// configured limit. No-op when unlimited. The sleep duration is computed
    /// under the lock and the lock dropped before awaiting.
    pub async fn throttle(&self, bytes: u64) {
        let rate = self.limit_bps.load(Ordering::Relaxed) as f64;
        if rate <= 0.0 {
            return;
        }
        let sleep_for = {
            let mut b = self.bucket.lock().unwrap();
            let now = Instant::now();
            let elapsed = now.duration_since(b.last).as_secs_f64();
            b.last = now;
            // Refill, allowing at most ~1s of burst.
            b.tokens = (b.tokens + elapsed * rate).min(rate);
            b.tokens -= bytes as f64;
            if b.tokens < 0.0 {
                Duration::from_secs_f64(-b.tokens / rate)
            } else {
                Duration::ZERO
            }
        };
        if sleep_for > Duration::ZERO {
            tokio::time::sleep(sleep_for).await;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn wait_if_paused_unblocks_on_resume() {
        let ctl = std::sync::Arc::new(DownloadControl::new(0));
        ctl.set_paused(true);
        assert!(ctl.is_paused());

        let c2 = ctl.clone();
        let waiter = tokio::spawn(async move { c2.wait_if_paused().await });

        tokio::time::sleep(Duration::from_millis(50)).await;
        assert!(!waiter.is_finished(), "should block while paused");

        ctl.set_paused(false);
        tokio::time::timeout(Duration::from_secs(1), waiter)
            .await
            .expect("did not wake on resume")
            .unwrap();
    }

    #[tokio::test]
    async fn unlimited_speed_is_a_noop() {
        let ctl = DownloadControl::new(0);
        let t = Instant::now();
        ctl.throttle(50 * 1024 * 1024).await;
        assert!(t.elapsed() < Duration::from_millis(50));
    }

    #[tokio::test]
    async fn speed_limit_delays_to_match_rate() {
        // 1 MiB/s. Drain the ~1 MiB burst, then a 256 KiB request must be
        // delayed ~0.25 s to hold the average rate.
        let ctl = DownloadControl::new(1024);
        ctl.throttle(1024 * 1024).await; // consumes the burst allowance
        let t = Instant::now();
        ctl.throttle(256 * 1024).await;
        let waited = t.elapsed();
        assert!(
            waited >= Duration::from_millis(200) && waited < Duration::from_millis(600),
            "expected ~0.25s throttle, got {:?}",
            waited
        );
    }
}
