# System Configuration

Global system settings that affect the entire Pyrate.Media instance.

## Settings Page

Navigate to **Admin** -> **Settings** to configure system-wide options.

## System Settings

### Site Name

The display name of your Pyrate.Media instance. This is shown in:

- The toolbar header
- Page titles
- Notification emails

Change it by editing the text field and clicking the save button.

## Feature Toggles

### Subscription System

Toggle the subscription/membership system on or off.

- **Enabled**: Users see a "Membership" page where they can view and manage subscription plans
- **Disabled**: The membership page is hidden and subscription features are inactive

### Invite System

Toggle the invitation system on or off.

- **Enabled**: Users can create invite links and send friend requests from the "Invite Friends" page
- **Disabled**: The invite functionality is hidden; new users can only be created by admins or via OIDC

## Environment Configuration

Some settings are configured via environment variables rather than the admin UI:

### Database

- `DATABASE_URL` - PostgreSQL connection string
- `REDIS_URL` - Redis connection string

### Authentication

- `SECRET_KEY` - JWT signing secret (must be unique and secure)
- `OIDC_ENABLED` - Enable OIDC authentication
- `OIDC_CLIENT_ID` - OIDC client ID
- `OIDC_CLIENT_SECRET` - OIDC client secret
- `OIDC_DISCOVERY_URL` - OIDC provider discovery URL

### Elasticsearch

- `ELASTICSEARCH_URL` - Elasticsearch connection URL (optional, enables enhanced search)

### General

- `DEBUG` - Enable debug mode (never in production)

See the [Installation Guide](../getting-started/installation.md) for full environment variable documentation.
