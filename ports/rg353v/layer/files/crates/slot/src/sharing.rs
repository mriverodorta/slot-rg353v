//! File sharing controls. Samba work runs outside the render thread.
use slot_input::Btn;
use std::process::Command;
use std::sync::mpsc::{self, Receiver};
use std::time::Instant;

#[derive(Clone, Debug, PartialEq, Eq)]
struct Status {
    enabled: bool,
    state: String,
    address: String,
    access: String,
}
impl Status {
    fn parse(text: &str) -> Result<Self, String> {
        if text.len() > 4096 {
            return Err("Sharing response too large".into());
        }
        let fields: std::collections::BTreeMap<_, _> = text
            .lines()
            .filter_map(|line| line.split_once('\t'))
            .collect();
        if fields.get("protocol") != Some(&"1")
            || !matches!(fields.get("enabled"), Some(&"0" | &"1"))
        {
            return Err("File sharing unavailable".into());
        }
        let field = |name| -> Result<String, String> {
            fields
                .get(name)
                .map(|s| s.to_string())
                .ok_or_else(|| "Incomplete sharing status".into())
        };
        Ok(Self {
            enabled: fields["enabled"] == "1",
            state: field("state")?,
            address: field("address")?,
            access: field("access")?,
        })
    }
}
fn job(change: Option<bool>) -> Receiver<Result<Status, String>> {
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let result = (|| {
            let path = std::env::var_os("SLOT_CORE_DIR")
                .map(|p| std::path::PathBuf::from(p).join("slot-sharing-ui"))
                .filter(|p| p.is_file())
                .unwrap_or_else(|| "/usr/bin/slot-sharing".into());
            if !path.is_file() {
                return Err("Sharing is available on the handheld".into());
            }
            let args = match change {
                Some(true) => vec!["set", "on"],
                Some(false) => vec!["set", "off"],
                None => vec!["status"],
            };
            let output = Command::new("python3")
                .arg(path)
                .args(args)
                .output()
                .map_err(|_| "Sharing tools could not start".to_string())?;
            if !output.status.success() {
                return Err("Sharing request failed; X to retry".into());
            }
            Status::parse(&String::from_utf8_lossy(&output.stdout))
        })();
        let _ = tx.send(result);
    });
    rx
}

pub struct Menu {
    status: Option<Status>,
    error: Option<String>,
    job: Option<Receiver<Result<Status, String>>>,
    changing: bool,
    refreshed: Instant,
}
impl Menu {
    pub fn open() -> Self {
        Self {
            status: None,
            error: None,
            job: Some(job(None)),
            changing: false,
            refreshed: Instant::now(),
        }
    }
    pub fn poll(&mut self) {
        if let Some(receiver) = &self.job {
            let result = match receiver.try_recv() {
                Ok(result) => result,
                Err(mpsc::TryRecvError::Empty) => return,
                Err(mpsc::TryRecvError::Disconnected) => {
                    Err("Sharing request ended; X to retry".into())
                }
            };
            self.job = None;
            self.changing = false;
            self.refreshed = Instant::now();
            match result {
                Ok(status) => {
                    self.status = Some(status);
                    self.error = None;
                }
                Err(error) => {
                    self.error = Some(error);
                    self.status = None;
                }
            }
        } else if self.error.is_none() && self.refreshed.elapsed().as_secs() >= 2 {
            self.job = Some(job(None));
        }
    }
    pub fn button(&mut self, button: Btn) -> bool {
        if button == Btn::B {
            return true;
        }
        if self.changing {
            return false;
        }
        match button {
            Btn::Left | Btn::Right if self.job.is_none() => {
                if let Some(status) = &self.status {
                    self.job = Some(job(Some(!status.enabled)));
                    self.changing = true;
                }
            }
            Btn::X if self.job.is_none() => {
                self.error = None;
                self.job = Some(job(None));
            }
            _ => {}
        }
        false
    }
    pub fn labels(&self) -> Vec<String> {
        vec![
            "File Sharing".into(),
            "File Sharing".into(),
            "Status".into(),
            "SMB address".into(),
            self.status
                .as_ref()
                .map(|s| s.address.clone())
                .unwrap_or_else(|| "--".into()),
            "Access".into(),
            self.error.clone().unwrap_or_default(),
        ]
    }
    pub fn values(&self) -> Vec<(usize, String)> {
        vec![
            (
                2,
                if self.changing {
                    "Updating...".into()
                } else {
                    self.status
                        .as_ref()
                        .map(|s| s.state.clone())
                        .unwrap_or_else(|| {
                            if self.error.is_some() {
                                "Unavailable".into()
                            } else {
                                "Checking...".into()
                            }
                        })
                },
            ),
            (
                5,
                self.status
                    .as_ref()
                    .map(|s| s.access.clone())
                    .unwrap_or_else(|| "--".into()),
            ),
        ]
    }
    pub fn selected_row(&self) -> Option<usize> {
        self.status.as_ref().map(|_| 1)
    }
    pub fn toggle_value(&self) -> Option<slot_ui::QuickValue> {
        self.status
            .as_ref()
            .map(|s| slot_ui::QuickValue::flag(s.enabled))
    }
    pub fn legend(&self) -> Vec<slot_ui::Hint> {
        slot_ui::hint_row(if self.error.is_some() {
            &[("B", "Back"), ("X", "Retry")]
        } else if self.status.is_some() && !self.changing {
            &[("B", "Back"), ("<>", "Change")]
        } else {
            &[("B", "Back")]
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    const ON: &str =
        "protocol\t1\nenabled\t1\nstate\tRunning\naddress\tsmb://192.0.2.10/Slot\naccess\tGuest\n";
    #[test]
    fn protocol_requires_known_version_and_complete_status() {
        assert!(Status::parse("protocol\t2").is_err());
        assert!(Status::parse("protocol\t1\nenabled\t1").is_err());
        assert!(Status::parse(&ON.replace("enabled\t1", "enabled\tyes")).is_err());
        assert_eq!(Status::parse(ON).unwrap().address, "smb://192.0.2.10/Slot");
    }
    #[test]
    fn native_toggle_and_full_width_smb_address() {
        let mut menu = Menu {
            status: Some(Status::parse(ON).unwrap()),
            error: None,
            job: None,
            changing: false,
            refreshed: Instant::now(),
        };
        assert_eq!(menu.toggle_value(), Some(slot_ui::QuickValue::On));
        assert_eq!(menu.selected_row(), Some(1));
        assert_eq!(menu.labels()[4], "smb://192.0.2.10/Slot");
        assert!(!menu.values().iter().any(|(row, _)| *row == 4));
        menu.button(Btn::A);
        assert!(menu.job.is_none(), "A must not toggle a native setting");
        assert!(menu.button(Btn::B));
    }
    #[test]
    fn failed_change_discards_stale_enabled_state() {
        let (tx, rx) = mpsc::channel();
        tx.send(Err("Failed".into())).unwrap();
        let mut menu = Menu {
            status: Some(Status::parse(ON).unwrap()),
            error: None,
            job: Some(rx),
            changing: true,
            refreshed: Instant::now(),
        };
        menu.poll();
        assert_eq!(menu.toggle_value(), None);
        assert!(menu.error.is_some());
        assert!(!menu.changing);
        assert!(menu.legend().iter().any(|h| h.key == "X"));
    }
}
