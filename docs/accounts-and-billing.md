# Accounts & Billing

Everything related to user accounts, plans, and the internal-balance billing model.

---

## Accounts

### Registration

New users register with **email and password**. Passwords are hashed with **bcrypt** — the original password is never stored, and it never appears in logs.

Minimum password length is 8 characters. Email must be a valid address and unique across the system.

### Login

Login uses **session cookies**. The cookie is signed with `SECRET_KEY` and contains only a user ID — no password, no token, no personal data.

Cookie properties:

| Property | Value |
|---|---|
| `HttpOnly` | yes (JavaScript cannot read it) |
| `SameSite` | `Lax` |
| `Secure` | controlled by `HTTPS_ONLY` in `.env` |
| Max age | `SESSION_MAX_AGE` (default 14 days) |

### Logout

Logging out clears the server-side session. The browser is redirected to `/login`.

---

## OAuth

Voince supports **Google** and **GitHub** sign-in in addition to email/password. Both are optional — if the corresponding credentials are missing in `.env`, the buttons on the login page are disabled and route to an error page.

### Linking by email

If a user signs in with Google using an email address that already belongs to a password account, Voince **links** the OAuth identity to the existing account instead of creating a duplicate.

This linking only happens when the OAuth provider returns a **verified** email address. For Google, verified emails are the default. For GitHub, Voince requests the primary verified address via the `/user/emails` endpoint.

If the email cannot be verified, the account is **not** linked automatically.

### Google OAuth — setup

1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (e.g. `Voince`).
3. **APIs & Services → OAuth consent screen** → **External**.
4. Fill in the app name and support email. Add your own Google account under **Test users** while in testing mode.
5. **APIs & Services → Credentials → Create OAuth client ID**:
   - Application type: **Web application**.
   - Authorized JavaScript origins: `http://localhost:8000` (and your production URL).
   - Authorized redirect URIs: `http://localhost:8000/auth/google/callback`.
6. Copy the **Client ID** and **Client secret** into `.env`:

```env
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
```

### GitHub OAuth — setup

1. Open [GitHub Developer Settings](https://github.com/settings/developers) → **OAuth Apps** → **New OAuth App**.
2. Homepage URL: `http://localhost:8000`.
3. Authorization callback URL: `http://localhost:8000/auth/github/callback`.
4. Copy the **Client ID** and generate a **Client secret** into `.env`:

```env
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
```

GitHub allows only one callback URL per OAuth App. For production, create a separate OAuth App for the production domain.

---

## Plans

Voince has two plans.

### Free

- **$0 / month.**
- **10 invoices per month.**
- All features included: AI extraction, validation, review, edit, approve/reject, CSV export, Excel export, invoice history.

### Pro

- **$10 / month.**
- **100 invoices per month.**
- Everything in Free.
- Priority processing (the model stays loaded in memory across requests).
- Early access to new features.

The **monthly counter** resets on the first day of the next calendar month, using UTC.

---

## Internal balance model

Voince does not charge the user's credit card, and it does not issue per-invoice payments. Instead, the user tops up an **internal balance** with crypto, and the monthly Pro fee is **debited automatically from that balance**.

This design has a few advantages:

- The user pays once every few months instead of once a month.
- The subscription can renew without an interactive session — a background job handles it.
- Payment provider fees are paid once per top-up, not once per invoice.

Every change to the balance is recorded as a `Transaction` row:

- `topup` — funds added.
- `subscription_charge` — monthly fee debited.

The full ledger is visible on the Account page (last 10 transactions).

---

## Payment flow

Voince uses **Trybit** for crypto payments.

```
User clicks "Upgrade to Pro"
        ↓
Server creates a NOWPayments payment (POST /v1/payment)
        ↓
User is shown:
  - a QR code with the wallet address
  - the wallet address as text
  - a copy button
        ↓
User sends USDT (or another supported coin) from any wallet
        ↓
NOWPayments sends a webhook to /webhooks/nowpayments
        ↓
Server verifies the HMAC-SHA512 signature
        ↓
Balance is credited, subscription is activated
```

### Why QR codes point to the wallet

Unlike some other providers, NOWPayments returns the **destination wallet address** at payment creation time. Voince generates a wallet-compatible QR (e.g. `tron:TXxx...?amount=100`) so the user can scan it directly with Trust Wallet, Binance, MetaMask, or any other wallet — one scan, one payment.

### Idempotency

Webhooks can be delivered more than once. Voince records each top-up by its `order_id` and credits the balance **only the first time** a paid webhook is received for that order.

If the same event is delivered again, the server returns `200 OK` but does not increase the balance.

---

## Subscription lifecycle

### Activation

After a successful top-up, if the balance is enough to cover a Pro month, Voince:

1. Debits the Pro price from the balance.
2. Activates a 30-day Pro period.
3. Marks the subscription status as `active`.

### Auto-renewal

A daily job (`scripts/auto_renew.py`) runs through the following logic:

1. Users whose Pro period ends in the next 24 hours and who have enough balance are charged and extended by 30 days.
2. Users whose balance is too low are marked `past_due`. Their Pro access continues until the end of the paid period.
3. Users whose period has already ended are downgraded to Free.

The job is idempotent — running it twice in a row is harmless.

Set it up as a cron job on your server:

```
0 6 * * *  cd /srv/voince && .venv/bin/python -m scripts.auto_renew \
           >> /var/log/voince-renewals.log 2>&1
```

### Cancellation

The user can cancel from the Account page. On cancellation:

- The status becomes `cancelled`.
- **The user keeps Pro access until the end of the current paid period.**
- Renewal is disabled.
- If the balance still holds funds, they remain available.

### Past-due

If a renewal charge fails due to insufficient balance, the subscription status becomes `past_due`. The Account page shows a link to add funds. If the balance is topped up before the paid period ends, the next daily run will renew the subscription normally.

If the period ends without a successful charge, the account is downgraded to Free and the counter returns to the Free limit (10 invoices/month).

---

## Configuration reference

All payment-related variables are listed in [Configuration](configuration.md#payments-optional).

**Never commit real API keys or secrets to git.** The `.env` file is already in `.gitignore`. If a secret is accidentally leaked, treat it as compromised and rotate it immediately.