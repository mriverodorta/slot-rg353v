//! SSH administration with native settings and the shared password keyboard.
use slot_input::Btn;
use std::collections::BTreeMap;
use std::io::Write;
use std::process::{Command, Stdio};
use std::sync::mpsc::{self, Receiver};
use std::time::Instant;

type Fields = BTreeMap<String, String>;
fn parse(text: &str) -> Result<Fields, String> {
    if text.len() > 8192 {
        return Err("SSH response too large".into());
    }
    let values: Fields = text
        .lines()
        .filter_map(|l| l.split_once('\t'))
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect();
    if values.get("protocol").map(String::as_str) != Some("1") {
        return Err("SSH status unavailable".into());
    }
    Ok(values)
}
fn job(args: Vec<String>, secret: Option<String>) -> Receiver<Result<Fields, String>> {
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let result = (|| {
            let path = std::env::var_os("SLOT_CORE_DIR")
                .map(|p| std::path::PathBuf::from(p).join("slot-ssh-ui"))
                .filter(|p| p.is_file())
                .unwrap_or_else(|| "/usr/bin/slot-ssh".into());
            if !path.is_file() {
                return Err("SSH tools unavailable".into());
            }
            let mut child = Command::new("python3")
                .arg(path)
                .args(args)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::null())
                .spawn()
                .map_err(|_| "SSH tools could not start".to_string())?;
            if let Some(secret) = secret {
                child
                    .stdin
                    .take()
                    .ok_or("SSH input unavailable")?
                    .write_all(secret.as_bytes())
                    .map_err(|_| "Password request failed".to_string())?;
            } else {
                drop(child.stdin.take());
            }
            let output = child
                .wait_with_output()
                .map_err(|_| "SSH request ended".to_string())?;
            if !output.status.success() {
                return Err("SSH request failed; check input and retry".into());
            }
            parse(&String::from_utf8_lossy(&output.stdout))
        })();
        let _ = tx.send(result);
    });
    rx
}
#[derive(Clone, PartialEq, Eq)]
enum Page {
    Main,
    Password,
    Preview,
    Confirm,
}
pub struct Menu {
    values: Fields,
    page: Page,
    selected: usize,
    keyboard: slot_ui::Keyboard,
    first: Option<String>,
    message: String,
    job: Option<Receiver<Result<Fields, String>>>,
    changing: bool,
    refreshed: Instant,
    yes: bool,
}
impl Menu {
    pub fn open() -> Self {
        Self {
            values: Fields::new(),
            page: Page::Main,
            selected: 0,
            keyboard: slot_ui::Keyboard::new(64, true),
            first: None,
            message: "Checking SSH...".into(),
            job: Some(job(vec!["status".into()], None)),
            changing: false,
            refreshed: Instant::now(),
            yes: false,
        }
    }
    fn get(&self, k: &str) -> &str {
        self.values.get(k).map(String::as_str).unwrap_or("")
    }
    fn known(&self) -> bool {
        matches!(self.get("enabled"), "0" | "1")
    }
    fn request(&mut self, args: Vec<String>, secret: Option<String>) {
        self.changing = true;
        self.message = "Updating...".into();
        self.job = Some(job(args, secret));
    }
    pub fn poll(&mut self) {
        if let Some(receiver) = &self.job {
            let result = match receiver.try_recv() {
                Ok(r) => r,
                Err(mpsc::TryRecvError::Empty) => return,
                Err(mpsc::TryRecvError::Disconnected) => {
                    Err("SSH request ended; X to retry".into())
                }
            };
            self.job = None;
            self.changing = false;
            self.refreshed = Instant::now();
            match result {
                Ok(fields) => {
                    self.values.extend(fields);
                    self.message.clear();
                    if self.page == Page::Password {
                        self.keyboard.clear();
                        self.first = None;
                        self.page = Page::Main;
                        self.message = "Password saved".into();
                    } else if self.page == Page::Confirm {
                        self.page = Page::Main;
                        self.message = "Public keys imported".into();
                    } else if self.page == Page::Preview && self.get("count") == "0" {
                        self.message = "No .pub files in Config/SSH".into();
                    }
                }
                Err(e) => {
                    self.message = e;
                    if self.page == Page::Password {
                        self.keyboard.clear();
                        self.first = None;
                    }
                    if self.page == Page::Main {
                        self.values.remove("enabled");
                    }
                }
            }
        } else if self.page == Page::Main && self.refreshed.elapsed().as_secs() >= 3 {
            self.job = Some(job(vec!["status".into()], None));
            self.refreshed = Instant::now();
        }
    }
    pub fn button(&mut self, button: Btn) -> bool {
        use Btn::*;
        if self.changing {
            return false;
        }
        if button == B {
            self.keyboard.clear();
            self.first = None;
            if self.page == Page::Main {
                return true;
            }
            self.page = Page::Main;
            self.message.clear();
            return false;
        }
        match self.page {
            Page::Password => {
                use slot_ui::KeyboardAction as K;
                let action = match button {
                    Left => Some(K::Left),
                    Right => Some(K::Right),
                    Up => Some(K::Up),
                    Down => Some(K::Down),
                    A => Some(K::Add),
                    Y => Some(K::Delete),
                    X => Some(K::ToggleVisibility),
                    L1 => Some(K::PreviousSection),
                    R1 => Some(K::NextSection),
                    Start => {
                        self.submit_password();
                        None
                    }
                    _ => None,
                };
                if let Some(action) = action {
                    self.keyboard.apply(action);
                    self.message.clear();
                }
            }
            Page::Preview => {
                if button == A && self.get("count").parse::<usize>().unwrap_or(0) > 0 {
                    self.page = Page::Confirm;
                    self.yes = false;
                } else if button == X && self.job.is_none() {
                    self.job = Some(job(vec!["preview".into()], None));
                    self.message = "Reading public keys...".into();
                }
            }
            Page::Confirm => match button {
                Up | Down | Left | Right => self.yes = !self.yes,
                A if self.yes => self.request(
                    vec![
                        "import".into(),
                        "--expected".into(),
                        self.get("digest").into(),
                    ],
                    None,
                ),
                A => self.page = Page::Main,
                _ => {}
            },
            Page::Main => match button {
                Up => self.selected = (self.selected + 2) % 3,
                Down => self.selected = (self.selected + 1) % 3,
                Left | Right if self.selected == 0 && self.known() && self.job.is_none() => self
                    .request(
                        vec![
                            "set".into(),
                            if self.get("enabled") == "1" {
                                "off"
                            } else {
                                "on"
                            }
                            .into(),
                        ],
                        None,
                    ),
                A if self.selected == 1 => {
                    self.page = Page::Password;
                    self.keyboard.clear();
                    self.first = None;
                    self.message.clear();
                }
                A if self.selected == 2 => {
                    self.page = Page::Preview;
                    self.job = Some(job(vec!["preview".into()], None));
                    self.message = "Reading public keys...".into();
                }
                X if self.job.is_none() => self.job = Some(job(vec!["status".into()], None)),
                _ => {}
            },
        }
        false
    }
    fn submit_password(&mut self) {
        let value = self.keyboard.value().to_string();
        if !(8..=64).contains(&value.len()) {
            self.message = "Use 8 to 64 bytes".into();
            return;
        }
        if let Some(first) = self.first.take() {
            if first != value {
                self.message = "Passwords did not match; try again".into();
                self.keyboard.clear();
                return;
            }
            self.keyboard.clear();
            self.request(vec!["password".into()], Some(value));
        } else {
            self.first = Some(value);
            self.keyboard.clear();
            self.message.clear();
        }
    }
    pub fn keyboard_view(&self) -> Option<slot_ui::KeyboardView> {
        (self.page == Page::Password).then(|| {
            self.keyboard.view(
                if self.first.is_some() {
                    "CONFIRM SSH PASSWORD"
                } else {
                    "SET SSH PASSWORD"
                },
                "ROOT LOGIN · 8 TO 64 BYTES",
                &self.message,
            )
        })
    }
    pub fn labels(&self) -> Vec<String> {
        match self.page {
            Page::Main => vec![
                "SSH".into(),
                "SSH".into(),
                "Status".into(),
                "User".into(),
                "Set Password".into(),
                "Import Public Key".into(),
                self.get("address").into(),
                self.message.clone(),
            ],
            Page::Password => vec![],
            Page::Preview => vec![
                "Import Public Key".into(),
                "Copy .pub files using file sharing".into(),
                "Slot/Config/SSH".into(),
                format!("Keys found: {}", self.get("count")),
                self.get("fingerprint").chars().take(25).collect(),
                self.get("fingerprint").chars().skip(25).collect(),
                self.message.clone(),
            ],
            Page::Confirm => vec![
                "Import Public Keys?".into(),
                format!("{} keys from Config/SSH", self.get("count")),
                "Existing keys will be kept".into(),
                "Cancel".into(),
                "Import".into(),
                self.message.clone(),
            ],
        }
    }
    pub fn values(&self) -> Vec<(usize, String)> {
        if self.page != Page::Main {
            return vec![];
        }
        vec![
            (
                2,
                if self.changing {
                    "Updating..."
                } else {
                    self.get("state")
                }
                .into(),
            ),
            (3, "root".into()),
            (4, self.get("password").into()),
        ]
    }
    pub fn selected_row(&self) -> Option<usize> {
        match self.page {
            Page::Main => Some([1, 4, 5][self.selected]),
            Page::Confirm => Some(if self.yes { 4 } else { 3 }),
            _ => None,
        }
    }
    pub fn toggle_value(&self) -> Option<slot_ui::QuickValue> {
        (self.page == Page::Main && self.known())
            .then(|| slot_ui::QuickValue::flag(self.get("enabled") == "1"))
    }
    pub fn legend(&self) -> Vec<slot_ui::Hint> {
        if self.changing {
            return vec![];
        }
        if self.page == Page::Password {
            return self.keyboard.legend("Save");
        }
        slot_ui::hint_row(match self.page {
            Page::Main if self.selected == 0 => &[("B", "Back"), ("<>", "Change")],
            Page::Main => &[("B", "Back"), ("A", "Open")],
            Page::Preview => &[("B", "Back"), ("X", "Rescan"), ("A", "Review")],
            _ => &[("B", "Back"), ("A", "Select")],
        })
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn password_requires_confirmation_masks_and_clears_on_cancel() {
        let mut m = Menu::open();
        m.job = None;
        m.selected = 1;
        m.button(Btn::A);
        for _ in 0..8 {
            m.button(Btn::A);
        }
        assert!(!m.keyboard_view().unwrap().labels[2].text.contains('a'));
        m.button(Btn::Start);
        assert_eq!(m.first.as_deref(), Some("aaaaaaaa"));
        assert!(m.keyboard.value().is_empty());
        m.button(Btn::X);
        assert!(m.legend().iter().any(|h| h.label == "Hide"));
        m.button(Btn::B);
        assert!(m.first.is_none());
        assert!(m.keyboard.value().is_empty());
    }
    #[test]
    fn short_and_mismatched_passwords_never_spawn_changes() {
        let mut m = Menu::open();
        m.job = None;
        m.page = Page::Password;
        m.submit_password();
        assert!(m.job.is_none());
        m.first = Some("different".into());
        for _ in 0..8 {
            m.keyboard.apply(slot_ui::KeyboardAction::Add);
        }
        m.submit_password();
        assert!(m.job.is_none());
        assert!(m.first.is_none());
    }
    #[test]
    fn import_defaults_to_cancel_and_native_toggle_is_not_an_a_action() {
        let mut m = Menu::open();
        m.job = None;
        m.values.insert("enabled".into(), "1".into());
        m.button(Btn::A);
        assert!(m.job.is_none());
        m.page = Page::Preview;
        m.values.insert("count".into(), "1".into());
        m.button(Btn::A);
        assert!(!m.yes);
        assert_eq!(m.selected_row(), Some(3));
        m.button(Btn::B);
        assert!(m.page == Page::Main);
    }
}
