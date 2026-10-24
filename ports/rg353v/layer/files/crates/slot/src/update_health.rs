use std::path::PathBuf;
use std::time::{Duration, Instant};

/// A bounded startup heartbeat, enabled only for an updater trial.
pub struct Heartbeat {
    path: Option<PathBuf>,
    started: Instant,
    last: Option<Instant>,
}

impl Heartbeat {
    pub fn from_env() -> Self {
        Self {
            path: std::env::var_os("SLOT_UPDATE_READY").map(PathBuf::from),
            started: Instant::now(),
            last: None,
        }
    }

    pub fn needs_frame(&self) -> bool {
        self.path.is_some()
            && self.started.elapsed() <= Duration::from_secs(45)
            && self
                .last
                .is_none_or(|last| last.elapsed() >= Duration::from_secs(1))
    }

    pub fn frame(&mut self) {
        let Some(path) = self.path.as_ref() else {
            return;
        };
        let now = Instant::now();
        if now.duration_since(self.started) > Duration::from_secs(45) {
            self.path = None;
            return;
        }
        if self
            .last
            .is_some_and(|last| now.duration_since(last) < Duration::from_secs(1))
        {
            return;
        }
        // Written only after a successful display swap; no permanent storage I/O.
        if std::fs::write(path, b"frame\n").is_ok() {
            self.last = Some(now);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn a_stable_shelf_still_proves_trial_liveness_at_one_second_intervals() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("ready");
        let mut h = Heartbeat {
            path: Some(path.clone()),
            started: Instant::now(),
            last: None,
        };
        assert!(h.needs_frame());
        h.frame();
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "frame\n");
        assert!(!h.needs_frame());
        h.last = Some(Instant::now() - Duration::from_secs(2));
        assert!(h.needs_frame());
        h.started = Instant::now() - Duration::from_secs(46);
        assert!(!h.needs_frame());
        h.path = None;
        assert!(!h.needs_frame());
    }
}
