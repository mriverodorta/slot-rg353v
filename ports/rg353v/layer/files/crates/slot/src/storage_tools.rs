//! Explicit, optional storage maintenance. No probes before opening this page.
use slot_input::Btn;
use std::{
    collections::BTreeMap,
    process::Command,
    sync::mpsc::{self, Receiver},
    time::Instant,
};
type Reply = Result<BTreeMap<String, String>, String>;
fn job(command: &'static str, token: String) -> Receiver<Reply> {
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let result = (|| {
            let dir = std::env::var_os("SLOT_CORE_DIR")
                .map(std::path::PathBuf::from)
                .ok_or("Available on handheld")?;
            let mut cmd = Command::new("python3");
            cmd.arg(dir.join("slot-storage-tools-ui"))
                .arg(command)
                .current_dir("/");
            if command != "status" {
                cmd.arg(token);
            }
            let output = cmd.output().map_err(|_| "Could not start storage tools")?;
            if output.stdout.len() > 8192 {
                return Err("Storage response too large".into());
            }
            let values: BTreeMap<String, String> = String::from_utf8_lossy(&output.stdout)
                .lines()
                .filter_map(|l| l.split_once('\t'))
                .map(|(k, v)| {
                    (
                        k.into(),
                        v.chars().filter(|c| !c.is_control()).take(512).collect(),
                    )
                })
                .collect();
            if values.get("protocol").map(String::as_str) != Some("1") {
                return Err("Storage tools unavailable".into());
            }
            Ok(values)
        })();
        let _ = tx.send(result);
    });
    rx
}
pub struct Menu {
    targets: Vec<(String, String)>,
    target: usize,
    selected: usize,
    confirm: bool,
    job: Option<Receiver<Reply>>,
    busy: bool,
    started: Instant,
    message: String,
    cwd: Option<std::path::PathBuf>,
}
impl Menu {
    pub fn open() -> Self {
        Self {
            targets: vec![],
            target: 0,
            selected: 0,
            confirm: false,
            job: Some(job("status", String::new())),
            busy: false,
            started: Instant::now(),
            message: "Finding SD games storage...".into(),
            cwd: None,
        }
    }
    pub fn locked(&self) -> bool {
        self.busy
    }
    pub fn poll(&mut self) {
        let result = match self.job.as_ref().map(|rx| rx.try_recv()) {
            Some(Ok(r)) => r,
            Some(Err(mpsc::TryRecvError::Disconnected)) => Err("Storage worker interrupted".into()),
            _ => return,
        };
        self.job = None;
        self.busy = false;
        if let Some(cwd) = self.cwd.take() {
            if std::env::set_current_dir(cwd).is_err() {
                self.message = "Could not restore working folder; restart Slot".into();
                return;
            }
        }
        match result {
            Err(e) => self.message = e,
            Ok(values) => {
                if values.contains_key("count") {
                    self.targets = (0..3)
                        .filter_map(|i| {
                            Some((
                                values.get(&format!("token_{i}"))?.clone(),
                                values.get(&format!("label_{i}"))?.clone(),
                            ))
                        })
                        .collect();
                    self.target = 0;
                    self.message = if self.targets.is_empty() {
                        "No eligible SD games partition".into()
                    } else {
                        "Choose a card, then Check or Repair".into()
                    };
                } else {
                    self.message = values
                        .get("message")
                        .cloned()
                        .unwrap_or_else(|| "Storage result unavailable".into());
                }
            }
        }
    }
    fn begin(&mut self, action: &'static str) {
        if let Some((token, _)) = self.targets.get(self.target) {
            // The launcher may be inside SLOT. Release that directory before unmount.
            if std::env::var_os("SLOT_ROOT").is_some_and(|p| p == "/storage/slotcontent") {
                self.cwd = std::env::current_dir().ok();
                if std::env::set_current_dir("/").is_err() {
                    self.message = "Cannot release content folder".into();
                    return;
                }
            }
            self.busy = true;
            self.started = Instant::now();
            self.message = "Checking storage...".into();
            self.job = Some(job(action, token.clone()));
        }
    }
    pub fn button(&mut self, b: Btn) -> bool {
        if self.busy {
            return false;
        }
        if self.job.is_some() {
            return b == Btn::B;
        }
        if self.confirm {
            match b {
                Btn::B => self.confirm = false,
                Btn::A => {
                    self.confirm = false;
                    self.begin("repair");
                }
                _ => {}
            }
            return false;
        }
        match b {
            Btn::B => return true,
            Btn::Up => self.selected = (self.selected + 2) % 3,
            Btn::Down => self.selected = (self.selected + 1) % 3,
            Btn::Left | Btn::Right if self.selected == 0 && !self.targets.is_empty() => {
                self.target = (self.target + 1) % self.targets.len()
            }
            Btn::A if self.selected == 0 && !self.targets.is_empty() => {
                self.target = (self.target + 1) % self.targets.len()
            }
            Btn::A if self.selected == 1 => self.begin("check"),
            Btn::A if self.selected == 2 && !self.targets.is_empty() => self.confirm = true,
            Btn::X => {
                self.message = "Finding SD games storage...".into();
                self.job = Some(job("status", String::new()));
            }
            _ => {}
        }
        false
    }
    pub fn selected_row(&self) -> Option<usize> {
        if self.busy || self.confirm {
            None
        } else {
            Some(self.selected + 1)
        }
    }
    pub fn legend(&self) -> Vec<slot_ui::Hint> {
        if self.busy {
            vec![]
        } else if self.confirm {
            slot_ui::hint_row(&[("B", "Cancel"), ("A", "Repair")])
        } else {
            slot_ui::hint_row(&[("B", "Back"), ("A", "Select"), ("X", "Refresh")])
        }
    }
    pub fn rows(&self) -> Vec<String> {
        let target = self
            .targets
            .get(self.target)
            .map(|t| t.1.as_str())
            .unwrap_or("No SD games partition");
        if self.confirm {
            return vec![
                "Repair SD Games Storage?".into(),
                target.into(),
                "Repair changes filesystem data.".into(),
                "Back up games and saves first.".into(),
                "Only the selected SD games partition.".into(),
                "System and eMMC stay protected.".into(),
            ];
        }
        let mut rows = vec![
            "Check/Repair Storage".into(),
            target.into(),
            "Check (read only)".into(),
            "Repair...".into(),
        ];
        if self.busy {
            rows.push(format!("Working... {}s", self.started.elapsed().as_secs()));
            rows.push("Keep this device powered on.".into());
        }
        // Wrap the bounded result to fit the native panel.
        let words = self.message.split_whitespace();
        let mut line = String::new();
        for word in words {
            if line.len() + word.len() > 38 && !line.is_empty() {
                rows.push(std::mem::take(&mut line));
            }
            if !line.is_empty() {
                line.push(' ');
            }
            line.push_str(word);
        }
        if !line.is_empty() {
            rows.push(line);
        }
        rows.truncate(8);
        rows
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    fn menu() -> Menu {
        Menu {
            targets: vec![("a".repeat(64), "TF1 games".into())],
            target: 0,
            selected: 2,
            confirm: false,
            job: None,
            busy: false,
            started: Instant::now(),
            message: String::new(),
            cwd: None,
        }
    }
    #[test]
    fn repair_requires_confirmation_and_can_be_cancelled_without_starting_a_job() {
        let mut m = menu();
        assert!(!m.button(Btn::A));
        assert!(m.confirm);
        assert!(!m.locked());
        assert!(m.job.is_none());
        m.button(Btn::B);
        assert!(!m.confirm);
        assert!(m.job.is_none());
        assert!(m.button(Btn::B));
    }
    #[test]
    fn busy_operation_cannot_be_cancelled_or_restarted() {
        let mut m = menu();
        let (_tx, rx) = mpsc::channel();
        m.job = Some(rx);
        m.busy = true;
        for b in [Btn::A, Btn::B, Btn::Up, Btn::X] {
            assert!(!m.button(b));
            assert!(m.locked());
            assert_eq!(m.selected, 2);
        }
        assert!(m.legend().is_empty());
    }
}
