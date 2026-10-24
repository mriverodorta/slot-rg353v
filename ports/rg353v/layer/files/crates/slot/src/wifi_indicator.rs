//! Deferred RG353V shelf status. Never scans, changes radio settings, or waits on the UI thread.
use std::path::Path;
use std::sync::mpsc::{self, Receiver, TryRecvError};
use std::time::{Duration, Instant};

const REFRESH: Duration = Duration::from_secs(2);

#[derive(Default)]
pub(crate) struct Watcher {
    started: bool,
    active: bool,
    connected: bool,
    discard: bool,
    next: Option<Instant>,
    job: Option<Receiver<bool>>,
}

impl Watcher {
    pub fn start(&mut self) {
        self.started = true;
    }

    pub fn reset(&mut self) {
        self.connected = false;
        self.next = None;
        self.discard = self.job.is_some();
    }

    pub fn poll(&mut self, active: bool) -> bool {
        if !self.started {
            return false;
        }
        if active != self.active {
            self.reset();
            self.active = active;
        }
        let mut completed = None;
        if let Some(rx) = &self.job {
            completed = match rx.try_recv() {
                Ok(value) => Some(value),
                Err(TryRecvError::Disconnected) => Some(false),
                Err(TryRecvError::Empty) => None,
            };
        }
        if let Some(value) = completed {
            self.job = None;
            self.connected = active && !self.discard && value;
            self.next = (!self.discard).then(|| Instant::now() + REFRESH);
            self.discard = false;
        }
        if active && self.job.is_none() && self.next.is_none_or(|due| Instant::now() >= due) {
            let (tx, rx) = mpsc::channel();
            if std::thread::Builder::new()
                .name("slot-wifi-status".into())
                .spawn(move || {
                    let _ = tx.send(connected_at(Path::new("/sys/class/net/wlan0")));
                })
                .is_ok()
            {
                self.job = Some(rx);
            } else {
                self.connected = false;
                self.next = Some(Instant::now() + REFRESH);
            }
        }
        self.connected
    }
}

// This board's RTL8821CS reports carrier only while associated. Requiring
// operational "up" also hides a disabled, unavailable or unassociated radio.
// These tiny sysfs reads stay on the worker; no process, scan or D-Bus call.
fn connected_at(interface: &Path) -> bool {
    std::fs::read_to_string(interface.join("operstate")).is_ok_and(|state| state.trim() == "up")
        && std::fs::read_to_string(interface.join("carrier"))
            .is_ok_and(|carrier| carrier.trim() == "1")
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn first_frame_and_off_shelf_do_not_start_network_work() {
        let mut w = Watcher::default();
        assert!(!w.poll(true));
        assert!(w.job.is_none());
        w.start();
        assert!(!w.poll(false));
        assert!(w.job.is_none());
    }
    #[test]
    fn connection_changes_errors_and_resume_are_not_sticky() {
        let mut w = Watcher {
            started: true,
            active: true,
            ..Default::default()
        };
        let result = |w: &mut Watcher, value| {
            let (tx, rx) = mpsc::channel();
            tx.send(value).unwrap();
            w.job = Some(rx);
        };
        result(&mut w, true);
        assert!(w.poll(true));
        result(&mut w, false);
        assert!(!w.poll(true));
        result(&mut w, true);
        assert!(w.poll(true));
        w.reset();
        assert!(!w.connected);
        // A result sampled before leaving the shelf cannot reappear after wake.
        result(&mut w, true);
        w.discard = true;
        w.poll(true);
        assert!(!w.connected);
        w.poll(false);
        assert!(!w.connected);
    }
    #[test]
    fn only_an_up_associated_radio_is_connected_and_removal_clears_it() {
        let dir = tempfile::tempdir().unwrap();
        for (state, carrier, expected) in [
            ("up", "1", true),
            ("up", "0", false),
            ("down", "0", false),
            ("dormant", "1", false),
            ("unknown", "1", false),
            ("up", "invalid", false),
        ] {
            std::fs::write(dir.path().join("operstate"), state).unwrap();
            std::fs::write(dir.path().join("carrier"), carrier).unwrap();
            assert_eq!(connected_at(dir.path()), expected);
        }
        std::fs::remove_file(dir.path().join("carrier")).unwrap();
        assert!(!connected_at(dir.path()));
        std::fs::remove_file(dir.path().join("operstate")).unwrap();
        assert!(!connected_at(dir.path()));
    }
}
