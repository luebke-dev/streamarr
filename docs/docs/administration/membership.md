# Membership & Vouchers

streamarr.media includes an optional, Stripe-backed membership system: you define **subscription packages** (paid plans), and users either subscribe with a credit card or redeem a **voucher** code. Everything a member is entitled to — libraries, stream quality, concurrent streams — comes from the [group](user-management.md) linked to their package.

!!! note "Memberships are optional"
    Subscriptions are disabled by default. When disabled, all users have unrestricted access and all membership UI is hidden. Enable them under **Admin** -> **Settings** -> **Subscriptions & Payments** -> **Enable Subscriptions**.

## How it fits together

| Piece | What it does |
|-------|--------------|
| **Package** | A plan with a name, description, and monthly price |
| **Group** | Carries the actual entitlements (allowed libraries, max video/audio quality, max concurrent streams); members of a package automatically receive its group |
| **Stripe** | Handles recurring card payments, invoices, and payment methods |
| **Voucher** | A redeemable code that grants a package for a fixed number of days — no card required |

Users manage their plan, payment methods, and billing history on the [Membership page](../user-guide/membership.md).

## Configuring Stripe

Stripe credentials are stored in the server settings store under the `payment.*` keys:

| Key | Value |
|-----|-------|
| `payment.enabled` | `true` to activate the payment provider |
| `payment.stripe_secret_key` | Your Stripe secret key (`sk_...`) |
| `payment.stripe_publishable_key` | Your Stripe publishable key (`pk_...`) |
| `payment.stripe_webhook_secret` | The webhook signing secret (`whsec_...`) |

!!! warning "No settings form yet"
    There is currently no admin UI form for entering Stripe keys. Insert them as rows in the `settings` database table (one key per row, JSON values). Settings are loaded at startup, so restart the backend and workers after inserting them directly.

While Stripe is not configured, the packages pages show a warning banner ("Stripe is not configured…"), users see no payment UI, and new packages cannot be created.

### Webhook

Payment confirmations, failed payments, and subscription changes reach the server via a Stripe webhook. In the Stripe dashboard, create a webhook endpoint pointing at:

```
https://<your-server>/api/subscriptions/webhooks/stripe
```

Subscribe it to these events:

- `invoice.payment_succeeded`
- `invoice.payment_failed`
- `customer.subscription.updated`
- `customer.subscription.deleted`

Copy the endpoint's signing secret into `payment.stripe_webhook_secret` — webhook requests are rejected until it is set.

## Subscription packages

Navigate to **Admin** -> **Subscription Packages**. The table lists each package with its price, linked group, Stripe sync status, and active state.

To create a package, click **Create Package** and fill in:

- **Name** and **Description** — shown to users on the plan picker
- **Price (monthly)** — in the main currency unit, e.g. `9.99` (default currency EUR)
- **Group** — members of this package automatically receive this group
- **Active** toggle

Saving syncs the package to Stripe as a product with a monthly recurring price; the Stripe column shows a green check once linked.

!!! note "Deleting deactivates"
    The delete action deactivates a package instead of erasing it. Deactivated plans disappear from the user-facing plan picker but stay visible in the admin table (and existing subscriptions keep working).

## Vouchers

Navigate to **Admin** -> **Vouchers** to manage redeemable membership codes — useful for gifts, promotions, trials, or running memberships without card payments entirely.

=== "Single code"

    Click **Create Code** and set:

    - **Package** — the plan the code grants
    - **Duration (days)** — how many days of membership when redeemed
    - **Uses** — maximum number of redemptions per code
    - **Valid until** — optional redemption deadline; leave empty for unlimited
    - **Custom code** — optional; leave empty for automatic generation
    - **Note** — internal note, optional

=== "Batch generation"

    Click **Batch Generate** to create many codes at once. In addition to the fields above, set:

    - **Count** — how many codes to generate
    - **Prefix** — optional, prepended to all codes, e.g. `PROMO-`

Generated codes are 12 characters from an unambiguous alphabet (no `0/O/1/I/L`); custom codes are stored uppercase.

Each row in the voucher table shows redemption progress (**Uses**, e.g. `3 / 10`) and an active **Status** toggle — switch it off to block further redemptions without deleting the code.

!!! tip "CSV export"
    **Export CSV** downloads all vouchers (code, package, duration, uses, expiry, status, note) — handy for mail merges or handing codes to a reseller.

### Redemption behavior

Users redeem codes in the **Redeem Voucher** section of their [Membership page](../user-guide/membership.md). On redemption:

- With no active membership, a new one starts immediately and runs for the voucher's duration; the user is also added to the package's group.
- With an active membership of the **same** package, the expiry date is extended by the voucher's duration.
- With an active membership of a **different** package, redemption is rejected.

Expired, deactivated, or fully used codes cannot be redeemed; multi-use codes count down atomically, so a code can never be over-redeemed.
