//! Failure-only context. Healthy saves perform no extra filesystem operations.
use std::{
    io,
    path::Path,
    sync::{Mutex, OnceLock},
    time::{SystemTime, UNIX_EPOCH},
};
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StorageFault {
    pub path: String,
    pub operation: String,
    pub errno: Option<i32>,
    pub reason: String,
    pub timestamp: u64,
}
static RECENT: OnceLock<Mutex<Vec<StorageFault>>> = OnceLock::new();
pub fn storage_faults() -> Vec<StorageFault> {
    RECENT
        .get_or_init(Default::default)
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .clone()
}
fn clean(value: &str, limit: usize) -> String {
    value
        .chars()
        .map(|c| if c.is_control() { ' ' } else { c })
        .take(limit)
        .collect()
}
pub fn record(path: &Path, operation: &str, error: &io::Error) {
    let fault = StorageFault {
        path: clean(&path.to_string_lossy(), 512),
        operation: operation.into(),
        errno: error.raw_os_error(),
        reason: clean(&error.to_string(), 256),
        timestamp: SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs(),
    };
    eprintln!(
        "slot: storage: {}: {}: {} (errno {:?})",
        fault.operation, fault.path, fault.reason, fault.errno
    );
    {
        let mut recent = RECENT
            .get_or_init(Default::default)
            .lock()
            .unwrap_or_else(|e| e.into_inner());
        if recent.len() == 12 {
            recent.remove(0);
        }
        recent.push(fault.clone());
    }
    // RAM only, never recurse through atomic_write on the failing media.
    if cfg!(target_os = "linux")
        && (path.starts_with("/storage") || path.starts_with("/run/slot-sd-library"))
    {
        let _=std::fs::write("/run/slot-storage-error",format!("fault_path\t{}\nfault_operation\t{}\nfault_errno\t{}\nfault_reason\t{}\nfault_time\t{}\n",fault.path,fault.operation,fault.errno.map(|n|n.to_string()).unwrap_or_else(||"Unknown".into()),fault.reason,fault.timestamp));
    }
}
