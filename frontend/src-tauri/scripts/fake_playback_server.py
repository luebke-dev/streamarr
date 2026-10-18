"""A stand-in for the server's playback endpoints, for testing without a server.

Why this exists: the native playback chain had to be verified while the test server's
database was down. Waiting for infrastructure to test client code is the wrong way
round — the chain's own correctness (capabilities -> play response -> plan -> tunnel ->
mpv -> position) does not depend on the server being healthy, and this makes that
verifiable in a minute instead of not at all.

It answers with the *measured* shapes, not invented ones: the play response fields are
those of a real `direct_play` answer (spike 0.3), and `/api/stream/file` serves the real
test medium with range support, which is what makes mpv seek.

Usage:
    python3 fake_playback_server.py [port]      # default 8443

    # Certificates for the name, so TLS is real and not switched off:
    openssl req -x509 -newkey rsa:2048 -keyout k.pem -out c.pem -days 2 -nodes \
      -subj "/CN=streamarr.luebke.internal" \
      -addext "subjectAltName=DNS:streamarr.luebke.internal"
    cat k.pem c.pem > b.pem

Then point the app at it:
    PLAY_BASE=https://streamarr.luebke.internal:8443 PLAY_PIN=127.0.0.1 \
    PLAY_CA=c.pem cargo run --example play_probe

Environment:
    FAKE_MEDIA   file to serve (default /tmp/mpvt/long.mkv)
    FAKE_POSITION  stored resume position in seconds (default 300)
    FAKE_DURATION  duration to report (default 600)
"""
import http.server, ssl, json, os, re
MEDIA = os.environ.get("FAKE_MEDIA", "/tmp/mpvt/long.mkv")
POSITION = float(os.environ.get("FAKE_POSITION", "300"))
DURATION = float(os.environ.get("FAKE_DURATION", "600"))

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        if self.path.startswith("/api/media/") and "user-data" in self.path:
            # Eine gespeicherte Position -> die Wiedergabe muss fortsetzen.
            self._json({"playback_position_seconds": POSITION,
                        "duration_seconds": DURATION,
                        "progress_percentage": 100.0 * POSITION / max(DURATION, 1),
                        "is_played": False,
                        "selected_audio_track_index": None,
                        "selected_subtitle_track_index": None})
            return
        if self.path.startswith("/api/stream/file"):
            data = open(MEDIA, "rb").read()
            rng = self.headers.get("Range")
            if rng:
                m = re.match(r"bytes=(\d+)-(\d*)", rng)
                start = int(m.group(1)); end = int(m.group(2) or len(data) - 1)
                chunk = data[start:end+1]
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
                self.send_header("Content-Type", "video/x-matroska")
                self.send_header("Content-Length", str(len(chunk)))
                self.end_headers(); self.wfile.write(chunk); return
            self.send_response(200)
            self.send_header("Content-Type", "video/x-matroska")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers(); self.wfile.write(data); return
        self._json({"detail": "unbekannt"}, 404)
    def do_POST(self):
        if self.path.startswith("/api/play/"):
            # Genau die Felder, die der echte Server liefert (Spike 0.3).
            self._json({"status": "ok", "token": "mock-token-123",
                        "session_id": "mock-session", "media_source_id": "src-1",
                        "playback_method": "direct_play", "direct_stream": True,
                        "duration": DURATION, "width": 320, "height": 180,
                        "stream_info": {"source_file": MEDIA, "transcoding": False,
                                        "transcoding_reasons": [],
                                        "client_capabilities": {}}})
            return
        self._json({"detail": "unbekannt"}, 404)

s = http.server.ThreadingHTTPServer(("127.0.0.1", 8443), H)
c = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); c.load_cert_chain(os.environ.get("FAKE_CERT", "/tmp/rt/b.pem"))
s.socket = c.wrap_socket(s.socket, server_side=True)
print("MOCK bereit auf 8443", flush=True)
s.serve_forever()
