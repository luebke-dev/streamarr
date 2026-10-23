//! The video surface: libmpv's renderer drawing into a Wayland subsurface of our own window.
//!
//! This is the production form of spike 05 (see `docs/plans/spike-05-libmpv.md`). Everything
//! here was measured before it was written; the five constraints that came out of the spike
//! are not preferences but preconditions:
//!
//! 1. The libmpv handle must be created **before** GTK is initialised —
//!    [`streamarr_desktop_player::libmpv::Libmpv::create`] returns an error naming that cause.
//!    This module receives an already created handle and never makes one.
//! 2. Every render call needs an FBO description, even for the default framebuffer; that
//!    belongs to the player crate and is why `render` takes dimensions rather than nothing.
//! 3. Window and page are transparent, and the picture lies **below** the webview's surface.
//! 4. A Wayland window config yields a **GLES2** context on this driver, not desktop GL.
//! 5. The child surface is `set_desync()`, otherwise the frame rate follows the UI's commits.
//!
//! The picture is a *subsurface*, not a second window: one window, one place where the user
//! looks, and the control bar can be drawn above the video by ordinary HTML.

#![cfg(feature = "libmpv")]

use raw_window_handle::{HasDisplayHandle, HasWindowHandle, RawDisplayHandle, RawWindowHandle};
use std::ffi::{c_char, c_int, c_void};
use streamarr_desktop_player::libmpv::{Libmpv, MpvRenderContext, OpenGlInitParams};
use wayland_client::protocol::wl_surface::WlSurface;
use wayland_client::{Connection, EventQueue, Proxy as _};

/// What the surface needs to know about the app's window.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WindowHandles {
    pub surface: usize,
    pub display: usize,
    pub width: u32,
    pub height: u32,
}

/// Reads the Wayland surface and display of a window.
///
/// Returns an error on any other backend instead of pretending: this design rests on
/// Wayland subsurfaces, so an X11 or Windows window is a different question, not a variant.
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

/// The Wayland objects the surface needs, behind one `Dispatch` state.
mod wl {
    use wayland_client::globals::{registry_queue_init, GlobalListContents};
    use wayland_client::protocol::{
        wl_buffer::WlBuffer, wl_callback::WlCallback, wl_compositor::WlCompositor,
        wl_registry::WlRegistry, wl_shm::WlShm, wl_shm_pool::WlShmPool,
        wl_subcompositor::WlSubcompositor, wl_subsurface::WlSubsurface, wl_surface::WlSurface,
    };
    use wayland_client::{Connection, Dispatch, EventQueue, Proxy, QueueHandle};

    use super::WindowHandles;

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

    // Every interface needs its own empty `Dispatch`; three lines each keeps the used set
    // visible instead of hidden in generated code.
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

    pub struct Bound {
        pub connection: Connection,
        pub queue: EventQueue<State>,
        pub compositor: WlCompositor,
        pub subcompositor: WlSubcompositor,
        pub parent: WlSurface,
    }

    /// Takes over the display Tauri is already using and binds what a subsurface needs.
    ///
    /// `Backend::from_foreign_display` runs in "guest" mode: dropping it does not close the
    /// connection, which matters because Tauri owns it and must keep it.
    pub fn bind(handles: &WindowHandles) -> Result<Bound, String> {
        use wayland_client::backend::ObjectId;

        let display = handles.display as *mut wayland_sys::client::wl_display;
        let surface = handles.surface as *mut wayland_sys::client::wl_proxy;

        // SAFETY: both pointers come from `raw_window_handle` for this very window and stay
        // valid as long as it lives.
        let backend =
            unsafe { wayland_backend::sys::client::Backend::from_foreign_display(display) };
        let connection = Connection::from_backend(backend);

        // SAFETY: the interface description is the generated one for `wl_surface`, and the
        // pointer belongs to the display adopted above.
        let id = unsafe { ObjectId::from_ptr(WlSurface::interface(), surface) }
            .map_err(|e| format!("ungültige Oberfläche: {e:?}"))?;
        let parent = WlSurface::from_id(&connection, id).map_err(|e| e.to_string())?;

        let (globals, queue) =
            registry_queue_init::<State>(&connection).map_err(|e| e.to_string())?;
        let qh = queue.handle();

        let compositor: WlCompositor = globals
            .bind(&qh, 4..=6, ())
            .map_err(|e| format!("wl_compositor: {e}"))?;
        let subcompositor: WlSubcompositor = globals
            .bind(&qh, 1..=1, ())
            .map_err(|e| format!("wl_subcompositor: {e}"))?;

        Ok(Bound {
            connection,
            queue,
            compositor,
            subcompositor,
            parent,
        })
    }
}

/// The GL side: an EGL context that mpv draws through.
struct Gl {
    display: khronos_egl::Display,
    context: khronos_egl::Context,
    surface: khronos_egl::Surface,
    loader: Box<Loader>,
}

/// Holds the EGL instance so mpv's `get_proc_address` callback can reach it.
///
/// Boxed in [`Gl`] and never moved afterwards: mpv keeps the context pointer for its whole
/// lifetime, so the address has to stay valid.
struct Loader {
    egl: khronos_egl::DynamicInstance<khronos_egl::EGL1_5>,
}

unsafe extern "C" fn get_proc_address(ctx: *mut c_void, name: *const c_char) -> *mut c_void {
    if ctx.is_null() || name.is_null() {
        return std::ptr::null_mut();
    }
    // SAFETY: `ctx` is the `Loadout` pointer handed to mpv in `OpenGlInitParams`, and it
    // outlives the render context.
    let loader = unsafe { &*(ctx as *const Loader) };
    let name = unsafe { std::ffi::CStr::from_ptr(name) }
        .to_string_lossy()
        .into_owned();
    loader
        .egl
        .get_proc_address(&name)
        .map(|p| p as *mut c_void)
        .unwrap_or(std::ptr::null_mut())
}

/// Rejects sizes a surface cannot have, before anything touches Wayland or EGL.
///
/// A zero-sized surface is not an edge case worth supporting: it comes from a hidden or not
/// yet realised window, and passing it on produces compositor errors that say nothing about
/// the real cause.
fn checked_size(size: (u32, u32)) -> Result<(i32, i32), String> {
    let (width, height) = (size.0 as i32, size.1 as i32);
    if width <= 0 || height <= 0 {
        return Err(format!("unbrauchbare Größe {width}x{height}"));
    }
    Ok((width, height))
}

/// The video surface of one window.
pub struct VideoSurface {
    connection: Connection,
    queue: EventQueue<wl::State>,
    child: WlSurface,
    subsurface: wayland_client::protocol::wl_subsurface::WlSubsurface,
    egl: Gl,
    egl_window: *mut wayland_sys::egl::wl_egl_window,
    wayland_egl: &'static wayland_sys::egl::WaylandEgl,
    // `None` only during teardown: the renderer must go before the GL context.
    render: Option<MpvRenderContext>,
    width: i32,
    height: i32,
}

impl VideoSurface {
    /// Creates the surface for `window`, using the already created `mpv` instance.
    ///
    /// `mpv` must have been created before GTK (see the module documentation); this takes it
    /// by reference precisely so the ordering cannot be hidden here.
    pub fn create(window: &WindowHandles, mpv: &Libmpv, size: (u32, u32)) -> Result<Self, String> {
        let (width, height) = checked_size(size)?;

        let bound = wl::bind(window)?;
        let qh = bound.queue.handle();

        let child = bound.compositor.create_surface(&qh, ());
        let subsurface = bound
            .subcompositor
            .get_subsurface(&child, &bound.parent, &qh, ());
        subsurface.set_position(0, 0);
        // The picture belongs *under* the interface — that is what makes one window possible.
        subsurface.place_below(&bound.parent);
        // Independent of the webview's commits; without this the frame rate follows the UI.
        subsurface.set_desync();

        let wayland_egl =
            wayland_sys::egl::wayland_egl_option().ok_or("libwayland-egl nicht ladbar")?;
        // SAFETY: the child surface is alive as long as this struct holds it.
        let raw_surface = child.id().as_ptr() as *mut c_void;
        let egl_window =
            unsafe { (wayland_egl.wl_egl_window_create)(raw_surface as *mut _, width, height) };
        if egl_window.is_null() {
            return Err("wl_egl_window_create lieferte nichts".to_string());
        }

        let egl = Self::create_gl(window, egl_window)?;

        let mut init = OpenGlInitParams {
            get_proc_address: Some(get_proc_address),
            get_proc_address_ctx: &*egl.loader as *const Loader as *mut c_void,
        };
        let render = MpvRenderContext::create(mpv, &mut init).map_err(|e| e.to_string())?;

        Ok(Self {
            connection: bound.connection,
            queue: bound.queue,
            child,
            subsurface,
            egl,
            egl_window,
            wayland_egl,
            render: Some(render),
            width,
            height,
        })
    }

    fn create_gl(
        window: &WindowHandles,
        egl_window: *mut wayland_sys::egl::wl_egl_window,
    ) -> Result<Gl, String> {
        use khronos_egl as egl;

        // `EGL_PLATFORM_WAYLAND_KHR`, from the Khronos registry — the crate does not export
        // the platform constants.
        const PLATFORM_WAYLAND_KHR: egl::Enum = 0x31d8;

        // SAFETY: libEGL is loaded at runtime and handed the display Tauri already uses.
        let instance = unsafe {
            egl::DynamicInstance::<egl::EGL1_5>::load_required_from_filename("libEGL.so.1")
        }
        .map_err(|e| format!("libEGL nicht ladbar: {e}"))?;

        let display = unsafe {
            instance.get_platform_display(
                PLATFORM_WAYLAND_KHR,
                window.display as *mut c_void,
                // The platform list carries only the terminator; surface attributes below
                // are answered with `BadAttribute` — measured during the spike.
                &[egl::ATTRIB_NONE],
            )
        }
        .map_err(|e| format!("get_platform_display: {e:?}"))?;
        instance
            .initialize(display)
            .map_err(|e| format!("eglInitialize: {e:?}"))?;

        let config = instance
            .choose_first_config(
                display,
                &[
                    egl::SURFACE_TYPE,
                    egl::WINDOW_BIT,
                    egl::RENDERABLE_TYPE,
                    // GLES2 deliberately: with a window config this driver gives an ES2
                    // context and answers desktop GL with `BadConfig` (measured).
                    egl::OPENGL_ES2_BIT,
                    egl::NONE,
                ],
            )
            .map_err(|e| format!("choose_first_config: {e:?}"))?
            .ok_or("keine passende EGL-Konfiguration")?;

        let context = instance
            .create_context(
                display,
                config,
                None,
                &[egl::CONTEXT_CLIENT_VERSION as c_int, 2, egl::NONE],
            )
            .map_err(|e| format!("create_context: {e:?}"))?;
        let surface = unsafe {
            instance.create_window_surface(display, config, egl_window as *mut c_void, None)
        }
        .map_err(|e| format!("create_window_surface: {e:?}"))?;
        instance
            .make_current(display, Some(surface), Some(surface), Some(context))
            .map_err(|e| format!("make_current: {e:?}"))?;

        Ok(Gl {
            display,
            context,
            surface,
            loader: Box::new(Loader { egl: instance }),
        })
    }

    /// Draws the current frame and presents it.
    ///
    /// Waits for a Wayland frame callback afterwards, because `swap_buffers` returns
    /// immediately: without the callback a "frame rate" measures how fast the CPU hands over
    /// buffers rather than what the display shows.
    ///
    /// The GL context must be current on the calling thread — it is, until [`Self::resize`]
    /// is called from elsewhere; callers must keep all calls on the thread that created the
    /// surface.
    pub fn render_once(&mut self) -> Result<(), String> {
        self.render
            .as_ref()
            .ok_or("Renderer bereits abgebaut")?
            .render(0, self.width, self.height)
            .map_err(|e| e.to_string())?;
        self.egl
            .loader
            .egl
            .swap_buffers(self.egl.display, self.egl.surface)
            .map_err(|e| format!("swap_buffers: {e:?}"))?;

        let qh = self.queue.handle();
        let _callback = self.child.frame(&qh, ());
        self.queue
            .roundtrip(&mut wl::State)
            .map_err(|e| format!("roundtrip: {e}"))?;
        Ok(())
    }

    /// Follows a window size change.
    pub fn resize(&mut self, size: (u32, u32)) -> Result<(), String> {
        let (width, height) = checked_size(size)?;
        unsafe { (self.wayland_egl.wl_egl_window_resize)(self.egl_window, width, height, 0, 0) };
        self.width = width;
        self.height = height;
        Ok(())
    }

    /// The picture size, for callers that report it.
    pub fn size(&self) -> (i32, i32) {
        (self.width, self.height)
    }
}

impl Drop for VideoSurface {
    fn drop(&mut self) {
        // mpv's renderer holds GL objects in our context, so it goes first; then EGL, then
        // the Wayland objects. Wrong order is the kind of teardown that looks fine until the
        // app closes a window.
        // Fields drop *after* this body, so mpv's renderer would outlive the context it
        // draws through. Dropping it explicitly first is the whole point of the `Option`.
        drop(self.render.take());

        let egl = &self.egl.loader.egl;
        egl.make_current(self.egl.display, None, None, None).ok();
        egl.destroy_surface(self.egl.display, self.egl.surface).ok();
        egl.destroy_context(self.egl.display, self.egl.context).ok();
        unsafe { (self.wayland_egl.wl_egl_window_destroy)(self.egl_window) };
        self.subsurface.destroy();
        self.child.destroy();
        self.connection.flush().ok();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_real_size_is_accepted() {
        assert_eq!(checked_size((1920, 1080)), Ok((1920, 1080)));
    }

    #[test]
    fn a_zero_size_is_refused_before_wayland_sees_it() {
        // Comes from a hidden or not yet realised window; passing it on produces
        // compositor errors that say nothing about the real cause.
        assert!(checked_size((0, 1080)).is_err());
        assert!(checked_size((1920, 0)).is_err());
        assert!(checked_size((0, 0)).is_err());
    }

    #[test]
    fn an_unrealistically_large_size_does_not_wrap() {
        // u32 -> i32 conversion is where a wrap would hide; a value above i32::MAX must be
        // refused rather than turned negative.
        let huge = (u32::MAX, 1080);
        assert!(checked_size(huge).is_err(), "{:?} must not pass", huge);
    }
}
