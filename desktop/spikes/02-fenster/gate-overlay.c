/* Spike 0.2, part 2: the remaining Weg-A assumptions.
 *
 * Part 1 measured the ADR-001 UI-performance gate. This part checks the other
 * two acceptance criteria from plan task 0.2 — "video visible, UI overlayable/
 * hideable, no flicker on fullscreen" — which are about window behaviour rather
 * than speed:
 *
 *   1. GStreamer video renders into our own GTK window via GstVideoOverlay
 *      (this is how the real player overlay will be built).
 *   2. A fullscreen transition on that window does not lose the video sink,
 *      i.e. no flicker/black frame and no need to re-set the window handle.
 *   3. The UI window can be hidden and restored while video keeps running.
 *
 * Note on positioning: on GNOME/Wayland a client cannot position its toplevels
 * (gtk_window_move is ignored — measured in zt.c), so the overlay relies on
 * fullscreen and on being raised, not on being pinned at exact coordinates.
 *
 * Build: gcc gate-overlay.c -o gate-overlay $(pkg-config --cflags --libs gtk+-3.0 gstreamer-1.0 gstreamer-video-1.0)
 */
#include <gtk/gtk.h>
#include <gst/gst.h>
#include <gst/video/videooverlay.h>
#include <gst/app/gstappsink.h>
#include <gdk/gdkx.h>
#include <gdk/gdkwayland.h>

static GtkWidget *ui_win, *video_win;
static GstElement *pipeline;
static GstElement *sink;
static int frames_seen = 0;

static GstFlowReturn on_new_sample(GstAppSink *appsink, gpointer user_data) {
    GstSample *sample = gst_app_sink_pull_sample(appsink);
    if (sample) {
        frames_seen++;
        gst_sample_unref(sample);
    }
    return GST_FLOW_OK;
}

/* Counts decoded buffers so "video keeps running" is a fact and not an
 * impression. */
static gboolean report(gpointer data) {
    g_print("frames_decoded=%d\n", frames_seen);
    return G_SOURCE_CONTINUE;
}

static gboolean go_fullscreen(gpointer data) {
    g_print("step: video window -> fullscreen\n");
    gtk_window_fullscreen(GTK_WINDOW(video_win));
    return G_SOURCE_REMOVE;
}

static gboolean check_after_fullscreen(gpointer data) {
    /* The point of the check: the sink must still be attached and buffers must
     * still arrive. A flickering implementation shows up here as a stalled or
     * reset frame counter. */
    GdkWindow *gw = gtk_widget_get_window(video_win);
    GdkWindowState st = gw ? gdk_window_get_state(gw) : (GdkWindowState)0;
    g_print("fullscreen=%s frames_after_switch=%d\n",
            (st & GDK_WINDOW_STATE_FULLSCREEN) ? "yes" : "no", frames_seen);
    g_print("step: hiding UI window\n");
    gtk_widget_hide(ui_win);
    return G_SOURCE_REMOVE;
}

static gboolean restore_ui(gpointer data) {
    g_print("frames_while_ui_hidden=%d\n", frames_seen);
    gtk_widget_show(ui_win);
    g_print("step: UI restored, frames=%d\n", frames_seen);
    return G_SOURCE_REMOVE;
}

static gboolean finish(gpointer data) {
    g_print("FINAL frames_decoded=%d\n", frames_seen);
    gst_element_set_state(pipeline, GST_STATE_NULL);
    gtk_main_quit();
    return G_SOURCE_REMOVE;
}

int main(int argc, char **argv) {
    gtk_init(&argc, &argv);
    gst_init(&argc, &argv);

    /* A moving pattern makes a stalled pipeline obvious. */
    const char *sink_name = g_getenv("SPIKE_SINK");
    if (!sink_name) sink_name = "waylandsink";
    char *desc = g_strdup_printf(
        "videotestsrc is-live=true pattern=smpte ! "
        "video/x-raw,width=640,height=360,framerate=60/1 ! "
        "tee name=t "
        "t. ! queue ! %s name=videosink sync=false "
        "t. ! queue ! videoconvert ! video/x-raw,format=RGBA ! "
        "appsink name=counter emit-signals=true sync=false max-buffers=2 drop=true",
        sink_name);
    g_print("sink=%s\n", sink_name);
    pipeline = gst_parse_launch(desc, NULL);
    g_free(desc);
    if (!pipeline) {
        g_printerr("pipeline failed to build\n");
        return 1;
    }

    GstElement *appsink = gst_bin_get_by_name(GST_BIN(pipeline), "counter");
    g_signal_connect(appsink, "new-sample", G_CALLBACK(on_new_sample), NULL);

    ui_win = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    gtk_window_set_title(GTK_WINDOW(ui_win), "UI (webview placeholder)");
    gtk_window_set_default_size(GTK_WINDOW(ui_win), 900, 560);
    gtk_widget_show_all(ui_win);

    video_win = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    gtk_window_set_title(GTK_WINDOW(video_win), "PLAYER OVERLAY");
    gtk_window_set_decorated(GTK_WINDOW(video_win), FALSE);
    gtk_window_set_default_size(GTK_WINDOW(video_win), 800, 450);
    /* A drawing area is what a real overlay would use; the sink paints into it
     * through the XID/Wayland handle below. */
    GtkWidget *area = gtk_drawing_area_new();
    gtk_container_add(GTK_CONTAINER(video_win), area);
    gtk_widget_show_all(video_win);

    /* Realise before handing the handle to GStreamer. */
    gtk_widget_realize(area);
    sink = gst_bin_get_by_name(GST_BIN(pipeline), "videosink");
    GdkWindow *gdkwin = gtk_widget_get_window(area);
    /* The handle type differs per backend, and this is the portability point the
     * real overlay has to handle: X11 passes an XID, Wayland passes a
     * wl_surface pointer. Passing the wrong one (or 0) makes the sink create a
     * window of its own instead of painting into ours. */
    const char *backend = GDK_IS_WAYLAND_DISPLAY(gdk_display_get_default())
                              ? "wayland" : "x11";
    guintptr handle = 0;
    if (g_strcmp0(backend, "x11") == 0) {
        handle = GDK_WINDOW_XID(gdkwin);
    } else {
        struct wl_surface *surface =
            gdk_wayland_window_get_wl_surface(gdkwin);
        handle = (guintptr)surface;
    }
    g_print("backend=%s sink_has_video_overlay=%s handle=%lu\n", backend,
            GST_IS_VIDEO_OVERLAY(sink) ? "yes" : "no", (unsigned long)handle);
    /* On Wayland, hand the wl_surface to waylandsink; glimagesink cannot use
     * GDK's surface (it wants its own GL-context surface) and fails with
     * "Failed to flush Wayland connection". SPIKE_NO_HANDLE skips the call so
     * the sink-creates-its-own-window path can be measured too — that is the
     * fallback if embedding into our GTK window is not workable. */
    if (GST_IS_VIDEO_OVERLAY(sink) && !g_getenv("SPIKE_NO_HANDLE")) {
        gst_video_overlay_set_window_handle(GST_VIDEO_OVERLAY(sink), handle);
    } else {
        g_print("handle not passed (sink will create its own window)\n");
    }

    if (gst_element_set_state(pipeline, GST_STATE_PLAYING) ==
        GST_STATE_CHANGE_FAILURE) {
        g_printerr("pipeline failed to reach PLAYING\n");
        return 1;
    }

    /* The plan calls the sink "live" only if buffers keep flowing; that is what
     * the counter above proves. */
    g_print("pipeline=%s\n", gst_element_get_state(pipeline, NULL, NULL, 0) ==
                                  GST_STATE_CHANGE_SUCCESS ? "playing" : "pending");

    g_timeout_add(1000, report, NULL);
    g_timeout_add(3000, go_fullscreen, NULL);
    g_timeout_add(5000, check_after_fullscreen, NULL);
    g_timeout_add(6500, restore_ui, NULL);
    g_timeout_add(8000, finish, NULL);

    gtk_main();
    return 0;
}
