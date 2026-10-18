# Versioning and Releases

Streamarr ships as more than one artifact, and each of them is versioned by a
different tool: a Python package, two npm packages, a Tauri shell that is also a
Rust crate, container images, a Helm chart, and desktop bundles. This page decides
how those are numbered, what a release publishes, and in which order. It is
written to be executable: the checks it describes run in CI, so a release that
does not follow it fails instead of publishing something inconsistent.

## The version scheme

`year.release.patch` — the current version is `2026.2.1`.

| Part | Increment when | Example |
|------|----------------|---------|
| `year` | the first release of a new calendar year | `2027.1.0` |
| `release` | anything a user can notice: a feature, a behaviour change, a new migration | `2026.3.0` |
| `patch` | fixes only, on an already released line | `2026.2.2` |

Calendar versioning fits because Streamarr is a self-hosted application, not a
library: nobody resolves a version range, but everybody asks "which build is my
server on, and is there something newer". A date-ish number answers that by
itself, and it is what the project already used before there were releases.

Deliberately **not** part of the scheme:

- No `-dev` suffix on `main`. The tree carries the last released number until the
  version is bumped for the next release; a build from `main` is identified by its
  commit SHA and image digest, not by pretending to be a different version.
- No separate versions per component for shipped pieces. Backend, web UI, desktop
  shell and images always share the product version — that is what makes "2026.3.0"
  a meaningful answer to "what is broken".
- Internal, non-shipped crates keep their own `0.1.0`: `desktop/player`, and the
  `lightrays` and downloader services. Nothing consumes their version numbers.

## One source of truth

The version is written in six places, because six tools read it and none of them
reads another's file:

| File | Who reads it |
|------|--------------|
| `VERSION` | everything below; the only file a human edits |
| `backend/pyproject.toml` | the Python package and its metadata |
| `frontend/package.json` | the web UI |
| `frontend/src-capacitor/package.json` | the Android shell |
| `frontend/src-tauri/Cargo.toml` | the desktop binary |
| `frontend/src-tauri/tauri.conf.json` | what the bundler writes into `.deb`/`.rpm`/MSI |

The last one is why drift is not cosmetic: the updater compares the *running*
build's version (from `tauri.conf.json`) with the release feed, and `dpkg` compares
the package version against what is already installed.

```bash
scripts/version.py show          # print the product version
scripts/version.py set 2026.3.0  # write it to every manifest
scripts/version.py check         # fail if any of them disagrees
```

`set` rewrites the version in place — a bump is a one-line diff per file, not a
reformatting of every inline array in `tauri.conf.json`.

CI (`version` workflow) runs `check` on every pull request and push, plus
`desktop/scripts/check_versions.sh`, and on a `v*` tag it additionally asserts
that the tag and the `CHANGELOG.md` section match `VERSION`.

## Tags

A release is a **tag on `main`**, annotated, named `v<version>`:

```bash
git tag -a v2026.3.0 -m "Streamarr 2026.3.0"
git push origin v2026.3.0
```

The tag is what publishes. Nothing else triggers a release, and nothing is
released that is not on `main` — a tag on a side branch would produce images whose
code no reviewer has seen merged.

## What a release publishes

| Artifact | Where | Name |
|----------|-------|------|
| Container images | GitHub Container Registry | `ghcr.io/luebke-dev/streamarr-backend`, `-frontend`, `-lightrays`, `-torrent`, `-usenet`, `-spotify`, `-retro` |
| Desktop bundles | GitHub Release assets | `Streamarr_<version>_amd64.deb`, `.rpm`, `.AppImage`, NSIS `.exe`, `.msi` |
| Updater manifest | GitHub Release asset | `latest.json` |
| Helm chart | GitHub Release asset | `streamarr-<version>.tgz` |
| Documentation | GitHub Pages | <https://streamarr.luebke.dev> |

Image tags on a release:

- `2026.3.0` — exact, what a deployment should pin.
- `2026.3` — floats to the newest patch of that release line.
- `latest` — floats to the newest release. **Not** published from `main`: `latest`
  must never point at unreleased code.

Pushes to `main` still build and publish the branch name and the commit SHA, so a
deployment can follow the tip deliberately and can pin a digest for a bug report.

`ghcr.io` allows exactly one path segment after the owner, so image names are flat:
`streamarr-torrent`, not `downloaders/torrent`. The component directory in the
repository says where the code lives; the image name says what is published.

## Release procedure

1. Land everything that belongs in the release on `main` (PRs merged, CI green).
2. Decide the number: `release` for features, `patch` for fixes only.
3. `scripts/version.py set <version>` — one commit, "chore(release): <version>".
4. Rename `## [Unreleased]` in `CHANGELOG.md` to `## [<version>]`, add the date,
   and leave a fresh empty `## [Unreleased]` on top. Fill in **Upgrade notes** if
   the release adds a migration or changes a default.
5. Verify locally: `python3 scripts/version.py check`,
   `bash desktop/scripts/check_versions.sh`.
6. Merge the version commit to `main` and let CI finish on that exact commit.
7. `git tag -a v<version> -m "Streamarr <version>"` and push the tag.
8. Watch the workflows the tag starts: `images` (seven images), `version`
   (tag/CHANGELOG assertions), `desktop` (bundles + `latest.json`).
9. Publish the GitHub Release from the tag, with the CHANGELOG section as its
   body and the bundles attached. Mark it a pre-release for `-rc` tags.
10. Upgrade one instance and check the boring things: `alembic upgrade head`
    applied, login works, a poster renders, one episode plays, `/api/filters`
    answers 200.

## Patch releases and hotfixes

A fix for a released version goes through `main` like everything else, then a new
`patch` tag. There are no maintenance branches: the project has one deployment
target and a single maintainer, and a second branch would mean two migration
histories. If a release is broken badly enough that waiting for the next `main`
build is unacceptable, the fix lands on `main` first and the patch tag follows —
never the other way around.

## Pre-releases

`-rc` suffixes are allowed for the number of the release being prepared:
`v2026.3.0-rc.1`. They publish images with the `-rc.1` tag and a GitHub
pre-release, and never move `latest`. `scripts/version.py` rejects anything that
is not `year.release.patch`, so an `-rc` is cut from a `main` whose `VERSION` is
already `2026.3.0`; the tag carries the suffix, `VERSION` does not.

## Upgrade notes and migrations

- Migrations are forward-only and run as their own step (`alembic upgrade head`,
  the compose `migrate` service, or the chart's pre-upgrade hook) before any app
  process starts.
- Every release that adds a migration says so under **Upgrade notes** in the
  CHANGELOG, because an operator reading a list of fixes will not guess it.
- Enum and column drift between the plugin-generated models and PostgreSQL is
  caught by a test (`backend/tests/test_mediatype_enum_migrations.py`) rather than
  by a 500 on a live instance: a `mediatype` value that no migration adds is the
  exact failure that produced three broken endpoints.
- A release never requires a manual data fix. If a change cannot be expressed as a
  migration, it is not ready to ship.

## Desktop update feed

The desktop app already points at GitHub Releases:

```json
"plugins": { "updater": { "endpoints": [
  "https://github.com/luebke-dev/streamarr/releases/latest/download/latest.json"
] } }
```

Two pieces are missing before that path can work, and both belong to the first
release:

1. **A real signing key.** `tauri.conf.json` still carries
   `pubkey: PLACEHOLDER_REPLACE_WITH_THE_TAURI_UPDATER_PUBLIC_KEY`. Generate a key
   pair (`npx tauri signer generate`), put the public key in the config, and the
   private key plus its password into the repository secrets
   (`TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`).
2. **A publisher.** `createUpdaterArtifacts` is unset and the `desktop` workflow
   builds `.deb`/`.rpm` on `main` only — no tag trigger, no `latest.json`, no
   upload. Until a tag produces signed bundles and a `latest.json`, the feed
   answers 404 and the app correctly treats that as "no update".

The public key must be committed *before* the first bundles are built: an update
signed with a key whose public half is not in the old binary can never be
installed.

## Rolling back

- **Images.** Pin the previous version tag in the deployment. Nothing else is
  needed: images are immutable.
- **Database.** A restore from `pg_dump`, because migrations do not run backwards.
  This is why the backup path is part of the product and not a script in the
  deployment directory.
- **Desktop.** A GitHub Release can be marked as latest again; the updater follows
  the release list, so re-pointing `latest` to an older published release is
  enough for clients to be offered it.

## What has to be true before the first release

These are not opinions, they are the current state (verified 2026-10-19):

| Item | State |
|------|-------|
| Version tags | none — `git tag` is empty, so nothing has ever been published |
| Container images | no image exists on any registry: `ghcr.io/luebke-dev/streamarr-backend` is denied to anonymous pulls, `registry.gitlab.com/streamarr.media` answers 404 |
| Installer | `deployment/install.sh` still defaults to `registry.gitlab.com/streamarr.media` and must point at the published registry |
| Desktop bundles | built in CI on `main`, never attached to a release, never signed |
| Updater key | placeholder in `tauri.conf.json` |
| Helm chart | documented as an OCI artifact under the GitLab registry that does not exist; publishing it as a release asset is the smaller step |
| CHANGELOG | exists, `Unreleased` only |

The first release therefore has to: bump to a real number, publish images to
`ghcr.io` and make the packages public, point the installer and the prod compose
file at those names, generate the updater key, and attach bundles plus
`latest.json` to the GitHub Release.
