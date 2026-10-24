//! Documentation captures through the real frontend, using a read-only library and isolated progress.
//! This example is mounted into a prepared workspace; it is never firmware code.
use slot::{audio::StubSink, frontend::Frontend, screenshots};
use slot_gfx::{Compositor, SdlSurface, Surface};
use slot_input::{Btn, InputSource, Millis, RawEvent};
use slot_power::SimPlatform;
use slot_store::{write_slot_state, Platform, SlotState};
use slot_ui::QuickRow;
use std::{fs, path::{Path, PathBuf}, time::Duration};

struct Input(Vec<RawEvent>);
impl InputSource for Input {
    fn poll(&mut self, _: Millis) -> Vec<RawEvent> { std::mem::take(&mut self.0) }
}
struct Ui { f: Frontend, c: Compositor, s: SdlSurface, now: u64, out: PathBuf }
impl Ui {
    fn step(&mut self, events: Vec<RawEvent>) {
        self.now += 16;
        self.f.advance_at(&mut Input(events), self.now, 1.0 / 60.0);
        self.f.render(&mut self.c, (640, 480));
        self.s.swap().unwrap();
        self.f.frame_presented();
        self.f.finish_boot_assets(&mut self.c);
        std::thread::sleep(Duration::from_millis(2));
    }
    fn wait(&mut self, n: usize) { for _ in 0..n { self.step(vec![]); } }
    fn wait_realtime(&mut self, duration: Duration) {
        let until = std::time::Instant::now() + duration;
        while std::time::Instant::now() < until { self.step(vec![]); }
    }
    fn tap(&mut self, b: Btn) {
        self.step(vec![RawEvent::Down(b)]); self.step(vec![RawEvent::Up(b)]);
    }
    fn home(&mut self) { for _ in 0..12 { self.tap(Btn::B); } self.wait(30); }
    fn open(&mut self, row: QuickRow) {
        self.home(); self.tap(Btn::Menu);
        let mut chain = vec![row];
        while let Some(parent) = chain.last().unwrap().parent() { chain.push(parent); }
        for target in chain.into_iter().rev() {
            for _ in 0..QuickRow::ALL.len() {
                if self.f.app().quick_menu() == Some(target) { break; }
                self.tap(Btn::Down);
            }
            assert_eq!(self.f.app().quick_menu(), Some(target), "navigation to {target:?}");
            if target != row { self.tap(Btn::A); }
        }
        self.wait(30);
    }
    fn shot(&mut self, name: &str) {
        self.wait(24);
        self.f.render(&mut self.c, (640, 480));
        self.write_frame(name);
    }
    fn write_frame(&mut self, name: &str) {
        type Read = unsafe extern "C" fn(i32, i32, i32, i32, u32, u32, *mut std::ffi::c_void);
        let read: Read = unsafe { std::mem::transmute(self.s.proc_address("glReadPixels")) };
        let mut px = vec![0u8; 640 * 480 * 4];
        unsafe { read(0, 0, 640, 480, 0x1908, 0x1401, px.as_mut_ptr().cast()); }
        let top: Vec<u8> = px.chunks_exact(640 * 4).rev().flatten().copied().collect();
        if name != "gallery-image-hidden" && !name.starts_with("game-") {
            assert!(top.chunks_exact(4).filter(|p| p[0] > 180 && p[1] > 180 && p[2] > 180).count() > 40, "missing text: {name}");
        }
        assert!(top.chunks_exact(4).filter(|p| p[0] > 40 || p[1] > 40 || p[2] > 40).count() > 200, "empty capture: {name}");
        if name.starts_with("game-") {
            // A game need not contain white text. Check the game viewport,
            // excluding its bottom logo, so a black game with a bezel fails.
            assert!(top[..640*420*4].chunks_exact(4).filter(|p|p[0]>40||p[1]>40||p[2]>40).count()>5000,"empty game viewport: {name}");
        }
        let mut enc = png::Encoder::new(fs::File::create(self.out.join(format!("{name}.png"))).unwrap(), 640, 480);
        enc.set_color(png::ColorType::Rgba);
        enc.write_header().unwrap().write_image_data(&top).unwrap();
        println!("Captured {name}");
    }
    fn enter(&mut self, row: QuickRow, name: &str) { self.open(row); self.tap(Btn::A); self.wait(80); self.shot(name); }
    fn transfer(&mut self, name: &str, lines: &[&str], phase: &str) {
        // Same menu-face, line positioning and footer as usb_storage::screen;
        // only its status input is an isolated documentation fixture.
        let mut draws=vec![];
        for (i,line) in std::iter::once(&"USB Storage").chain(lines.iter()).enumerate() {
            let face=slot_ui::menu_face(line);
            let id=self.c.create_texture(face.w,face.h,&face.rgba);
            slot_ui::draw_menu_line((id,face.w,face.h),14.0+i as f32*43.0,43.0,false,&mut draws);
        }
        self.c.fit((640,480)); self.c.begin_frame(); self.c.draw_list(&draws); self.c.end_frame((640,480));
        if let Some(label)=slot::usb_storage::transfer_legend(phase) {
            let face=slot_ui::hint_face("B",label);
            let id=self.c.create_texture(face.w,face.h,&face.rgba);
            let mut legend=vec![]; slot_ui::draw_menu_legend(&[(id,face.w)],&mut legend);
            self.c.draw_footer_overlay((640,480),&legend);
        }
        self.write_frame(name);
    }
}
fn capture_updates(u: &mut Ui) -> Result<(), Box<dyn std::error::Error>> {
    u.enter(QuickRow::Updates, "updates");
    fs::write("/tmp/slot-doc-ota-phase", "waiting")?;
    u.enter(QuickRow::Updates,"updates-waiting-internet");
    fs::write("/tmp/slot-doc-ota-phase", "paused")?;
    u.wait_realtime(Duration::from_secs(3)); u.shot("updates-resume");
    fs::write("/tmp/slot-doc-ota-phase", "health")?;
    u.wait_realtime(Duration::from_secs(3)); u.shot("updates-startup-check");
    fs::remove_file("/tmp/slot-doc-ota-phase")?;
    u.wait_realtime(Duration::from_secs(3)); u.shot("updates-complete");
    Ok(())
}
const ZELDA: &str = "The Legend of Zelda - A Link To The Past";
const GOLDEN: &str = "Golden Sun - The Lost Age";
const METROID: &str = "Metroid - Fusion";
fn prepare_library(root: &Path, library: &Path) -> Result<(), Box<dyn std::error::Error>> {
    use std::os::unix::fs::symlink;
    for (platform,names) in [
        (Platform::Gba,vec![ZELDA,METROID,GOLDEN]),
        (Platform::Gb,vec!["Legend of Zelda - Link's Awakening"]),
        (Platform::Gbc,vec!["Legend of Zelda, The - Link's Awakening DX","Legend of Zelda, The - Oracle of Ages"]),
    ] {
        let p=platform.dir_name();
        fs::create_dir_all(root.join("Games").join(p))?;
        fs::create_dir_all(root.join("Labels").join(p))?;
        fs::create_dir_all(root.join("Saves").join(p))?;
        for name in names {
            let rom=platform.extensions().iter().map(|ext|library.join("Games").join(p).join(format!("{name}.{ext}"))).find(|p|p.is_file()).expect("Missing selected game");
            let art=library.join("Labels").join(p).join(format!("{name}.png"));
            assert!(rom.is_file() && art.is_file(),"Missing game/art for {name}");
            symlink(&rom,root.join("Games").join(p).join(rom.file_name().unwrap()))?;
            symlink(art,root.join("Labels").join(p).join(format!("{name}.png")))?;
            let save=library.join("Saves").join(p).join(format!("{name}.sav"));
            if save.is_file() {fs::copy(save,root.join("Saves").join(p).join(format!("{name}.sav")))?;}
            let resume=library.join("States").join(p).join("mgba").join(name).join(if name==GOLDEN {"2026-10-19_11-17-16.state"} else {"resume.state"});
            if resume.is_file() {
                let dest=root.join("States").join(p).join("mgba").join(name);
                fs::create_dir_all(&dest)?; fs::copy(resume,dest.join("resume.state"))?;
            }
        }
    }
    fs::remove_dir(root.join("BIOS"))?;
    symlink(library.join("BIOS"),root.join("BIOS"))?;
    Ok(())
}
fn gallery_image(root: &Path, platform: Platform, title: &str, png: &Path, index: usize) {
    let dest=root.join("Screenshots").join(platform.dir_name()).join(screenshots::component(title));
    fs::create_dir_all(&dest).unwrap();
    fs::copy(png,dest.join(format!("2026-10-22_12-00-{index:02}.png"))).unwrap();
}
fn capture_settings_info(u: &mut Ui, root: &Path, state: &SlotState, stamp: i64) -> Result<(), Box<dyn std::error::Error>> {
        for (row, name) in [
            (QuickRow::SchedutilGovernor, "info-governor"),
            (QuickRow::EnhancedAudio, "info-enhanced-audio"),
            (QuickRow::RunAhead, "info-run-ahead"),
            (QuickRow::OverlayStyle, "info-overlay-style"),
            (QuickRow::UsbNetwork, "info-usb-network"),
            (QuickRow::FeatureInGameShader, "info-in-game-shaders"),
        ] {
            u.open(row); u.shot(&format!("{name}-hint"));
            let value = u.f.app().quick_value(row);
            u.tap(Btn::Y); u.shot(name);
            assert!(!u.f.app().settings_info_rows().is_empty());
            u.tap(Btn::B);
            assert_eq!(u.f.app().quick_menu(), Some(row));
            assert_eq!(u.f.app().quick_value(row), value);
        }
        u.enter(QuickRow::StorageTools, "storage-top");
        u.tap(Btn::Down); u.tap(Btn::Down); u.wait(60);
        u.tap(Btn::Y); u.shot("info-save-location");
        assert!(u.f.app().settings_info_rows()[0].contains("Save location"));
        u.tap(Btn::B); u.home();
        let mut play=state.clone(); play.cart=Some(ZELDA.into()); play.cart_platform=Some(Platform::Gba);
        write_slot_state(root,&play)?;
        u.f=Frontend::boot_with(Box::new(SimPlatform::at(root.into()).stopped_at(stamp)),Box::new(StubSink::draining()));
        u.f.upload_faces(&mut u.c); u.wait(400);
        u.tap(Btn::Menu); u.wait(60); u.tap(Btn::Down); u.tap(Btn::Down); u.tap(Btn::A);
        assert_eq!(u.f.app().input_context(),slot_input::Context::Menu);
        // Settings / Screen / GBA shader: real paused-game input path.
        u.tap(Btn::A); u.tap(Btn::A);
        u.tap(Btn::Y); u.shot("info-paused-game");
        assert!(!u.f.app().settings_info_rows().is_empty());
        u.tap(Btn::B);
    write_slot_state(root, state)?;
    u.f=Frontend::boot_with(Box::new(SimPlatform::at(root.into()).stopped_at(stamp)),Box::new(StubSink::draining()));
    u.f.upload_faces(&mut u.c); u.wait(100);
    Ok(())
}
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let out = PathBuf::from(std::env::args().nth(1).expect("output directory")); fs::create_dir_all(&out)?;
    let root = tempfile::tempdir()?;
    for name in slot::root::DIRS { fs::create_dir_all(root.path().join(name))?; }
    let library=PathBuf::from(std::env::var("WIKI_LIBRARY").expect("Read-only game library is required"));
    prepare_library(root.path(),&library)?;
    let surface = SdlSurface::new()?;
    let compositor = Compositor::new(&surface)?;
    let stamp = slot_store::days_from_civil(2026,10,22)*86400+16*3600;
    let mut f = Frontend::boot_with(Box::new(SimPlatform::at(root.path().into()).stopped_at(stamp)),Box::new(StubSink::draining()));
    let mut c = compositor; f.upload_faces(&mut c);
    let mut u = Ui {f,c,s:surface,now:0,out}; u.wait(20); u.shot("clock-setup");
    let mut state = SlotState {clock_set:true, utc_offset_min:-240, game_border:true,
        perfect_overlay:true, perfect_shader_gba:Some(slot_store::Shader::Shimmerless), show_fps:false,
        ..Default::default()};
    state.toggle_favorite(Platform::Gba,ZELDA);
    state.toggle_favorite(Platform::Gba,METROID);
    state.toggle_favorite(Platform::Gba,GOLDEN);
    state.shelf=Some("gba".into());
    state.shelf_cart=Some(slot_store::Recent {platform:Platform::Gba,stem:ZELDA.into()});
    write_slot_state(root.path(),&state)?;
    u.f = Frontend::boot_with(Box::new(SimPlatform::at(root.path().into()).stopped_at(stamp)),Box::new(StubSink::draining()));
    u.f.upload_faces(&mut u.c); u.wait(100); u.shot("shelf");
    if std::env::var_os("WIKI_ONLY_OTA").is_none() {
        capture_settings_info(&mut u, root.path(), &state, stamp)?;
        if std::env::var_os("WIKI_ONLY_INFO").is_some() { return Ok(()); }
    }
    if std::env::var_os("WIKI_ONLY_OTA").is_some() {
        capture_updates(&mut u)?;
        return Ok(());
    }
    for (row,name) in [
        (QuickRow::Appearance,"settings"), (QuickRow::WallpaperDimming,"appearance"),
        (QuickRow::Brightness,"screen"), (QuickRow::GbaShader,"screen-gba"),
        (QuickRow::GbcShader,"screen-gbc"), (QuickRow::GbShader,"screen-gb"),
        (QuickRow::OverlayStyle,"overlays"), (QuickRow::EnhancedAudio,"audio"),
        (QuickRow::RunAhead,"game"), (QuickRow::ControlsInGame,"controls"),
        (QuickRow::GameA,"controls-game"), (QuickRow::ScScreenshot,"controls-shortcuts"),
        (QuickRow::ShelfFavorite,"controls-shelf"), (QuickRow::Network,"connections"),
        (QuickRow::UsbNetwork,"usb"), (QuickRow::DateTime,"system"),
        (QuickRow::SchedutilGovernor,"cpu-governor"),
        (QuickRow::Diagnostics,"system-bottom"), (QuickRow::FeatureStateBrowser,"features"),
        (QuickRow::FeatureInGameColor,"features-in-game"),
        (QuickRow::ScreenshotShaders,"screenshots"), (QuickRow::SetClock,"date-time"),
        (QuickRow::Gallery,"settings-gallery"),
    ] {
        u.open(row); u.shot(name);
        if row == QuickRow::SchedutilGovernor {
            assert!(!u.f.app().schedutil_governor());
            u.tap(Btn::Right); assert!(u.f.app().schedutil_governor());
            u.shot("cpu-governor-on");
            u.tap(Btn::Left); assert!(!u.f.app().schedutil_governor());
        }
    }
    for (row,name) in [
        (QuickRow::Network,"wifi"), (QuickRow::Sharing,"file-sharing"),
        (QuickRow::Ssh,"ssh"), (QuickRow::UsbNetwork,"usb-network"),
        (QuickRow::UsbStorage,"usb-storage"), (QuickRow::StorageTools,"storage"),
        (QuickRow::Diagnostics,"diagnostics"), (QuickRow::Updates,"updates"),
        (QuickRow::Help,"help"), (QuickRow::Content,"content"),
        (QuickRow::About,"about"),
    ] {u.enter(row,name);}
    capture_updates(&mut u)?;
    u.enter(QuickRow::StorageTools,"storage-top");
    u.tap(Btn::Down); u.tap(Btn::Down); u.wait(60);
    assert!(u.f.app().diagnostics_view().iter().any(|s|s=="Save location: System"));
    u.shot("storage-system"); u.tap(Btn::A); u.wait(120);
    assert!(u.f.app().diagnostics_view().iter().any(|s|s=="Save location: Game"));
    u.shot("storage-game"); u.tap(Btn::A); u.wait(120);
    u.transfer("usb-storage-waiting",&["Waiting for computer...","Use the DC USB-C data port","Allow USB access if prompted"],"waiting");
    u.transfer("usb-storage-connected",&["Connected to computer","Open SLOT on your computer","","Eject SLOT before unplugging","Slot resumes after ejecting"],"shared");
    u.enter(QuickRow::Network,"wifi-status"); u.tap(Btn::Down); u.tap(Btn::A); u.wait(80); u.shot("wifi-networks");
    u.tap(Btn::A); u.shot("wifi-password");
    u.enter(QuickRow::Ssh,"ssh"); u.tap(Btn::Down); u.tap(Btn::A); u.shot("ssh-set-password");
    u.enter(QuickRow::Diagnostics,"diagnostics"); u.tap(Btn::A); u.shot("diagnostics-versions");
    u.tap(Btn::B); u.tap(Btn::Down); u.tap(Btn::A); u.wait(60);
    assert!(u.f.app().diagnostics_view().iter().any(|s|s=="File Sharing: active"));
    u.shot("diagnostics-services");
    u.enter(QuickRow::StorageTools,"storage"); u.tap(Btn::A); u.shot("storage-eject");
    u.open(QuickRow::GameA); u.tap(Btn::A); u.shot("controls-recording"); u.tap(Btn::Menu);
    u.home();
    for (index,(platform,title,name)) in [
        (Platform::Gba,ZELDA,"game-zelda"),
        (Platform::Gba,METROID,"game-metroid-fusion"),
        (Platform::Gba,GOLDEN,"game-golden-sun-battle"),
        (Platform::Gb,"Legend of Zelda - Link's Awakening","game-zelda-gb"),
        (Platform::Gbc,"Legend of Zelda, The - Link's Awakening DX","game-zelda-gbc"),
    ].into_iter().enumerate() {
        let mut play=state.clone(); play.cart=Some(title.into()); play.cart_platform=Some(platform);
        play.perfect_overlay=platform==Platform::Gba;
        play.shader_gb=slot_store::Shader::ShimmerlessLcd;
        play.shader_gbc=Some(slot_store::Shader::ShimmerlessLcd);
        write_slot_state(root.path(),&play)?;
        u.f=Frontend::boot_with(Box::new(SimPlatform::at(root.path().into()).stopped_at(stamp)),Box::new(StubSink::draining()));
        u.f.upload_faces(&mut u.c); u.wait(if title==METROID {1200} else {400});
        assert!(matches!(u.f.app().phase(),slot::app::Phase::Playing {..}),"Actual core failed: {title}");
        if title==METROID {u.tap(Btn::Start);u.wait(600);u.tap(Btn::Start);u.wait_realtime(Duration::from_secs(5));}
        u.shot(name);
        if title == ZELDA {
            u.step(vec![RawEvent::Down(Btn::Power)]); u.wait(75);
            u.step(vec![RawEvent::Up(Btn::Power)]); u.wait(30);
            u.shot("power-menu-game"); u.tap(Btn::B); u.wait(30);
        }
        gallery_image(root.path(),platform,title,&u.out.join(format!("{name}.png")),index);
        u.step(vec![RawEvent::Down(Btn::Menu)]);u.wait(75);u.step(vec![RawEvent::Up(Btn::Menu)]);u.wait(100);
    }
    write_slot_state(root.path(),&state)?;
    u.f=Frontend::boot_with(Box::new(SimPlatform::at(root.path().into()).stopped_at(stamp)),Box::new(StubSink::draining()));
    u.f.upload_faces(&mut u.c);u.wait(100);
    u.enter(QuickRow::Gallery,"gallery-grid-date");
    u.tap(Btn::R1); u.wait(80); u.shot("gallery-grid-platform");
    u.tap(Btn::R1); u.wait(80); u.shot("gallery-grid-game");
    u.tap(Btn::A); u.wait(80); u.shot("gallery-image");
    u.wait(160); u.shot("gallery-image-hidden");
    u.tap(Btn::X); u.wait(80); u.shot("gallery-delete"); u.tap(Btn::B);
    u.home();
    let mut favorites=state.clone();
    favorites.shelf=Some("favorites".into());
    favorites.shelf_cart=Some(slot_store::Recent {platform:Platform::Gba,stem:ZELDA.into()});
    write_slot_state(root.path(),&favorites)?;
    u.f = Frontend::boot_with(Box::new(SimPlatform::at(root.path().into()).stopped_at(stamp)),Box::new(StubSink::draining()));
    u.f.upload_faces(&mut u.c); u.wait(100); u.shot("favorites");
    write_slot_state(root.path(),&state)?;
    u.f = Frontend::boot_with(Box::new(SimPlatform::at(root.path().into()).stopped_at(stamp)),Box::new(StubSink::draining()));
    u.f.upload_faces(&mut u.c); u.wait(100);
    u.tap(Btn::A); u.wait(200); u.shot("game-slot-overlay");
    u.step(vec![RawEvent::Down(Btn::Select)]); u.tap(Btn::R1);
    u.step(vec![RawEvent::Up(Btn::Select)]); u.wait(100);
    u.tap(Btn::Menu); u.wait(12); u.shot("pause");
    u.tap(Btn::Down); u.tap(Btn::A); u.wait(20); u.shot("states");
    u.tap(Btn::Y); u.shot("states-delete"); u.tap(Btn::B);
    // All disposable content, saves and state outputs remain in TempDir.
    println!("Guide captures complete; read-only games/art, isolated progress and stub audio; no live services accessed.");
    Ok(())
}
