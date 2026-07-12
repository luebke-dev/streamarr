# System Settings

Server-wide configuration lives in **Admin → Settings** (`/admin/settings`). Almost everything is stored in the database and edited at runtime — environment variables are only used for connection-level settings such as `DATABASE_URL`, `REDIS_URL`, and `SECRET_KEY` (see the [Installation Guide](../getting-started/installation.md)).

!!! note "Superusers only"
    The admin area requires superuser privileges — see the [Administration Overview](overview.md).

## The Settings page

| Card | What it configures |
|------|--------------------|
| **System Settings** | The **Site Name** shown in the toolbar |
| **OIDC** | Single sign-on: enable OIDC, allow local login, auto-create users, client ID/secret, discovery URL, redirect URIs, scopes |
| **Subscriptions & Payments** | Toggle the Stripe-backed membership system → [Membership & Vouchers](membership.md) |
| **Invite System** | Toggle user invites → [Friends & Invites](../user-guide/friends.md) |
| **Favorites** | **Protect Favorites from Cleanup** — media favorited by at least one user is skipped by automatic library cleanup |
| **Favorites Automation** | Auto-download favorites, upgrade them to better releases, RSS sync, plus interval/batch/concurrency limits |
| **Friends System** | Toggle friend requests between users |
| **Global Permission Defaults** | Server-wide caps: allowed libraries, max concurrent streams / game streams / transcodings, max video and audio quality |
| **Backup and Restore** | Export and restore settings or database snapshots → [Maintenance & Backups](maintenance.md) |

!!! tip "Feature toggles hide UI"
    Disabling subscriptions gives all users unrestricted access and hides membership UI; disabling invites or friends hides those pages entirely.

The automation switches are all **off by default** and require "Protect Favorites from Cleanup" plus the per-user "keep favorites" permission; RSS sync is additionally enabled per indexer → [Indexers](indexers.md). Group- and user-level permissions can never exceed the Global Permission Defaults → [Users & Groups](user-management.md).

## Localization and public URL

- **System locale** (`de-DE` or `en-US`) is chosen in the setup wizard and controls the default metadata language (localized titles and descriptions). It can be changed later via `PUT /api/settings/system`.
- **UI language** is a per-user preference (English/German) → [User Settings](../user-guide/settings.md).
- **Public app URL** is the base for links in outbound emails and OIDC redirects. Set the `APP_URL` environment variable or the `app_url` field of `PUT /api/settings/system` (the database value wins). If neither is set, the server falls back to the first CORS origin and logs a warning at startup.

## Branding and theming

Branding is server-driven and applied on every client at app start. There is currently **no admin page** for it — superusers configure it through the REST API:

=== "Configuration — `GET`/`PUT /api/branding/configuration`"

    | Field | Purpose |
    |-------|---------|
    | `server_name` | Branding display name (default `pyrate.media`) |
    | `login_disclaimer` | Text shown on the login page |
    | `logo_url` | Custom logo URL |
    | `custom_css` | Global CSS injected into every client |
    | `splashscreen_enabled` | Toggle the splash screen |
    | `active_theme_id` | Which theme is active |

=== "Themes — `GET`/`PUT /api/branding/themes`"

    Up to 50 themes, each with `id`, `name`, `enabled`, a **`dark`** flag (switches the client into dark or light mode), **`colors`** (Quasar color tokens, applied as `--q-*` CSS variables — e.g. `primary`, `secondary`), **`variables`** (custom `--pyrate-*` CSS variables), and per-theme `custom_css`. Activate one with `PUT /api/branding/themes/active`.

## Notifications

Users receive **in-app notifications** (bell icon). Admins can create them for one user (`POST /api/notifications/admin/send`) or many (`POST /api/notifications/bulk`), optionally with an email copy.

**Outbound providers** forward server events (e.g. `task.failed`, `task.completed`, `library.scan`, `activity.created`) to external services. Supported types: **Webhook**, **Slack**, **Discord**, and **Email**. Providers and their event subscriptions are managed via `GET`/`PUT /api/notifications/admin/settings`; `POST /api/notifications/admin/dispatch-event` sends a test event.

### Email delivery (SMTP)

Verification, password-reset, and notification emails are sent through SMTP, configured by the `email.*` settings keys: `enabled` (default off), `smtp_host`, `smtp_port` (587), `smtp_user`, `smtp_password`, `smtp_use_tls` (on), `smtp_use_ssl` (off), `from_email`, `from_name`, `reply_to`.

!!! warning "No dedicated email settings page"
    Write these keys with the **Restore Settings** box on the Settings page (paste a JSON object such as `{"email.enabled": true, "email.smtp_host": "mail.example.com"}`) or via `POST /api/backups/settings/restore`. Email settings are loaded at startup — restart the backend and worker afterwards.

## Network

Network settings (`GET`/`PUT /api/settings/network`) cover public hostname, bind host/port, HTTPS certificate/key paths, and a remote-access flag; `GET /api/settings/network/runtime` reports the effective configuration and whether a restart is pending. They are API-only — in the standard deployments TLS and external access are handled by the bundled reverse proxy instead → [Deployment Overview](../deployment/overview.md).

## Storage cleanup

A scheduled cleanup job runs **every 6 hours** and removes stale transcode temp files, old download records, orphaned media files, and duplicates. Tune it via `GET`/`PUT /api/settings/storage`:

| Setting | Default | Effect |
|---------|---------|--------|
| `temp_max_age_hours` | 2 | Delete transcode temp files older than this |
| `temp_max_size_gb` | unset | Optional size cap for the temp directory |
| `download_record_max_age_days` | 30 | Prune old download records |
| `cleanup_orphaned_files` | on | Remove media files no longer referenced by the library |
| `cleanup_duplicates` | on | Remove duplicate media files |

Run it on demand as **Full Storage Cleanup** in **Admin → Tasks** (smaller tasks exist for temp files and stale transcoding sessions) → [Maintenance & Backups](maintenance.md). Disk usage per library, downloads, and temp space is shown on the [Dashboard](dashboard.md). Enable **Protect Favorites from Cleanup** on the Settings page to keep favorited media safe from cleanup.
