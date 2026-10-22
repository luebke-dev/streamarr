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
