//! Abstract container runtime — pluggable backend that spawns and
//! manages the per-session "app" workloads.
//!
//! Two implementations live alongside this module:
//!
//! * [`crate::docker`] uses bollard to talk to a local Docker daemon.
//!   This is the developer-laptop and local-host path.
//! * [`crate::k8s_runtime`] uses the kube crate to spawn Kubernetes Pods
//!   in a namespace it has been granted RBAC access to. This is the
//!   production path; Lightrays does not need ambient privileges on the
//!   host because the cluster API enforces the boundary.
//!
//! The trait is intentionally narrow — the abstraction is "spawn a
//! short-lived workload from a server-resolved config and observe its
//! lifecycle." Each backend resolves its own per-workload privileges;
//! the GOW Steam image still needs SYS_ADMIN to bind-mount apps_state
//! inside its own filesystem, but that lives in the runtime config,
//! not in Lightrays' own pod.

use anyhow::Result;
use async_trait::async_trait;

use crate::docker::{ContainerConfig, ContainerSession, ContainerStats};

#[async_trait]
pub trait Runtime: Send + Sync {
    /// Health check — returns `Ok(())` if the backend is reachable.
    async fn ping(&self) -> Result<()>;

    /// Spawn a workload with the given configuration. Returns a name
    /// that subsequent calls can use to refer to it.
    async fn start(&self, config: &ContainerConfig, session: &ContainerSession) -> Result<String>;

    /// Block until the workload exits and return its exit code. Returns
    /// `137` (SIGKILL) when the runtime can't determine an exit code.
    async fn wait_for_exit(&self, name: &str) -> i64;

    /// Append the tail of the workload's logs to the lightrays log
    /// stream. No-op when the runtime exposes log dumps as opt-in only.
    async fn dump_logs(&self, name: &str, tail_lines: usize);

    /// Stop the workload gracefully and clean up.
    async fn stop(&self, name: &str) -> Result<()>;

    /// One-shot resource usage snapshot.
    async fn stats(&self, name: &str) -> Result<ContainerStats>;
}
