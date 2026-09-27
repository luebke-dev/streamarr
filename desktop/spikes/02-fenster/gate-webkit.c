/* Spike 0.2, part 1: the ADR-001 performance gate.
 *
 * ADR 001 keeps Tauri/WebKitGTK but names WebKitGTK's UI performance as the
 * single real risk, and commits to re-opening the decision if it fails on the
 * target systems. That gate needs a number, so this runs the same benchmark
 * that spikes/bench.html runs, in the same engine Tauri uses (WebKitGTK), and
 * prints the result as JSON.
 *
 * The benchmark itself is deliberately the shape of the real Streamarr UI: a
 * long list of media cards, CSS animation, and scripted scrolling. WebKitGTK's
 * documented weakness is the compositor/scroll path, not video — video is
 * native here by design.
 *
 * Build (inside the dev container, which owns the GTK/WebKit dev headers):
 *   gcc gate-webkit.c -o gate-webkit $(pkg-config --cflags --libs webkit2gtk-4.1)
 */
#include <gtk/gtk.h>
#include <webkit2/webkit2.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

static const char *bench_path;
static gboolean got_result = FALSE;

/* The host pulls the result out of the page instead of waiting for the page to
 * push it. Both push routes were tried — a `script-message-received` handler
 * and watching `notify::title` — and neither fired on WebKitGTK 2.54, while
 * `evaluate_javascript` is the plain, documented path. A measurement harness
 * should not depend on an engine detail it is not measuring. */
static void on_result_ready(GObject *source, GAsyncResult *res, gpointer user_data) {
    GError *error = NULL;
    JSCValue *value = webkit_web_view_evaluate_javascript_finish(
        WEBKIT_WEB_VIEW(source), res, &error);
    if (!value) {
        fprintf(stderr, "evaluate failed: %s\n", error ? error->message : "?");
        g_clear_error(&error);
        gtk_main_quit();
        return;
    }
    char *text = jsc_value_to_string(value);
    printf("%s\n", text ? text : "null");
    fflush(stdout);
    got_result = (text && strncmp(text, "{\"engine\"", 10) == 0);
    g_free(text);
    g_object_unref(value);
    gtk_main_quit();
}

/* Runs 15 s after load, comfortably past the benchmark's own 12 s window. */
static gboolean pull_result(gpointer data) {
    WebKitWebView *view = WEBKIT_WEB_VIEW(data);
    webkit_web_view_evaluate_javascript(
        view,
        "JSON.stringify(window.__benchResult || {error:'benchmark did not finish'})",
        -1, NULL, NULL, NULL, on_result_ready, NULL);
    return G_SOURCE_REMOVE;
}

static gboolean load_bench(gpointer data) {
    WebKitWebView *view = WEBKIT_WEB_VIEW(data);
    char *uri = g_strdup_printf("file://%s", bench_path);
    webkit_web_view_load_uri(view, uri);
    g_free(uri);
    return G_SOURCE_REMOVE;
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s /path/to/bench.html [width height]\n", argv[0]);
        return 2;
    }
    bench_path = argv[1];
    if (bench_path[0] != '/') {
        fprintf(stderr, "error: benchmark path must be absolute (got '%s');\n"
                        "       a relative path loads file:/// and measures"
                        " nothing\n", bench_path);
        return 2;
    }
    if (g_file_test(bench_path, G_FILE_TEST_EXISTS) == FALSE) {
        fprintf(stderr, "error: %s does not exist\n", bench_path);
        return 2;
    }
    int w = argc > 2 ? atoi(argv[2]) : 1920;
    int h = argc > 3 ? atoi(argv[3]) : 1080;

    gtk_init(&argc, &argv);

    WebKitWebView *view = WEBKIT_WEB_VIEW(webkit_web_view_new());

    /* Hardware acceleration is the point of the measurement; if it silently
     * falls back to software the numbers are meaningless, so it is requested
     * and the settings are left otherwise at their defaults. */
    WebKitSettings *settings = webkit_web_view_get_settings(view);
    webkit_settings_set_hardware_acceleration_policy(
        settings, WEBKIT_HARDWARE_ACCELERATION_POLICY_ALWAYS);
    webkit_settings_set_enable_webgl(settings, TRUE);
    webkit_settings_set_enable_smooth_scrolling(settings, TRUE);

    GtkWidget *win = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    gtk_window_set_title(GTK_WINDOW(win), "gate-webkit");
    gtk_window_set_default_size(GTK_WINDOW(win), w, h);
    gtk_container_add(GTK_CONTAINER(win), GTK_WIDGET(view));
    g_signal_connect(win, "destroy", G_CALLBACK(gtk_main_quit), NULL);
    g_timeout_add(15000, pull_result, view);
    gtk_widget_show_all(win);

    g_timeout_add(500, load_bench, view);

    /* WebKitGTK exposes its version so the report can name the exact engine. */
    fprintf(stderr, "webkitgtk=%u.%u.%u viewport=%dx%d\n",
            webkit_get_major_version(), webkit_get_minor_version(),
            webkit_get_micro_version(), w, h);

    /* Hard ceiling slightly above the benchmark's own 12 s window. */
    g_timeout_add(25000, (GSourceFunc)gtk_main_quit, NULL);
    gtk_main();

    return got_result ? 0 : 1;
}
