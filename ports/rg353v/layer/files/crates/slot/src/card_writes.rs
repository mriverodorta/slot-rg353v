//! A successful unrelated write must never hide an unresolved failure.
use std::{collections::BTreeSet, sync::Mutex};
#[derive(Default)]
pub struct CardWrites {
    failures: Mutex<BTreeSet<String>>,
}
impl CardWrites {
    pub fn wrote<T>(&self, key: &str, result: &std::io::Result<T>) {
        let mut failures = self.failures.lock().unwrap_or_else(|e| e.into_inner());
        if result.is_ok() {
            failures.remove(key);
        } else {
            failures.insert(key.to_owned());
        }
    }
    pub fn failing(&self) -> bool {
        !self
            .failures
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .is_empty()
    }
}
