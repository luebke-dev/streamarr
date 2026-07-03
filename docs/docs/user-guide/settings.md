# User Settings

On the settings page, you can edit your profile, adjust language settings, and change your password.

## Opening the Settings

Open the settings via:

- **User Menu** (top right) -> **Settings**
- Or navigate directly to `/settings`

## Editing Your Profile

### Personal Information

Edit your personal details:

- **First Name**: Your first name
- **Last Name**: Your last name
- **Email**: Your email address (read-only for OIDC accounts)
- **Username**: Your public display name

Click **Update Profile** to save the changes.

### Account Information

On the right side you can see:

- **User ID**: Your unique ID
- **Account Status**: Active or Inactive
- **Administrator**: If you have admin privileges
- **Authentication**: "OIDC" if you are logged in via an external provider
- **Registered since**: When your account was created

## Language Settings

Pyrate.Media offers three independent language settings:

### UI Language

The language of the user interface:

- **German (de-DE)**
- **English (en-US)**

The interface is immediately displayed in the selected language.

### Audio Language

Your preferred audio track for streaming:

- During playback, the audio track in your preferred language is automatically selected
- If not available, the default audio track of the file is used

### Subtitle Language

Your preferred subtitle language:

- Subtitles are burned into the video during transcoding
- If not available, no subtitles are displayed

## Changing Your Password

!!! info "Only for local accounts"
    OIDC users cannot change their password in Pyrate.Media - this is done at the identity provider.

1. Scroll to the **Change Password** section
2. Enter your current password
3. Enter the new password
4. Confirm the new password
5. Click **Change Password**

## Next Steps

- [Dashboard](dashboard.md) - Back to the home page
- [Friends & Invitations](friends.md) - Manage friends
- [Membership](membership.md) - Subscription management (if enabled)
