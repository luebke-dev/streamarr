# Spike 0.3 — mpv-Messprogramm

Reproduktion der Messung aus [spike-03-mpv.md](../../spike-03-mpv.md).

Der Spike steuert `mpv` als **separaten Prozess** über dessen JSON-IPC. Er linkt
bewusst **nicht** gegen libmpv — genau das ist die Entscheidung, die er belegt.

## Voraussetzungen

```bash
distrobox enter tauri44
sudo dnf install -y mpv ffmpeg
```

`ffmpeg` wird nur zum Erzeugen der Testdateien gebraucht, nicht zur Laufzeit.

## Testdateien erzeugen

Nicht im Repo (14 MB / 4 MB), aber mit einem Befehl reproduzierbar:

```bash
mkdir -p /tmp/mpvt && cd /tmp/mpvt

# Zwei Tonspuren (de/en), keine Untertitel
ffmpeg -y -f lavfi -i testsrc=duration=300:size=640x360:rate=25 \
       -f lavfi -i sine=frequency=440:duration=300 \
       -f lavfi -i sine=frequency=880:duration=300 \
       -map 0:v -map 1:a -map 2:a -c:v libx264 -preset ultrafast -c:a ac3 \
       -metadata:s:a:0 language=ger -metadata:s:a:1 language=eng -t 300 test.mkv

# Mit Untertitelspur — prüft die Spurauswahl
printf '1\n00:00:01,000 --> 00:00:04,000\nDeutscher Untertitel\n\n' > sub.srt
ffmpeg -y -f lavfi -i testsrc=duration=120:size=640x360:rate=25 \
       -f lavfi -i sine=frequency=440:duration=120 -i sub.srt \
       -map 0:v -map 1:a -map 2:s -c:v libx264 -preset ultrafast -c:a ac3 -c:s srt \
       -metadata:s:a:0 language=ger -t 120 sub.mkv
```

## Lauf

```bash
cd frontend/src-tauri/player
cargo build --features mpv --bin spike-mpv

./target/debug/spike-mpv /tmp/mpvt/test.mkv
./target/debug/spike-mpv /tmp/mpvt/sub.mkv
```

Erwartet: `12/12 checks passed` in beiden Fällen.

`SPIKE_TRACE=1` gibt jedes rohe IPC-Objekt aus. Damit wurden sowohl der
Typfehler (`invalid parameter`, weil die Property-ID als String gesendet wurde)
als auch die fehlenden Events gefunden.

## Gegen einen echten Server

```bash
# Play-Token holen (Query-Parameter, nicht JSON-Body!)
curl --resolve streamarr.luebke.internal:443:10.10.60.30 \
  -X POST -H "Authorization: Bearer $STREAMARR_API_KEY" \
  "$STREAMARR_BASE_URL/api/play/$GUID?supported_video_codecs=h264,h265&supported_audio_codecs=aac,ac3&client_max_resolution=4k"

# Der zurückgegebene token gehört an den Datei-Endpunkt (Direct Play, HTTP 206)
./target/debug/spike-mpv "$STREAMARR_BASE_URL/api/stream/file?token=$TOKEN"
```

**Split-DNS beachten.** Der Name löst auf eine tote Tailscale-Adresse auf; mpv
hat kein `--resolve`. In einem Mount-Namespace lässt sich das umgehen:

```bash
cp /etc/hosts /tmp/hosts.spike
echo '10.10.60.30 streamarr.luebke.internal' >> /tmp/hosts.spike
sudo unshare -m bash -c 'mount --bind /tmp/hosts.spike /etc/hosts; ./target/debug/spike-mpv "$URL"'
```

Das ist eine **Diagnosehilfe**, keine Lösung: die App selbst braucht eine
konfigurierbare Server-Adresse (siehe Spike 0.1).

## Die Prüfungen im Einzelnen

| Prüfung | Warum sie so formuliert ist |
|---|---|
| Datei lädt und spielt | Wartet auf eine `time-pos`-Meldung. Die `loadfile`-Antwort allein bedeutet nur „angenommen" und wäre ein Fehlalarm. |
| Direct Play | Prüft, dass die URL keine HLS-Playlist ist — HLS wäre der Transcode-Weg. |
| Seek | Ziel ist ein **Anteil** der Laufzeit, nicht ein fester Wert. Ein Seek auf exakt die Dauer landet im EOF und stoppt die Wiedergabe. |
| Spurauswahl | Liest `track-list` **und** setzt `sid`, weil „lesbar" nicht „wählbar" bedeutet. |
| Sauberer Exit | Prüft, dass kein Prozess zurückbleibt — sonst leckt die App einen Prozess pro Wiedergabe. |
