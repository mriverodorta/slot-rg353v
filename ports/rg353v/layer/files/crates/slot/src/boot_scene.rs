//! CPU-only startup overlaps SDL/DRM. Device handles, audio and all texture
//! uploads remain on their original threads; no core is opened here.
use crate::{app::App, cart_faces::CartFaces};
use std::{
    path::PathBuf,
    thread::{self, JoinHandle},
};

pub struct Scene(JoinHandle<(App, CartFaces)>);
impl Scene {
    pub fn start(root: PathBuf) -> Option<Self> {
        thread::Builder::new()
            .name("slot-boot-scene".into())
            .spawn(move || {
                let library = crate::boot_library::Scan::start(&root);
                let app = App::boot_with_library(&root, library);
                let mut faces = CartFaces::spawn(root);
                faces.prepare(&app);
                crate::boot_time::mark("scene pixels queued");
                (app, faces)
            })
            .ok()
            .map(Self)
    }
    pub(crate) fn finish(self) -> Option<(App, CartFaces)> {
        // Thread start/join failure uses the ordinary fresh synchronous path.
        self.0.join().ok()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::app::Phase;
    use slot_store::{Platform, Recent, SlotState};
    fn library(root: &std::path::Path) {
        crate::root::ensure(root);
        for platform in Platform::ALL {
            for n in 0..10 {
                let ext = platform.dir_name().to_ascii_lowercase();
                std::fs::write(
                    root.join("Games")
                        .join(platform.dir_name())
                        .join(format!("Game {n:02}.{ext}")),
                    vec![0; 0x150],
                )
                .unwrap();
            }
        }
    }
    #[test]
    fn threaded_scene_preserves_browsed_recents_favorites_and_console_selection() {
        let dir = tempfile::tempdir().unwrap();
        library(dir.path());
        for shelf in ["gb", "gbc", "gba", "recents", "favorites"] {
            let cart = Recent {
                platform: Platform::Gbc,
                stem: "Game 05".into(),
            };
            let state = SlotState {
                clock_set: true,
                shelf: Some(shelf.into()),
                shelf_cart: Some(cart.clone()),
                recents: vec![cart.clone()],
                favorites: vec![cart],
                ..SlotState::default()
            };
            slot_store::write_slot_state(dir.path(), &state).unwrap();
            let (actual, _faces) = Scene::start(dir.path().into()).unwrap().finish().unwrap();
            let serial = App::boot(dir.path());
            assert_eq!(actual.selected_stem(), serial.selected_stem());
            assert_eq!(actual.face_wants(), serial.face_wants());
            for want in actual.face_wants() {
                assert_eq!(
                    actual.face_cart(want.shelf, want.index),
                    serial.face_cart(want.shelf, want.index)
                );
            }
            assert!(matches!(actual.phase(), Phase::Shelf));
            assert_eq!(slot_store::read_slot_state(dir.path()), state);
        }
    }
    #[test]
    fn fresh_clock_and_game_resume_stay_in_their_original_phase() {
        let dir = tempfile::tempdir().unwrap();
        library(dir.path());
        let (actual, _faces) = Scene::start(dir.path().into()).unwrap().finish().unwrap();
        assert!(matches!(
            actual.phase(),
            Phase::SetClock {
                from_menu: false,
                ..
            }
        ));
        let state = SlotState {
            clock_set: true,
            cart: Some("Game 05".into()),
            cart_platform: Some(Platform::Gba),
            ..SlotState::default()
        };
        slot_store::write_slot_state(dir.path(), &state).unwrap();
        let (actual, _faces) = Scene::start(dir.path().into()).unwrap().finish().unwrap();
        assert!(matches!(actual.phase(), Phase::Inserting { .. }));
        assert_eq!(actual.selected_stem(), Some("Game 05"));
        // App preparation opens no emulation core and writes no save/state data.
        assert_eq!(slot_store::read_slot_state(dir.path()), state);
    }
    #[test]
    fn failed_preparation_is_discarded_for_the_serial_fallback() {
        let scene = Scene(thread::spawn(|| panic!("injected boot worker failure")));
        assert!(scene.finish().is_none());
    }
}
