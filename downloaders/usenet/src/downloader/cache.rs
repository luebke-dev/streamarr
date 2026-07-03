//! Global decoded-byte cache budget.
//!
//! Mirrors SABnzbd's article cache (`articlecache.py`): instead of letting
//! every file buffer all of its segments in RAM (the old
//! `BTreeMap<u32, Vec<u8>>` model that used ~7 GB on large releases), each
//! in-flight batch reserves its byte size before being fetched and releases
//! it once the decoded data has been written to disk. When the writer lags
//! behind the network, fetch tasks block on `reserve()` — natural
//! backpressure that bounds total RAM regardless of release size or how
//! many files/jobs run concurrently.

use std::sync::Arc;
use tokio::sync::{OwnedSemaphorePermit, Semaphore};

/// Permits are counted in KiB so the budget stays well within the `u32`
/// range `acquire_many` requires (500 MB ≈ 512 000 permits).
const UNIT_BYTES: usize = 1024;

#[derive(Clone)]
pub struct ArticleCache {
    sem: Arc<Semaphore>,
    capacity_kib: usize,
}

/// Held for the lifetime of the buffered data; dropping it returns the
/// budget so blocked fetchers can proceed.
pub struct CacheReservation {
    _permit: OwnedSemaphorePermit,
}

impl ArticleCache {
    pub fn new(capacity_bytes: usize) -> Self {
        let capacity_kib = (capacity_bytes / UNIT_BYTES)
            .max(1)
            // Semaphore::MAX_PERMITS is far higher, but acquire_many takes a
            // u32 so keep the ceiling there.
            .min(u32::MAX as usize);
        Self {
            sem: Arc::new(Semaphore::new(capacity_kib)),
            capacity_kib,
        }
    }

    /// Reserve `bytes` of cache budget, awaiting until space is available.
    /// A request larger than the whole budget is clamped to full capacity so
    /// an oversized batch still makes progress (one at a time) instead of
    /// deadlocking.
    pub async fn reserve(&self, bytes: usize) -> CacheReservation {
        let want = bytes.div_ceil(UNIT_BYTES).clamp(1, self.capacity_kib) as u32;
        let permit = self
            .sem
            .clone()
            .acquire_many_owned(want)
            .await
            .expect("article cache semaphore closed");
        CacheReservation { _permit: permit }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[tokio::test]
    async fn reservation_blocks_until_budget_is_freed() {
        // 1 MiB budget. Take the whole thing, then a second full-budget
        // reservation must wait until the first is dropped.
        let cache = ArticleCache::new(1024 * 1024);
        let first = cache.reserve(1024 * 1024).await;

        let cache2 = cache.clone();
        let waiter =
            tokio::spawn(async move { cache2.reserve(1024 * 1024).await });

        // Still blocked while `first` is held.
        tokio::time::sleep(Duration::from_millis(50)).await;
        assert!(!waiter.is_finished(), "second reserve should block while budget is held");

        drop(first);
        // Now it can proceed.
        tokio::time::timeout(Duration::from_secs(1), waiter)
            .await
            .expect("reserve did not unblock after budget freed")
            .expect("waiter task panicked");
    }

    #[tokio::test]
    async fn oversized_request_is_clamped_and_does_not_deadlock() {
        // Asking for more than the whole budget must still succeed (clamped
        // to capacity) rather than block forever.
        let cache = ArticleCache::new(64 * 1024);
        let _r = tokio::time::timeout(
            Duration::from_secs(1),
            cache.reserve(10 * 1024 * 1024),
        )
        .await
        .expect("oversized reserve deadlocked instead of clamping");
    }
}
