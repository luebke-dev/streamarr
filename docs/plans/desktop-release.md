# Release der Desktop-App

Wie ein Release entsteht, was zusammenpassen muss und wie man eines
zurücknimmt. Geschrieben für den Fall, dass es jemand anderes tun muss als
derjenige, der es zuletzt getan hat.

## Was zusammengehören muss

Die Produktversion steht an **drei** Stellen, und drei verschiedene Werkzeuge
lesen sie:

| Datei | Wer sie liest | Wofür |
|---|---|---|
| `frontend/package.json` | `yarn`, die Web-UI | was die Oberfläche anzeigt |
| `frontend/src-tauri/Cargo.toml` | Cargo | die Version des Binaries |
| `frontend/src-tauri/tauri.conf.json` | der Bundler | was ins Paket geschrieben wird |

Sie **müssen** gleich sein, und zwar nicht aus Ordnungsliebe:

* Der Update-Prüfer vergleicht die Version des **laufenden Builds** — also die aus
  `tauri.conf.json` — mit der des Feeds. Steht dort eine andere als im Binary, wird
  ein Update angeboten, das schon installiert ist, oder gar keines, obwohl eines
  vorliegt.
* Das `.deb` trägt die Version aus `tauri.conf.json`. `dpkg` hält sie gegen die des
  installierten Pakets: Laufen sie auseinander, entsteht ein Paket, das sich nicht
  sauber aktualisieren lässt.

`frontend/src-tauri/scripts/check_versions.sh` prüft das und **schlägt fehl**, wenn eine der
drei abweicht. Zwei Mutationen wurden geprüft: eine geänderte
`Cargo.toml`-Version und eine geänderte `tauri.conf.json` werden beide namentlich
gemeldet.

`frontend/src-tauri/player/Cargo.toml` trägt bewusst eine **eigene** Version (`0.1.0`): die
Kiste ist eine interne Bibliothek und wird nicht ausgeliefert. Das Skript meldet
das als Hinweis, nicht als Fehler.

## Der Ablauf

```bash
# 1. Version an allen drei Stellen setzen (Beispiel 2026.3.0)
#    package.json, src-tauri/Cargo.toml, src-tauri/tauri.conf.json
./frontend/src-tauri/scripts/check_versions.sh          # muss "OK" sagen

# 2. Alles prüfen
cd frontend/src-tauri/player && cargo test --locked
cd ../../frontend/src-tauri && cargo test --locked
cd ../.. && (cd frontend && npx vitest run)  # 24 bekannte Fehler sind die Baseline
./frontend/src-tauri/scripts/check_bundle_deps.sh \
    frontend/src-tauri/target/release/Streamarr \
    frontend/src-tauri/target/release/bundle/deb/*.deb \
    frontend/src-tauri/target/release/bundle/rpm/*.rpm

# 3. Pakete bauen
cd frontend && npx tauri build --bundles deb,rpm,appimage

# 4. Windows: nur über die CI (siehe unten)

# 5. Update-Feed aktualisieren — eigener Endpunkt, siehe unten
```

## Der Update-Feed ist nicht die Instanz

Ein Punkt, der beim Aufsetzen eines Releases überrascht: **der Update-Endpunkt
gehört nicht zum Streamarr-Server.** Er ist eine Konstante im Bundle
(`tauri.conf.json`) und zeigt auf den Release-Feed des Projekts.

Die Begründung steht in ADR 001 und ist keine Geschmacksfrage: `ProfileStore`
hält *mehrere* Server, es gibt also keine kanonische Instanz, die man fragen
könnte; ein von der Instanz gelieferter Feed würde bedeuten, dass der Betreiber
irgendeines Servers die Codeauslieferung an die Maschine seiner Nutzer steuert;
und jede selbst gehostete Installation müsste Desktop-Bundles mitführen. Der
Server prüft die Client-Version nicht einmal (gemessen: keine
`X-Client-Version`-Behandlung im Backend), die beiden Versionen sind also
tatsächlich unabhängig.

## Signatur

`tauri.conf.json` setzt **kein** `createUpdaterArtifacts`. Das ist Absicht: mit
`true` bricht `tauri build` ab, wenn kein Signaturschlüssel gesetzt ist
(„A public key has been found, but no private key…"). Ein Build, der nur mit
Schlüssel durchläuft, wäre ein Build, der in der CI ohne Schlüssel scheitert.

Für ein echtes Release wird die Einstellung beim Aufruf überschrieben und der
Schlüssel gesetzt:

```bash
export TAURI_SIGNING_PRIVATE_KEY=…        # nicht im Repo
npx tauri build --config '{"bundle":{"createUpdaterArtifacts":true}}'
```

Ein **halb** ersetzter oder Platzhalter-Schlüssel gilt als „nicht
konfiguriert" (`updater::is_configured`), damit ein Build keine Updates
verspricht, die er nicht einlösen kann.

## Windows

Das NSIS-Ziel ist in `bundle.targets` konfiguriert und wird im CI-Job
`bundles-windows` auf `windows-latest` gebaut, der anschließend prüft, dass das
Artefakt existiert — ein Bundler, der „erfolgreich" ist, ohne eine Datei zu
schreiben, würde den Build-Schritt sonst wertlos machen.

Ein MSI entsteht nicht: WiX legt die Major-Version in ein Byte, und `2026.2.1`
passt dort nicht (`app version major number cannot be greater than 255`). Eine
MSI-Ausgabe bräuchte zuerst ein anderes Versorgungsschema.

**Es gibt in diesem Projekt keinen Windows-Host.** Die Installer sind also
gebaut, aber von niemandem ausgeführt worden. Das ist eine andere Art von
Beleg als ein Build, den jemand gestartet und durchgeklickt hat, und die
Anleitung sagt das so.

Der MSI-Upgrade-Code ist **festgenagelt** (`7818935a-be79-58de-92f1-d3a642e253fc`,
der von `tauri inspect wix-upgrade-code` abgeleitete Wert). Ohne ihn leitet Tauri
ihn aus dem Produktnamen ab: eine Umbenennung lässt Windows das Update für eine
**andere** Anwendung halten, und Nutzer haben am Ende zwei Kopien installiert.

## Rollback

Drei Ebenen, je nachdem, was kaputt ist.

### 1. Ein Update war schlecht — Feed zurückziehen

Den Release im Feed als „latest" **entfernen**, nicht überschreiben. Der
Update-Prüfer liest `latest.json`; ist sie nicht erreichbar, meldet er
`CheckOutcome::Unavailable` und ändert nichts. Eine zurückgezogene Version durch
eine ältere zu *ersetzen* ist kein Rollback: der Prüfer bietet nur an, was
**höher** ist als die laufende Version (`UpdatePolicy::decide` vergleicht
numerisch je Komponente), eine ältere Version würde also stillschweigend
ignoriert.

### 2. Die Version ist kaputt — neue Version veröffentlichen

Der übliche Weg. Die Versionsnummer muss **höher** sein als die kaputte; ein
Downgrade ist nicht vorgesehen und würde auch nicht angenommen.

### 3. Ein Paket war schlecht — aus dem Feed nehmen, nicht neu bauen

Ein `.deb` derselben Version mit anderem Inhalt ist nicht zulässig: `dpkg`
vergleicht die Version, nicht den Hash. Ein korrigiertes Paket braucht eine neue
Version.

### Was Rollback **nicht** kann

Bereits installierte Versionen werden nicht zurückgeholt. Es gibt keinen
Rückkanal, der eine Installation zum Herunterstufen auffordert. Ein schlechtes
Release ist deshalb vor allem ein Problem für alle, die es noch nicht haben.

## Was vor dem Ausliefern gemessen sein muss

Diese Liste ist aus dem entstanden, was in diesem Projekt tatsächlich schiefging:

- [ ] `check_versions.sh` sagt OK — sonst bietet der Prüfer falsche Updates an
- [ ] `check_bundle_deps.sh` sagt OK — sonst startet die App auf einem frischen
      System nicht (dieser Fehler wurde zweimal gefunden: `libudev1` fehlte, weil
      das `gamepad`-Feature dazukam)
- [ ] `--bundles deb,rpm` endet mit Exit 0 und die Pakete sind **nicht** leer
- [ ] Das `.deb` lässt sich installieren und **starten** (die CI tut das mit
      `xvfb-run`; ein Start ohne Display beweist nichts)
- [ ] `mkdocs build --strict` läuft durch, wenn die Anleitung sich geändert hat
- [ ] Die Frontend-Testanzahl ist nicht über die Baseline gestiegen
