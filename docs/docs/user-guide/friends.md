# Friends & Invitations

Pyrate.Media offers a social system with friendships and invitations to share the platform with others.

## Opening the Page

Open the friends page via:

- **User Menu** -> **Invite Friends**
- Or navigate directly to `/invite-a-friend`

The page has two tabs: **Friends** and **Invitations**.

## Friends

### Sending a Friend Request

1. Switch to the **Friends** tab
2. Enter your friend's email address
3. Click **Send Request**
4. Your friend will receive a notification

### Managing Requests

**Incoming requests**: Other users who want to add you as a friend.

- Click the **checkmark** to accept
- Click the **X** to decline

**Sent requests**: Your pending requests to others.

- "Pending" status is displayed
- You can withdraw a request

### Friends List

Accepted friends are displayed in the friends list with:

- **Avatar**: Profile picture or initials
- **Name**: Display name
- **Email**: Email address
- **Remove**: Option to end the friendship

## Invitations

Through invitations, you can invite new users to your Pyrate.Media instance.

!!! info "Prerequisite"
    The invitation system must be enabled by the admin.

### Creating an Invitation

1. Switch to the **Invitations** tab
2. Click **Create Invitation**
3. An invitation link is generated and automatically copied to the clipboard
4. Share the link with the person you want to invite

### Invitation Links

Each invitation has:

- **Link**: The URL for registration (automatically copied)
- **Status**: Pending, Accepted, Expired, or Inactive
- **Used by**: Who used the invitation
- **Created on**: When the invitation was created
- **Valid until**: When the invitation expires (default: 7 days)

### Status Colors

| Status | Color | Meaning |
|--------|-------|-----------|
| Pending | Blue | Link has not been used yet |
| Accepted | Green | Someone has registered |
| Expired | Red | Validity period exceeded |
| Inactive | Grey | Manually deactivated |

### Deleting an Invitation

Click the **Trash icon** next to an invitation and confirm the deletion.

## Registration via Invitation

When someone opens your invitation link:

1. They are redirected to the registration page
2. They can create a new account
3. After registration, the invitation is marked as "Used"

## Next Steps

- [Watch Parties](watch-parties.md) - Watch together with friends
- [Settings](settings.md) - Customize profile and language
- [Dashboard](dashboard.md) - Back to the home page
