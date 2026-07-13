# Account & Login

Everything about signing in, creating an account, and managing your profile in streamarr.media.

## First-Run Setup

On a brand-new server, opening the app takes you to a short **setup wizard**:

1. **Administrator Account** — name, email address, and password for the first user
2. **System Configuration** — site name and default language
3. **Confirmation** — review your settings and complete the setup

Afterwards you sign in with the administrator credentials you just created. See the [Quick Start](../getting-started/quick-start.md) for the full walkthrough.

## Signing In

=== "Local account"

    1. Open streamarr.media in your browser or app
    2. Enter your **Email** and **Password**
    3. Click **Sign In**

=== "Single sign-on (OIDC)"

    If your administrator has connected an external identity provider (e.g. Keycloak or Authentik):

    1. Click **Sign In with OIDC**
    2. You are redirected to the identity provider — sign in there
    3. You are sent back to streamarr.media, already signed in

    On your first OIDC sign-in an account can be created for you automatically, so no separate registration is needed.

!!! note
    Depending on how your server is configured, only one of the two methods may be offered — the administrator can disable local login or skip OIDC entirely.

### Server Address

The web app detects the server automatically when it is served from the same address as the backend. On the desktop and Android apps — or when connecting to a different instance — you can enter the **Server Address** yourself; use **Use another server** to change a saved one.

The login page also shows a **QR code**: scan it from a device that is already signed in to hand the server address over to the new device, so you don't have to type it on a TV or in the desktop app.

!!! tip "Login page background"
    The login screen shows rotating backdrop images from the server's media library, including the title they belong to — a small preview of what's inside.

## Creating an Account

New accounts are created **by invitation**. You receive an invite link from an existing user or the administrator (see [Friends & Invites](friends.md)); opening it takes you to the registration page, which shows who invited you and how long the invite is valid.

Fill out the form:

| Field | Notes |
|-------|-------|
| First / Last Name | Required |
| Email Address | Used to sign in and for verification |
| Username | Optional — used as your display name |
| Password | At least 8 characters, entered twice |
| Interface Language | English or German |
| Preferred Audio Languages | Multiple, ordered by priority |
| Preferred Subtitle Language | Optional — leave empty to disable subtitles by default |

Click **Create Account** — you are signed in immediately and taken to the home page. You and the person who invited you are automatically connected as friends.

!!! warning "Verify your email"
    Without a valid invite link, the registration page cannot be used. And don't skip the verification email (below) — you won't be able to sign in again until your address is confirmed.

## Email Verification

After registration you receive a verification email:

1. Click the link in the email
2. The app confirms your address with **Email verified!**
3. Continue with **Go to Login**

Local sign-in is refused until the address is verified. Accounts created through OIDC are considered verified by the identity provider.

## Forgot Password

1. Click **Forgot password** on the login page
2. Enter your email address and click **Send Reset Link**
3. Open the link in the email and enter a new password (at least 8 characters, twice)
4. Sign in with the new password

If the link has expired, simply request a new one.

!!! info "Security note"
    The same success message is shown whether or not the email address exists, so nobody can probe which addresses are registered. Reset requests are also rate-limited.

## Managing Your Profile

Open **Settings** from the user menu to manage your account:

- **Personal Information** — first/last name, email address, and username (display name). OIDC accounts cannot change their email here; it comes from the identity provider.
- **Account Information** — your user ID, account status, sign-in method, and registration date.
- **Language** — interface language, preferred audio languages, and subtitle language.
- **Change Password** — enter your current password and a new one. For OIDC accounts the password is managed by the identity provider instead.
- **Danger Zone** — permanently delete your account. This cannot be undone.

The same page also holds playback, parental-control, gaming, and device preferences — see [User Settings](settings.md) and [Devices, Casting & Offline](devices.md).

To sign out, choose **Logout** from the user menu and confirm.

## Next Steps

- [Dashboard & Home](dashboard.md) — get to know the app
- [User Settings](settings.md) — fine-tune playback and languages
- [Friends & Invites](friends.md) — invite others to your server
