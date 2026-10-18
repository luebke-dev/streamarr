/* Spike 0.2, part 3: z-order and stacking, the last Weg-A assumption.
 *
 * Plan task 0.2 requires "video visible, UI overlayable/hideable". Part 2 proved
 * hide/show of the UI; this checks whether the overlay can also be *stacked
 * above* the UI without hiding it, which is what a HUD or a "pause over
 * playback" needs.
 *
 * GNOME/Mutter has no layer-shell, and a client cannot position its toplevels
 * (measured in zt.c), so stacking is the only lever a Wayland app really has.
 * This checks whether gtk_window_present(GDK_CURRENT_TIME) actually raises.
 *
 * Build: gcc gate-zorder.c -o gate-zorder $(pkg-config --cflags --libs gtk+-3.0)
 */
#include <gtk/gtk.h>

static GtkWindow *ui, *overlay;

static gboolean raise_overlay(gpointer data) {
    g_print("step: overlay -> present (raise request)\n");
    gtk_window_present(GTK_WINDOW(overlay));
    return G_SOURCE_REMOVE;
}

static gboolean check(gpointer data) {
    /* GDK does not expose a z-order query, so the check is behavioural: the
     * request must be accepted without an error and both windows must remain
     * mapped. A compositor that refuses stacking simply leaves the overlay
     * behind the UI, which is why the real app keeps hide/show as the primary
     * strategy and treats raising as a bonus. */
    GdkWindow *ow = gtk_widget_get_window(GTK_WIDGET(overlay));
    GdkWindow *uw = gtk_widget_get_window(GTK_WIDGET(ui));
    g_print("overlay_mapped=%s ui_mapped=%s\n",
            (ow && gdk_window_is_visible(ow)) ? "yes" : "no",
            (uw && gdk_window_is_visible(uw)) ? "yes" : "no");
    g_print("overlay_state_fullscreen=%s\n",
            (gdk_window_get_state(ow) & GDK_WINDOW_STATE_FULLSCREEN) ? "yes" : "no");
    gtk_main_quit();
    return G_SOURCE_REMOVE;
}

int main(int argc, char **argv) {
    gtk_init(&argc, &argv);

    ui = GTK_WINDOW(gtk_window_new(GTK_WINDOW_TOPLEVEL));
    gtk_window_set_title(ui, "UI (webview)");
    gtk_window_set_default_size(ui, 900, 560);
    gtk_widget_show_all(GTK_WIDGET(ui));

    overlay = GTK_WINDOW(gtk_window_new(GTK_WINDOW_TOPLEVEL));
    gtk_window_set_title(overlay, "OVERLAY (video)");
    gtk_window_set_decorated(overlay, FALSE);
    gtk_window_set_default_size(overlay, 640, 360);
    gtk_widget_show_all(GTK_WIDGET(overlay));

    g_timeout_add(1000, raise_overlay, NULL);
    g_timeout_add(2500, check, NULL);
    gtk_main();
    return 0;
}
