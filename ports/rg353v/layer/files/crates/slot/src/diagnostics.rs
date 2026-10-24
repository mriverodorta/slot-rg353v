//! On-demand, offline diagnostics. Slow reads stay off the UI thread.
use slot_input::Btn;
use std::collections::BTreeMap;
use std::process::Command;
use std::sync::mpsc::{self, Receiver};
use std::time::{Duration, Instant};

#[derive(Default, Debug)]
struct Snapshot(BTreeMap<String, String>);
impl Snapshot {
    fn parse(text: &str) -> Result<Self, String> {
        if text.len() > 8192 {
            return Err("Diagnostics response too large".into());
        }
        let values: BTreeMap<_, _> = text
            .lines()
            .filter_map(|line| line.split_once('\t'))
            .map(|(k, v)| {
                (
                    k.to_string(),
                    v.chars().filter(|c| !c.is_control()).take(512).collect(),
                )
            })
            .collect();
        if values.get("protocol").map(String::as_str) != Some("1") {
            return Err("Diagnostics unavailable".into());
        }
        Ok(Self(values))
    }
    fn get(&self, key: &str) -> &str {
        self.0
            .get(key)
            .map(String::as_str)
            .filter(|v| !v.is_empty())
            .unwrap_or("Checking...")
    }
}
fn job(storage: bool) -> Receiver<Result<Snapshot, String>> {
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let result = (|| {
            let path = std::env::var_os("SLOT_CORE_DIR")
                .map(std::path::PathBuf::from)
                .map(|p| p.join("slot-diagnostics-ui"))
                .filter(|p| p.is_file())
                .ok_or("Diagnostics available on handheld")?;
            let mut command = Command::new("python3");
            command.arg(path).arg("status");
            if storage {
                command.arg("--storage");
            }
            let output = command
                .output()
                .map_err(|_| "Diagnostics could not start")?;
            if !output.status.success() {
                return Err("Diagnostics failed; try again".into());
            }
            Snapshot::parse(&String::from_utf8_lossy(&output.stdout))
        })();
        let _ = tx.send(result);
    });
    rx
}
#[derive(PartialEq, Debug)]
enum Page {
    Main,
    Versions,
    Services,
    Storage,
}
pub struct Menu {
    tools: Option<crate::storage_menu::Menu>,
    page: Page,
    selected: usize,
    storage_first: usize,
    view: Snapshot,
    job: Option<Receiver<Result<Snapshot, String>>>,
    refreshed: Instant,
    message: String,
    features: crate::features::Features,
}
impl Menu {
    pub fn open() -> Self {
        Self::with_features(crate::features::Features::default())
    }
    pub fn with_features(features: crate::features::Features) -> Self {
        Self {
            features,
            tools: None,
            page: Page::Main,
            selected: 0,
            storage_first: 0,
            view: Snapshot::default(),
            job: Some(job(false)),
            refreshed: Instant::now(),
            message: String::new(),
        }
    }
    pub fn storage_tools(features: crate::features::Features) -> Self {
        Self {
            features: crate::features::Features::default(),
            tools: Some(crate::storage_menu::Menu::open(features)),
            page: Page::Main,
            selected: 0,
            storage_first: 0,
            view: Snapshot::default(),
            job: None,
            refreshed: Instant::now(),
            message: String::new(),
        }
    }
    pub fn is_storage_tools(&self) -> bool {
        self.tools.is_some()
    }
    pub fn settings_info(&self) -> Option<crate::settings_info::Info> {
        self.tools.as_ref().and_then(|m| m.settings_info())
    }
    pub fn locked(&self) -> bool {
        self.tools.as_ref().is_some_and(|m| m.locked())
    }
    pub fn poll(&mut self) {
        if let Some(tools) = &mut self.tools {
            tools.poll();
            return;
        }
        if let Some(rx) = &self.job {
            match rx.try_recv() {
                Ok(result) => {
                    match result {
                        Ok(view) => {
                            self.message.clear();
                            self.view = view;
                        }
                        Err(error) => self.message = error,
                    }
                    self.job = None;
                    self.refreshed = Instant::now();
                }
                Err(mpsc::TryRecvError::Disconnected) => {
                    self.job = None;
                    self.message = "Diagnostics interrupted; retry".into();
                    self.refreshed = Instant::now();
                }
                Err(mpsc::TryRecvError::Empty) => {}
            }
        } else if self.refreshed.elapsed() >= Duration::from_secs(5) {
            self.job = Some(job(self.page == Page::Storage));
        }
    }
    pub fn button(&mut self, button: Btn) -> bool {
        if let Some(tools) = &mut self.tools {
            return tools.button(button);
        }
        match button {
            Btn::B if self.page == Page::Main => return true,
            Btn::B => self.page = Page::Main,
            Btn::Up if self.page == Page::Storage => {
                self.storage_first = self.storage_first.saturating_sub(1)
            }
            Btn::Down if self.page == Page::Storage => {
                self.storage_first =
                    (self.storage_first + 1).min(self.storage_lines().len().saturating_sub(7))
            }
            Btn::Up if self.page == Page::Main => self.selected = (self.selected + 2) % 3,
            Btn::Down if self.page == Page::Main => self.selected = (self.selected + 1) % 3,
            Btn::A if self.page == Page::Main => {
                self.page = match self.selected {
                    0 => Page::Versions,
                    1 => Page::Services,
                    _ => Page::Storage,
                };
                if self.page == Page::Storage {
                    self.storage_first = 0;
                    self.job = Some(job(true));
                }
            }
            Btn::X if self.job.is_none() => self.job = Some(job(self.page == Page::Storage)),
            _ => {}
        }
        false
    }
    pub fn selected_row(&self) -> Option<usize> {
        if let Some(tools) = &self.tools {
            return tools.selected_row();
        }
        match self.page {
            Page::Main => Some(self.selected + 1),
            _ => None,
        }
    }
    pub fn legend(&self) -> Vec<slot_ui::Hint> {
        if let Some(tools) = &self.tools {
            return tools.legend();
        }
        let hints = match self.page {
            Page::Main => vec![("B", "Back"), ("A", "Open"), ("X", "Refresh")],
            Page::Storage => vec![("B", "Back"), ("^v", "Scroll"), ("X", "Refresh")],
            _ => vec![("B", "Back"), ("X", "Refresh")],
        };
        slot_ui::hint_row(&hints)
    }
    fn storage_lines(&self) -> Vec<String> {
        let mut lines = Vec::new();
        for (label, key) in [
            ("Path", "fault_path"),
            ("Action", "fault_operation"),
            ("Error", "fault_reason"),
            ("Errno", "fault_errno"),
            ("Time (Unix)", "fault_time"),
            ("Content", "content_mount"),
            ("Kernel", "fs_error"),
        ] {
            let text = format!("{label}: {}", self.view.get(key));
            let chars: Vec<char> = text.chars().collect();
            lines.extend(chars.chunks(42).map(|c| c.iter().collect::<String>()));
        }
        lines
    }
    pub fn rows(&self) -> Vec<String> {
        if let Some(tools) = &self.tools {
            return tools.rows();
        }
        let v = &self.view;
        match self.page {
            Page::Main => vec![
                "Diagnostics".into(),
                "Versions".into(),
                "Services".into(),
                "Storage".into(),
                format!("IP: {}", v.get("ip")),
                format!("Available RAM: {}", v.get("ram")),
                format!("Free Games Space: {}", v.get("free")),
                if self.message.is_empty() {
                    format!("Failed Services: {}", v.get("failed"))
                } else {
                    self.message.clone()
                },
            ],
            Page::Storage => std::iter::once("Storage Diagnostics".into())
                .chain(
                    self.storage_lines()
                        .into_iter()
                        .skip(self.storage_first)
                        .take(7),
                )
                .collect(),
            Page::Versions => vec![
                "Versions".into(),
                format!("Slot: {}", v.get("slot")),
                format!("OS: {}", v.get("os")),
                format!("Kernel: {}", v.get("kernel")),
                format!("Profile: {}", v.get("profile")),
                format!("Slot Source: {}", v.get("source_slot")),
                format!("ROCKNIX Source: {}", v.get("source_os")),
                format!("Layer: {}", v.get("layer")),
            ],
            Page::Services => {
                let mut rows = vec![
                    "Services".into(),
                    format!("Slot: {}", v.get("slot-rg353v")),
                    format!("Content: {}", v.get("storage-slotcontent")),
                ];
                for (feature, label, key) in [
                    ("wifi", "Network", "NetworkManager"),
                    ("wifi", "Wi-Fi", "slot-wpa-supplicant"),
                    ("wifi", "Wi-Fi Recovery", "slot-wifi-probe-recovery"),
                    ("sharing", "File Sharing", "slot-sharing"),
                    ("ssh", "SSH", "sshd"),
                ] {
                    if self.features.has(feature) {
                        rows.push(format!("{label}: {}", v.get(key)));
                    }
                }
                rows
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn menu() -> Menu {
        Menu {
            tools: None,
            page: Page::Main,
            selected: 0,
            storage_first: 0,
            view: Snapshot::parse("protocol\t1\nram\t1.5 GiB\nip\t192.0.2.10").unwrap(),
            job: None,
            refreshed: Instant::now(),
            message: String::new(),
            features: crate::features::Features::default(),
        }
    }
    #[test]
    fn navigation_wraps_through_storage() {
        let mut m = menu();
        m.button(Btn::Up);
        assert_eq!(m.selected, 2);
        m.button(Btn::A);
        assert_eq!(m.page, Page::Storage);
        assert!(m.job.is_some());
        m.button(Btn::B);
        assert_eq!(m.page, Page::Main);
        m.button(Btn::Down);
        assert_eq!(m.selected, 0);
        assert!(m.button(Btn::B));
    }
    #[test]
    fn versions_and_services_return_to_selection() {
        let mut m = menu();
        m.button(Btn::A);
        assert_eq!(m.page, Page::Versions);
        m.button(Btn::B);
        m.button(Btn::Down);
        m.button(Btn::A);
        assert_eq!(m.page, Page::Services);
        m.button(Btn::B);
        assert_eq!(m.selected_row(), Some(2));
    }
    #[test]
    fn bounded_protocol_and_live_values() {
        assert!(Snapshot::parse("oops").is_err());
        assert!(Snapshot::parse(&"x".repeat(8193)).is_err());
        let m = menu();
        assert!(m.rows().contains(&"Available RAM: 1.5 GiB".into()));
        assert!(m.rows().contains(&"IP: 192.0.2.10".into()));
    }
    #[test]
    fn refresh_during_collection_keeps_the_existing_worker() {
        let mut m = menu();
        let (tx, rx) = mpsc::channel();
        m.job = Some(rx);
        m.button(Btn::X);
        tx.send(Ok(Snapshot::parse("protocol\t1\nram\t1.0 GiB").unwrap()))
            .unwrap();
        m.poll();
        assert_eq!(m.view.get("ram"), "1.0 GiB");
        assert!(m.job.is_none());
    }
    #[test]
    fn successful_refresh_clears_errors_and_rows_fit_menu() {
        let mut m = menu();
        m.message = "Diagnostics failed; try again".into();
        let (tx, rx) = mpsc::channel();
        tx.send(Ok(Snapshot::parse("protocol\t1\nfailed\t0").unwrap()))
            .unwrap();
        m.job = Some(rx);
        m.poll();
        assert!(m.message.is_empty());
        assert_eq!(m.rows().len(), 8);
        assert!(m.rows().contains(&"Failed Services: 0".into()));
    }
    #[test]
    fn file_sharing_uses_the_installed_ksmbd_service_key() {
        let mut m = menu();
        m.page = Page::Services;
        m.view = Snapshot::parse("protocol\t1\nslot-sharing\tactive\nsmbd\tinactive\n").unwrap();
        assert!(m.rows().contains(&"File Sharing: active".into()));
    }
}
