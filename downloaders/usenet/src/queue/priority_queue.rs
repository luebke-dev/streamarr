use crate::models::job::QueueEntry;
use std::collections::BinaryHeap;
use tokio::sync::Notify;
use uuid::Uuid;

pub struct PriorityQueue {
    heap: std::sync::Mutex<BinaryHeap<QueueEntry>>,
    notify: Notify,
}

impl PriorityQueue {
    pub fn new() -> Self {
        Self {
            heap: std::sync::Mutex::new(BinaryHeap::new()),
            notify: Notify::new(),
        }
    }

    pub fn push(&self, entry: QueueEntry) {
        {
            let mut heap = self.heap.lock().unwrap();
            heap.push(entry);
        }
        self.notify.notify_one();
    }

    pub fn pop(&self) -> Option<QueueEntry> {
        let mut heap = self.heap.lock().unwrap();
        heap.pop()
    }

    /// Wait until an item is available, then pop it.
    pub async fn pop_wait(&self) -> QueueEntry {
        loop {
            if let Some(entry) = self.pop() {
                return entry;
            }
            self.notify.notified().await;
        }
    }

    pub fn remove(&self, job_id: &Uuid) -> bool {
        let mut heap = self.heap.lock().unwrap();
        let before = heap.len();
        let items: Vec<QueueEntry> = heap.drain().filter(|e| e.job_id != *job_id).collect();
        let removed = before != items.len();
        *heap = BinaryHeap::from(items);
        removed
    }

    pub fn len(&self) -> usize {
        self.heap.lock().unwrap().len()
    }
}
