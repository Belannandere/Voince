# Privacy & Security

Voince is designed with two priorities: **keeping your invoices local** and **keeping your account safe**.

---

## Local AI processing

The language model runs on the same server that hosts Voince. When a user uploads a PDF:

- The file is saved to the `uploads/` directory on that server.
- Text is extracted locally.
- The text is sent to Ollama on `http://localhost:11434` — **also on the same server**.
- The model returns JSON, which is validated and stored in the local SQLite database.

Nothing is sent to OpenAI, Anthropic, Google, or any other cloud AI service.

### What leaves the server

Voince does not send invoice contents anywhere except to the local Ollama instance. The only outbound HTTP requests from the app are:

- **OAuth flows** — the user's browser talks to Google or GitHub directly; the server exchanges authorization codes.
- **Payment provider** — the server talks to NOWPayments to create payments and verify webhooks. Only the order ID and amount are sent, never invoice contents.

---

## Supported documents and data retention

- Files uploaded by a user are stored in `uploads/` on the server.
- Extracted data (invoice header, line items, validation result) is stored in the SQLite database.
- Users can delete their entire account from the **Settings** page. Deletion removes:
  - the `users` row,
  - all their `documents`,
  - all their `invoices`, `line_items`, and `validation_results`,
  - all their `topups` and `transactions`,
  - and all uploaded PDF files from `uploads/`.

Deletion is permanent. There is no soft-delete, and no automatic backup is created.

---

## Authentication and session security

- **Passwords** are hashed with **bcrypt**. The plaintext is never stored and never logged.
- **Session cookies** are signed with `SECRET_KEY` and contain only a `user_id`.
- Cookies are marked **`HttpOnly`** — JavaScript cannot read them.
- Cookies use **`SameSite=Lax`**, which protects against most CSRF attacks.
- In production, set `HTTPS_ONLY=true` in `.env` so cookies are marked **`Secure`** and only sent over HTTPS.

### `SECRET_KEY`

`SECRET_KEY` signs session cookies. If it changes, all existing sessions become invalid. If it leaks, an attacker can forge sessions.

Rules:

- Generate a strong random value for production:
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(48))"
  ```
- **Never commit `SECRET_KEY` to git.** It lives in `.env`, which is gitignored.
- **Never share `SECRET_KEY` in screenshots, chats, or documentation.**

---

## Data isolation

Users are isolated from each other by a strict repository-level rule:

> Every query that touches a user's data filters by the logged-in `user_id`.

This is enforced in `app/repository.py` — the templates and endpoints never see a raw "all documents" query. A dedicated test file, `tests/test_isolation_deep.py`, exercises the following scenarios:

- User A cannot fetch `/invoices/<id>` for an invoice owned by user B.
- User A cannot edit, approve, or reject user B's invoices.
- User A cannot export user B's invoices via CSV.
- Anonymous users are redirected to `/login` for any user-scoped route.

If any of these tests fails, the build should be considered broken.

---

## Payment security

- **No card data.** Voince does not process or store card numbers.
- **No private keys.** Voince does not hold crypto wallets or private keys.
- **Webhook verification.** Every incoming NOWPayments webhook is verified against HMAC-SHA512 using `NOWPAYMENTS_IPN_SECRET` **before** any side effect.
- **Idempotency.** Replayed webhooks do not credit the balance twice.
- **Server-side pricing.** The Pro price is defined in `.env` — never taken from the request body. A user cannot downgrade the price by manipulating a form.

---

## Privacy posture

What Voince does:

- Stores uploaded PDFs on the server.
- Stores extracted invoice data on the server.
- Stores account data (email, hashed password, OAuth IDs, balance, transactions).
- Logs application events (requests, errors) without invoice contents or secrets.

What Voince does **not** do:

- Send invoice contents to a cloud AI.
- Share user data with third parties.
- Sell user data.
- Use invoice contents for training models.

### Logging

Application logs record events like:

```
[billing] user 1 credited 10.00 -> balance 10.00 (topup)
[webhook] order=VOINCE-TOPUP-1-a1b2c3d4e5f6 status=finished
[ai] extract_invoice took 34210 ms
```

Logs **do not** contain:

- passwords or password hashes,
- session cookies,
- API keys or webhook secrets,
- invoice contents, supplier names, or amounts.

### Deleting your account

From **Settings → Danger zone**:

1. Type your account email to confirm.
2. Enter your current password (if the account has one).
3. Click **Permanently delete my account**.

Deletion is immediate and irreversible.

---

## Reporting a vulnerability

If you find a security issue, do not open a public issue. Instead, contact the maintainers privately. Provide:

- A description of the issue.
- Steps to reproduce.
- Any proof-of-concept code or screenshots.

Please allow reasonable time for the issue to be fixed before disclosing it publicly.

---

## Hardening checklist for production

Before exposing Voince to the internet:

- [ ] Set a strong random `SECRET_KEY`.
- [ ] Set `HTTPS_ONLY=true` and serve the app behind a TLS-terminating reverse proxy.
- [ ] Set `PUBLIC_BASE_URL` to the real public URL.
- [ ] Restrict or whitelist the source IP of admin access at the proxy level.
- [ ] Enable daily backups of `invoices.db` and `uploads/`.
- [ ] Rotate payment API keys periodically and immediately on any suspicion of leakage.
- [ ] Do not log full request bodies for `/webhooks/*`.
- [ ] Keep Ollama running on `localhost` only — do not expose port `11434` to the internet.
- [ ] Review `docs/troubleshooting.md` for known operational pitfalls.