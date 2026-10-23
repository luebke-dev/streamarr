//! Spike 05 (ADR 003): the window's Wayland handles, read from inside the running app.
//!
//! This is the first increment of the spike and deliberately the smallest one: it proves
//! that the app can obtain the `wl_surface` and `wl_display` of **its own** window, which
//! every later step depends on. No rendering, no libmpv, no new protocol bindings — if this
//! prints addresses, question 1 of ADR 003 is answered for the app rather than for a
//! documentation page.
//!
//! Behind the `spike-render` feature, so it never reaches a package.

use raw_window_handle::{HasDisplayHandle, HasWindowHandle, RawDisplayHandle, RawWindowHandle};
#[cfg(feature = "spike-render")]
use wayland_client::protocol::wl_surface::WlSurface;

/// What the spike learned about this window.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WindowHandles {
    pub surface: usize,
    pub display: usize,
    pub width: u32,
    pub height: u32,
}

/// Reads the Wayland surface and display of a window.
///
/// Returns an error on any other backend instead of pretending: the whole plan (ADR 003)
/// rests on Wayland subsurfaces, so an X11 or Windows window is a different question.
pub fn read_handles<W>(window: &W, size: (u32, u32)) -> Result<WindowHandles, String>
where
    W: HasWindowHandle + HasDisplayHandle,
{
    let handle = window.window_handle().map_err(|e| e.to_string())?.as_raw();
    let display = window.display_handle().map_err(|e| e.to_string())?.as_raw();

    let RawWindowHandle::Wayland(surface) = handle else {
        return Err(format!("kein Wayland-Fenster, sondern {handle:?}"));
    };
    let RawDisplayHandle::Wayland(display) = display else {
        return Err(format!("keine Wayland-Anzeige, sondern {display:?}"));
    };

    Ok(WindowHandles {
        surface: surface.surface.as_ptr() as usize,
        display: display.display.as_ptr() as usize,
        width: size.0,
        height: size.1,
    })
}

/// Adopts the app's own Wayland connection and hands back a proxy for its surface.
///
/// This is the step the whole plan rests on: if the backend cannot take over the display
/// Tauri is using, nothing else matters — the render API needs a `wl_surface` of *this*
/// window, and a second connection to the compositor would not help.
///
/// `Backend::from_foreign_display` runs in "guest" mode: dropping it does not close the
/// connection, which is what we want — Tauri owns the display and must keep it.
#[cfg(feature = "spike-render")]
pub fn adopt_connection(
    handles: &WindowHandles,
) -> Result<(wayland_client::Connection, WlSurface), String> {
    use wayland_client::backend::ObjectId;
    use wayland_client::Proxy;

    let display = handles.display as *mut _;
    let surface = handles.surface as *mut _;

    // SAFETY: both pointers come from `raw_window_handle` for this very window and stay
    // valid as long as the window lives; the guest backend does not close them.
    let backend = unsafe { wayland_backend::sys::client::Backend::from_foreign_display(display) };
    let connection = wayland_client::Connection::from_backend(backend);

    // SAFETY: the interface description is the generated one for `wl_surface`, and the
    // pointer belongs to the display we just adopted.
    // SAFETY: as above; the interface description matches the pointer we obtained.
    let id = unsafe { ObjectId::from_ptr(WlSurface::interface(), surface) }
        .map_err(|e| format!("ungültige Oberfläche: {e:?}"))?;
    let proxy = WlSurface::from_id(&connection, id).map_err(|e| e.to_string())?;
    Ok((connection, proxy))
}

/// The Wayland plumbing the subsurface needs.
///
/// `probe_globals` and `show_magenta_patch` share one `Dispatch` state on purpose: the
/// boilerplate is the expensive part, and a state that can do both is what the production
/// code will need anyway.
#[cfg(feature = "spike-render")]
mod wayland {
    use super::{adopt_connection, WindowHandles};
    use std::io::Write;
    use std::os::fd::AsFd;
    use wayland_client::globals::{registry_queue_init, GlobalListContents};
    use wayland_client::protocol::{
        wl_buffer::WlBuffer, wl_callback::WlCallback, wl_compositor::WlCompositor,
        wl_registry::WlRegistry,
        wl_shm::{Format, WlShm}, wl_shm_pool::WlShmPool, wl_subcompositor::WlSubcompositor,
        wl_subsurface::WlSubsurface, wl_surface::WlSurface,
    };
    use wayland_client::{Connection, Dispatch, Proxy, QueueHandle};

    pub struct State;

    impl Dispatch<WlRegistry, GlobalListContents> for State {
        fn event(
            _: &mut Self,
            _: &WlRegistry,
            _: <WlRegistry as Proxy>::Event,
            _: &GlobalListContents,
            _: &Connection,
            _: &QueueHandle<Self>,
        ) {
        }
    }

    // Every interface we touch needs its own empty `Dispatch`. Three lines each beats
    // thirty, and it documents exactly which interfaces the spike uses.
    macro_rules! ignore {
        ($($iface:ty),* $(,)?) => {$(
            impl Dispatch<$iface, ()> for State {
                fn event(
                    _: &mut Self,
                    _: &$iface,
                    _: <$iface as Proxy>::Event,
                    _: &(),
                    _: &Connection,
                    _: &QueueHandle<Self>,
                ) {
                }
            }
        )*};
    }
    ignore!(
        WlCompositor,
        WlSubcompositor,
        WlShm,
        WlShmPool,
        WlBuffer,
        WlSurface,
        WlSubsurface,
        WlCallback
    );

    /// Binds the three globals the subsurface needs.
    pub(super) fn bind(
        handles: &WindowHandles,
    ) -> Result<
        (
            Connection,
            wayland_client::EventQueue<State>,
            WlCompositor,
            WlSubcompositor,
            WlShm,
            WlSurface,
        ),
        String,
    > {
        let (connection, parent) = adopt_connection(handles)?;
        let (globals, queue) =
            registry_queue_init::<State>(&connection).map_err(|e| e.to_string())?;
        let qh = queue.handle();

        let compositor: WlCompositor = globals
            .bind(&qh, 4..=6, ())
            .map_err(|e| format!("wl_compositor: {e}"))?;
        let subcompositor: WlSubcompositor = globals
            .bind(&qh, 1..=1, ())
            .map_err(|e| format!("wl_subcompositor: {e}"))?;
        let shm: WlShm = globals.bind(&qh, 1..=1, ()).map_err(|e| format!("wl_shm: {e}"))?;
        Ok((connection, queue, compositor, subcompositor, shm, parent))
    }

    pub fn probe_globals(handles: &WindowHandles) -> Result<String, String> {
        let (_, _, compositor, subcompositor, shm, _) = bind(handles)?;
        let _ = (compositor, subcompositor, shm);
        Ok("compositor, subcompositor und shm gebunden".to_string())
    }

    /// Puts a magenta `wl_shm` subsurface **above** the app's own surface.
    ///
    /// Above, not below, and on purpose: this half proves the infrastructure — child
    /// surface, shared memory buffer, commit, stacking — without changing a single line of
    /// app configuration. If magenta covers part of the window, the remaining question is
    /// only *which way round* the stacking goes, and that is where `transparent: true`
    /// enters as its own deliberate change.
    pub fn show_magenta_patch(handles: &WindowHandles) -> Result<String, String> {
        let (width, height) = (400i32, 300i32);
        let stride = width * 4;
        let size = (stride * height) as usize;

        let (connection, mut queue, compositor, subcompositor, shm, parent) = bind(handles)?;
        let qh = queue.handle();

        // A file in the runtime dir, unlinked immediately: the compositor only needs the
        // descriptor. Cheap, `libc`-free, and exactly what a real renderer will do later
        // with a dmabuf instead.
        let dir = std::env::var("XDG_RUNTIME_DIR").unwrap_or_else(|_| "/tmp".into());
        let path = format!("{dir}/streamarr-spike-shm-{}", std::process::id());
        let mut file = std::fs::File::options()
            .read(true)
            .write(true)
            .create_new(true)
            .open(&path)
            .map_err(|e| format!("Pufferdatei {path}: {e}"))?;
        let _ = std::fs::remove_file(&path);
        file.set_len(size as u64).map_err(|e| e.to_string())?;

        let mut pixels = vec![0u8; size];
        for pixel in pixels.chunks_exact_mut(4) {
            pixel.copy_from_slice(&[0xff, 0x00, 0xff, 0xff]); // BGRA
        }
        file.write_all(&pixels).map_err(|e| e.to_string())?;

        let pool: WlShmPool = shm.create_pool(file.as_fd(), size as i32, &qh, ());
        let buffer = pool.create_buffer(0, width, height, stride, Format::Argb8888, &qh, ());

        let child = compositor.create_surface(&qh, ());
        let subsurface = subcompositor.get_subsurface(&child, &parent, &qh, ());
        subsurface.set_position(0, 0);
        // Below now: the point of the whole exercise. Above was proven first.
        subsurface.place_below(&parent);

        child.attach(Some(&buffer), 0, 0);
        child.damage_buffer(0, 0, width, height);
        child.commit();
        connection.flush().map_err(|e| e.to_string())?;
        queue.roundtrip(&mut State).map_err(|e| e.to_string())?;
        queue.roundtrip(&mut State).map_err(|e| e.to_string())?;

        // The objects must outlive the function; in a throwaway probe leaking them is the
        // honest option — dropping would send destroy requests and remove the patch.
        std::mem::forget((pool, buffer, child, subsurface));
        Ok(format!("magenta Patch {width}x{height} unter der WebView gesetzt"))
    }
}

#[cfg(feature = "spike-render")]
pub use wayland::{probe_globals, show_magenta_patch};

#[cfg(test)]
mod tests {
    use super::*;

    // The function cannot be exercised without a real window, but the shape it returns is
    // what the next step consumes — a compile-time check is still worth having, and the
    // struct must stay copyable and comparable for logging.
    #[test]
    fn the_handles_are_plain_numbers_that_can_be_logged() {
        let handles = WindowHandles {
            surface: 0x55d0,
            display: 0x55c0,
            width: 1920,
            height: 1080,
        };
        let copy = handles.clone();
        assert_eq!(handles, copy);
        assert_ne!(handles.surface, 0);
        assert_ne!(handles.display, 0);
    }
}

/// Creates **our own** EGL context on the display Tauri is already using.
///
/// Question (c)/(d) of ADR 003: libmpv's render API draws through *our* GL context, so that
/// context has to exist next to WebKit's and share the same Wayland display. A pbuffer is
/// enough to answer whether that works at all — it needs no `wl_egl_window` and no swap
/// loop, so a failure here is about EGL, not about presentation.
#[cfg(feature = "spike-render")]
pub fn probe_egl(handles: &WindowHandles) -> Result<String, String> {
    use khronos_egl as egl;
    use std::ffi::c_void;

    let display_ptr = handles.display as *mut c_void;
    // `EGL_PLATFORM_WAYLAND_KHR`, straight from the Khronos registry: the crate does not
    // export the platform constants.
    const PLATFORM_WAYLAND_KHR: egl::Enum = 0x31d8;

    // SAFETY: loading libEGL and handing it the same display Tauri uses.
    let egl = unsafe { egl::DynamicInstance::<egl::EGL1_5>::load_required_from_filename("libEGL.so.1") }
        .map_err(|e| format!("libEGL nicht ladbar: {e}"))?;
    let display = unsafe {
        egl.get_platform_display(
            PLATFORM_WAYLAND_KHR,
            display_ptr,
            // The platform display takes no surface attributes — those belong in
            // `choose_first_config`. Passing them here is answered with `BadAttribute`,
            // which is what the first run of this probe measured.
            &[egl::ATTRIB_NONE],
        )
    }
    .map_err(|e| format!("get_platform_display: {e:?}"))?;
    egl.initialize(display)
        .map_err(|e| format!("eglInitialize: {e:?}"))?;

    let config = egl
        .choose_first_config(
            display,
            &[
                egl::SURFACE_TYPE,
                egl::PBUFFER_BIT,
                egl::RENDERABLE_TYPE,
                egl::OPENGL_BIT,
                egl::RED_SIZE,
                8,
                egl::GREEN_SIZE,
                8,
                egl::BLUE_SIZE,
                8,
                egl::NONE,
            ],
        )
        .map_err(|e| format!("choose_first_config: {e:?}"))?
        .ok_or("keine passende EGL-Konfiguration")?;

    let context = egl
        .create_context(
            display,
            config,
            None,
            &[
                egl::CONTEXT_MAJOR_VERSION,
                1,
                egl::CONTEXT_MINOR_VERSION,
                5,
                egl::NONE,
            ],
        )
        .map_err(|e| format!("create_context: {e:?}"))?;
    let surface = egl
        .create_pbuffer_surface(display, config, &[egl::WIDTH, 16, egl::HEIGHT, 16, egl::NONE])
        .map_err(|e| format!("create_pbuffer_surface: {e:?}"))?;
    egl.make_current(display, Some(surface), Some(surface), Some(context))
        .map_err(|e| format!("make_current: {e:?}"))?;

    // The context is only worth something if GL answers. Fetching the two strings through
    // `get_proc_address` keeps the spike free of a GL binding crate.
    let version = gl_string(&egl, "glGetString", 0x1f02).unwrap_or_else(|| "?".into());
    let renderer = gl_string(&egl, "glGetString", 0x1f01).unwrap_or_else(|| "?".into());
    let vendor = egl
        .query_string(Some(display), egl::VENDOR)
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_else(|_| "?".into());

    egl.make_current(display, None, None, None)
        .map_err(|e| format!("make_current none: {e:?}"))?;
    egl.destroy_surface(display, surface)
        .map_err(|e| format!("destroy_surface: {e:?}"))?;
    egl.destroy_context(display, context)
        .map_err(|e| format!("destroy_context: {e:?}"))?;

    Ok(format!("EGL {vendor} · GL {version} · {renderer}"))
}

#[cfg(feature = "spike-render")]
fn gl_string(
    egl: &khronos_egl::DynamicInstance<khronos_egl::EGL1_5>,
    name: &str,
    what: u32,
) -> Option<String> {
    type GetString = unsafe extern "system" fn(u32) -> *const u8;
    let proc = egl.get_proc_address(name)?;
    // SAFETY: `glGetString` has this exact signature; the pointer comes from the loader.
    let f: GetString = unsafe { std::mem::transmute(proc) };
    let ptr = unsafe { f(what) };
    if ptr.is_null() {
        return None;
    }
    Some(unsafe { std::ffi::CStr::from_ptr(ptr as *const i8) }.to_string_lossy().into_owned())
}

/// Renders into the child surface with our own GL context and measures the frame rate.
///
/// Question (c): is a real swap loop into the subsurface usable at a sane rate? The loop
/// waits for a Wayland **frame callback** after every swap, because `swap_buffers` returns
/// immediately — counting swaps alone would measure how fast the CPU hands over buffers,
/// not what the screen shows.
#[cfg(feature = "spike-render")]
pub fn run_swap_loop(handles: &WindowHandles) -> Result<String, String> {
    use khronos_egl as egl;
    use std::ffi::c_void;
    use std::time::Instant;
    use wayland_client::Proxy as _;

    const PLATFORM_WAYLAND_KHR: egl::Enum = 0x31d8;
    const GL_COLOR_BUFFER_BIT: u32 = 0x4000;

    let (connection, mut queue, compositor, subcompositor, _shm, parent) = wayland::bind(handles)?;
    let qh = queue.handle();
    let (width, height) = (handles.width as i32, handles.height as i32);

    let child = compositor.create_surface(&qh, ());
    let subsurface = subcompositor.get_subsurface(&child, &parent, &qh, ());
    subsurface.set_position(0, 0);
    subsurface.place_below(&parent);
    // Independent of the webview's own commits: the picture must not wait for the UI.
    subsurface.set_desync();

    let egl_lib =
        unsafe { wayland_sys::egl::wayland_egl_option() }.ok_or("libwayland-egl fehlt")?;
    // SAFETY: the child surface is alive for as long as this function runs.
    let raw_surface = child.id().as_ptr() as *mut c_void;
    // The `dlopen` bindings expose the functions as fields, not as methods.
    let egl_window =
        unsafe { (egl_lib.wl_egl_window_create)(raw_surface as *mut _, width, height) };
    if egl_window.is_null() {
        return Err("wl_egl_window_create lieferte nichts".into());
    }

    // SAFETY: same display Tauri uses; the EGL window belongs to that display.
    let egl = unsafe {
        egl::DynamicInstance::<egl::EGL1_5>::load_required_from_filename("libEGL.so.1")
    }
    .map_err(|e| format!("libEGL nicht ladbar: {e}"))?;
    let display = unsafe {
        egl.get_platform_display(
            PLATFORM_WAYLAND_KHR,
            handles.display as *mut c_void,
            &[egl::ATTRIB_NONE],
        )
    }
    .map_err(|e| format!("get_platform_display: {e:?}"))?;
    egl.initialize(display)
        .map_err(|e| format!("eglInitialize: {e:?}"))?;
    let config = egl
        .choose_first_config(
            display,
            &[
                egl::SURFACE_TYPE,
                egl::WINDOW_BIT,
                egl::RENDERABLE_TYPE,
                egl::OPENGL_BIT,
                egl::RED_SIZE,
                8,
                egl::GREEN_SIZE,
                8,
                egl::BLUE_SIZE,
                8,
                egl::NONE,
            ],
        )
        .map_err(|e| format!("choose_first_config: {e:?}"))?
        .ok_or("keine passende EGL-Konfiguration")?;
    // No version attributes: asking for GL 1.5 explicitly is answered with `BadMatch` when
    // the window config does not offer exactly that. The context the driver picks is what
    // libmpv will use anyway.
    //
    // `BadConfig` then means the *config* is the problem, so the error carries what the
    // config actually is instead of leaving the next reader to guess.
    let config_facts = format!(
        "Oberfläche={:#x} Renderbar={:#x} Caveat={:#x}",
        egl.get_config_attrib(display, config, egl::SURFACE_TYPE as i32)
            .unwrap_or(-1),
        egl.get_config_attrib(display, config, egl::RENDERABLE_TYPE as i32)
            .unwrap_or(-1),
        egl.get_config_attrib(display, config, egl::CONFIG_CAVEAT as i32)
            .unwrap_or(-1),
    );
    // The window config advertises GL *and* ES (`0x4c`), yet a plain GL context is answered
    // with `BadConfig`. ES2 is explicitly offered, so it is the honest next attempt.
    let context = egl
        .create_context(
            display,
            config,
            None,
            &[egl::CONTEXT_CLIENT_VERSION as i32, 2, egl::NONE],
        )
        .or_else(|e| {
            log::warn!("SPIKE05 GL-Kontext nicht möglich: {e:?} ({config_facts})");
            egl.create_context(display, config, None, &[egl::CONTEXT_CLIENT_VERSION as i32, 1, egl::NONE])
        })
        .map_err(|e| format!("create_context: {e:?} ({config_facts})"))?;
    let surface = unsafe {
        egl.create_window_surface(display, config, egl_window as *mut c_void, None)
    }
    .map_err(|e| format!("create_window_surface: {e:?}"))?;
    egl.make_current(display, Some(surface), Some(surface), Some(context))
        .map_err(|e| format!("make_current: {e:?}"))?;

    type ClearColor = unsafe extern "system" fn(f32, f32, f32, f32);
    type Clear = unsafe extern "system" fn(u32);
    let proc = |name: &str| egl.get_proc_address(name).ok_or_else(|| format!("{name} fehlt"));
    let clear_color: ClearColor = unsafe { std::mem::transmute(proc("glClearColor")?) };
    let clear: Clear = unsafe { std::mem::transmute(proc("glClear")?) };

    // Warmup without waiting: the very first swaps attach buffers and map the surface, and
    // a frame callback before that never arrives — the first run of this probe hung there.
    for _ in 0..3 {
        unsafe {
            clear_color(0.05, 0.25, 0.85, 1.0);
            clear(GL_COLOR_BUFFER_BIT);
        }
        egl.swap_buffers(display, surface)
            .map_err(|e| format!("swap_buffers: {e:?}"))?;
        connection.flush().ok();
    }

    let frames = 120u32;
    let started = Instant::now();
    let mut done = 0u32;
    for _ in 0..frames {
        // SAFETY: a current GL context with a window surface is bound.
        unsafe {
            clear_color(0.05, 0.25, 0.85, 1.0);
            clear(GL_COLOR_BUFFER_BIT);
        }
        egl.swap_buffers(display, surface)
            .map_err(|e| format!("swap_buffers: {e:?}"))?;
        let _callback = child.frame(&qh, ());
        queue.roundtrip(&mut wayland::State).map_err(|e| e.to_string())?;
        done += 1;
        if started.elapsed().as_secs_f64() > 6.0 {
            break;
        }
    }
    let seconds = started.elapsed().as_secs_f64();

    egl.make_current(display, None, None, None).ok();
    egl.destroy_surface(display, surface).ok();
    egl.destroy_context(display, context).ok();
    unsafe { (egl_lib.wl_egl_window_destroy)(egl_window) };
    // Keep the surface chain alive: destroying it would remove the picture we just measured.
    std::mem::forget((child, subsurface, connection));
    Ok(format!(
        "{done} Bilder in {seconds:.2} s = {:.1} fps (mit Frame-Callbacks)",
        done as f64 / seconds
    ))
}

/// Let libmpv draw through **our** context — question (d).
///
/// The point is not playback convenience but whether WebKit's and mpv's renderers tolerate
/// each other. mpv renders into the default framebuffer of the window surface we already
/// swap, so no FBO juggling is involved and a failure points at the render context rather
/// than at our plumbing.
///
/// The source is a generated test pattern (`av://lavfi:…`) on purpose: no token, no server,
/// nothing to leak — and it is visually unmistakable.
#[cfg(feature = "spike-render")]
pub fn run_libmpv_probe(handles: &WindowHandles) -> Result<String, String> {
    use khronos_egl as egl;
    use std::ffi::{c_char, c_int, c_void, CStr, CString};
    use std::time::Instant;
    use wayland_client::Proxy as _;

    #[repr(C)]
    struct MpvRenderParam {
        type_: c_int,
        data: *mut c_void,
    }

    /// `mpv_opengl_fbo`: the render target. Required for the OpenGL render API even when
    /// the target is the default framebuffer (fbo = 0) — without it `render` fails on every
    /// frame, which is what the first run of this probe measured.
    #[repr(C)]
    struct MpvOpenGlFbo {
        fbo: c_int,
        w: c_int,
        h: c_int,
        internal_format: c_int,
    }

    #[repr(C)]
    struct MpvOpenGlInitParams {
        get_proc_address:
            Option<unsafe extern "C" fn(*mut c_void, *const c_char) -> *mut c_void>,
        get_proc_address_ctx: *mut c_void,
    }

    #[link(name = "mpv")]
    extern "C" {
        fn mpv_create() -> *mut c_void;
        fn mpv_client_api_version() -> u64;
        fn mpv_initialize(ctx: *mut c_void) -> c_int;
        fn mpv_command_string(ctx: *mut c_void, args: *const c_char) -> c_int;
        fn mpv_render_context_create(
            out: *mut *mut c_void,
            mpv: *mut c_void,
            params: *mut MpvRenderParam,
        ) -> c_int;
        fn mpv_render_context_render(ctx: *mut c_void, params: *mut MpvRenderParam) -> c_int;
        fn mpv_error_string(code: c_int) -> *const c_char;
        fn mpv_get_property_string(ctx: *mut c_void, name: *const c_char) -> *mut c_char;
    }

    const PARAM_INVALID: c_int = 0;
    const PARAM_API_TYPE: c_int = 1;
    const PARAM_OPENGL_INIT_PARAMS: c_int = 2;
    const PARAM_OPENGL_FBO: c_int = 3;

    struct Loader {
        egl: egl::DynamicInstance<egl::EGL1_5>,
    }

    unsafe extern "C" fn get_proc_address(
        ctx: *mut c_void,
        name: *const c_char,
    ) -> *mut c_void {
        if ctx.is_null() || name.is_null() {
            return std::ptr::null_mut();
        }
        let loader = unsafe { &*(ctx as *const Loader) };
        let name = unsafe { CStr::from_ptr(name) }.to_string_lossy().into_owned();
        loader
            .egl
            .get_proc_address(&name)
            .map(|p| p as *mut c_void)
            .unwrap_or(std::ptr::null_mut())
    }

    let error = |code: c_int, what: &str| {
        let text = unsafe {
            let ptr = mpv_error_string(code);
            if ptr.is_null() {
                String::from("unbekannt")
            } else {
                CStr::from_ptr(ptr).to_string_lossy().into_owned()
            }
        };
        format!("{what}: {text} ({code})")
    };

    let (connection, mut queue, compositor, subcompositor, _shm, parent) = wayland::bind(handles)?;
    let qh = queue.handle();
    let (width, height) = (handles.width as i32, handles.height as i32);

    let child = compositor.create_surface(&qh, ());
    let subsurface = subcompositor.get_subsurface(&child, &parent, &qh, ());
    subsurface.set_position(0, 0);
    subsurface.place_below(&parent);
    subsurface.set_desync();

    let egl_lib =
        unsafe { wayland_sys::egl::wayland_egl_option() }.ok_or("libwayland-egl fehlt")?;
    let raw_surface = child.id().as_ptr() as *mut c_void;
    let egl_window =
        unsafe { (egl_lib.wl_egl_window_create)(raw_surface as *mut _, width, height) };

    // The instance is not `Clone`, so it lives in the loader from the start and every EGL
    // call goes through it.
    let mut loader = Loader {
        egl: unsafe {
            egl::DynamicInstance::<egl::EGL1_5>::load_required_from_filename("libEGL.so.1")
        }
        .map_err(|e| format!("libEGL nicht ladbar: {e}"))?,
    };
    let display = unsafe {
        loader.egl.get_platform_display(
            0x31d8,
            handles.display as *mut c_void,
            &[egl::ATTRIB_NONE],
        )
    }
    .map_err(|e| format!("get_platform_display: {e:?}"))?;
    loader.egl
        .initialize(display)
        .map_err(|e| format!("eglInitialize: {e:?}"))?;
    let config = loader.egl
        .choose_first_config(
            display,
            &[
                egl::SURFACE_TYPE,
                egl::WINDOW_BIT,
                egl::RENDERABLE_TYPE,
                egl::OPENGL_ES2_BIT,
                egl::NONE,
            ],
        )
        .map_err(|e| format!("choose_first_config: {e:?}"))?
        .ok_or("keine passende EGL-Konfiguration")?;
    let context = loader.egl
        .create_context(
            display,
            config,
            None,
            &[egl::CONTEXT_CLIENT_VERSION as c_int, 2, egl::NONE],
        )
        .map_err(|e| format!("create_context: {e:?}"))?;
    let surface = unsafe {
        loader.egl.create_window_surface(display, config, egl_window as *mut c_void, None)
    }
    .map_err(|e| format!("create_window_surface: {e:?}"))?;
    loader.egl
        .make_current(display, Some(surface), Some(surface), Some(context))
        .map_err(|e| format!("make_current: {e:?}"))?;

    let mut api_type = CString::new("opengl").map_err(|e| e.to_string())?;
    let mut init = MpvOpenGlInitParams {
        get_proc_address: Some(get_proc_address),
        get_proc_address_ctx: &mut loader as *mut Loader as *mut c_void,
    };
    let mut params = [
        MpvRenderParam {
            type_: PARAM_API_TYPE,
            data: api_type.as_ptr() as *mut c_void,
        },
        MpvRenderParam {
            type_: PARAM_OPENGL_INIT_PARAMS,
            data: &mut init as *mut MpvOpenGlInitParams as *mut c_void,
        },
        MpvRenderParam {
            type_: PARAM_INVALID,
            data: std::ptr::null_mut(),
        },
    ];

    // If the binding is wrong, this number says so before anything else looks mysterious.
    let api_version = unsafe { mpv_client_api_version() };
    // Created before GTK, because `mpv_create` fails afterwards (measured; see
    // `create_mpv_before_gtk`).
    let mpv = EARLY_MPV
        .get()
        .map(|p| *p as *mut c_void)
        .ok_or_else(|| {
            format!("kein früh angelegtes mpv-Handle (API-Version {api_version})")
        })?;
    let rc = unsafe { mpv_initialize(mpv) };
    if rc < 0 {
        return Err(error(rc, "mpv_initialize"));
    }
    let mut render_ctx: *mut c_void = std::ptr::null_mut();
    let rc = unsafe { mpv_render_context_create(&mut render_ctx, mpv, params.as_mut_ptr()) };
    if rc < 0 {
        return Err(error(rc, "mpv_render_context_create"));
    }

    let command = CString::new("loadfile av://lavfi:testsrc2=size=1280x720:rate=30")
        .map_err(|e| e.to_string())?;
    let rc = unsafe { mpv_command_string(mpv, command.as_ptr()) };
    if rc < 0 {
        return Err(error(rc, "loadfile"));
    }

    let mut fbo = MpvOpenGlFbo {
        fbo: 0,
        w: width,
        h: height,
        internal_format: 0,
    };
    let mut render_params = [
        MpvRenderParam {
            type_: PARAM_OPENGL_FBO,
            data: &mut fbo as *mut MpvOpenGlFbo as *mut c_void,
        },
        MpvRenderParam {
            type_: PARAM_INVALID,
            data: std::ptr::null_mut(),
        },
    ];
    let mut first_error: Option<String> = None;

    for _ in 0..3 {
        unsafe {
            mpv_render_context_render(render_ctx, render_params.as_mut_ptr());
        }
        loader.egl.swap_buffers(display, surface).ok();
        connection.flush().ok();
    }

    let frames = 120u32;
    let started = Instant::now();
    let mut rendered = 0u32;
    let mut failed = 0u32;
    for _ in 0..frames {
        let rc = unsafe { mpv_render_context_render(render_ctx, render_params.as_mut_ptr()) };
        if rc < 0 {
            failed += 1;
            if first_error.is_none() {
                first_error = Some(error(rc, "render"));
            }
        } else {
            rendered += 1;
        }
        loader.egl
            .swap_buffers(display, surface)
            .map_err(|e| format!("swap_buffers: {e:?}"))?;
        let _callback = child.frame(&qh, ());
        queue
            .roundtrip(&mut wayland::State)
            .map_err(|e| e.to_string())?;
        if started.elapsed().as_secs_f64() > 8.0 {
            break;
        }
    }
    let seconds = started.elapsed().as_secs_f64();

    // Evidence that mpv really decoded, not merely that our loop ran.
    let format = unsafe {
        let name = CString::new("video-format").unwrap();
        let value = mpv_get_property_string(mpv, name.as_ptr());
        if value.is_null() {
            "?".to_string()
        } else {
            CStr::from_ptr(value).to_string_lossy().into_owned()
        }
    };

    std::mem::forget((child, subsurface, connection, render_ctx, mpv, loader));
    Ok(format!(
        "{rendered} mpv-Bilder ({failed} Fehler) in {seconds:.2} s = {:.1} fps · Format {format}{}",
        rendered as f64 / seconds,
        first_error
            .map(|e| format!(" · erster Fehler: {e}"))
            .unwrap_or_default()
    ))
}

/// Is `mpv_create` failing because of *this process*, or because of *when* it is called?
///
/// Calling it at two very different moments answers that, and the two answers point at
/// completely different problems.
#[cfg(feature = "spike-render")]
pub fn probe_mpv_create(when: &str) -> String {
    use std::ffi::c_void;
    #[link(name = "mpv")]
    extern "C" {
        fn mpv_create() -> *mut c_void;
        fn mpv_destroy(ctx: *mut c_void);
    }
    let handle = unsafe { mpv_create() };
    let report = format!("{when}: mpv_create = {handle:?}");
    if !handle.is_null() {
        unsafe { mpv_destroy(handle) };
    }
    report
}

/// libmpv must be created **before GTK is initialised**.
///
/// Measured, and reproduced outside Tauri in a minimal program:
///
/// ```text
/// vor gtk_init:  mpv_create = 0x5639c0c404a0   (initialize = 0)
/// nach gtk_init: mpv_create = 0x0
/// ```
///
/// A handle created before `gtk_init()` keeps working afterwards — it initialises, loads a
/// file and decodes (`video-format: wrapped_avframe`). So the constraint is a matter of
/// *order*, not of incompatibility, and the app can satisfy it: `run()` calls this before
/// `tauri::Builder`, and everything later reuses the handle.
#[cfg(feature = "spike-render")]
pub static EARLY_MPV: std::sync::OnceLock<usize> = std::sync::OnceLock::new();

#[cfg(feature = "spike-render")]
pub fn create_mpv_before_gtk() -> String {
    use std::ffi::c_void;
    #[link(name = "mpv")]
    extern "C" {
        fn mpv_create() -> *mut c_void;
    }
    let handle = unsafe { mpv_create() };
    if handle.is_null() {
        return "mpv_create = 0x0".to_string();
    }
    let _ = EARLY_MPV.set(handle as usize);
    format!("mpv_create = {handle:?} (vor GTK angelegt)")
}
