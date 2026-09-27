# Spike 0.1 — WebRTC-Messprogramme

Reproduktion der Messungen aus [spike-01-gstreamer.md](../../../docs/plans/spike-01-gstreamer.md).

## 1. Lokaler Decode-Beweis (kein Server nötig)

Der wichtigste Teil: belegt, dass die Dekodierkette funktioniert, ohne auf eine
Lightrays-Session angewiesen zu sein.

```bash
distrobox enter tauri44
cd desktop/player
cargo build --features spike --bin spike-local-webrtc
./target/debug/spike-local-webrtc
```

Erwartet (Exit-Code 0):

```
sender   ICE: Checking -> Connected -> Completed
receiver ICE: Checking -> Connected -> Completed
decode branch using vah264dec (hardware)
ENCODED=421  DECODED=420
RESULT: 420 frames decoded from 421 encoded
```

Zwei `webrtcbin` verhandeln über Loopback; ICE, DTLS und SRTP laufen wirklich.
Identisch zur Produktion ist die gesamte Medienkette (`vah264enc` sowie
`rtph264depay`/`h264parse`/`vah264dec`). Unterschiedlich ist **nur** der
Signalisierungstransport.

## 2. Client gegen den echten Server

```bash
# Session starten (Token aus ~/.config/streamarr/testserver.env)
curl --resolve streamarr.luebke.internal:443:10.10.60.30 \
  -X POST -H "Authorization: Bearer $STREAMARR_API_KEY" \
  -d '{"width":1280,"height":720,"fps":60,"bitrate_kbps":8000}' \
  "$STREAMARR_BASE_URL/api/lightrays/launch/$GUID"

./target/debug/spike-webrtc "$WSURL" "$TICKET" [--render]
```

**Split-DNS beachten:** `SPIKE_RESOLVE=streamarr.luebke.internal:443:10.10.60.30`,
weil DNS auf eine tote Tailscale-Adresse zeigt. ALPN wird auf `http/1.1`
festgenagelt, sonst hängt der Handshake an nginx' h2-Präferenz.

## Umgebungsabhängigkeiten

Ohne die RPM-Fusion-`freeworld`-Pakete hat Fedora **kein H.264** — siehe die
Doku. Zusätzlich nötig: `libnice-gstreamer1` (sonst startet `webrtcbin` nicht),
`openssl-devel`, und `native-tls` statt rustls wegen der internen CA.
