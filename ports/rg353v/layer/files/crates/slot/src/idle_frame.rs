//! Compare the complete CPU scene before issuing any GL draw or display swap.
use slot_gfx::Draw;

#[derive(Clone, Copy, PartialEq, Debug)]
pub struct State {
    pub window: (u32, u32),
    pub texture_epoch: u64,
    pub blue_light: u8,
    pub screen_power: f32,
    pub shake: f32,
    pub lift: f32,
    pub split: Option<f32>,
}

#[derive(Default)]
pub struct IdleFrame {
    state: Option<State>,
    scene: Vec<Draw>,
    overlay: Vec<Draw>,
    footer: Vec<Draw>,
}

impl IdleFrame {
    pub fn reset(&mut self) {
        self.state = None;
    }

    /// False means the existing scanout is already the requested complete image.
    /// All other phases (including emulation) always draw. Exact comparisons
    /// preserve animation steps; texture generations detect in-place uploads.
    pub fn changed(
        &mut self,
        shelf: bool,
        state: State,
        scene: &[Draw],
        overlay: &[Draw],
        footer: &[Draw],
    ) -> bool {
        if !shelf {
            self.reset();
            return true;
        }
        if self.state == Some(state)
            && self.scene == scene
            && self.overlay == overlay
            && self.footer == footer
        {
            return false;
        }
        self.state = Some(state);
        self.scene.clear();
        self.scene.extend_from_slice(scene);
        self.overlay.clear();
        self.overlay.extend_from_slice(overlay);
        self.footer.clear();
        self.footer.extend_from_slice(footer);
        true
    }
}
