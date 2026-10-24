//! On-demand safe removal of secondary SD cards, plus optional maintenance.
use slot_input::Btn;
use std::{
    collections::BTreeMap,
    process::Command,
    sync::mpsc::{self, Receiver},
};
type Reply = Result<BTreeMap<String, String>, String>;
fn job(action: &'static str, slot: String, token: String) -> Receiver<Reply> {
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let result = (|| {
            let mut command = Command::new("/usr/bin/slot-sd-library");
            command.arg(action).current_dir("/");
            if action == "ui-save-location" {
                command.arg(slot);
            } else if action != "ui-refresh" {
                command.arg(slot).arg(token);
            }
            let output = command.output().map_err(|_| "Card tools unavailable")?;
            if output.stdout.len() > 8192 {
                return Err("Card response too large".into());
            }
            let values: BTreeMap<String, String> = String::from_utf8_lossy(&output.stdout)
                .lines()
                .filter_map(|s| s.split_once('\t'))
                .map(|(k, v)| {
                    (
                        k.into(),
                        v.chars().filter(|c| !c.is_control()).take(240).collect(),
                    )
                })
                .collect();
            if values.get("protocol").map(String::as_str) != Some("1") {
                return Err("Card tools unavailable".into());
            }
            Ok(values)
        })();
        let _ = tx.send(result);
    });
    rx
}
#[derive(Clone)]
struct Card {
    slot: String,
    state: String,
    token: String,
    action: String,
}
pub struct Menu {
    cards: Vec<Card>,
    maintenance: bool,
    save_location: Option<String>,
    tools: Option<crate::storage_tools::Menu>,
    selected: usize,
    confirm: bool,
    job: Option<Receiver<Reply>>,
    busy: bool,
    message: String,
}
impl Menu {
    pub fn open(features: crate::features::Features) -> Self {
        let external = features.has("external-sd");
        Self {
            cards: if external {
                ["TF1", "TF2"]
                    .into_iter()
                    .map(|s| Card {
                        slot: s.into(),
                        state: "Checking...".into(),
                        token: String::new(),
                        action: String::new(),
                    })
                    .collect()
            } else {
                vec![]
            },
            maintenance: features.has("storage-tools"),
            save_location: external.then(|| "System".into()),
            tools: None,
            selected: 0,
            confirm: false,
            job: external.then(|| job("ui-refresh", String::new(), String::new())),
            busy: false,
            message: "A ejects a card, or mounts it again.".into(),
        }
    }
    pub fn settings_info(&self) -> Option<crate::settings_info::Info> {
        (!self.busy
            && !self.confirm
            && self.job.is_none()
            && self.tools.is_none()
            && self.selected == self.cards.len()
            && self.save_location.is_some())
        .then_some(crate::settings_info::Info::SAVE_LOCATION)
    }
    pub fn locked(&self) -> bool {
        self.busy || self.tools.as_ref().is_some_and(|m| m.locked())
    }
    pub fn poll(&mut self) {
        if let Some(tools) = &mut self.tools {
            tools.poll();
            return;
        }
        let result = match self.job.as_ref().map(|r| r.try_recv()) {
            Some(Ok(v)) => v,
            Some(Err(mpsc::TryRecvError::Disconnected)) => Err("Card worker interrupted".into()),
            _ => return,
        };
        self.job = None;
        self.busy = false;
        match result {
            Err(e) => self.message = e,
            Ok(v) => {
                if let Some(location) = v
                    .get("save_location")
                    .filter(|s| matches!(s.as_str(), "System" | "Game"))
                {
                    self.save_location = Some(location.clone());
                }
                for (i, card) in self.cards.iter_mut().enumerate() {
                    if let Some(state) = v.get(&format!("state_{i}")) {
                        card.state = state.clone();
                        card.token = v.get(&format!("token_{i}")).cloned().unwrap_or_default();
                        card.action = v.get(&format!("action_{i}")).cloned().unwrap_or_default();
                    }
                }
                self.message = v
                    .get("message")
                    .cloned()
                    .unwrap_or_else(|| "A ejects a card, or mounts it again.".into());
            }
        }
    }
    fn begin(&mut self) {
        let Some(card) = self.cards.get(self.selected) else {
            return;
        };
        let action = match card.action.as_str() {
            "eject" => "ui-eject",
            "mount" => "ui-mount",
            _ => return,
        };
        self.busy = true;
        self.message = if action == "ui-eject" {
            "Ejecting card..."
        } else {
            "Mounting card..."
        }
        .into();
        self.job = Some(job(action, card.slot.clone(), card.token.clone()));
    }
    pub fn button(&mut self, b: Btn) -> bool {
        if let Some(tools) = &mut self.tools {
            if tools.button(b) {
                self.tools = None;
            }
            return false;
        }
        if self.busy {
            return false;
        }
        if self.confirm {
            if b == Btn::B {
                self.confirm = false;
            }
            if b == Btn::A {
                self.confirm = false;
                self.begin();
            }
            return false;
        }
        if b == Btn::B {
            return true;
        }
        if self.job.is_some() {
            return false;
        }
        let save_row = self.cards.len();
        let maintenance_row = save_row + usize::from(self.save_location.is_some());
        let count = maintenance_row + usize::from(self.maintenance);
        match b {
            Btn::Up if count > 0 => self.selected = (self.selected + count - 1) % count,
            Btn::Down if count > 0 => self.selected = (self.selected + 1) % count,
            Btn::A | Btn::Left | Btn::Right
                if self.selected == save_row && self.save_location.is_some() =>
            {
                let next = if self.save_location.as_deref() == Some("System") {
                    "game"
                } else {
                    "system"
                };
                self.busy = true;
                self.message = "Changing save location...".into();
                self.job = Some(job("ui-save-location", next.into(), String::new()));
            }
            Btn::A if self.selected == maintenance_row && self.maintenance => {
                self.tools = Some(crate::storage_tools::Menu::open())
            }
            Btn::A => {
                if let Some(card) = self.cards.get(self.selected) {
                    match card.action.as_str() {
                        "eject" => self.confirm = true,
                        "mount" => self.begin(),
                        _ => self.message = card.state.clone(),
                    }
                }
            }
            Btn::X if !self.cards.is_empty() => {
                self.job = Some(job("ui-refresh", String::new(), String::new()))
            }
            _ => {}
        }
        false
    }
    pub fn selected_row(&self) -> Option<usize> {
        if let Some(tools) = &self.tools {
            return tools.selected_row();
        }
        if self.busy || self.confirm {
            None
        } else {
            Some(self.selected + 1)
        }
    }
    pub fn legend(&self) -> Vec<slot_ui::Hint> {
        if let Some(tools) = &self.tools {
            return tools.legend();
        }
        if self.busy {
            vec![]
        } else if self.confirm {
            slot_ui::hint_row(&[("B", "Cancel"), ("A", "Eject")])
        } else if self.job.is_some() {
            slot_ui::hint_row(&[("B", "Back")])
        } else {
            if self.selected == self.cards.len() && self.save_location.is_some() {
                slot_ui::hint_row(&[("B", "Back"), ("<>", "Change"), ("Y", "Info")])
            } else {
                slot_ui::hint_row(&[("B", "Back"), ("A", "Select"), ("X", "Refresh")])
            }
        }
    }
    pub fn rows(&self) -> Vec<String> {
        if let Some(tools) = &self.tools {
            return tools.rows();
        }
        if self.confirm {
            return vec![
                format!("Eject {}?", self.cards[self.selected].slot),
                "Games on this card will leave the shelf.".into(),
                "Wait for Safe to remove, then remove it.".into(),
                "You can also mount it again here.".into(),
            ];
        }
        let mut rows = vec!["Storage".into()];
        rows.extend(
            self.cards
                .iter()
                .map(|c| format!("{}: {}", c.slot, c.state)),
        );
        if let Some(location) = &self.save_location {
            rows.push(format!("Save location: {location}"));
        }
        if self.maintenance {
            rows.push("Check/Repair Storage".into());
        }
        rows.push(String::new());
        let mut line = String::new();
        let help =
            if self.selected == self.cards.len() && self.save_location.is_some() && !self.busy {
                if self.save_location.as_deref() == Some("Game") {
                    "Saves and States stay with each game's library."
                } else {
                    "Saves and States use this system's SLOT storage."
                }
            } else {
                &self.message
            };
        for word in help.split_whitespace() {
            if line.len() + word.len() + 1 > 42 && !line.is_empty() {
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
    fn menu(state: &str, action: &str) -> Menu {
        Menu {
            cards: vec![Card {
                slot: "TF1".into(),
                state: state.into(),
                token: "a".repeat(64),
                action: action.into(),
            }],
            maintenance: true,
            save_location: Some("System".into()),
            tools: None,
            selected: 0,
            confirm: false,
            job: None,
            busy: false,
            message: String::new(),
        }
    }
    #[test]
    fn info_is_only_available_on_ready_save_location() {
        let mut m = menu("Mounted", "eject");
        assert!(m.settings_info().is_none());
        m.button(Btn::Down);
        assert_eq!(
            m.settings_info(),
            Some(crate::settings_info::Info::SAVE_LOCATION)
        );
        assert!(m.legend().iter().any(|h| h.key == "Y" && h.label == "Info"));
        let before = m.rows();
        m.button(Btn::Y);
        assert_eq!(m.rows(), before);
        m.busy = true;
        assert!(m.settings_info().is_none());
        m.busy = false;
        m.confirm = true;
        assert!(m.settings_info().is_none());
        m.confirm = false;
        let (_tx, rx) = mpsc::channel();
        m.job = Some(rx);
        assert!(m.settings_info().is_none());
        assert!(!m.legend().iter().any(|h| h.label == "Info"));
    }
    #[test]
    fn save_location_is_between_cards_and_maintenance() {
        let mut m = menu("Mounted", "eject");
        assert_eq!(m.rows()[2], "Save location: System");
        m.button(Btn::Down);
        assert_eq!(m.selected_row(), Some(2));
        assert!(m.rows().iter().any(|s| s.contains("this system")));
        m.button(Btn::Down);
        assert_eq!(m.selected_row(), Some(3));
        assert_eq!(m.rows()[3], "Check/Repair Storage");
    }
    #[test]
    fn eject_requires_confirmation_and_cancel_does_no_work() {
        let mut m = menu("Mounted", "eject");
        m.button(Btn::A);
        assert!(m.confirm);
        assert!(m.job.is_none());
        m.button(Btn::B);
        assert!(!m.confirm);
        assert!(m.job.is_none());
    }
    #[test]
    fn protected_disk_cannot_start_eject() {
        let mut m = menu("System disk - protected", "");
        m.button(Btn::A);
        assert!(!m.confirm);
        assert!(m.job.is_none());
        assert_eq!(m.message, "System disk - protected");
    }
    #[test]
    fn busy_cannot_close_or_restart() {
        let mut m = menu("Mounted", "eject");
        m.busy = true;
        for b in [Btn::A, Btn::B, Btn::X, Btn::Down] {
            assert!(!m.button(b));
        }
        assert_eq!(m.selected, 0);
        assert!(m.legend().is_empty());
    }
    #[test]
    fn result_updates_cards_and_safe_to_remove_text() {
        let mut m = menu("Mounted", "eject");
        let (tx, rx) = mpsc::channel();
        m.job = Some(rx);
        m.busy = true;
        tx.send(Ok([
            ("protocol", "1"),
            ("state_0", "Safe to remove"),
            ("action_0", "mount"),
            ("token_0", "abc"),
            ("message", "TF1 is safe to remove"),
        ]
        .into_iter()
        .map(|(k, v)| (k.into(), v.into()))
        .collect()))
            .unwrap();
        m.poll();
        assert!(!m.locked());
        assert_eq!(m.cards[0].action, "mount");
        assert!(m.rows().contains(&"TF1: Safe to remove".into()));
    }
}
