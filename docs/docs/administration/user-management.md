# User & Group Management

Manage user accounts, permissions, and groups in Pyrate.Media.

## User Roles

### Superuser (Admin)

Users with `is_superuser` enabled:

- Full access to the admin area
- Can manage other users and system settings
- Can edit system lists and configure plugins
- Can view all downloads and sessions

### Regular User

Standard users:

- Can browse and play media
- Can create personal lists and favorites
- Can adjust their own settings
- No access to the admin area

## User Management

Navigate to **Admin** -> **Users** to see all registered users.

### User List

The users page shows a table with:

- **Name** and **email**
- **Status**: Active/Inactive badge
- **Role**: Superuser badge if applicable
- **Auth type**: OIDC badge if using external provider
- **Created**: Registration date
- **Actions**: View, Edit, Delete

### Creating a User

1. Navigate to **Admin** -> **Users** -> **Create User**
2. Fill in the form:
    - **Email**: Unique email address (required)
    - **First Name** and **Last Name**
    - **Username**: Public display name
    - **Password**: For local authentication
    - **Superuser**: Enable for admin privileges
3. Click **Create**

### Editing a User

1. Click a user in the list or the **Edit** button
2. Editable fields:
    - Name, email, username
    - Superuser status
    - Active/Inactive status
3. Click **Save**

### User Detail Page

Clicking a user shows their detail page with:

- Profile information
- Account status and role
- Activity history
- Created lists
- Registered devices

### Deleting a User

1. Click the **Delete** button next to a user
2. Confirm the deletion

!!! warning "Warning"
    Deleting a user also removes all their lists, favorites, and viewing history.

### Password Management

For local accounts (not OIDC):

- Admins can reset a user's password from the edit page
- Users can change their own password in their settings

## OIDC Users

Users who authenticate via OIDC (external identity provider):

- Accounts are created automatically on first login
- Email comes from the identity provider
- No local password - password changes happen at the identity provider
- Shown with an "OIDC" badge in the user list

## Group Management

Navigate to **Admin** -> **Groups** to manage user groups.

### Creating a Group

1. Navigate to **Admin** -> **Groups** -> **Create Group**
2. Enter a **name** and optional **description**
3. Select **members** from existing users
4. Configure **permissions** (what the group can access)
5. Click **Create**

### Editing a Group

1. Click a group in the list
2. Add or remove members
3. Change permissions
4. Click **Save**

## Invite Management

Navigate to **Admin** -> **Invites** to manage the invitation system.

The invite management shows all created invitations across all users:

- **Token/Link**: The invitation URL
- **Status**: Pending, Used, Expired, Inactive
- **Created by**: Which user created the invite
- **Used by**: Which user used the invite (if any)
- **Created/Expires**: Timestamps
- **Actions**: Delete

!!! info "Note"
    Individual users can create and manage their own invites from the [Friends & Invites](../user-guide/friends.md) page. The admin view shows ALL invites across the system.

## Device Management

Navigate to **Admin** -> **Devices** to see all registered devices:

- **Device Name** and **type** (browser, mobile, TV)
- **User**: Which user the device belongs to
- **Last Active**: When the device was last seen
- **Platform**: Operating system/browser info
- **Actions**: View details, Remove device
