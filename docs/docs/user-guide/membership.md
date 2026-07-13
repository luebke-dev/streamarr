# Membership

streamarr.media can optionally offer paid subscription plans. Payments are processed through **Stripe**; membership can also be granted with **voucher codes**.

!!! info "Optional feature"
    Memberships are a per-instance feature that the administrator must enable and configure. If you do not see a **Membership** entry in your user menu, the feature is not available on your server. See [Membership & Vouchers](../administration/membership.md) for the admin side.

## Opening the Membership page

Open the user menu (your avatar in the toolbar) and select **Membership**, or navigate to `/membership` directly. The page is titled *"Manage your subscription and billing information"* and contains everything below on a single screen.

## Current plan

If you have an active subscription, the top card shows:

- **Plan name**, monthly **price**, and **description**
- **Features** included in the plan
- **Status** chip and the **next billing** date

| Status | Meaning |
|--------|---------|
| **Active** | Your subscription is running normally |
| **Expiring** | Your subscription has been cancelled and remains valid until the shown date |

While a plan is **Expiring**, a **Renew Now** button lets you re-subscribe before access ends. Without any subscription, a banner invites you to pick a plan below.

## Available plans

All purchasable plans are shown as cards with name, price per month, description, and a feature checklist. Plan features reflect what the administrator has configured, for example:

- Number of libraries available
- Number of concurrent streams
- Maximum video quality (e.g. 4K)
- Compressed or lossless audio
- Offline downloads

Your current plan is highlighted, and each other card offers **Subscribe** (no active plan), **Upgrade** (more expensive plan), or **Downgrade** (cheaper plan).

## Changing plans

1. Click **Upgrade** or **Downgrade** on the plan you want.
2. A confirmation dialog compares your **Current Plan** with the **New Plan** side by side.
3. Click **Confirm Change** — changes take effect immediately.

## Cancelling a subscription

1. Click **Cancel Subscription** on your current plan.
2. Read the warning: your access remains active until the end of the paid period; after that date you lose access to subscriber content.
3. Click **Confirm Cancellation** (or **Keep Subscription** to back out).

The plan then shows as **Expiring** until the date is reached — you can still use **Renew Now** to change your mind.

## Redeeming vouchers

The **Redeem Voucher** section accepts codes handed out by your administrator (e.g. `ABCD-1234-EFGH`). Enter the code and click **Redeem**:

- With no active subscription, the voucher's plan is activated for the voucher's duration — *"Membership activated"*.
- With an active subscription on the **same** plan, your expiry date is extended — *"Membership extended"*.
- With an active subscription on a **different** plan, redemption is refused; cancel the current plan first.

Invalid, expired, or fully used-up codes are rejected with a matching error message.

!!! tip "No card required"
    Voucher redemption does not require a payment method — it is a convenient way to get membership on instances that do not take card payments.

## Payment method

The **Payment Method** card shows your saved card (brand, last four digits, expiry date) with an **Update Payment** button, or an **Add Payment Method** button if none is on file.

Card details are entered in a secure Stripe form (card number plus optional cardholder name) and are sent directly to Stripe — the server never sees your full card data.

!!! note
    If the dialog shows *"Payments are not configured on this server"*, the instance runs without Stripe — memberships can then only be granted via vouchers or by an administrator.

## Billing history

The **Billing History** table lists your Stripe invoices with **Date**, **Plan**, **Amount**, and **Status** (**Paid** or **Failed**). Use **Download Invoice** to open the invoice PDF in a new tab. *"No invoices yet"* appears if you have no billing history.

## Next steps

- [User Settings](settings.md) — profile, language, and playback preferences
- [Streaming & Playback](streaming.md) — what stream quality and limits mean in practice
- [Membership & Vouchers (Admin)](../administration/membership.md) — how plans and vouchers are configured
