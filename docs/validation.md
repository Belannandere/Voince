# Validation

The validator is the deterministic part of the pipeline. It takes the `Invoice` object produced by the AI and returns a structured result describing what is wrong.

> The AI does not participate in validation. All checks are executed by pure Python.

---

## The result object

```python
@dataclass
class ValidationResult:
    status: str          # "passed" or "review"
    errors: list[str]
    warnings: list[str]
```

- `status = "passed"` — no **errors** (warnings may still be present).
- `status = "review"` — at least one error.

Both errors and warnings are shown to the user. The user decides whether to approve, edit, or reject.

---

## Rules

### Required fields (errors)

| Field | Rule |
|---|---|
| `supplier_name` | Must be non-empty. |
| `invoice_number` | Must be non-empty. |
| `total` | Must be a number. |

These are considered essential to identify and store an invoice. If any is missing, the invoice goes into `review`.

### Arithmetic (errors)

**Subtotal + tax must approximately equal total.**

The comparison uses a tolerance of **0.02** (2 cents) to account for currency rounding. If the difference is larger, Voince reports:

> *Subtotal + tax (X) does not match total (Y).*

Only checked if all three fields are present.

### Line items (warnings)

**Line-item completeness.** Every line item with a missing `description`, `quantity`, `unit_price`, or `total` generates a warning.

**Sum of line items vs. subtotal.** If `subtotal` is present, Voince computes the sum of line-item totals and compares it to `subtotal` with a tolerance of **0.05** (5 cents). A mismatch produces a warning:

> *Sum of line items (X) does not match subtotal (Y).*

Why is this a warning and not an error? Because in practice:

- Some invoices have discounts or freight lines that are not shown as line items.
- Rounding on long itemised lists can drift by a few cents.
- The user can still make the call.

### Presence warnings

Missing, but not blocking:

- `invoice_date`
- `due_date`
- `currency`
- `line_items` (empty list)

These produce warnings like:

> *Invoice date is missing.*

> *No line items found.*

---

## Tolerances

| Check | Tolerance |
|---|---|
| `subtotal + tax ≈ total` | 0.02 |
| `sum(line_items.total) ≈ subtotal` | 0.05 |

Tolerance values are module-level constants in `app/validation.py` — easy to tune if needed.

**Why not zero?** Floating point arithmetic and currency rounding mean that `100.00 + 20.00` occasionally evaluates to `120.00000000000001`. Comparing with `==` would produce false positives. A small tolerance is the standard approach.

---

## What validation does not do

- It does not inspect the raw PDF text.
- It does not consult the AI.
- It does not check that the values are plausible for the real world.
- It does not talk to an exchange rate service.

It is intentionally narrow: arithmetic, required fields, completeness.

---

## Where the rules live

All rules are implemented in `app/validation.py` in the function `validate_invoice(invoice: Invoice) -> ValidationResult`. It is a pure function — no database access, no HTTP calls, no side effects.

That design makes the rules trivial to unit test. See `tests/` for examples.

---

## Human review

Validation is not a gate, it is a guide. Every invoice — regardless of status — can be edited and re-validated before being approved.

The typical flow when the validator flags something:

1. **User opens the invoice** and sees a red or yellow validation block.
2. **User clicks Edit** and corrects the field or line item.
3. **On save**, validation runs again on the updated values.
4. **User approves** once the block is green or the remaining warnings are acceptable.

If the user approves an invoice with errors, the errors are still persisted in `validation_results` — for audit purposes.