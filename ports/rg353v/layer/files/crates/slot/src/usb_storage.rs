//! Content handoff to a USB host; the service owns all filesystem transitions.
use slot_input::Btn;
use std::process::Command;
use std::sync::mpsc::{self, Receiver};

pub struct Menu {
    job: Option<Receiver<Result<(), String>>>,
    message: String,
    starting: bool,
}
impl Menu {
    pub fn open() -> Self {
        Self {
            job: None,
            message: String::new(),
            starting: false,
        }
    }
    pub fn poll(&mut self) {
        if let Some(job) = &self.job {
            match job.try_recv() {
                Ok(result) => {
                    self.job = None;
                    self.starting = result.is_ok();
                    self.message = result
                        .err()
                        .unwrap_or_else(|| "Preparing USB storage...".into());
                }
                Err(mpsc::TryRecvError::Empty) => {}
                Err(mpsc::TryRecvError::Disconnected) => {
                    self.job = None;
                    self.starting = false;
                    self.message = "USB storage could not start".into();
                }
            }
        }
    }
    pub fn button(&mut self, button: Btn) -> bool {
        if self.busy() {
            return false;
        }
        if button == Btn::B {
            return true;
        }
        if button == Btn::A {
            let (tx, rx) = mpsc::channel();
            self.job = Some(rx);
            self.starting = true;
            self.message = "Preparing USB storage...".into();
            std::thread::spawn(move || {
                let result = Command::new("/usr/bin/slot-usb-storage")
                    .arg("start")
                    .output()
                    .map_err(|_| "USB storage is available on the handheld".to_string())
                    .and_then(|out| {
                        if out.status.success() {
                            Ok(())
                        } else {
                            let text = String::from_utf8_lossy(&out.stderr);
                            Err(text
                                .lines()
                                .last()
                                .unwrap_or("Could not start USB storage")
                                .chars()
                                .take(80)
                                .collect())
                        }
                    });
                let _ = tx.send(result);
            });
        }
        false
    }
    pub fn busy(&self) -> bool {
        self.starting || self.job.is_some()
    }
    pub fn labels(&self) -> Vec<String> {
        [
            "USB Storage",
            "Connect to computer",
            "",
            "Games, saves and wallpapers",
            "Slot pauses during file transfer",
            "Safely eject SLOT on your computer",
            &self.message,
        ]
        .iter()
        .map(|s| s.to_string())
        .collect()
    }
    pub fn selected_row(&self) -> Option<usize> {
        (!self.busy()).then_some(1)
    }
    pub fn legend(&self) -> Vec<slot_ui::Hint> {
        slot_ui::hint_row(if self.busy() {
            &[]
        } else {
            &[("B", "Back"), ("A", "Connect")]
        })
    }
}

impl Default for Menu {
    fn default() -> Self {
        Self::open()
    }
}

pub fn transfer_legend(phase: &str) -> Option<&'static str> {
    match phase.trim() {
        "waiting" => Some("Cancel"),
        "shared" => Some("Finish"),
        _ => None,
    }
}

#[cfg(feature = "rg353v")]
pub fn screen() -> Result<(), Box<dyn std::error::Error>> {
    use slot_gfx::{Compositor, SdlSurface, Surface};
    use slot_input::{InputSource, RawEvent};
    use std::{
        path::Path,
        time::{Duration, Instant},
    };
    let root = Path::new("/run/slot-usb");
    let mut surface = SdlSurface::new()?;
    let mut compositor = Compositor::new(&surface)?;
    let window = surface.window_size();
    compositor.set_full_panel(true);
    let mut input = crate::input::DeviceInput::open(root);
    let mut previous = String::new();
    let mut faces = Vec::new();
    let mut textures = Vec::new();
    let hints: Vec<_> = ["Cancel", "Finish"]
        .into_iter()
        .map(|label| {
            let face = slot_ui::hint_face("B", label);
            let id = compositor.create_texture(face.w, face.h, &face.rgba);
            (id, face.w)
        })
        .collect();
    let began = Instant::now();
    while root.join("active").exists() {
        let status = std::fs::read_to_string(root.join("status")).unwrap_or_default();
        if status != previous {
            faces.clear();
            for (i, line) in std::iter::once("USB Storage")
                .chain(status.lines().take(6))
                .enumerate()
            {
                let mut text = line.to_string();
                let mut face = slot_ui::menu_face(&text);
                while face.w > slot_ui::OUT_W - 40 && !text.is_empty() {
                    text.pop();
                    face = slot_ui::menu_face(&format!("{text}..."));
                }
                let id = if let Some(&id) = textures.get(i) {
                    compositor.update_texture(id, face.w, face.h, &face.rgba);
                    id
                } else {
                    let id = compositor.create_texture(face.w, face.h, &face.rgba);
                    textures.push(id);
                    id
                };
                faces.push((id, face.w, face.h));
            }
            previous = status;
        }
        for event in input.poll(began.elapsed().as_millis() as u64) {
            if event == RawEvent::Down(Btn::B) {
                let _ = std::fs::write(root.join("cancel"), b"cancel\n");
            }
        }
        let mut draws = Vec::new();
        for (i, face) in faces.iter().enumerate() {
            slot_ui::draw_menu_line(*face, 14.0 + i as f32 * 43.0, 43.0, false, &mut draws);
        }
        compositor.fit(window);
        compositor.begin_frame();
        compositor.draw_list(&draws);
        compositor.end_frame(window);
        let mut legend = Vec::new();
        let phase = std::fs::read_to_string(root.join("phase")).unwrap_or_default();
        if let Some(label) = transfer_legend(&phase) {
            let index = usize::from(label == "Finish");
            slot_ui::draw_menu_legend(&[hints[index]], &mut legend);
        }
        compositor.draw_footer_overlay(window, &legend);
        surface.swap()?;
        std::fs::write(root.join("screen-ready"), b"ready\n")?;
        std::thread::sleep(Duration::from_millis(80));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    #[test]
    fn waiting_can_cancel_but_shared_requires_finishing() {
        assert_eq!(super::transfer_legend("waiting\n"), Some("Cancel"));
        assert_eq!(super::transfer_legend("shared\n"), Some("Finish"));
        for phase in ["", "preparing", "restoring", "unknown"] {
            assert_eq!(super::transfer_legend(phase), None);
        }
    }
}
