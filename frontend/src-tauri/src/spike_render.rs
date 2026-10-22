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
        wl_buffer::WlBuffer, wl_compositor::WlCompositor, wl_registry::WlRegistry,
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
        WlSubsurface
    );

    /// Binds the three globals the subsurface needs.
    fn bind(
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
