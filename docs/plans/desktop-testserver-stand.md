# Testserver: Stand der Datenbank und wie die Live-Nachweise nachgeholt werden

**Status: offen.** Diese Seite hält fest, warum die drei Live-Nachweise für die
Desktop-App (Anmeldung, Medienwiedergabe, Spiel-Streaming) derzeit nicht
erbracht werden können, und was genau fehlt. Sie ist absichtlich eine
Momentaufnahme mit Datum — sie beschreibt einen Zustand, nicht eine Regel.

Stand: **2026-09-27**, gemessen auf `streamarr.luebke.internal` (`ssh streamarr`,
root) und aus dem Entwicklungscontainer `tauri44` heraus.

## Warum überhaupt eine Seite dafür

Die Desktop-App ist gegen drei Dinge gebaut, die sich nur gegen einen echten
Server beweisen lassen: dass eine Anmeldung durchläuft und das Token einen
Neustart übersteht, dass eine Bibliotheksdatei wirklich über den nativen
mpv-Kern abspielt, und dass eine Lightrays-Sitzung wirklich startet und ihr
Bild im Overlay-Fenster ankommt. Alle drei hängen an derselben Abhängigkeit —
der Datenbank des Servers. Solange die fehlt, sind diese Punkte **nicht
gemessen**, und das steht so in der Nutzeranleitung. Eine unbewiesene
Behauptung wäre schlimmer als eine benannte Lücke.

## Der Zustand

| Was | Zustand | Wie festgestellt |
|---|---|---|
| `app-db-1` (Postgres) | **existiert nicht** | `docker ps -a` listet keinen Container |
| Netzwerk `app_default` | **verwaister Endpunkt** | `docker network inspect`: `app-db-1` mit `EndpointID` `cd3e4a1c3ca7…`, IP `172.21.0.2/16` |
| Backend | scheitert an der DB | `app-backend-python-1`: `OSError: [Errno 113] Connect call failed ('172.21.0.2', 5432)` |
| Datenbankdateien | **intakt** | `/opt/streamarr/data/postgres`, **1,6 GB**, Besitzer `999:0`, `PG_VERSION` vorhanden |
| Rolle und DB | **`pyrate`** (nicht `streamarr`) | `/opt/streamarr/app/.env`: `POSTGRES_USER=pyrate`, `POSTGRES_DB=pyrate` |
| Verbindungszeichenfolge | `db:5432/pyrate` | `DATABASE_URL=postgresql+asyncpg://…@db:5432/pyrate` im Backend |
| Docker-Netzwerk-IP | `172.21.0.2` | genau die Adresse, auf die das Backend wartet |
| Andere Container | laufen | backend, lightrays, redis, scheduler, worker, frontend, grafana, prometheus, elasticsearch |

### Die Kette, soweit rekonstruierbar

1. `docker events --since 72h --filter container=app-db-1` zeigt ein
   **`destroy`** — der Container wurde entfernt, nicht nur gestoppt. Ein
   `docker start` hätte also gar nichts geholfen.
2. `dmesg` enthält zwei `Memory cgroup out of memory`-Ereignisse; eines nennt
   `sabnzbdplus` als Opfer. Das ist der **wahrscheinliche**, aber nicht
   bewiesene Auslöser: Der Kernel hat unter Speicherdruck einen Prozess
   getötet, und der Container ist dabei verschwunden.
3. Beim Entfernen wurde der **Netzwerk-Endpunkt nicht mit aufgeräumt**. Er hält
   seither `172.21.0.2` besetzt — dieselbe Adresse, die das Backend über den
   DNS-Namen `db` auflöst. Deshalb ist die DB für das Backend unerreichbar,
   selbst wenn ein neuer Container läuft.

### Warum „healthy" hier in die Irre führt

Ein neu gestarteter `app-db-1` meldete `health: starting`, und
`pg_isready -U streamarr` antwortete „accepting connections". Beides ist
irreführend:

- `pg_isready` prüft den **Socket**, nicht ob die erwartete Rolle existiert.
  Mit `-U streamarr` antwortete Postgres „accepting connections", obwohl es
  diese Rolle gar nicht gibt — die Rolle heißt `pyrate`.
- Der von Docker als `healthy` gemeldete Container hatte **kein Netzwerk**:
  `NetworkSettings.Networks` war `{}`. Er war also für das Backend unerreichbar
  und trotzdem „gesund". Ein Healthcheck, der nur den Socket prüft, kann das
  nicht erkennen.

Wer hier nachsieht: **nicht auf `docker ps` verlassen, sondern
`docker inspect … --format '{{json .NetworkSettings.Networks}}'` und
`psql -U pyrate -d pyrate -tAc 'SELECT 1'` prüfen.**

### Eingriffe, die bereits versucht wurden (und ihre Wirkung)

Diese Schritte wurden vor dem Beschluss „kein weiterer Servereingriff"
ausgeführt. Sie sind hier festgehalten, damit der Zustand erklärbar ist:

| Schritt | Ergebnis |
|---|---|
| `docker compose up -d db` | Container erstellt, Start scheitert: `endpoint with name app-db-1 already exists` |
| `docker network disconnect -f app_default app-db-1` | entfernt den Endpunkt **nicht** |
| `docker rm -f app-db-1` + `network disconnect -f` | Container gelöscht; Endpunkt bleibt |
| `docker compose up -d --force-recreate db` | scheitert erneut am selben Endpunkt |

**Netto-Wirkung:** Der Endpunkt hält weiterhin `172.21.0.2`; ein
`app-db-1`-Container existiert derzeit nicht. Die **Daten sind unberührt** — sie
liegen in einem Bind-Mount, nicht in einem Docker-Volume, ein Container-Löschen
fasst sie also nicht an. Der Datenbestand ist unverändert 1,6 GB.

## Was zu tun ist — zwei Schritte

Das Verzeichnis ist ein Bind-Mount
(`${DATA_DIR:-./data}/postgres:/var/lib/postgresql/data:rw,z`), kein
Docker-Volume. Deshalb kann der Container gefahrlos neu erzeugt werden; die
Daten bleiben. **Kein `docker compose down -v`, kein Volume-Löschen.**

### 1. Docker-Daemon neu starten (löst den verwaisten Endpunkt)

Ein Daemon-Neustart ist der zuverlässige Weg, den Endpunkt loszuwerden — er
überlebt `disconnect` und `rm`. Alle zehn laufenden Container tragen die
Restart-Policy `unless-stopped`, kommen also von selbst wieder hoch. Zur
Sicherheit die Liste vorher festhalten:

```bash
ssh streamarr
docker ps --format '{{.Names}}\t{{.Status}}' > /root/pre-restart.txt
sudo systemctl restart docker
```

Beim Start ist `live-restore` **nicht** konfiguriert (es gibt keine
`/etc/docker/daemon.json`), die Container werden also kurz neu gestartet.

> Auf den Zeitpunkt achten: Auf dem Host lief zwischenzeitlich ein
> `cargo test` in einem Container mit dem Image `lightrays-check` (2,77 GB).
> Ein solcher Build ist kein Grund, den Neustart aufzuschieben, aber er
> produziert Last; bei knappem Speicher lieber abwarten, bis er durch ist.

### 2. Datenbank-Container neu erzeugen

```bash
cd /opt/streamarr/app
sudo docker compose up -d db
```

Danach prüfen — **beide** Befehle, nicht nur den Healthcheck:

```bash
# Hat der Container ein Netzwerk und die richtige IP?
sudo docker inspect app-db-1 --format '{{json .NetworkSettings.Networks}}'

# Antwortet die richtige Rolle?
sudo docker exec app-db-1 psql -U pyrate -d pyrate -tAc 'SELECT 1'
```

Erwartet: eine Netzwerkanbindung in `app_default`, und `1` als Antwort.

### 3. Durchstich prüfen

```bash
# Ohne Anmeldung — muss sofort antworten, nicht 500.
curl -s --resolve streamarr.luebke.internal:443:10.10.60.30 \
  https://streamarr.luebke.internal/api/auth/status

# Mit dem Testschlüssel (liegt außerhalb des Repos).
set -a; . ~/.config/streamarr/testserver.env; set +a
curl -s --resolve streamarr.luebke.internal:443:10.10.60.30 \
  -H "Authorization: Bearer $STREAMARR_API_KEY" \
  https://streamarr.luebke.internal/api/libraries
```

Ein `HTTP 500` mit `Errno 113` heißt: Schritt 1 oder 2 hat nicht gegriffen. Ein
`HTTP 422` beim Anmelde-Endpunkt ist dagegen ein **gutes** Zeichen — es ist ein
Validierungsfehler, kein Datenbankfehler.

## Was das freischaltet

Sobald die beiden Schritte durch sind, lassen sich die drei offenen Nachweise
in dieser Reihenfolge erbringen:

1. **Anmeldung und Token-Neustart** — `POST /api/auth/local/login` gegen den
   Server, dann `session_state` nach einem Neustart der App. Prüft, ob das
   Token im Schlüsselbund wirklich überlebt.
2. **Medienwiedergabe** — die Datei „Casablanca“
   (`9b0308f3-9426-4e92-b765-1b05d87ed656`) über den nativen mpv-Kern, mit
   Resume-Position und Spurauswahl, gegen `GET /api/stream/file?token=`.
3. **Spiel-Streaming** — `POST /api/lightrays/launch/…` mit der SNES-ROM
   (`e7ed4ae8-3a76-40a8-8bd2-65e7fb0a1bb2`), danach die WebRTC-Sitzung im
   Overlay-Fenster.

Die App selbst muss dafür nicht angefasst werden; sie ist gegen diesen Server
gebaut.

## Zwei Dinge, die dabei auffielen und nicht zur DB gehören

- **Die Platte lief voll.** `/` stand bei **100 %** (3,5 MB frei), nachdem es
  kurz zuvor 89 % (3,6 GB frei) gewesen waren. In dieser Zeit schlug
  Redis' Hintergrund-Speichern mit `Quota exceeded` fehl und startete immer
  wieder neu. Später erholte es sich auf ~93 %. **Kein Zusammenhang mit den
  Desktop-App-Arbeiten:** die Ursache war ein `lightrays-check`-Image
  (2,77 GB) plus ein 971-MB-`dump.rdb` unter `/opt/streamarr/data/redis`.
  Zwei unabhängige Beobachtungen: **ohne Log-Rotation** (keine
  `/etc/docker/daemon.json`, Treiber `json-file`) war ein einzelnes
  Container-Log **500 MB** groß. Beides ist ein eigener Vorgang.
- **`getent ahosts streamarr.luebke.internal` liefert weiterhin nur
  `100.64.0.2`** — eine tote Tailscale-Adresse. Ohne IP-Pin läuft jede Anfrage
  in einen Timeout (20 s). Deshalb hält die Shell den Pin; siehe
  [ADR 001](adr-001-desktop-shell.md).

## Nachtrag 11.10.: das Enum `mediatype` ist unvollstaendig

Gemessen, nicht vermutet: `/api/trailers`, `/api/filters` und
`/api/suggestions/autocomplete/typed` antworten mit **HTTP 500**, und zwar auch
ohne Desktop-App, direkt per `curl` mit dem API-Schluessel. Der Grund steht im
Backend-Log:

```
asyncpg.exceptions.InvalidTextRepresentationError:
invalid input value for enum mediatype: "AUTHORS"
```

Gegen die Datenbank geprueft (`pg_enum` in der Datenbank `pyrate`):

```
MOVIES SHOWS GAMES MUSIC BOOKS AUDIOBOOKS SEASONS EPISODES ARTISTS ALBUMS
SONGS AUDIOBOOK_CHAPTERS PHOTOS HOME_VIDEOS
```

`AUTHORS` **fehlt**, waehrend die API `AUTHORS` als gueltigen Wert akzeptiert und
das Backend ihn abfragt. Das ist ein **Schema-/Code-Versatz** — eine Migration,
die auf dieser Instanz nicht gelaufen ist.

Was das fuer die Desktop-Arbeit bedeutet: diese drei Endpunkte fallen aus, weil
**der Server** ausfaellt, nicht der Client. Dieselben Endpunkte ruft die Weboberflaeche
auf, also trifft es sie genauso. Die betroffenen Abschnitte der Startseite bleiben
leer.

Nicht behoben: eine Migration auf dem Server ist ein Eingriff und war nicht
beauftragt.

