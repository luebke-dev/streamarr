# Account & Login

Here you will learn how to log in, register, and manage your account in Pyrate.Media.

## Initial Setup (Installation)

On the very first launch of Pyrate.Media, a **setup wizard** appears:

1. **Create admin account**: Email, name, and password for the first administrator
2. **Basic settings**: Set site name and default language
3. **Done**: You will be redirected to the login page

## Login

### Local Login

1. Open Pyrate.Media in the browser
2. Enter your **email** and **password**
3. Click **Log in**

### OIDC Login (Single Sign-On)

If your administrator has configured an external identity provider (e.g., Keycloak, Google, etc.):

1. Click **Log in with OIDC**
2. You will be redirected to the identity provider
3. Log in there
4. You will be automatically redirected back to Pyrate.Media

### QR Code Login

For logging in on another device (e.g., TV):

1. Open Pyrate.Media on the target device — a QR code will be displayed
2. Scan the QR code with your smartphone
3. Confirm the login on your smartphone
4. The target device will be logged in automatically

### Server URL

On the login page, you can change the server URL if you want to connect to a different Pyrate.Media instance. By default, the local server is detected automatically.

## Registration

New users can register in two ways:

### Via Invitation Link

1. You receive an invitation link from an existing user
2. Open the link — you will land on the registration page
3. Fill out the form:
    - **First name** and **Last name**
    - **Email address**
    - **Username** (public display name)
    - **Password** (with confirmation)
4. Choose your **language settings**:
    - UI language (German or English)
    - Preferred audio language
    - Preferred subtitle language
5. Click **Create account**

### Via OIDC

When OIDC is enabled, accounts are automatically created on first login.

## Forgot Password

1. Click **Forgot password** on the login page
2. Enter your email address
3. You will receive an email with a reset link
4. Open the link and set a new password

!!! info "Security Note"
    For security reasons, a success message is always displayed regardless of whether the email exists. This way, no one can find out which email addresses are registered.

## Email Verification

If enabled by the admin, you must verify your email address:

1. After registration, you will receive a verification email
2. Click the link in the email
3. Your account will be activated

## Background on the Login Page

The login page displays rotating background images from your media library — a nice preview of the available content.

## Next Steps

- [Dashboard](dashboard.md) — Get to know the app
- [Settings](settings.md) — Customize profile and language
- [Friends & Invitations](friends.md) — Invite others
