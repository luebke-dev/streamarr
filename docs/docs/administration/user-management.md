# Users & Groups

pyrate.media has one user system shared by streaming, downloads, and gaming. Everything in this chapter lives in the admin area: **Users**, **Groups**, **Invites**, and **Devices** in the sidebar's Users section, plus **Active Sessions** under Monitoring & Queues.

## Roles

There are exactly two roles. **Superusers** (the **Administrator** toggle on a user) get full access to the admin area. Regular users browse and play media within their permissions.

!!! note
    Groups and permissions control what users can see, play, and download — they never grant admin access.

## Managing users

**Admin → Users** lists all accounts with first/last name, email, active status, role, and creation date, plus edit and delete actions.

- **Create**: **Add User** asks for first/last name, email, and a password (leave empty for OIDC-only users), with **Active User** and **Administrator** toggles.
- **Edit**: besides the basic fields, the edit page covers language preferences (interface language, prioritized audio languages, subtitle language), per-user playback preferences (skip intro/outro/credits: show button, skip automatically, or disabled), **Permission Overrides**, and a read-only **Effective Permissions** card showing the resolved result. Entering a password here sets a new one for the user.
- **Detail page**: click a user to see account info (groups, locale), authentication (local or OIDC, OIDC subject, last login), activity statistics, and the user's invites, devices, and lists.

!!! warning
    Deleting a user also deletes their lists, favorites, viewing history, devices, invites, and API keys.

Accounts for **OIDC** users are created automatically on first SSO login; they have no local password — password changes happen at the identity provider.

## Permissions

Permissions resolve through three layers:

| Layer | Where | Behavior |
|-------|-------|----------|
| Global defaults | **Admin → Settings → Global Permission Defaults** | Hard caps for everyone — group and user permissions cannot exceed them |
| Groups | **Admin → Groups** | Shared permission profiles |
| User overrides | **Admin → Users → Edit** | Highest priority; empty fields inherit from group or global defaults |

Groups and user overrides configure the same set of controls:

| Section | Settings |
|---------|----------|
| Library Access | **Allowed Libraries** — which library types (movies, shows, music, games, books, photos) can be browsed and played |
| Streaming Limits | Max concurrent streams, max game streams |
| Quality Limits | Maximum video quality; maximum audio quality (compressed vs. lossless) |
| Transcoding | Max concurrent transcodings (`0` = no transcoding allowed) |
| Rate limits | Offline, prefetch, and on-demand downloads; indexer API requests and downloads; playbacks — each as a count per period (minute to month), empty = unlimited |
| Favorites | Protect favorites from library cleanup |

!!! tip "Group membership"
    Users are placed into groups automatically by the membership package they subscribe to — see [Membership & Vouchers](membership.md). Direct assignment is also possible via the API (`POST /api/groups/assign`). The groups list shows each group's member count.

## Parental controls

Each user has a maximum age rating: media rated above it is hidden and blocked, while unrated media stays visible. Users set their own threshold under **User Settings → Parental control** (No limit, 0+, 6+, 12+, 16+, 18+ — see [User Settings](../user-guide/settings.md)). Administrators can override it for any account via `PUT /api/users/{user_guid}/parental-control`.

!!! tip
    For child accounts, combine an age-rating limit with a restricted **Allowed Libraries** list.

## Invites

The invite system can be switched on or off under **Admin → Settings → Invite System**. **Admin → Invites** shows every invite in the system — including those users create themselves via [Friends & Invites](../user-guide/friends.md) — with creator, who used it, expiry, usage count vs. max uses, and active state.

Creating an invite takes an optional description, an expiry date (empty = never expires), and a max-use count (empty = unlimited). The copy action puts the registration link (`/register?invite=<token>`) on the clipboard, and **Cleanup Expired** removes stale invites in bulk.

## Active sessions

**Admin → Active Sessions** shows two live tables:

- **Transcoding sessions** — user, content, codecs, resolution, progress, and status, with per-session **Terminate** and a global **Terminate All**. **Cleanup** removes orphaned temp files and stale sessions.
- **Device sessions** — devices with an active WebSocket connection, what they are playing, and their playback state and queue.

See [Monitoring](monitoring.md) for stream metrics over time.

## Devices

**Admin → Devices** lists every registered device across all users with browser/platform, owner, playback status, last activity, IP address, and online state (a **Show inactive** toggle includes dormant ones). You can rename a device, inspect its live session, or remove it — optionally permanently. Users manage their own devices as described in [Devices, Casting & Offline](../user-guide/devices.md).

## API keys

API keys allow scripts and integrations to call the REST API as a specific user. There is no admin UI yet — superusers manage them via the API:

- `POST /api/api-keys` with a name (and optional `user_guid`) returns the key **once**; it starts with `pmak_` and is stored only as a hash.
- Send it as a Bearer token: `Authorization: Bearer pmak_...`.
- `GET /api/api-keys` lists keys with prefix and last-used time; keys can be revoked or deleted.
