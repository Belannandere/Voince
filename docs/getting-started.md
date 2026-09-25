# Getting Started

The fastest path from zero to a CSV file with invoice data.

**Time to first result:** about 3 minutes (assuming Voince is already installed and Ollama is running).

> If Voince is not installed yet, start with [Installation](installation.md).

---

## 1. Create an account

1. Open the app in your browser: <http://localhost:8000>
2. Click **Get started** in the top-right corner.
3. Enter your email and a password (at least 8 characters).
4. Click **Create account**.

You can also sign up with **Google** or **GitHub** instead of a password. See [Accounts & billing](accounts-and-billing.md).

After signing up you are logged in automatically and start on the **Free** plan.

---

## 2. Sign in (if you logged out)

1. Open <http://localhost:8000/login>.
2. Enter the email and password you used during registration.
3. Click **Sign in**.

---

## 3. Upload an invoice

1. Open **Upload** in the top navigation.
2. Drag a PDF invoice onto the dropzone, or click to browse your files.
3. The selected file appears below the dropzone with its name and size.
4. Click **Process Invoice**.

> **The PDF must have a selectable text layer.** You should be able to highlight text in any PDF viewer. If the PDF is a scan, Voince will tell you it needs OCR (see [Troubleshooting](troubleshooting.md)).

---

## 4. Wait for AI extraction

The page shows a processing state:

```
Processing invoice…
Extracting text, analyzing invoice, validating data.
This may take 30–90 seconds on first run.
```

- **First run** — Ollama loads the model into memory, which takes extra time.
- **Subsequent runs** — the model stays in memory for 30 minutes, so it is much faster.

Do not close the tab. When processing finishes, the result page opens automatically.

---

## 5. Review extracted data

The result page shows:

- **Invoice** — supplier, number, invoice date, due date.
- **Financial** — currency, subtotal, tax, total.
- **Line items** — description, quantity, unit price, total per row.
- **Validation** — checks passed, warnings, and errors.

Common validation results:

| Status | Meaning |
|---|---|
| ✓ All checks passed | Everything looks correct. |
| ⚠ No critical errors | Warnings only (e.g. missing due date). |
| ✗ Needs review | An arithmetic or required-field check failed. |

---

## 6. Approve or edit

Three actions are available at the bottom:

- **Approve** — accept the invoice as it is. Its status changes to `approved`.
- **Edit** — open a form where you can correct any field or line item.
- **Reject** — mark the document as not-processed.

**Edit is strongly recommended** if the validator shows warnings or errors. When you save, validation runs again on the updated values.

---

## 7. Export CSV or Excel

From any single invoice:

- Open the invoice from the **Invoices** page.
- Click **⬇ CSV** or **⬇ Excel** in the actions panel.

From the **Invoices** list:

- Click **⬇ Download all CSV** in the header to get a single CSV file with every invoice.
- Excel export of all invoices is coming — for now, use CSV.

**Single-invoice CSV columns:**

```
supplier_name, invoice_number, invoice_date, currency, subtotal, tax, total
```

**Excel export** includes two sheets:
- **Invoices** — one row per invoice.
- **Line items** — one row per line item, linked by invoice number.

---

## Example result

Given a PDF containing:

```
INVOICE
Supplier: Acme Inc.
Invoice Number: INV-1042
Date: 2026-03-12
Due Date: 2026-04-12
Currency: USD

Subtotal: $1,240.00
Tax:      $124.00
Total:    $1,364.00
```

Voince extracts and validates:

| Field | Value |
|---|---|
| Supplier | Acme Inc. |
| Invoice number | INV-1042 |
| Date | 2026-03-12 |
| Due date | 2026-04-12 |
| Currency | USD |
| Subtotal | 1240 |
| Tax | 124 |
| Total | 1364 |
| Validated | ✓ Subtotal + tax matches total |

---

## The Free plan

Every new account starts on the **Free** plan:

- **10 invoices per month.**
- Includes every feature: AI extraction, validation, review, editing, CSV and Excel export, invoice history.
- The counter resets automatically on the first day of the next month (UTC).

When you hit the limit, the app will show a message and offer an upgrade. See [Accounts & billing](accounts-and-billing.md#plans) for details on the Pro plan.

---

## Next steps

- [Features](features.md) — full list of what Voince can do.
- [AI pipeline](ai-pipeline.md) — how the AI actually works.
- [Validation](validation.md) — the exact rules Voince checks.