/* Does Wayland let a client position/stack its own toplevel windows?
 * The plan's Weg A depends on pinning an overlay window to the webview's
 * position, so this measures exactly that assumption. */
#include <gtk/gtk.h>

static gboolean report(gpointer data) {
    GtkWindow *w = GTK_WINDOW(data);
    gint x = -1, y = -1;
    gtk_window_get_position(w, &x, &y);
    gtk_window_move(w, 120, 90);
    gint x2 = -1, y2 = -1;
    gtk_window_get_position(w, &x2, &y2);
    g_print("REQUESTED (120,90) -> BEFORE (%d,%d) AFTER (%d,%d)\n", x, y, x2, y2);
    g_print("MOVE_HONOURED=%s\n", (x2 == 120 && y2 == 90) ? "yes" : "NO");
    gtk_main_quit();
    return G_SOURCE_REMOVE;
}

int main(int argc, char **argv) {
    gtk_init(&argc, &argv);
    g_print("GDK_BACKEND=%s\n", gdk_display_get_name(gdk_display_get_default()));

    GtkWidget *ui = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    gtk_window_set_title(GTK_WINDOW(ui), "simulated webview UI");
    gtk_window_set_default_size(GTK_WINDOW(ui), 640, 400);
    gtk_widget_show_all(ui);

    GtkWidget *ov = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    gtk_window_set_title(GTK_WINDOW(ov), "simulated player overlay");
    gtk_window_set_default_size(GTK_WINDOW(ov), 480, 270);
    gtk_window_move(GTK_WINDOW(ov), 120, 90);
    gtk_widget_show_all(ov);

    g_timeout_add(1500, report, ov);
    gtk_main();
    return 0;
}
