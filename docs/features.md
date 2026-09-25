# Features

A complete list of what Voince can do **today**. Nothing on this page is aspirational.

---

## AI extraction

- **Upload** a PDF invoice via drag-and-drop or the file picker.
- **Extract** every field the model can find: supplier, invoice number, invoice date, due date, currency, subtotal, tax, total.
- **Extract line items** — description, quantity, unit price, and total per row.
- **Enforce** a strict schema via Ollama's `format: "json"` mode.
- **Bound** the input text to 8000 characters, keeping only the header, totals, and line items region.

The full pipeline is documented in [AI pipeline](ai-pipeline.md).

---

## Deterministic validation

- **Required fields** — supplier, invoice number, total.
- **Arithmetic** — subtotal + tax vs. total.
- **Line-item sum** vs. subtotal.
- **Presence warnings** — missing date, currency, or line items.

See [Validation](validation.md) for exact rules and tolerances.

---

## Human review

- **Review page** displays extracted fields, line items, and validation messages side by side.
- **Edit** opens a form for the invoice header and every line item.
- **Approve** marks the invoice as approved.
- **Reject** marks it as rejected.
- **Re-validation** runs automatically on every save.

---

## Accounts

- **Registration** with email and password.
- **Login / logout** with session cookies.
- **Google OAuth** — optional.
- **GitHub OAuth** — optional.
- **Account linking** by verified email.
- **Account page** shows plan, balance, monthly usage, and subscription status.
- **Settings** page lets the user change email, set or change password, and delete the account.

See [Accounts & billing](accounts-and-billing.md).

---

## Plans and limits

- **Free** — 10 invoices per month.
- **Pro** — 100 invoices per month.
- **Monthly reset** — counters reset automatically on the first day of the next calendar month (UTC).
- **Enforcement** — the limit is checked **before** any PDF or AI processing starts. When the limit is reached, the upload page shows an upgrade prompt.

---

## Billing (crypto)

- **Balance-based model.** The user tops up an internal balance with crypto; the subscription fee is debited from that balance every month.
- **Crypto payments via NOWPayments** — user pays with any supported coin.
- **Webhook-based crediting.** The balance is credited only after a verified NOWPayments callback.
- **Auto-renewal.** A daily job charges the monthly Pro fee and extends the subscription.
- **Past-due handling.** If the balance is insufficient, the account is marked `past_due` but Pro access remains until the end of the paid period.
- **Cancellation.** The user can cancel; the subscription remains active until the end of the period.

---

## Exports

### CSV

- **Single invoice** — `Download CSV` on the result page.
- **All invoices** — `Download all CSV` on the Invoices page.

Columns:

```
supplier_name, invoice_number, invoice_date, currency, subtotal, tax, total
```

### Excel

- **Single invoice** — `Download Excel` on the result page.

Two sheets:

- **Invoices** — one row per invoice.
- **Line items** — one row per line item, linked by invoice number.

---

## Data isolation

Every query that reads or writes invoice data filters by the logged-in user's ID. User A cannot see user B's invoices, documents, line items, validation results, top-ups, or transactions.

Data isolation is enforced at the repository level, not in the templates — so it applies to every endpoint: list, detail, edit, approve, reject, export.

There is a dedicated test suite for this in `tests/test_isolation_deep.py`.

---

## Internationalization

- **Four languages:** English, Spanish, German, French.
- **Language switcher** in the navigation bar.
- **Choice persisted** in a cookie.

The switcher uses SVG icons (a globe and language codes) rather than emoji flags, so the interface looks the same on every operating system.

---

## Dark and light theme

- **Light** — default.
- **Dark** — toggled from the account menu.
- **Choice persisted** in `localStorage`.

The theme is applied **before** the first paint, so there is no flash of light content on a dark page.

---

## What Voince does not do yet

- **No OCR.** Scanned PDFs without a text layer are rejected with a clear message.
- **No email ingestion.** Every invoice is uploaded manually.
- **No accounting integrations.** QuickBooks, Xero, and similar tools are not connected.
- **No multi-user teams.** Accounts are individual.
- **No bulk upload.** Files are uploaded one at a time.
- **No delete endpoint for invoices.** Records can be removed only via direct database access.

These are roadmap items. See the main `README.md` for details.