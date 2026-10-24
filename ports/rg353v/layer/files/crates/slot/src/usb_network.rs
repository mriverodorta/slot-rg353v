//! Opt-in USB Ethernet and computer-provided Internet. Blocking work runs only while this page is open.
use slot_input::Btn;
use std::collections::BTreeMap;
use std::process::Command;
use std::sync::mpsc::{self, Receiver};
use std::time::Instant;
type Fields = BTreeMap<String, String>;
fn parse(text: &str) -> Result<Fields, String> {
    if text.len() > 4096 {
        return Err("USB status too large".into());
    }
    let fields: Fields = text
        .lines()
        .filter_map(|l| l.split_once('\t'))
        .map(|(k, v)| (k.into(), v.into()))
        .collect();
    if !matches!(fields.get("protocol").map(String::as_str), Some("1" | "2"))
        || !matches!(fields.get("enabled").map(String::as_str), Some("0" | "1"))
    {
        return Err("USB network status unavailable".into());
    }
    if fields.get("protocol").map(String::as_str) == Some("2") {
        for key in ["legacy", "internet"] {
            if !matches!(fields.get(key).map(String::as_str), Some("0" | "1")) {
                return Err("USB network settings incomplete".into());
            }
        }
    }
    Ok(fields)
}
fn job(change: Option<(&'static str, bool)>) -> Receiver<Result<Fields, String>> {
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let args = match change {
            Some(("enabled", true)) => vec!["on"],
            Some(("enabled", false)) => vec!["off"],
            Some((name, on)) => vec![name, if on { "on" } else { "off" }],
            None => vec!["status"],
        };
        let result = Command::new("/usr/bin/slot-usb-network")
            .args(args)
            .output()
            .map_err(|_| "USB networking tools unavailable".to_string())
            .and_then(|p| {
                if p.status.success() {
                    parse(&String::from_utf8_lossy(&p.stdout))
                } else {
                    Err("Change failed; finish USB storage or retry".into())
                }
            });
        let _ = tx.send(result);
    });
    rx
}
pub struct Menu {
    fields: Fields,
    selected: usize,
    pending: Option<Receiver<Result<Fields, String>>>,
    changing: bool,
    refreshed: Instant,
    message: String,
}
impl Menu {
    pub fn open() -> Self {
        Self {
            fields: Fields::new(),
            selected: 1,
            pending: Some(job(None)),
            changing: false,
            refreshed: Instant::now(),
            message: "Checking...".into(),
        }
    }
    fn enabled(&self) -> Option<bool> {
        match self.fields.get("enabled").map(String::as_str) {
            Some("1") => Some(true),
            Some("0") => Some(false),
            _ => None,
        }
    }
    fn get(&self, name: &str) -> &str {
        self.fields.get(name).map(String::as_str).unwrap_or("--")
    }
    pub fn poll(&mut self) {
        if let Some(pending) = &self.pending {
            let result = match pending.try_recv() {
                Ok(result) => result,
                Err(mpsc::TryRecvError::Empty) => return,
                Err(mpsc::TryRecvError::Disconnected) => Err("Request ended; retry".into()),
            };
            self.pending = None;
            self.changing = false;
            self.refreshed = Instant::now();
            match result {
                Ok(fields) => {
                    self.fields = fields;
                    self.message.clear();
                }
                Err(message) => {
                    self.message = message;
                    self.fields.clear();
                }
            }
        } else if self.refreshed.elapsed().as_secs() >= 3 {
            self.pending = Some(job(None));
            self.refreshed = Instant::now();
        }
    }
    pub fn button(&mut self, button: Btn) -> bool {
        if self.changing {
            return false;
        }
        if button == Btn::B {
            return true;
        }
        match button {
            Btn::Up => {
                self.selected = if self.selected == 1 {
                    3
                } else {
                    self.selected - 1
                }
            }
            Btn::Down => {
                self.selected = if self.selected == 3 {
                    1
                } else {
                    self.selected + 1
                }
            }
            Btn::Left | Btn::Right if self.enabled().is_some() && self.pending.is_none() => {
                let name = ["enabled", "legacy", "internet"][self.selected - 1];
                // An older helper only supports the existing On/Off control.
                if self.selected > 1 && self.get("protocol") != "2" {
                    self.message = "New USB tools required".into();
                    return false;
                }
                let on = !self.flag(name);
                self.pending = Some(job(Some((name, on))));
                self.changing = true;
                self.message = "Reconnecting USB...".into();
            }
            Btn::X if self.pending.is_none() => {
                self.pending = Some(job(None));
                self.message = "Checking...".into();
            }
            _ => {}
        }
        false
    }
    fn flag(&self, name: &str) -> bool {
        if name == "legacy" && self.get("protocol") == "1" {
            return true;
        }
        self.get(name) == "1"
    }
    pub fn labels(&self) -> Vec<String> {
        vec![
            "USB Networking".into(),
            "USB Networking".into(),
            "Legacy USB Mode".into(),
            "Internet via USB".into(),
            "Status".into(),
            "IP Address".into(),
            if !self.message.is_empty() {
                self.message.clone()
            } else if self.enabled() == Some(false) {
                "Use the DC USB-C data port".into()
            } else if self.get("ssh") != "--" {
                self.get("ssh").into()
            } else {
                "Enable sharing on your computer".into()
            },
        ]
    }
    pub fn values(&self) -> Vec<(usize, String)> {
        if self.enabled().is_none() {
            return Vec::new();
        }
        let mut values = vec![
            (4, self.get("state").into()),
            (5, self.get("address").into()),
        ];
        for (i, key) in ["enabled", "legacy", "internet"].iter().enumerate() {
            if self.selected_row() != Some(i + 1) {
                values.push((i + 1, if self.flag(key) { "On" } else { "Off" }.into()));
            }
        }
        values
    }
    pub fn selected_row(&self) -> Option<usize> {
        self.enabled()
            .filter(|_| !self.changing)
            .map(|_| self.selected)
    }
    pub fn toggle_value(&self) -> Option<slot_ui::QuickValue> {
        self.enabled().map(|_| {
            slot_ui::QuickValue::flag(
                self.flag(["enabled", "legacy", "internet"][self.selected - 1]),
            )
        })
    }
    pub fn legend(&self) -> Vec<slot_ui::Hint> {
        slot_ui::hint_row(if self.changing {
            &[]
        } else if self.enabled().is_some() {
            &[("B", "Back"), ("<>", "Change")]
        } else {
            &[("B", "Back"), ("X", "Retry")]
        })
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn requires_version_and_boolean_flag() {
        assert!(parse("protocol\t1\nenabled\t1\n").is_ok());
        for text in [
            "enabled\t1\n",
            "protocol\t1\nenabled\tmaybe\n",
            "protocol\t1\n",
        ] {
            assert!(parse(text).is_err());
        }
    }
    #[test]
    fn status_and_native_toggle_use_fixed_rows() {
        let fields = parse("protocol\t1\nenabled\t1\nstate\tConnected\naddress\t172.31.53.1\nssh\tssh root@172.31.53.1\n").unwrap();
        let mut menu = Menu {
            fields,
            selected: 1,
            pending: None,
            changing: false,
            refreshed: Instant::now(),
            message: String::new(),
        };
        assert_eq!(menu.toggle_value(), Some(slot_ui::QuickValue::On));
        assert_eq!(menu.selected_row(), Some(1));
        assert_eq!(
            menu.values(),
            vec![
                (4, "Connected".into()),
                (5, "172.31.53.1".into()),
                (2, "On".into()),
                (3, "Off".into())
            ]
        );
        assert_eq!(menu.labels()[6], "ssh root@172.31.53.1");
        assert!(menu.labels().len() <= 7);
        assert!(menu.button(Btn::B));
        menu.changing = true;
        assert!(!menu.button(Btn::B));
        assert_eq!(menu.selected_row(), None);
    }
    #[test]
    fn internet_and_legacy_controls_follow_selection_without_losing_status() {
        let fields = parse("protocol\t2\nenabled\t1\nlegacy\t0\ninternet\t1\nstate\tShared network ready\naddress\t192.168.137.2\nssh\tssh root@192.168.137.2\n").unwrap();
        let mut menu = Menu {
            fields,
            selected: 1,
            pending: None,
            changing: false,
            refreshed: Instant::now(),
            message: String::new(),
        };
        menu.button(Btn::Down);
        assert_eq!(menu.selected_row(), Some(2));
        assert_eq!(menu.toggle_value(), Some(slot_ui::QuickValue::Off));
        assert!(!menu.values().iter().any(|(row, _)| *row == 2));
        menu.button(Btn::Down);
        assert_eq!(menu.selected_row(), Some(3));
        assert_eq!(menu.toggle_value(), Some(slot_ui::QuickValue::On));
        assert_eq!(menu.labels().len(), 7);
        menu.button(Btn::Down);
        assert_eq!(menu.selected_row(), Some(1));
        menu.button(Btn::Up);
        assert_eq!(menu.selected_row(), Some(3));
        assert!(parse("protocol\t2\nenabled\t1\nlegacy\t0\n").is_err());
    }
}
