//! SDL2 owns the EGL/GBM/KMS lifecycle on mainline Linux handhelds.
//! It is loaded at runtime, like the existing fbdev EGL and ALSA backends.
use std::time::Instant;

use std::ffi::{c_char, c_int, c_void, CStr, CString};

use libloading::Library;

use crate::{GfxError, Surface};

type Ptr = *mut c_void;
const SDL_INIT_VIDEO: u32 = 0x20;
const SDL_WINDOW_OPENGL: u32 = 0x2;
const SDL_WINDOW_FULLSCREEN_DESKTOP: u32 = 0x1001;
const SDL_WINDOWPOS_UNDEFINED: i32 = 0x1fff0000;
const SDL_GL_CONTEXT_MAJOR_VERSION: i32 = 17;
const SDL_GL_CONTEXT_MINOR_VERSION: i32 = 18;
const SDL_GL_CONTEXT_PROFILE_MASK: i32 = 21;
const SDL_GL_CONTEXT_PROFILE_ES: i32 = 4;

struct Sdl {
    set_hint: unsafe extern "C" fn(*const c_char, *const c_char) -> c_int,
    init: unsafe extern "C" fn(u32) -> c_int,
    quit: unsafe extern "C" fn(u32),
    error: unsafe extern "C" fn() -> *const c_char,
    driver: unsafe extern "C" fn() -> *const c_char,
    attribute: unsafe extern "C" fn(c_int, c_int) -> c_int,
    window: unsafe extern "C" fn(*const c_char, c_int, c_int, c_int, c_int, u32) -> Ptr,
    destroy_window: unsafe extern "C" fn(Ptr),
    create_context: unsafe extern "C" fn(Ptr) -> Ptr,
    delete_context: unsafe extern "C" fn(Ptr),
    make_current: unsafe extern "C" fn(Ptr, Ptr) -> c_int,
    drawable_size: unsafe extern "C" fn(Ptr, *mut c_int, *mut c_int),
    swap_interval: unsafe extern "C" fn(c_int) -> c_int,
    swap_window: unsafe extern "C" fn(Ptr),
    proc_address: unsafe extern "C" fn(*const c_char) -> *const c_void,
    pump_events: unsafe extern "C" fn(),
    flush_events: unsafe extern "C" fn(u32, u32),
    _lib: Library,
}

impl Sdl {
    fn load() -> Result<Self, GfxError> {
        let lib = unsafe { Library::new("libSDL2-2.0.so.0") }
            .or_else(|_| unsafe { Library::new("libSDL2.so") })
            .map_err(|e| GfxError::Context(format!("SDL2: {e}")))?;
        macro_rules! get {
            ($name:literal) => {
                *lib.get(concat!($name, "\0").as_bytes())
                    .map_err(|e| GfxError::Context(format!("{}: {e}", $name)))?
            };
        }
        unsafe {
            Ok(Self {
                set_hint: get!("SDL_SetHint"),
                init: get!("SDL_InitSubSystem"),
                quit: get!("SDL_QuitSubSystem"),
                error: get!("SDL_GetError"),
                driver: get!("SDL_GetCurrentVideoDriver"),
                attribute: get!("SDL_GL_SetAttribute"),
                window: get!("SDL_CreateWindow"),
                destroy_window: get!("SDL_DestroyWindow"),
                create_context: get!("SDL_GL_CreateContext"),
                delete_context: get!("SDL_GL_DeleteContext"),
                make_current: get!("SDL_GL_MakeCurrent"),
                drawable_size: get!("SDL_GL_GetDrawableSize"),
                swap_interval: get!("SDL_GL_SetSwapInterval"),
                swap_window: get!("SDL_GL_SwapWindow"),
                proc_address: get!("SDL_GL_GetProcAddress"),
                pump_events: get!("SDL_PumpEvents"),
                flush_events: get!("SDL_FlushEvents"),
                _lib: lib,
            })
        }
    }

    fn fail(&self, what: &str) -> GfxError {
        let message = unsafe { (self.error)() };
        let message = if message.is_null() {
            "unknown SDL error".into()
        } else {
            unsafe { CStr::from_ptr(message) }.to_string_lossy()
        };
        GfxError::Context(format!("{what}: {message}"))
    }
}

pub struct SdlSurface {
    sdl: Sdl,
    window: Ptr,
    context: Ptr,
    size: (u32, u32),
}

impl SdlSurface {
    /// Keep SDL's unused event queue drained even when scanout is unchanged.
    pub fn pump_events(&mut self) {
        unsafe {
            (self.sdl.pump_events)();
            (self.sdl.flush_events)(0, 0xffff);
        }
    }

    pub fn new() -> Result<Self, GfxError> {
        let start = Instant::now();
        let phase = |name: &str| {
            eprintln!(
                "slot: graphics: {name} at {:.3} ms",
                start.elapsed().as_secs_f64() * 1000.0
            );
        };
        let sdl = Sdl::load()?;
        phase("library loaded");
        // DeviceInput owns input, and swap() discards SDL's unused events.
        // SDL's default SIGTERM/SIGINT handlers turn termination into SDL_QUIT;
        // discarding that event would prevent the process from stopping.
        if unsafe { (sdl.set_hint)(c"SDL_NO_SIGNAL_HANDLERS".as_ptr(), c"1".as_ptr()) } == 0 {
            return Err(GfxError::Context(
                "SDL2 could not disable its signal handlers".into(),
            ));
        }
        if unsafe { (sdl.init)(SDL_INIT_VIDEO) } != 0 {
            return Err(sdl.fail("SDL_InitSubSystem(video)"));
        }
        phase("video initialized");
        // Establish ownership immediately so every subsequent error cleans up.
        let mut surface = Self {
            sdl,
            window: std::ptr::null_mut(),
            context: std::ptr::null_mut(),
            size: (0, 0),
        };
        let sdl = &surface.sdl;
        for (attribute, value) in [
            (SDL_GL_CONTEXT_PROFILE_MASK, SDL_GL_CONTEXT_PROFILE_ES),
            (SDL_GL_CONTEXT_MAJOR_VERSION, 2),
            (SDL_GL_CONTEXT_MINOR_VERSION, 0),
            (0, 8), // SDL_GL_RED_SIZE
            (1, 8), // SDL_GL_GREEN_SIZE
            (2, 8), // SDL_GL_BLUE_SIZE
            (5, 1), // SDL_GL_DOUBLEBUFFER
            (6, 0), // SDL_GL_DEPTH_SIZE
            (7, 0), // SDL_GL_STENCIL_SIZE
        ] {
            if unsafe { (sdl.attribute)(attribute, value) } != 0 {
                return Err(sdl.fail("SDL_GL_SetAttribute"));
            }
        }
        surface.window = unsafe {
            (sdl.window)(
                c"slot".as_ptr(),
                SDL_WINDOWPOS_UNDEFINED,
                SDL_WINDOWPOS_UNDEFINED,
                640,
                480,
                SDL_WINDOW_OPENGL | SDL_WINDOW_FULLSCREEN_DESKTOP,
            )
        };
        if surface.window.is_null() {
            return Err(sdl.fail("SDL_CreateWindow"));
        }
        phase("window created");
        surface.context = unsafe { (sdl.create_context)(surface.window) };
        if surface.context.is_null() {
            return Err(sdl.fail("SDL_GL_CreateContext"));
        }
        phase("context created");
        surface.make_current()?;
        phase("context current");
        let sdl = &surface.sdl;
        let (mut width, mut height) = (0, 0);
        unsafe { (sdl.drawable_size)(surface.window, &mut width, &mut height) };
        if width <= 0 || height <= 0 {
            return Err(GfxError::Context("SDL2 returned an empty drawable".into()));
        }
        surface.size = (width as u32, height as u32);
        if unsafe { (sdl.swap_interval)(1) } != 0 {
            eprintln!(
                "slot: {} (continuing with software pacing)",
                sdl.fail("vsync")
            );
        }
        let driver = unsafe { (sdl.driver)() };
        if !driver.is_null() {
            eprintln!(
                "slot: SDL2 video {}",
                unsafe { CStr::from_ptr(driver) }.to_string_lossy()
            );
        }
        phase("drawable and vsync ready");
        Ok(surface)
    }
}

impl Surface for SdlSurface {
    fn make_current(&mut self) -> Result<(), GfxError> {
        if unsafe { (self.sdl.make_current)(self.window, self.context) } != 0 {
            return Err(self.sdl.fail("SDL_GL_MakeCurrent"));
        }
        Ok(())
    }

    fn window_size(&self) -> (u32, u32) {
        self.size
    }

    fn swap(&mut self) -> Result<(), GfxError> {
        unsafe {
            (self.sdl.swap_window)(self.window);
            (self.sdl.pump_events)();
            // DeviceInput owns evdev input. Drain SDL's unused event queue.
            (self.sdl.flush_events)(0, 0xffff);
        }
        Ok(())
    }

    fn proc_address(&self, name: &str) -> *const c_void {
        let Ok(name) = CString::new(name) else {
            return std::ptr::null();
        };
        unsafe { (self.sdl.proc_address)(name.as_ptr()) }
    }
}

impl Drop for SdlSurface {
    fn drop(&mut self) {
        unsafe {
            if !self.context.is_null() {
                (self.sdl.make_current)(self.window, std::ptr::null_mut());
                (self.sdl.delete_context)(self.context);
            }
            if !self.window.is_null() {
                (self.sdl.destroy_window)(self.window);
            }
            (self.sdl.quit)(SDL_INIT_VIDEO);
        }
    }
}
