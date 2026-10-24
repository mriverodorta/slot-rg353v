//! NetworkManager integration. Blocking CLI work stays off the render thread.
use std::io::Write;
use std::process::{Command, Stdio};
use std::sync::mpsc::{self, Receiver};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AccessPoint {
    pub bssid: String,
    pub ssid: String,
    pub signal: u8,
    pub security: String,
    pub connected: bool,
}

pub fn fields(line: &str) -> Vec<String> {
    let mut result = vec![String::new()];
    let mut escaped = false;
    for c in line.chars() {
        if escaped {
            result.last_mut().unwrap().push(c);
            escaped = false;
        } else if c == '\\' {
            escaped = true;
        } else if c == ':' {
            result.push(String::new());
        } else {
            result.last_mut().unwrap().push(c);
        }
    }
    if escaped {
        result.last_mut().unwrap().push('\\');
    }
    result
}

pub fn parse_scan(text: &str) -> Vec<AccessPoint> {
    let mut aps: Vec<AccessPoint> = Vec::new();
    for line in text.lines() {
        let f = fields(line);
        if f.len() != 5 || f[2].is_empty() {
            continue;
        }
        let Ok(signal) = f[3].parse::<u8>() else {
            continue;
        };
        let ap = AccessPoint {
            connected: f[0] == "*",
            bssid: f[1].clone(),
            ssid: f[2].clone(),
            signal,
            security: f[4].clone(),
        };
        if let Some(existing) = aps
            .iter_mut()
            .find(|a| a.ssid == ap.ssid && a.security == ap.security)
        {
            // Mesh / dual-band networks may list a stronger, inactive BSSID
            // first. Keep the actual connected radio when collapsing names.
            if (ap.connected, ap.signal) > (existing.connected, existing.signal) {
                *existing = ap;
            }
            continue;
        }
        aps.push(ap);
    }
    aps.sort_by_key(|a| (std::cmp::Reverse(a.connected), std::cmp::Reverse(a.signal)));
    aps
}

pub fn scan() -> Result<Vec<AccessPoint>, String> {
    scan_using(std::ffi::OsStr::new("nmcli"))
}

fn scan_using(program: &std::ffi::OsStr) -> Result<Vec<AccessPoint>, String> {
    let devices = Command::new(program)
        .env("LC_ALL", "C")
        .args([
            "--terse",
            "--escape",
            "yes",
            "--fields",
            "DEVICE,TYPE,STATE",
            "device",
            "status",
        ])
        .output()
        .map_err(|_| "Wi-Fi tools unavailable".to_string())?;
    let interface = String::from_utf8_lossy(&devices.stdout)
        .lines()
        .map(fields)
        .find(|f| f.len() == 3 && f[1] == "wifi")
        .map(|f| f[0].clone())
        .ok_or_else(|| "Wi-Fi adapter unavailable".to_string())?;
    // An unavailable/unmanaged adapter can yield an empty AP list, which is
    // different from a working adapter completing a scan with no nearby APs.
    let state = Command::new(program)
        .env("LC_ALL", "C")
        .args([
            "--get-values",
            "GENERAL.STATE",
            "device",
            "show",
            &interface,
        ])
        .output()
        .map_err(|_| "Wi-Fi tools unavailable".to_string())?;
    let state_code = String::from_utf8_lossy(&state.stdout)
        .split_whitespace()
        .next()
        .and_then(|code| code.parse::<u32>().ok());
    if !state.status.success() || !matches!(state_code, Some(30..=120)) {
        return Err("Wi-Fi adapter unavailable; turn Wi-Fi off/on".into());
    }
    let output = Command::new(program)
        .env("LC_ALL", "C")
        .args([
            "--wait",
            "15",
            "--terse",
            "--escape",
            "yes",
            "--fields",
            "IN-USE,BSSID,SSID,SIGNAL,SECURITY",
            "device",
            "wifi",
            "list",
            "ifname",
            &interface,
            "--rescan",
            "yes",
        ])
        .output()
        .map_err(|_| "Could not scan Wi-Fi".to_string())?;
    if !output.status.success() {
        return Err("Wi-Fi scan failed; try again".into());
    }
    let text = String::from_utf8_lossy(&output.stdout);
    let aps = parse_scan(&text);
    if !text.trim().is_empty() && aps.is_empty() {
        return Err("Could not read Wi-Fi scan results".into());
    }
    Ok(aps)
}

pub fn connect(ap: &AccessPoint, password: &str) -> Result<String, String> {
    connect_using(std::ffi::OsStr::new("nmcli"), ap, password)
}

// A manual password entry must supersede a cached NetworkManager secret.
// `nmcli --ask device wifi connect` otherwise skips stdin for saved profiles.
fn saved_personal_profile(
    program: &std::ffi::OsStr,
    ap: &AccessPoint,
) -> Result<Option<(String, String)>, String> {
    if !ap.security.contains("WPA") {
        return Ok(None);
    }
    let profiles = Command::new(program)
        .env("LC_ALL", "C")
        .args([
            "--terse",
            "--escape",
            "yes",
            "--fields",
            "UUID,TYPE,DBUS-PATH",
            "connection",
            "show",
        ])
        .output()
        .map_err(|_| "Wi-Fi tools unavailable".to_string())?;
    if !profiles.status.success() {
        return Err("Could not read saved Wi-Fi networks; try again".into());
    }
    for line in String::from_utf8_lossy(&profiles.stdout).lines() {
        let f = fields(line);
        if f.len() != 3 || f[1] != "802-11-wireless" {
            continue;
        }
        let setting = Command::new(program)
            .env("LC_ALL", "C")
            .args([
                "--escape",
                "no",
                "--get-values",
                "802-11-wireless.ssid,802-11-wireless.bssid,802-11-wireless-security.key-mgmt",
                "connection",
                "show",
                "uuid",
                &f[0],
            ])
            .output()
            .map_err(|_| "Could not read saved Wi-Fi network".to_string())?;
        if !setting.status.success() {
            return Err("Could not read saved Wi-Fi network; try again".into());
        }
        let value = String::from_utf8_lossy(&setting.stdout);
        let parts: Vec<_> = value.lines().collect();
        if parts.len() != 3
            || parts[0] != ap.ssid
            || (!parts[1].is_empty() && !parts[1].eq_ignore_ascii_case(&ap.bssid))
            || !matches!(parts[2], "wpa-psk" | "sae")
        {
            continue;
        }
        let path = &f[2];
        if !path
            .strip_prefix("/org/freedesktop/NetworkManager/Settings/")
            .is_some_and(|tail| !tail.is_empty() && tail.bytes().all(|b| b.is_ascii_digit()))
        {
            return Err("Could not read saved Wi-Fi network; try again".into());
        }
        return Ok(Some((f[0].clone(), path.clone())));
    }
    Ok(None)
}

fn connect_using(
    program: &std::ffi::OsStr,
    ap: &AccessPoint,
    password: &str,
) -> Result<String, String> {
    connect_using_tools(program, std::ffi::OsStr::new("busctl"), ap, password)
}

fn connect_using_tools(
    program: &std::ffi::OsStr,
    busctl: &std::ffi::OsStr,
    ap: &AccessPoint,
    password: &str,
) -> Result<String, String> {
    if password.contains(['\n', '\r']) {
        return Err("Password contains an unsupported character".into());
    }
    let profile = saved_personal_profile(program, ap)?;
    if let Some((_, path)) = &profile {
        // ClearSecrets removes the cached secret too. Merely resetting the psk
        // setting to an empty string leaves that cache intact in NetworkManager.
        // This is confined to the selected personal Wi-Fi profile; its other
        // settings and all other saved networks remain unchanged.
        let cleared = Command::new(busctl)
            .args([
                "call",
                "org.freedesktop.NetworkManager",
                path,
                "org.freedesktop.NetworkManager.Settings.Connection",
                "ClearSecrets",
            ])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map_err(|_| "Could not update saved Wi-Fi password; try again".to_string())?;
        if !cleared.success() {
            return Err("Could not update saved Wi-Fi password; try again".into());
        }
    }
    // Send secrets on stdin, never shell-expand them or put them in argv/logs.
    let mut command = Command::new(program);
    command.env("LC_ALL", "C").args(["--ask", "--wait", "25"]);
    if let Some((uuid, _)) = &profile {
        command.args(["connection", "up", "uuid", uuid, "ap", &ap.bssid]);
    } else {
        command.args(["device", "wifi", "connect", &ap.bssid]);
    }
    let mut child = command
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|_| "Wi-Fi tools unavailable".to_string())?;
    if let Some(mut stdin) = child.stdin.take() {
        let _ = writeln!(stdin, "{password}");
    }
    if !child
        .wait()
        .map_err(|_| "Connection failed".to_string())?
        .success()
    {
        return Err("Could not connect. Check the password and try again.".into());
    }
    let interface = Command::new(program)
        .env("LC_ALL", "C")
        .args([
            "--terse",
            "--fields",
            "DEVICE,TYPE,STATE",
            "device",
            "status",
        ])
        .output()
        .ok()
        .and_then(|output| {
            String::from_utf8_lossy(&output.stdout)
                .lines()
                .find_map(|line| {
                    let f = fields(line);
                    (f.len() == 3 && f[1] == "wifi" && f[2] == "connected").then(|| f[0].clone())
                })
        });
    let address = interface
        .and_then(|interface| {
            Command::new(program)
                .args(["--get-values", "IP4.ADDRESS", "device", "show", &interface])
                .output()
                .ok()
        })
        .map(|output| {
            String::from_utf8_lossy(&output.stdout)
                .lines()
                .next()
                .unwrap_or_default()
                .split('/')
                .next()
                .unwrap_or_default()
                .to_string()
        })
        .unwrap_or_default();
    Ok(if address.is_empty() {
        "Connected".into()
    } else {
        format!("Connected: {address}")
    })
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
struct WifiStatus {
    enabled: bool,
    connected: bool,
    ssid: String,
    ip: String,
}
impl WifiStatus {
    fn connection_label(&self) -> &str {
        if !self.enabled {
            "Wi-Fi off"
        } else if !self.connected {
            "Not connected"
        } else if self.ssid.is_empty() {
            "Name unavailable"
        } else {
            &self.ssid
        }
    }
}
fn wifi_status() -> Result<WifiStatus, String> {
    if std::path::Path::new("/usr/share/slot/game-startup-v1").exists()
        && !std::path::Path::new("/run/slot-services/wifi.on").exists()
    {
        return Ok(WifiStatus::default());
    }
    wifi_status_using(std::ffi::OsStr::new("nmcli"))
}
fn wifi_status_using(program: &std::ffi::OsStr) -> Result<WifiStatus, String> {
    let run = |args: &[&str]| -> Result<String, String> {
        let output = Command::new(program)
            .env("LC_ALL", "C")
            .args(args)
            .output()
            .map_err(|_| "Wi-Fi tools unavailable".to_string())?;
        if !output.status.success() {
            return Err("Could not read Wi-Fi status".into());
        }
        Ok(String::from_utf8_lossy(&output.stdout)
            .trim_end_matches(['\r', '\n'])
            .to_string())
    };
    let enabled = run(&["radio", "wifi"])? == "enabled";
    let mut status = WifiStatus {
        enabled,
        ..Default::default()
    };
    if enabled {
        let devices = run(&[
            "--terse",
            "--escape",
            "yes",
            "--fields",
            "DEVICE,TYPE,STATE",
            "device",
            "status",
        ])?;
        for line in devices.lines() {
            let f = fields(line);
            if f.len() == 3 && f[1] == "wifi" && f[2] == "connected" {
                status.connected = true;
                // Read the actual SSID from the active profile, not its display
                // name or the scan cache (which may be empty after resume).
                let uuid = run(&["--get-values", "GENERAL.CON-UUID", "device", "show", &f[0]])
                    .unwrap_or_default();
                if !uuid.is_empty() && uuid != "--" {
                    status.ssid = run(&[
                        "--escape",
                        "no",
                        "--get-values",
                        "802-11-wireless.ssid",
                        "connection",
                        "show",
                        "uuid",
                        &uuid,
                    ])
                    .unwrap_or_default();
                }
                if status.ssid.is_empty() {
                    let scan = run(&[
                        "--terse",
                        "--escape",
                        "yes",
                        "--fields",
                        "IN-USE,BSSID,SSID,SIGNAL,SECURITY",
                        "device",
                        "wifi",
                        "list",
                        "ifname",
                        &f[0],
                        "--rescan",
                        "no",
                    ])
                    .unwrap_or_default();
                    status.ssid = parse_scan(&scan)
                        .into_iter()
                        .find(|ap| ap.connected)
                        .map(|ap| ap.ssid)
                        .unwrap_or_default();
                }
                status.ip = run(&["--get-values", "IP4.ADDRESS", "device", "show", &f[0]])?
                    .lines()
                    .next()
                    .unwrap_or_default()
                    .split('/')
                    .next()
                    .unwrap_or_default()
                    .to_string();
                break;
            }
        }
    }
    Ok(status)
}
fn status_job(toggle: Option<bool>) -> Receiver<ResultJob> {
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let result = (|| {
            if let Some(enabled) = toggle {
                if std::path::Path::new("/usr/share/slot/game-startup-v1").exists() {
                    let output = Command::new("/usr/bin/slot-services")
                        .args(["wifi", if enabled { "on" } else { "off" }])
                        .output()
                        .map_err(|_| "Wi-Fi tools unavailable".to_string())?;
                    if !output.status.success() {
                        return Err("Could not change Wi-Fi; retry".into());
                    }
                    return wifi_status();
                }
                let output = Command::new("nmcli")
                    .args([
                        "--wait",
                        "10",
                        "radio",
                        "wifi",
                        if enabled { "on" } else { "off" },
                    ])
                    .output()
                    .map_err(|_| "Wi-Fi tools unavailable".to_string())?;
                if !output.status.success() {
                    return Err("Could not change Wi-Fi setting".into());
                }
                // ROCKNIX's 080-network startup hook reads system.cfg and can
                // otherwise override NetworkManager's persisted radio state.
                let saved = Command::new("/bin/bash")
                    .args([
                        "-c",
                        ". /etc/profile.d/001-functions && set_setting wifi.enabled \"$1\" && test \"$(get_setting wifi.enabled)\" = \"$1\"",
                        "slot-wifi-setting",
                        if enabled { "1" } else { "0" },
                    ])
                    .output()
                    .map_err(|_| "Could not save Wi-Fi setting".to_string())?;
                if !saved.status.success() {
                    return Err("Wi-Fi changed, but could not save startup setting".into());
                }
            }
            wifi_status()
        })();
        let _ = tx.send(ResultJob::Status(result));
    });
    rx
}

enum ResultJob {
    Status(Result<WifiStatus, String>),
    Scan(Result<Vec<AccessPoint>, String>),
    Connected(Result<String, String>),
}
fn scan_job() -> Receiver<ResultJob> {
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let _ = tx.send(ResultJob::Scan(scan()));
    });
    rx
}
fn connect_job(ap: AccessPoint, password: String) -> Receiver<ResultJob> {
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let _ = tx.send(ResultJob::Connected(connect(&ap, &password)));
    });
    rx
}

pub struct Menu {
    overview: bool,
    overview_selected: usize,
    sharing: Option<crate::sharing::Menu>,
    usb: Option<crate::usb_storage::Menu>,
    usb_network: Option<crate::usb_network::Menu>,
    ssh: Option<crate::ssh::Menu>,
    services: Option<crate::services::Menu>,
    wifi: WifiStatus,
    wifi_known: bool,
    changing_wifi: bool,
    refreshed: std::time::Instant,
    aps: Vec<AccessPoint>,
    selected: usize,
    keyboard: slot_ui::Keyboard,
    editing: bool,
    status: String,
    job: Option<Receiver<ResultJob>>,
}

impl Menu {
    pub fn sharing() -> Self {
        let mut m = Self::new();
        m.sharing = Some(crate::sharing::Menu::open());
        m
    }
    pub fn ssh() -> Self {
        let mut m = Self::new();
        m.ssh = Some(crate::ssh::Menu::open());
        m
    }
    pub fn usb_network() -> Self {
        let mut menu = Self::new();
        menu.usb_network = Some(crate::usb_network::Menu::open());
        menu
    }
    pub fn usb_storage() -> Self {
        let mut menu = Self::new();
        menu.usb = Some(crate::usb_storage::Menu::open());
        menu
    }
    pub fn open() -> Self {
        let mut menu = Self::new();
        menu.job = Some(status_job(None));
        menu
    }
    fn new() -> Self {
        Self {
            overview: true,
            overview_selected: 0,
            sharing: None,
            usb: None,
            usb_network: None,
            ssh: None,
            services: None,
            wifi: WifiStatus::default(),
            wifi_known: false,
            changing_wifi: false,
            refreshed: std::time::Instant::now(),
            aps: Vec::new(),
            selected: 0,
            keyboard: slot_ui::Keyboard::new(64, true),
            editing: false,
            status: "Checking Wi-Fi...".into(),
            job: None,
        }
    }
    pub fn poll(&mut self) {
        if let Some(menu) = &mut self.usb_network {
            menu.poll();
            return;
        }
        if let Some(services) = &mut self.services {
            services.poll();
            return;
        }
        if let Some(usb) = &mut self.usb {
            usb.poll();
            return;
        }
        if let Some(ssh) = &mut self.ssh {
            ssh.poll();
            return;
        }
        if let Some(sharing) = &mut self.sharing {
            sharing.poll();
            return;
        }
        let Some(job) = &self.job else {
            if self.overview && self.refreshed.elapsed().as_secs() >= 2 {
                self.job = Some(status_job(None));
                self.refreshed = std::time::Instant::now();
            }
            return;
        };
        let result = match job.try_recv() {
            Ok(result) => result,
            Err(mpsc::TryRecvError::Empty) => return,
            Err(mpsc::TryRecvError::Disconnected) => {
                self.job = None;
                self.changing_wifi = false;
                self.status = "Request ended; try again".into();
                return;
            }
        };
        self.job = None;
        self.changing_wifi = false;
        match result {
            ResultJob::Status(Ok(wifi)) => {
                self.wifi = wifi;
                self.wifi_known = true;
                self.status = String::new();
                self.refreshed = std::time::Instant::now();
            }
            ResultJob::Status(Err(error)) => self.status = error,
            ResultJob::Scan(Ok(aps)) => {
                self.aps = aps;
                self.selected = 0;
                self.status = if self.aps.is_empty() {
                    "No networks found".into()
                } else {
                    String::new()
                };
            }
            ResultJob::Scan(Err(error)) => self.status = error,
            ResultJob::Connected(Ok(status)) => {
                self.editing = false;
                self.keyboard.clear();
                self.status = status;
                self.overview = true;
                self.job = Some(status_job(None));
            }
            ResultJob::Connected(Err(error)) => self.status = error,
        }
    }
    pub fn button(&mut self, button: slot_input::Btn) -> bool {
        use slot_input::Btn::*;
        if let Some(menu) = &mut self.usb_network {
            return menu.button(button);
        }
        if let Some(services) = &mut self.services {
            if services.button(button) {
                self.services = None;
                self.job = Some(status_job(None));
            }
            return false;
        }
        if let Some(usb) = &mut self.usb {
            return usb.button(button);
        }
        if let Some(ssh) = &mut self.ssh {
            return ssh.button(button);
        }
        if let Some(sharing) = &mut self.sharing {
            return sharing.button(button);
        }
        if button == B {
            if self.editing {
                self.editing = false;
                self.keyboard.clear();
            } else if !self.overview {
                self.overview = true;
                self.job = Some(status_job(None));
            } else {
                return true;
            }
            return false;
        }
        if self.job.is_some() && (!self.overview || self.changing_wifi) {
            return false;
        }
        if self.overview && !self.wifi_known {
            if matches!(button, A | X) {
                self.status = "Checking Wi-Fi...".into();
                self.job = Some(status_job(None));
            }
            return false;
        }
        if self.overview {
            match button {
                Up | Down => self.overview_selected = 1 - self.overview_selected,
                Left | Right if self.overview_selected == 0 => {
                    self.changing_wifi = true;
                    self.status = "Updating Wi-Fi...".into();
                    self.job = Some(status_job(Some(!self.wifi.enabled)));
                }
                A if self.overview_selected == 1 && self.wifi.enabled => {
                    self.overview = false;
                    self.status = "Scanning...".into();
                    self.job = Some(scan_job());
                }
                _ => {}
            }
        } else if self.editing {
            use slot_ui::KeyboardAction as Key;
            let action = match button {
                Left => Some(Key::Left),
                Right => Some(Key::Right),
                Up => Some(Key::Up),
                Down => Some(Key::Down),
                L1 => Some(Key::PreviousSection),
                R1 => Some(Key::NextSection),
                A => Some(Key::Add),
                Y => Some(Key::Delete),
                X => Some(Key::ToggleVisibility),
                Start => {
                    self.begin_connect();
                    None
                }
                _ => None,
            };
            if let Some(action) = action {
                self.keyboard.apply(action);
                self.status.clear();
            }
        } else {
            match button {
                Up if !self.aps.is_empty() => {
                    self.selected = (self.selected + self.aps.len() - 1) % self.aps.len()
                }
                Down if !self.aps.is_empty() => {
                    self.selected = (self.selected + 1) % self.aps.len()
                }
                X => {
                    self.status = "Scanning...".into();
                    self.job = Some(scan_job());
                }
                A if !self.aps.is_empty() => {
                    if self.aps[self.selected].security.contains("802.1X") {
                        self.status = "Enterprise Wi-Fi is not supported yet".into();
                    } else if self.aps[self.selected].security.is_empty()
                        || self.aps[self.selected].security == "--"
                    {
                        self.begin_connect();
                    } else {
                        self.editing = true;
                        self.keyboard.clear();
                        self.status = String::new();
                    }
                }
                _ => {}
            }
        }
        false
    }
    fn begin_connect(&mut self) {
        if let Some(ap) = self.aps.get(self.selected).cloned() {
            self.status = "Connecting...".into();
            self.job = Some(connect_job(ap, self.keyboard.value().to_string()));
        }
    }
    pub fn legend(&self) -> Vec<slot_ui::Hint> {
        if let Some(menu) = &self.usb_network {
            return menu.legend();
        }
        if let Some(services) = &self.services {
            return services.legend();
        }
        if let Some(usb) = &self.usb {
            return usb.legend();
        }
        if let Some(ssh) = &self.ssh {
            return ssh.legend();
        }
        if let Some(sharing) = &self.sharing {
            return sharing.legend();
        }
        let entries: &[(&str, &str)] = if self.overview {
            if !self.wifi_known || self.changing_wifi {
                &[("B", "Back")]
            } else if self.overview_selected == 0 {
                &[("B", "Back"), ("<>", "Change")]
            } else if self.wifi.enabled {
                &[("B", "Back"), ("A", "Open")]
            } else {
                &[("B", "Back")]
            }
        } else if self.job.is_some() {
            &[("B", "Back")]
        } else if self.editing {
            return self.keyboard.legend("Connect");
        } else if self.aps.is_empty() {
            &[("B", "Back"), ("X", "Rescan")]
        } else {
            &[("B", "Back"), ("X", "Rescan"), ("A", "Select")]
        };
        slot_ui::hint_row(entries)
    }
    pub fn keyboard_view(&self) -> Option<slot_ui::KeyboardView> {
        if let Some(ssh) = &self.ssh {
            return ssh.keyboard_view();
        }
        self.editing.then(|| {
            self.keyboard.view(
                "WI-FI PASSWORD",
                &self.aps[self.selected].ssid,
                &self.status,
            )
        })
    }
    pub fn usb_busy(&self) -> bool {
        self.usb.as_ref().is_some_and(|m| m.busy())
    }
    pub fn is_editing(&self) -> bool {
        self.editing
            || self
                .ssh
                .as_ref()
                .is_some_and(|m| m.keyboard_view().is_some())
    }
    pub fn is_overview(&self) -> bool {
        self.overview
    }
    pub fn toggle_row(&self) -> Option<usize> {
        self.usb_network
            .as_ref()
            .map_or(Some(1), |menu| menu.selected_row())
    }
    pub fn toggle_value(&self) -> Option<slot_ui::QuickValue> {
        if let Some(menu) = &self.usb_network {
            return menu.toggle_value();
        }
        if let Some(services) = &self.services {
            return services.toggle_value();
        }
        if self.usb.is_some() {
            return None;
        }
        if let Some(ssh) = &self.ssh {
            return ssh.toggle_value();
        }
        if let Some(sharing) = &self.sharing {
            return sharing.toggle_value();
        }
        (self.overview && self.wifi_known).then_some(slot_ui::QuickValue::flag(self.wifi.enabled))
    }
    pub fn selected_row(&self) -> Option<usize> {
        if let Some(menu) = &self.usb_network {
            return menu.selected_row();
        }
        if let Some(services) = &self.services {
            return services.selected_row();
        }
        if let Some(usb) = &self.usb {
            return usb.selected_row();
        }
        if let Some(ssh) = &self.ssh {
            return ssh.selected_row();
        }
        if let Some(sharing) = &self.sharing {
            return sharing.selected_row();
        }
        if self.overview {
            self.wifi_known.then_some([1, 4][self.overview_selected])
        } else if self.editing || self.aps.is_empty() {
            None
        } else {
            Some(self.selected % 6 + 1)
        }
    }
    pub fn values(&self) -> Vec<(usize, String)> {
        if let Some(menu) = &self.usb_network {
            return menu.values();
        }
        if let Some(services) = &self.services {
            return services.values();
        }
        if self.usb.is_some() {
            return Vec::new();
        }
        if let Some(ssh) = &self.ssh {
            return ssh.values();
        }
        if let Some(sharing) = &self.sharing {
            return sharing.values();
        }
        if !self.overview || !self.wifi_known {
            return Vec::new();
        }
        vec![
            (2, self.wifi.connection_label().into()),
            (
                3,
                if self.wifi.ip.is_empty() {
                    "--"
                } else {
                    &self.wifi.ip
                }
                .into(),
            ),
        ]
    }
    pub fn labels(&self) -> Vec<String> {
        if let Some(menu) = &self.usb_network {
            return menu.labels();
        }
        if let Some(services) = &self.services {
            return services.labels();
        }
        if let Some(usb) = &self.usb {
            return usb.labels();
        }
        if let Some(ssh) = &self.ssh {
            return ssh.labels();
        }
        if let Some(sharing) = &self.sharing {
            return sharing.labels();
        }
        let mut rows = self.rows().0;
        if self.overview && self.wifi_known {
            rows[1] = "Wi-Fi".into();
            rows[2] = "Connected".into();
            rows[3] = "IP address".into();
            if self.status.is_empty() {
                rows.pop();
            }
        }
        rows
    }
    pub fn rows(&self) -> (Vec<String>, Option<usize>) {
        if self.overview {
            if !self.wifi_known {
                return (
                    vec![
                        "Wi-Fi".into(),
                        "Wi-Fi: Checking...".into(),
                        "Connected: --".into(),
                        "IP: --".into(),
                        self.status.clone(),
                    ],
                    None,
                );
            }
            let rows = vec![
                "Wi-Fi".into(),
                format!("Wi-Fi: {}", if self.wifi.enabled { "On" } else { "Off" }),
                format!("Connected: {}", self.wifi.connection_label()),
                format!(
                    "IP: {}",
                    if self.wifi.ip.is_empty() {
                        "--"
                    } else {
                        &self.wifi.ip
                    }
                ),
                if self.wifi.enabled {
                    "Other Networks".into()
                } else {
                    "Other Networks (Wi-Fi off)".into()
                },
                self.status.clone(),
            ];
            return (rows, Some([1, 4][self.overview_selected]));
        }
        if self.editing {
            (Vec::new(), None)
        } else {
            let start = self.selected / 6 * 6;
            let mut rows = vec!["Wi-Fi networks".into()];
            rows.extend(self.aps.iter().skip(start).take(6).map(|a| {
                format!(
                    "{} {}  {}%",
                    if a.connected { "*" } else { " " },
                    a.ssid,
                    a.signal
                )
            }));
            if !self.status.is_empty() {
                rows.push(self.status.clone());
            }
            (
                rows,
                (!self.aps.is_empty()).then_some(self.selected % 6 + 1),
            )
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scan_dedup_keeps_connected_bssid_even_when_another_radio_is_stronger() {
        let inactive = " :AA\\:BB\\:CC\\:DD\\:EE\\:01:Home:100:WPA2";
        let active = "*:AA\\:BB\\:CC\\:DD\\:EE\\:02:Home:67:WPA2";
        for text in [
            format!("{inactive}\n{active}"),
            format!("{active}\n{inactive}"),
        ] {
            let aps = parse_scan(&text);
            assert_eq!(aps.len(), 1);
            assert!(aps[0].connected);
            assert_eq!(aps[0].bssid, "AA:BB:CC:DD:EE:02");
            assert_eq!(aps[0].signal, 67);
        }
    }

    #[cfg(unix)]
    #[test]
    fn status_reads_actual_profile_ssid_and_handles_missing_cache_without_false_disconnect() {
        use std::os::unix::fs::PermissionsExt;
        let tmp = tempfile::tempdir().unwrap();
        let script = tmp.path().join("nmcli");
        std::fs::write(
            &script,
            r#"#!/bin/sh
base=$(dirname "$0")
printf '%s\n' "$*" >> "$base/calls"
case "$*" in
 'radio wifi') cat "$base/radio";;
 *'DEVICE,TYPE,STATE device status') cat "$base/devices";;
 '--get-values GENERAL.CON-UUID device show wlan7') echo active-uuid;;
 '--escape no --get-values 802-11-wireless.ssid connection show uuid active-uuid')
   test -f "$base/profile" || exit 1
   cat "$base/profile";;
 *'device wifi list ifname wlan7 --rescan no') cat "$base/scan";;
 '--get-values IP4.ADDRESS device show wlan7') echo 192.168.2.2/24;;
 *) exit 1;;
esac
"#,
        )
        .unwrap();
        std::fs::set_permissions(&script, std::fs::Permissions::from_mode(0o700)).unwrap();
        std::fs::write(tmp.path().join("radio"), "enabled\n").unwrap();
        std::fs::write(tmp.path().join("devices"), "wlan7:wifi:connected\n").unwrap();
        std::fs::write(tmp.path().join("scan"), "").unwrap();
        std::fs::write(tmp.path().join("profile"), " Home:Office\\WiFi \n").unwrap();
        let status = wifi_status_using(script.as_os_str()).unwrap();
        assert!(status.connected);
        assert_eq!(status.ssid, " Home:Office\\WiFi ");
        assert_eq!(status.ip, "192.168.2.2");
        assert!(!std::fs::read_to_string(tmp.path().join("calls"))
            .unwrap()
            .contains("device wifi list"));

        std::fs::remove_file(tmp.path().join("profile")).unwrap();
        std::fs::write(
            tmp.path().join("scan"),
            " :AA\\:BB:Home:100:WPA2\n*:AA\\:CC:Home:67:WPA2\n",
        )
        .unwrap();
        let status = wifi_status_using(script.as_os_str()).unwrap();
        assert_eq!(status.connection_label(), "Home");
        std::fs::write(tmp.path().join("scan"), "").unwrap();
        let status = wifi_status_using(script.as_os_str()).unwrap();
        assert!(status.connected);
        assert_eq!(status.connection_label(), "Name unavailable");
        assert_eq!(status.ip, "192.168.2.2");

        std::fs::write(tmp.path().join("devices"), "wlan7:wifi:disconnected\n").unwrap();
        let status = wifi_status_using(script.as_os_str()).unwrap();
        assert!(!status.connected);
        assert_eq!(status.connection_label(), "Not connected");
        assert!(status.ip.is_empty());
        std::fs::write(tmp.path().join("radio"), "disabled\n").unwrap();
        assert_eq!(
            wifi_status_using(script.as_os_str())
                .unwrap()
                .connection_label(),
            "Wi-Fi off"
        );
    }

    #[test]
    fn initial_status_does_not_report_radio_off() {
        let mut menu = Menu::new();
        let (rows, selected) = menu.rows();
        assert!(rows.contains(&"Wi-Fi: Checking...".into()));
        assert!(!rows
            .iter()
            .any(|row| row.contains("off") || row.contains("Off")));
        assert_eq!(selected, None);
        let (tx, rx) = mpsc::channel();
        menu.job = Some(rx);
        tx.send(ResultJob::Status(Ok(WifiStatus {
            enabled: true,
            connected: true,
            ssid: "Home".into(),
            ip: "192.168.2.2".into(),
        })))
        .unwrap();
        menu.poll();
        assert!(menu.rows().0.contains(&"Wi-Fi: On".into()));
    }

    #[test]
    fn overview_uses_native_setting_labels_and_does_not_toggle_with_a() {
        let mut menu = Menu::new();
        menu.job = None;
        menu.wifi_known = true;
        menu.wifi = WifiStatus {
            enabled: true,
            connected: true,
            ssid: "Home:Office".into(),
            ip: "192.168.2.2".into(),
        };
        assert_eq!(menu.labels()[1], "Wi-Fi");
        assert_eq!(menu.toggle_value(), Some(slot_ui::QuickValue::On));
        assert_eq!(menu.values()[0], (2, "Home:Office".into()));
        menu.button(slot_input::Btn::A);
        assert!(menu.job.is_none());
        let (_tx, rx) = mpsc::channel();
        menu.job = Some(rx);
        menu.button(slot_input::Btn::Down);
        assert_eq!(
            menu.selected_row(),
            Some(4),
            "status refresh swallowed navigation"
        );
    }

    #[test]
    fn wifi_has_only_radio_and_picker_and_sharing_opens_directly() {
        let mut menu = Menu::new();
        menu.wifi_known = true;
        menu.button(slot_input::Btn::Down);
        assert_eq!(menu.selected_row(), Some(4));
        menu.button(slot_input::Btn::Down);
        assert_eq!(menu.selected_row(), Some(1));
        assert!(!menu
            .labels()
            .iter()
            .any(|s| s == "SSH" || s == "File Sharing"));
        let mut direct = Menu::sharing();
        assert!(direct.job.is_none());
        assert_eq!(direct.labels()[0], "File Sharing");
        assert!(direct.button(slot_input::Btn::B));
    }

    #[test]
    fn keyboard_masks_password_and_backspaces() {
        let mut menu = Menu {
            overview: false,
            overview_selected: 0,
            sharing: None,
            usb: None,
            usb_network: None,
            ssh: None,
            services: None,
            wifi: WifiStatus::default(),
            wifi_known: false,
            changing_wifi: false,
            refreshed: std::time::Instant::now(),
            aps: vec![AccessPoint {
                bssid: "AA:BB:CC:DD:EE:FF".into(),
                ssid: "Home".into(),
                signal: 90,
                security: "WPA2".into(),
                connected: false,
            }],
            selected: 0,
            keyboard: slot_ui::Keyboard::new(64, true),
            editing: true,
            status: String::new(),
            job: None,
        };
        for _ in 0..6 {
            menu.keyboard.apply(slot_ui::KeyboardAction::Add);
        }
        assert_eq!(menu.keyboard.value(), "aaaaaa");
        assert_eq!(menu.keyboard_view().unwrap().labels[2].text, "••••••|");
        assert_eq!(menu.legend()[0].label, "Show");
        menu.button(slot_input::Btn::X);
        assert_eq!(menu.keyboard_view().unwrap().labels[2].text, "aaaaaa|");
        assert_eq!(menu.legend()[0].label, "Hide");
        menu.button(slot_input::Btn::X);
        assert_eq!(menu.keyboard_view().unwrap().labels[2].text, "••••••|");
        assert!(menu.legend().iter().any(|hint| hint.key == "START"));
        assert!(!menu.rows().0.iter().any(|row| row.starts_with("A:")));

        menu.button(slot_input::Btn::Y);
        assert_eq!(menu.keyboard.value(), "aaaaa");
        menu.button(slot_input::Btn::R1);
        menu.button(slot_input::Btn::A);
        assert_eq!(menu.keyboard.value(), "aaaaaA");
        menu.button(slot_input::Btn::B);
        assert!(menu.keyboard.value().is_empty());
        assert!(!menu.editing);
        menu.button(slot_input::Btn::A);
        assert!(menu.editing);
        assert_eq!(menu.legend()[0].label, "Show");
    }

    #[test]
    fn overview_shows_connection_and_back_returns_from_picker() {
        let mut menu = Menu::new();
        menu.job = None;
        menu.wifi_known = true;
        menu.wifi = WifiStatus {
            enabled: true,
            connected: true,
            ssid: "Home:Office".into(),
            ip: "192.168.2.2".into(),
        };
        let rows = menu.rows().0;
        assert!(rows.contains(&"Connected: Home:Office".into()));
        assert!(rows.contains(&"IP: 192.168.2.2".into()));
        menu.overview = false;
        assert!(!menu.button(slot_input::Btn::B));
        assert!(menu.overview);
        assert!(menu.button(slot_input::Btn::B));
    }

    #[cfg(unix)]
    #[test]
    fn scan_distinguishes_unavailable_adapter_failed_scan_and_empty_results() {
        use std::os::unix::fs::PermissionsExt;
        let tmp = tempfile::tempdir().unwrap();
        for (state, scan_exit, scan_output, expected) in [
            ("20 (unavailable)", 0, "", Some("adapter unavailable")),
            ("30 (disconnected)", 1, "", Some("scan failed")),
            ("30 (disconnected)", 0, "", None),
            ("100 (connected)", 0, "unparseable", Some("scan results")),
        ] {
            let script = tmp.path().join(format!(
                "nmcli-{}-{}-{}",
                state,
                scan_exit,
                scan_output.len()
            ));
            let body = format!("#!/bin/sh\nif [ \"$1\" = --terse ]; then echo wlan7:wifi:disconnected; exit 0; fi\nif [ \"$1\" = --get-values ]; then echo '{state}'; exit 0; fi\nprintf '%s' '{scan_output}'\nexit {scan_exit}\n");
            std::fs::write(&script, body).unwrap();
            std::fs::set_permissions(&script, std::fs::Permissions::from_mode(0o700)).unwrap();
            match expected {
                Some(message) => {
                    let error = scan_using(script.as_os_str()).unwrap_err();
                    assert!(error.contains(message), "expected {message}, got {error}");
                }
                None => assert!(scan_using(script.as_os_str()).unwrap().is_empty()),
            }
        }
    }

    #[cfg(unix)]
    #[test]
    fn password_uses_stdin_and_connection_errors_are_sanitized() {
        use std::os::unix::fs::PermissionsExt;
        let tmp = tempfile::tempdir().unwrap();
        let script = tmp.path().join("nmcli");
        std::fs::write(&script, "#!/bin/sh\nbase=$(dirname \"$0\")\nif [ \"$1\" = --ask ]; then\n printf '%s\\n' \"$@\" > \"$base/args\"\n cat > \"$base/stdin\"\n echo secret-debug-message >&2\n exit 1\nfi\n").unwrap();
        std::fs::set_permissions(&script, std::fs::Permissions::from_mode(0o700)).unwrap();
        let ap = AccessPoint {
            bssid: "AA:BB:CC:DD:EE:FF".into(),
            ssid: "Home".into(),
            signal: 90,
            security: "WPA2".into(),
            connected: false,
        };
        let password = "test'$();password";
        let error = connect_using(script.as_os_str(), &ap, password).unwrap_err();
        assert!(!std::fs::read_to_string(tmp.path().join("args"))
            .unwrap()
            .contains(password));
        assert_eq!(
            std::fs::read_to_string(tmp.path().join("stdin")).unwrap(),
            format!("{password}\n")
        );
        assert!(!error.contains("secret-debug-message"));
    }

    #[cfg(unix)]
    #[test]
    fn manual_password_replaces_only_the_selected_personal_profiles_cached_secret() {
        use std::os::unix::fs::PermissionsExt;
        let tmp = tempfile::tempdir().unwrap();
        let program = tmp.path().join("nmcli");
        let busctl = tmp.path().join("busctl");
        std::fs::write(&program, r#"#!/bin/sh
base=$(dirname "$0")
case "$1" in
 --terse)
  printf '%s\n' 'other:802-11-wireless:/org/freedesktop/NetworkManager/Settings/1' 'bound:802-11-wireless:/org/freedesktop/NetworkManager/Settings/2' 'chosen:802-11-wireless:/org/freedesktop/NetworkManager/Settings/3'
  ;;
 --escape)
  case "$*" in
   *'uuid other') printf 'Other network\n\nwpa-psk\n' ;;
   *'uuid bound') printf 'Home:Office\n11:22:33:44:55:66\nwpa-psk\n' ;;
   *'uuid chosen') printf 'Home:Office\n\nwpa-psk\n' ;;
  esac
  ;;
 --ask)
  test -f "$base/cleared" || exit 8
  printf '%s\n' "$@" > "$base/args"
  cat > "$base/input"
  exit 1
  ;;
esac
"#).unwrap();
        std::fs::write(
            &busctl,
            r#"#!/bin/sh
base=$(dirname "$0")
printf '%s\n' "$@" > "$base/clear-args"
touch "$base/cleared"
"#,
        )
        .unwrap();
        for p in [&program, &busctl] {
            std::fs::set_permissions(p, std::fs::Permissions::from_mode(0o700)).unwrap();
        }
        let ap = AccessPoint {
            bssid: "AA:BB:CC:DD:EE:FF".into(),
            ssid: "Home:Office".into(),
            signal: 100,
            security: "WPA2 WPA3".into(),
            connected: false,
        };
        let password = "  new'$();\\password  ";
        assert!(
            connect_using_tools(program.as_os_str(), busctl.as_os_str(), &ap, password).is_err()
        );
        assert_eq!(
            std::fs::read_to_string(tmp.path().join("input")).unwrap(),
            format!("{password}\n")
        );
        let args = std::fs::read_to_string(tmp.path().join("args")).unwrap();
        assert!(args.contains("connection\nup\nuuid\nchosen\nap\nAA:BB:CC:DD:EE:FF"));
        assert!(!args.contains(password));
        let clear = std::fs::read_to_string(tmp.path().join("clear-args")).unwrap();
        assert!(clear.contains("/org/freedesktop/NetworkManager/Settings/3\n"));
        assert!(clear.contains("ClearSecrets"));
        assert!(!clear.contains(password));

        // A failed clear must not fall back to silently reusing the cached key.
        std::fs::remove_file(tmp.path().join("input")).unwrap();
        std::fs::write(&busctl, "#!/bin/sh\nexit 1\n").unwrap();
        let error = connect_using_tools(program.as_os_str(), busctl.as_os_str(), &ap, password)
            .unwrap_err();
        assert!(error.contains("Could not update saved Wi-Fi password"));
        assert!(!tmp.path().join("input").exists());
    }

    #[test]
    fn escaped_names_and_addresses_are_preserved() {
        let aps = parse_scan("*:AA\\:BB\\:CC\\:DD\\:EE\\:FF:Home\\:Office\\\\WiFi:91:WPA2\n :11\\:22\\:33\\:44\\:55\\:66:Guest:50:--");
        assert_eq!(aps[0].ssid, "Home:Office\\WiFi");
        assert_eq!(aps[0].bssid, "AA:BB:CC:DD:EE:FF");
        assert!(aps[0].connected);
        assert_eq!(aps.len(), 2);
    }
}
