//! Updates menu. All helper processes run off the render thread.
use slot_input::Btn;
use std::collections::BTreeMap;
use std::process::Command;
use std::sync::mpsc::{self, Receiver};
use std::time::{Duration, Instant};

#[derive(Clone, Default, Debug)]
pub struct Snapshot(BTreeMap<String, String>);
impl Snapshot {
    pub fn parse(text: &str) -> Result<Self, String> {
        if text.len() > 16 * 1024 {
            return Err("Update response too large".into());
        }
        let values: BTreeMap<_, _> = text
            .lines()
            .filter_map(|line| line.split_once('\t'))
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect();
        if values.get("protocol").map(String::as_str) != Some("1") {
            return Err("Updater unavailable on this system".into());
        }
        Ok(Self(values))
    }
    fn get(&self, key: &str) -> &str {
        self.0.get(key).map(String::as_str).unwrap_or("")
    }
    fn yes(&self, key: &str) -> bool {
        self.get(key) == "1"
    }
    fn can_install(&self) -> bool {
        self.yes("downloaded") && !self.yes("installed") && !self.yes("retained")
    }
    fn message(&self) -> String {
        if self.yes("cancel_requested") {
            return "Stopping after the current step...".into();
        }
        if self.yes("busy") && !self.yes("session") {
            match self.get("operation") {
                "check" => return "Checking for updates...".into(),
                "apply" if !matches!(self.get("event"), "installing" | "rebooting") => {
                    return "Verifying update; keep power connected".into()
                }
                "rollback-slot" | "rollback-os" => return "Restoring previous version...".into(),
                _ => {}
            }
        }
        match self.get("event") {
            "available" if self.yes("installed") => "Already up to date".into(),
            "available" if self.yes("retained") => "Release retained; use Roll back".into(),
            "available" => "Update available".into(),
            "up-to-date" => "Up to date".into(),
            "no-path" => "No supported update path".into(),
            "waiting-network" => format!("Waiting for internet... {}s / 120s", self.get("seconds")),
            "paused-network" => "Reconnect, then select Resume".into(),
            "waiting-health" => "Checking startup health...".into(),
            "resume-needed" => "Resume the unfinished updates".into(),
            "cancelled" => "Updates stopped".into(),
            "paused" => short(self.get("reason"), 64),
            "downloading" | "download-retry" => {
                let bytes = self.get("bytes").parse::<u64>().unwrap_or(0);
                let size = self.get("size").parse::<u64>().unwrap_or(0);
                format!(
                    "Downloading: {}%",
                    bytes
                        .saturating_mul(100)
                        .checked_div(size)
                        .unwrap_or(0)
                        .min(100)
                )
            }
            "downloaded" => "Download verified; ready to install".into(),
            "installing" => "Installing; keep power connected".into(),
            "rebooting" => "Restarting...".into(),
            "installed" => "Update installed".into(),
            "trial-started" => "Checking update startup...".into(),
            "rolled-back" => "Update rolled back; stopped".into(),
            "failed" => {
                let reason = self.get("reason");
                if reason.contains("urlopen")
                    || reason.contains("timed out")
                    || reason.contains("Connection")
                {
                    "Server unavailable; check Wi-Fi".into()
                } else {
                    short(reason, 64)
                }
            }
            _ => "Check for a signed update".into(),
        }
    }
}
fn short(value: &str, limit: usize) -> String {
    let mut result: String = value.chars().take(limit).collect();
    if value.chars().count() > limit {
        result.push_str("...");
    }
    result
}
fn lines(value: &str) -> Vec<String> {
    let mut result = vec![String::new()];
    for word in value.split_whitespace() {
        if result.last().unwrap().chars().count() + word.chars().count() + 1 > 48 {
            result.push(String::new());
        }
        let row = result.last_mut().unwrap();
        if !row.is_empty() {
            row.push(' ');
        }
        row.push_str(&short(word, 48));
    }
    result
}
fn helper(args: &[String]) -> Result<String, String> {
    let bundled =
        std::env::var_os("SLOT_CORE_DIR").map(|p| std::path::PathBuf::from(p).join("slot-ota-ui"));
    let path = bundled
        .filter(|p| p.is_file())
        .unwrap_or_else(|| "/usr/bin/slot-ota".into());
    if !path.is_file() {
        return Err("Updater is available on the handheld".into());
    }
    let output = Command::new("python3")
        .arg(path)
        .args(args)
        .output()
        .map_err(|_| "Updater could not start".to_string())?;
    if !output.status.success() {
        return Err("Update request failed; check Wi-Fi and retry".into());
    }
    Ok(String::from_utf8_lossy(&output.stdout).into_owned())
}
fn job(operation: Option<(String, String)>) -> Receiver<Result<Snapshot, String>> {
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let result = (|| {
            if let Some((operation, expected)) = operation {
                helper(&["request".into(), operation, "--expected".into(), expected])?;
            }
            Snapshot::parse(&helper(&["ui".into()])?)
        })();
        let _ = tx.send(result);
    });
    rx
}
#[derive(PartialEq)]
enum Page {
    Main,
    Notes,
    Rollback,
    Confirm(String, String),
}
pub struct Menu {
    view: Snapshot,
    selected: usize,
    page: Page,
    yes: bool,
    note: usize,
    error: Option<String>,
    job: Option<Receiver<Result<Snapshot, String>>>,
    refreshed: Instant,
    requesting: Option<String>,
}
impl Menu {
    pub fn open() -> Self {
        Self::initial(None)
    }
    fn initial(operation: Option<&str>) -> Self {
        Self {
            view: Snapshot::default(),
            selected: 0,
            page: Page::Main,
            yes: false,
            note: 0,
            error: None,
            job: Some(job(operation.map(|s| (s.to_string(), String::new())))),
            refreshed: Instant::now(),
            requesting: operation.map(str::to_string),
        }
    }
    pub fn resume() -> Self {
        Self::initial(Some("resume"))
    }
    pub fn locked(&self) -> bool {
        if self.view.yes("session") && self.view.yes("busy") {
            return true;
        }
        self.requesting
            .as_deref()
            .is_some_and(|s| matches!(s, "apply" | "resume") || s.starts_with("rollback"))
            || (self.view.yes("busy")
                && matches!(
                    self.view.get("operation"),
                    "apply" | "resume" | "rollback-slot" | "rollback-os"
                ))
    }
    pub fn poll(&mut self) {
        if let Some(rx) = &self.job {
            match rx.try_recv() {
                Ok(result) => {
                    self.job = None;
                    self.requesting = None;
                    match result {
                        Ok(view) => {
                            if view.yes("session")
                                && (!self.view.yes("session")
                                    || self.view.yes("busy") != view.yes("busy"))
                            {
                                self.selected =
                                    if view.yes("busy") || view.get("session_phase") == "failed" {
                                        3
                                    } else {
                                        2
                                    };
                            } else if self.view.yes("session") && !view.yes("session") {
                                self.selected = 0;
                            }
                            self.view = view;
                            self.error = None;
                        }
                        Err(error) => self.error = Some(error),
                    }
                    self.refreshed = Instant::now();
                }
                Err(mpsc::TryRecvError::Empty) => {}
                Err(mpsc::TryRecvError::Disconnected) => {
                    self.job = None;
                    self.requesting = None;
                    self.error = Some("Updater stopped; try again".into());
                }
            }
        } else if self.refreshed.elapsed()
            >= Duration::from_millis(if self.view.yes("busy") { 750 } else { 2000 })
        {
            self.job = Some(job(None));
        }
    }
    fn request(&mut self, operation: &str, expected: String) {
        self.requesting = Some(operation.into());
        self.job = Some(job(Some((operation.into(), expected))));
        self.error = None;
        self.page = Page::Main;
    }
    fn confirm(&mut self, operation: &str, expected: String) {
        self.page = Page::Confirm(operation.into(), expected);
        self.yes = false;
    }
    pub fn button(&mut self, button: Btn) -> bool {
        use Btn::*;
        if let Page::Confirm(operation, expected) = &self.page {
            let (operation, expected) = (operation.clone(), expected.clone());
            match button {
                B => self.page = Page::Main,
                Up | Down | Left | Right => self.yes = !self.yes,
                A if self.yes => self.request(&operation, expected),
                A => self.page = Page::Main,
                _ => {}
            }
            return false;
        }
        if self.view.yes("session") {
            if self.page == Page::Notes {
                match button {
                    B => self.page = Page::Main,
                    Up => self.note = self.note.saturating_sub(1),
                    Down => {
                        self.note = (self.note + 1)
                            .min(lines(self.view.get("notes")).len().saturating_sub(5))
                    }
                    _ => {}
                }
            } else {
                match button {
                    Up | Down => {
                        self.selected = if self.view.yes("busy") || self.selected == 2 {
                            3
                        } else {
                            2
                        }
                    }
                    X => {
                        self.page = Page::Notes;
                        self.note = 0;
                    }
                    B => self.confirm("cancel", String::new()),
                    A if self.selected == 3 => self.confirm("cancel", String::new()),
                    A if self.selected == 2 && !self.view.yes("busy") => {
                        if self.view.get("session_phase") == "failed" {
                            self.error = Some("Cancel the stopped session before retrying".into());
                        } else {
                            self.confirm("resume", String::new());
                        }
                    }
                    _ => {}
                }
            }
            return false;
        }
        if button == B {
            if self.locked() {
                return false;
            }
            if self.page == Page::Main {
                return true;
            }
            self.page = Page::Main;
            return false;
        }
        if self.requesting.is_some() || self.view.yes("busy") {
            return false;
        }
        match &self.page {
            Page::Main => match button {
                Up => self.selected = (self.selected + 3) % 4,
                Down => self.selected = (self.selected + 1) % 4,
                X => {
                    self.page = Page::Notes;
                    self.note = 0;
                }
                A => match self.selected {
                    0 => self.request("check", String::new()),
                    1 if !self.view.get("available").is_empty() && !self.view.yes("installed") => {
                        self.request("download", self.view.get("available").to_string());
                    }
                    2 if self.view.can_install() => {
                        self.confirm("apply", self.view.get("available").to_string());
                    }
                    3 => {
                        self.page = Page::Rollback;
                        self.selected = 0;
                    }
                    _ => self.error = Some("Check and download an update first".into()),
                },
                _ => {}
            },
            Page::Notes => match button {
                Up => self.note = self.note.saturating_sub(1),
                Down => {
                    self.note =
                        (self.note + 1).min(lines(self.view.get("notes")).len().saturating_sub(5))
                }
                _ => {}
            },
            Page::Rollback => match button {
                Up | Down => self.selected = 1 - self.selected,
                A => {
                    let (operation, target, expected) = if self.selected == 0 {
                        (
                            "rollback-slot",
                            self.view.get("rollback_slot"),
                            self.view.get("slot"),
                        )
                    } else {
                        (
                            "rollback-os",
                            self.view.get("rollback_os"),
                            self.view.get("os"),
                        )
                    };
                    if !target.is_empty() {
                        self.confirm(operation, expected.to_string());
                    } else {
                        self.error = Some("No compatible previous version".into());
                    }
                }
                _ => {}
            },
            Page::Confirm(operation, expected) => match button {
                Up | Down | Left | Right => self.yes = !self.yes,
                A if self.yes => self.request(&operation.clone(), expected.clone()),
                A => self.page = Page::Main,
                _ => {}
            },
        }
        false
    }
    pub fn progress(&self) -> Option<f32> {
        if !matches!(self.view.get("event"), "downloading" | "download-retry") {
            return None;
        }
        let size = self.view.get("size").parse::<f32>().ok()?;
        (size > 0.0)
            .then(|| (self.view.get("bytes").parse::<f32>().unwrap_or(0.0) / size).clamp(0.0, 1.0))
    }
    pub fn selected_row(&self) -> Option<usize> {
        match self.page {
            Page::Main => Some(self.selected + 4),
            Page::Notes => None,
            Page::Rollback => Some(self.selected + 1),
            Page::Confirm(_, _) => Some(if self.yes { 5 } else { 4 }),
        }
    }
    pub fn legend(&self) -> Vec<slot_ui::Hint> {
        let entries: &[(&str, &str)] = if matches!(self.page, Page::Confirm(_, _)) {
            &[("B", "Cancel"), ("A", "Select")]
        } else if self.view.yes("session") {
            &[("B", "Stop updates"), ("X", "Notes"), ("A", "Select")]
        } else if self.locked() {
            &[]
        } else if self.requesting.is_some() || self.view.yes("busy") {
            &[("B", "Back")]
        } else {
            match self.page {
                Page::Main => &[("B", "Back"), ("X", "Notes"), ("A", "Select")],
                Page::Notes => &[("B", "Back"), ("D-pad", "Scroll")],
                Page::Rollback => &[("B", "Back"), ("A", "Select")],
                Page::Confirm(_, _) => &[("B", "Cancel"), ("A", "Select")],
            }
        };
        slot_ui::hint_row(entries)
    }
    pub fn rows(&self) -> (Vec<String>, Option<usize>) {
        let message = self.error.clone().unwrap_or_else(|| self.view.message());
        match &self.page {
            Page::Main => (
                vec![
                    "Updates".into(),
                    format!("Slot: {}", short(self.view.get("slot"), 40)),
                    format!("System: {}", short(self.view.get("os"), 40)),
                    if self.view.yes("session") {
                        format!(
                            "Updates completed: {}",
                            self.view.get("steps").parse::<u32>().unwrap_or(0)
                        )
                    } else {
                        format!(
                            "Available: {}",
                            if self.view.get("available").is_empty() {
                                "--".into()
                            } else {
                                short(self.view.get("available"), 40)
                            }
                        )
                    },
                    if self.view.yes("session") {
                        if self.view.yes("busy") {
                            "Automatic updates active".into()
                        } else {
                            "Update session paused".into()
                        }
                    } else {
                        "Check for updates".into()
                    },
                    if self.view.yes("session") {
                        "Restarts continue automatically".into()
                    } else if self.view.yes("downloaded") {
                        "Download (verified)".into()
                    } else {
                        "Download".into()
                    },
                    if self.view.yes("session") {
                        "Resume updates".into()
                    } else {
                        "Install all updates".into()
                    },
                    if self.view.yes("session") {
                        "Stop updates...".into()
                    } else {
                        "Roll back...".into()
                    },
                    if self.job.is_some() && self.view.get("slot").is_empty() {
                        "Reading installed versions...".into()
                    } else {
                        message
                    },
                ],
                Some(self.selected + 4),
            ),
            Page::Notes => {
                let mut rows = vec![
                    "Release notes".into(),
                    short(self.view.get("available"), 44),
                ];
                let text = if self.view.get("notes").is_empty() {
                    "No release notes available"
                } else {
                    self.view.get("notes")
                };
                rows.extend(lines(text).into_iter().skip(self.note).take(5));
                rows.push(format!("Source: {}", short(self.view.get("source"), 42)));
                (rows, None)
            }
            Page::Rollback => (
                vec![
                    "Roll back".into(),
                    format!(
                        "Slot: {}",
                        if self.view.get("rollback_slot").is_empty() {
                            "Unavailable"
                        } else {
                            self.view.get("rollback_slot")
                        }
                    ),
                    if self.view.get("rollback_os").is_empty() {
                        "Previous system: unavailable".into()
                    } else {
                        "Previous system (restart)".into()
                    },
                    "Your games, settings and saves stay".into(),
                    message,
                ],
                Some(self.selected + 1),
            ),
            Page::Confirm(operation, expected) => (
                vec![
                    if operation == "apply" {
                        "Install all available updates?".into()
                    } else if operation == "resume" {
                        "Resume remaining updates?".into()
                    } else if operation == "cancel" {
                        "Stop after the current step?".into()
                    } else {
                        "Restore previous version?".into()
                    },
                    if operation == "cancel" {
                        "Any active startup check finishes first".into()
                    } else if matches!(operation.as_str(), "apply" | "resume") {
                        "Continues automatically after restarts".into()
                    } else if operation == "rollback-slot" {
                        short(self.view.get("rollback_slot"), 44)
                    } else if operation == "rollback-os" {
                        "Previous system release".into()
                    } else {
                        short(expected, 44)
                    },
                    "Keep power connected".into(),
                    "Games, settings and saves stay".into(),
                    "Cancel".into(),
                    "Continue".into(),
                ],
                Some(if self.yes { 5 } else { 4 }),
            ),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn menu() -> Menu {
        Menu {
            view: Snapshot::parse(
                "protocol\t1\nslot\told\nos\tos1\navailable\tnew\ndownloaded\t1\n",
            )
            .unwrap(),
            selected: 2,
            page: Page::Main,
            yes: false,
            note: 0,
            error: None,
            job: None,
            refreshed: Instant::now(),
            requesting: None,
        }
    }
    #[test]
    fn confirmation_defaults_to_cancel_and_b_exits_safely() {
        let mut menu = menu();
        menu.button(Btn::A);
        assert!(matches!(menu.page, Page::Confirm(_, _)));
        assert!(!menu.yes);
        menu.button(Btn::A);
        assert!(menu.page == Page::Main);
        menu.button(Btn::A);
        menu.button(Btn::B);
        assert!(menu.page == Page::Main);
        assert!(menu.job.is_none());
    }
    #[test]
    fn background_status_refresh_does_not_swallow_navigation() {
        let mut menu = menu();
        let (_tx, rx) = mpsc::channel();
        menu.job = Some(rx);
        menu.button(Btn::Down);
        assert_eq!(menu.selected, 3);
        menu.button(Btn::X);
        assert!(menu.page == Page::Notes);
    }
    #[test]
    fn malformed_protocol_is_not_an_installable_update() {
        assert!(Snapshot::parse("protocol\t2").is_err());
        assert!(!Snapshot::default().can_install());
        let mut menu = menu();
        menu.view.0.insert("retained".into(), "1".into());
        menu.button(Btn::A);
        assert!(menu.page == Page::Main);
        assert!(menu.job.is_none());
    }
    #[test]
    fn destructive_job_blocks_sleep_and_back_without_hiding_progress() {
        let mut menu = menu();
        menu.view.0.extend([
            ("busy".into(), "1".into()),
            ("operation".into(), "apply".into()),
        ]);
        assert!(menu.locked());
        assert!(menu.legend().is_empty());
        assert!(!menu.button(Btn::B));
        assert!(menu.rows().0.len() <= 10);
    }
    #[test]
    fn release_notes_scroll_and_progress_are_bounded() {
        let mut menu = menu();
        menu.view
            .0
            .insert("notes".into(), "a test release note ".repeat(100));
        menu.button(Btn::X);
        for _ in 0..100 {
            menu.button(Btn::Down);
        }
        assert!(menu.rows().0.len() <= 9);
        menu.view.0.extend([
            ("event".into(), "downloading".into()),
            ("size".into(), "100".into()),
            ("bytes".into(), "999".into()),
        ]);
        assert_eq!(menu.progress(), Some(1.0));
    }
    #[test]
    fn delayed_internet_is_waiting_then_resumable_without_a_boot_error() {
        let mut menu = menu();
        menu.view.0.extend([
            ("session".into(), "1".into()),
            ("busy".into(), "1".into()),
            ("operation".into(), "resume".into()),
            ("event".into(), "waiting-network".into()),
            ("seconds".into(), "27".into()),
        ]);
        assert!(menu.locked());
        assert_eq!(menu.view.message(), "Waiting for internet... 27s / 120s");
        menu.view.0.insert("event".into(), "paused-network".into());
        menu.view.0.insert("busy".into(), "0".into());
        assert!(!menu.locked());
        assert!(menu.rows().0.iter().any(|r| r == "Resume updates"));
        menu.button(Btn::A);
        assert!(matches!(menu.page, Page::Confirm(ref operation, _) if operation == "resume"));
    }
    #[test]
    fn stop_updates_requires_confirmation_even_while_installing() {
        let mut menu = menu();
        menu.view.0.extend([
            ("session".into(), "1".into()),
            ("busy".into(), "1".into()),
            ("event".into(), "installing".into()),
        ]);
        assert!(!menu.button(Btn::B));
        assert!(matches!(menu.page, Page::Confirm(ref operation, _) if operation == "cancel"));
        assert!(!menu.yes);
        menu.button(Btn::B);
        assert!(menu.page == Page::Main);
        assert!(menu.job.is_none());
    }
    #[test]
    fn unsupported_installation_is_distinct_from_a_verified_latest_version() {
        let mut view = Snapshot::default();
        view.0.insert("event".into(), "no-path".into());
        assert_eq!(view.message(), "No supported update path");
        view.0.insert("event".into(), "up-to-date".into());
        assert_eq!(view.message(), "Up to date");
    }
}
