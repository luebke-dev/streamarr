# Friends & Invites

streamarr.media has a built-in social layer: add other users on your server as **friends**, and bring new people on board with personal **invite links**. Friends and invites live on two separate pages, both reached from the user menu in the top-right corner.

!!! note "Availability"
    Both features are controlled by your administrator. The **Friends** and **Invite Friends** entries only appear in the user menu when the corresponding feature is enabled on the server.

## Friends

Open **User menu → Friends** (or navigate to `/friends`).

### Sending a friend request

1. In the **Add Friend** card, enter the email address the other person uses on this server.
2. Click **Send Friend Request**.

If something is off, the form tells you right away — for example when no user exists with that address, a request is already pending, or you are already friends. Your friend will see the request the next time they use streamarr.media.

### Handling requests

- **Incoming Requests** are listed on the friends page with an accept (check mark) and a decline (X) button. Declining asks for confirmation. Incoming requests are also shown as a banner across the top of the app — *"… sent you a friend request"* — with **Accept** and **Decline** right in the banner, so you don't need to visit the friends page at all.
- **Sent Requests** appear with a *Pending* chip until the other person reacts. Use the X button to withdraw a request you no longer want to send.

### Your friends list

Accepted friends are listed with their avatar, display name, and email address. The remove button next to a friend ends the friendship for both of you (after a confirmation dialog).

### What friends unlock

| Feature | What it does |
|---------|--------------|
| **Friends' Parties** | Active watch parties of your friends show up in the watch-party menu, ready to join with one click — see [Watch Parties](watch-parties.md) |
| **Friends are watching** | Friend activity feeds your personal recommendations, including a *"Friends are watching"* row — see [Dashboard & Home](dashboard.md) |
| **Instant friendship on invites** | Anyone who registers through your invite link becomes your friend automatically |

## Invites

Open **User menu → Invite Friends** (or navigate to `/invite-a-friend`) to invite people who don't have an account yet.

!!! info "Who can invite"
    The invite system must be enabled by your administrator. The server can also be configured so that only administrators may create invite links.

### Creating an invite link

1. Click **Create Link**.
2. A single-use invite link, valid for 7 days, is generated and copied to your clipboard automatically.
3. Share the link with the person you want to invite.

### Managing your invites

Your invites are listed in a table:

| Column | Meaning |
|--------|---------|
| **Invite Link** | The registration URL, with a copy button |
| **Status** | Color-coded chip — see below |
| **Accepted by** | Who registered with the invite |
| **Created** | When you created it |
| **Valid until** | When the link expires |

Possible statuses:

| Status | Meaning |
|--------|---------|
| Pending | The link has not been used yet |
| Accepted | Someone registered with it |
| Expired | The validity period has passed |
| Inactive | The invite has been deactivated |

To revoke an invite, click the trash icon and confirm — the link stops working immediately.

### What the invited person sees

1. Opening the link leads to the registration page, which validates the invite and shows who sent it and until when it is valid.
2. They fill in their details and create an account — see [Account & Login](account.md).
3. The invite switches to **Accepted**, with their name in the **Accepted by** column.

!!! tip "Instant friends"
    When someone registers through your invite link, the two of you are automatically added as friends — no separate friend request needed.

## Next steps

- [Watch Parties](watch-parties.md) — watch together with your friends
- [Dashboard & Home](dashboard.md) — where friend-based recommendations appear
- [User Settings](settings.md) — profile, language, and playback preferences
