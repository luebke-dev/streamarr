# User Settings

The settings page collects everything personal about your account: profile data, languages, parental control, playback behavior, cloud-gaming input, your devices, and security.

## Opening the Settings

- **User menu** (avatar, top right) → **Settings**
- Or navigate directly to `/settings`

## Profile

### Personal Information

- **First Name** / **Last Name**
- **Email Address** — read-only if you sign in via an external identity provider (OIDC)
- **Username** (optional) — used as your display name if provided

Click **Update Profile** to save, or **Reset** to discard your edits.

### Account Information

The sidebar shows read-only details: your **User ID**, **Account Status** (Active/Inactive), an **Administrator** badge if you have admin rights, the **Authentication** method (an *OIDC Provider* badge for SSO accounts), and **Registered since**.

## Language Settings

| Setting | What it does |
|---------|--------------|
| **Interface Language** | Language of the app itself. Changes apply immediately. |
| **Preferred Audio Languages** | An ordered priority list — the first language has the highest priority; use the arrows to reorder. When playback starts, the best-matching audio track is selected automatically. |
| **Preferred Subtitle Language** | A single language. If the file has a matching subtitle track, it is preselected when playback starts. Leave the field empty to disable subtitles by default. |

!!! note "Available interface translations"
    The interface is fully translated into **English** and **German**. Further languages appear in the dropdown, but their translations are not complete yet.

!!! tip "Your audio languages also steer downloads"
    When pyrate.media downloads something on your behalf (for example via Smart Play or monitored favorites), your preferred audio languages are factored into which release is chosen.

You can always override audio and subtitle tracks for the current video in the player itself — see [Streaming & Playback](streaming.md).

## Parental Control

Set an age-rating threshold for your own account: **No limit**, **0+**, **6+**, **12+**, **16+**, or **18+**. Movies and shows rated above the threshold are hidden and blocked; unrated media stays visible. Administrators can also enforce this setting per account.

## Playback

Choose how intros, outros, and credits are handled when markers are available:

| Option | Behavior |
|--------|----------|
| **Show skip button** | A skip button appears in the player (default) |
| **Skip automatically** | The segment is skipped without asking |
| **Disabled** | No button, no auto-skip |

Each of **Skip Intro**, **Skip Outro**, and **Skip Credits** can be set independently.

!!! note "Video quality needs no setup"
    Which codecs your device can play is detected automatically when you sign in, and the server uses that to decide between direct play and transcoding. There is nothing to configure here.

## Cloud Gaming

Input preferences for game streaming sessions (see [Games](games.md)):

- **Keyboard Layout** — the layout passed into your game session (English US/UK, German, French, Spanish, Italian, Portuguese, Russian, Japanese)
- **Mouse Speed** — sensitivity multiplier from 0.1x to 3.0x
- **Controller** — gamepad behavior for retro game sessions:
    - **Analog stick deadzone** (0–50%)
    - **D-Pad mode** — keep the D-pad as a D-pad, or map it to the left or right analog stick

## My Devices

Every device you sign in with appears as a card showing its platform, last activity, and last IP address. The device you are currently using is marked with a **Current Device** badge.

- **Edit** — give the device a custom name for easier identification
- **Delete** — remove the device; it is signed out. Removing your current device logs you out.

Each card also has an **Offline sync** panel listing that device's offline downloads with their status (*Queued*, *Downloading*, *Ready*, *Failed*, *Removed*), download progress, and expiry. How to download media for offline use and how casting works is covered in [Devices, Casting & Offline](devices.md).

## Security

### Change Password

For local accounts: enter your current password, then the new password (at least 8 characters) and its confirmation.

!!! info "OIDC accounts"
    If you sign in through an identity provider, password changes are done at the provider, not in pyrate.media.

### Danger Zone

**Delete Account** permanently removes your account after a confirmation dialog.

!!! warning
    Deleting your account is irreversible — all your data is lost.

## Desktop App: Server Connection

In the desktop app, an additional **Server Connection** section lets you change the **Server URL** your app connects to. Click **Save & Reconnect** to apply.

## Related Pages

- [Account & Login](account.md) — registration, login, password reset
- [Devices, Casting & Offline](devices.md) — offline downloads, casting, remote control
- [Friends & Invites](friends.md) — manage friends
- [Membership](membership.md) — subscription management (if enabled)
