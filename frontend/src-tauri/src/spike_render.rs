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
    let display = window
        .display_handle()
        .map_err(|e| e.to_string())?
        .as_raw();

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

/// Binds the globals the subsurface needs, and reports what the compositor offers.
///
/// This exists to answer one specific unknown before the subsurface is written: binding
/// globals on an **adopted** connection needs `Dispatch` implementations for every
/// interface, and that boilerplate is the part most likely to fight back. If this logs the
/// compositor, subcompositor and shm versions, the plumbing is done and the magenta test is
/// only shm handling away.
#[cfg(feature = "spike-render")]
pub fn probe_globals(handles: &WindowHandles) -> Result<String, String> {
    use wayland_client::globals::{registry_queue_init, GlobalListContents};
    use wayland_client::protocol::{wl_compositor::WlCompositor, wl_registry::WlRegistry,
        wl_shm::WlShm, wl_subcompositor::WlSubcompositor};
    use wayland_client::{Connection, Dispatch, QueueHandle};

    struct State;

    impl Dispatch<WlRegistry, GlobalListContents> for State {
        fn event(
            _: &mut Self,
            _: &WlRegistry,
            _: <WlRegistry as wayland_client::Proxy>::Event,
            _: &GlobalListContents,
            _: &Connection,
            _: &QueueHandle<Self>,
        ) {
        }
    }

    macro_rules! ignore {
        ($iface:ty) => {
            impl Dispatch<$iface, ()> for State {
                fn event(
                    _: &mut Self,
                    _: &$iface,
                    _: <$iface as wayland_client::Proxy>::Event,
                    _: &(),
                    _: &Connection,
                    _: &QueueHandle<Self>,
                ) {
                }
            }
        };
    }
    ignore!(WlCompositor);
    ignore!(WlSubcompositor);
    ignore!(WlShm);

    let (connection, _parent) = adopt_connection(handles)?;
    let (globals, queue) = registry_queue_init::<State>(&connection).map_err(|e| e.to_string())?;
    let qh = queue.handle();

    let compositor: WlCompositor = globals
        .bind(&qh, 4..=6, ())
        .map_err(|e| format!("wl_compositor: {e}"))?;
    let subcompositor: WlSubcompositor = globals
        .bind(&qh, 1..=1, ())
        .map_err(|e| format!("wl_subcompositor: {e}"))?;
    let shm: WlShm = globals.bind(&qh, 1..=1, ()).map_err(|e| format!("wl_shm: {e}"))?;

    // The versions are not the point — that all three could be bound on an *adopted*
    // connection is. Keeping the bindings alive until here is what proves it.
    let _ = (compositor, subcompositor, shm);
    Ok("compositor, subcompositor und shm gebunden".to_string())
}
