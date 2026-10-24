//! Explicit network extras; all blocking administration stays off the UI thread.
use slot_input::Btn;
use std::collections::BTreeMap;
use std::process::Command;
use std::sync::mpsc::{self, Receiver};
use std::time::Instant;

type State = (bool, bool);
type Job = Receiver<Result<State, String>>;
fn parse(text: &str) -> Result<State, String> {
    let fields: BTreeMap<_, _> = text.lines().filter_map(|l| l.split_once('\t')).collect();
    if fields.get("protocol") != Some(&"1") {
        return Err("Startup settings unavailable".into());
    }
    let flag = |key| match fields.get(key) {
        Some(&"1") => Ok(true),
        Some(&"0") => Ok(false),
        _ => Err("Startup response incomplete".to_string()),
    };
    Ok((flag("developer")?, flag("time")?))
}
fn job(change: Option<(&'static str, bool)>) -> Job {
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let args = match change {
            Some((name, on)) => vec![name, if on { "on" } else { "off" }],
            None => vec!["status"],
        };
        let result = Command::new("/usr/bin/slot-services")
            .args(args)
            .output()
            .map_err(|_| "Startup tools unavailable".to_string())
            .and_then(|p| {
                if p.status.success() {
                    parse(&String::from_utf8_lossy(&p.stdout))
                } else {
                    Err("Change failed; enable an Internet connection or retry".into())
                }
            });
        let _ = tx.send(result);
    });
    rx
}
pub struct Menu {
    selected: usize,
    state: State,
    known: bool,
    pending: Option<Job>,
    changing: bool,
    refreshed: Instant,
    message: String,
}
impl Menu {
    pub fn open() -> Self {
        Self {
            selected: 0,
            state: (false, false),
            known: false,
            pending: Some(job(None)),
            changing: false,
            refreshed: Instant::now(),
            message: "Checking...".into(),
        }
    }
    pub fn value(&self, feature: &str) -> Option<slot_ui::QuickValue> {
        self.known
            .then_some(slot_ui::QuickValue::flag(if feature == "developer" {
                self.state.0
            } else {
                self.state.1
            }))
    }
    pub fn notice(&self, feature: &str) -> Option<&str> {
        if !self.known {
            return Some("Checking...");
        }
        if self.message.is_empty() || ((feature == "developer") != (self.selected == 0)) {
            return None;
        }
        Some(if self.changing {
            "Updating..."
        } else {
            "Retry"
        })
    }
    pub fn busy(&self) -> bool {
        self.changing
    }
    pub fn toggle(&mut self, feature: &'static str) {
        if !self.known || self.pending.is_some() {
            return;
        }
        let on = if feature == "developer" {
            !self.state.0
        } else {
            !self.state.1
        };
        self.selected = if feature == "developer" { 0 } else { 1 };
        self.pending = Some(job(Some((feature, on))));
        self.changing = true;
        self.message = "Updating...".into();
    }
    pub fn poll(&mut self) {
        if let Some(pending) = &self.pending {
            match pending.try_recv() {
                Ok(result) => {
                    self.pending = None;
                    self.changing = false;
                    self.refreshed = Instant::now();
                    match result {
                        Ok(state) => {
                            self.state = state;
                            self.known = true;
                            self.message.clear();
                        }
                        Err(error) => self.message = error,
                    }
                }
                Err(mpsc::TryRecvError::Disconnected) => {
                    self.pending = None;
                    self.changing = false;
                    self.message = "Request ended; retry".into();
                }
                Err(mpsc::TryRecvError::Empty) => {}
            }
        } else if self.refreshed.elapsed().as_secs() >= 2 {
            self.refreshed = Instant::now();
            self.pending = Some(job(None));
        }
    }
    pub fn button(&mut self, b: Btn) -> bool {
        if b == Btn::B {
            return !self.changing;
        }
        if self.changing {
            return false;
        }
        match b {
            Btn::Up | Btn::Down => self.selected = 1 - self.selected,
            Btn::Left | Btn::Right if self.known => {
                let (feature, on) = if self.selected == 0 {
                    ("developer", !self.state.0)
                } else {
                    ("time", !self.state.1)
                };
                self.pending = Some(job(Some((feature, on))));
                self.changing = true;
                self.message = "Updating...".into();
            }
            _ => {}
        }
        false
    }
    pub fn labels(&self) -> Vec<String> {
        let mut rows = vec![
            "Startup & Services".into(),
            "Developer Mode".into(),
            "Network Time".into(),
            String::new(),
            "Developer Mode is remembered.".into(),
            "Otherwise each boot starts offline.".into(),
        ];
        if !self.message.is_empty() {
            rows.push(self.message.clone());
        }
        rows
    }
    pub fn selected_row(&self) -> Option<usize> {
        self.known.then_some(self.selected + 1)
    }
    pub fn toggle_value(&self) -> Option<slot_ui::QuickValue> {
        self.known
            .then_some(slot_ui::QuickValue::flag(if self.selected == 0 {
                self.state.0
            } else {
                self.state.1
            }))
    }
    pub fn values(&self) -> Vec<(usize, String)> {
        if !self.known {
            return Vec::new();
        }
        let row = if self.selected == 0 { 2 } else { 1 };
        let on = if row == 1 { self.state.0 } else { self.state.1 };
        vec![(row, if on { "On" } else { "Off" }.into())]
    }
    pub fn legend(&self) -> Vec<slot_ui::Hint> {
        slot_ui::hint_row(if self.changing {
            &[]
        } else if self.known {
            &[("B", "Back"), ("<>", "Change")]
        } else {
            &[("B", "Back")]
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn response_requires_both_boolean_fields() {
        assert_eq!(
            parse("protocol\t1\ndeveloper\t1\ntime\t0\n"),
            Ok((true, false))
        );
        assert!(parse("protocol\t1\ndeveloper\t1\n").is_err());
        assert!(parse("protocol\t1\ndeveloper\tmaybe\ntime\t0\n").is_err());
    }
    #[test]
    fn native_controls_keep_selection_and_boolean_value_in_the_same_row() {
        let mut m = Menu {
            selected: 0,
            state: (true, false),
            known: true,
            pending: None,
            changing: false,
            refreshed: Instant::now(),
            message: String::new(),
        };
        assert_eq!(m.selected_row(), Some(1));
        assert_eq!(m.toggle_value(), Some(slot_ui::QuickValue::On));
        assert_eq!(m.values(), vec![(2, "Off".into())]);
        m.button(Btn::Down);
        assert_eq!(m.selected_row(), Some(2));
        assert_eq!(m.toggle_value(), Some(slot_ui::QuickValue::Off));
        assert_eq!(m.values(), vec![(1, "On".into())]);
        assert!(m.button(Btn::B));
    }
}
