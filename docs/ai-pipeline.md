# AI Pipeline

This page explains how Voince turns a PDF invoice into structured data — and where the AI ends and Python begins.

---

## The core principle

> **The LLM extracts. Python decides.**

The language model is treated as a **proposer**, never as an authority. It returns structured JSON; that JSON is then validated by Pydantic and checked against deterministic business rules in Python. If the model invents a number, the validator catches it. If a required field is missing, the UI surfaces it.

The model never sees validation rules, never sees the score, and never decides whether an invoice is "correct". It cannot approve anything.

---

## The pipeline

```
PDF invoice
    ↓
pypdf — extract selectable text
    ↓
Ollama + Llama 3.2 — local inference
    ↓
Structured JSON (schema enforced by `format: json`)
    ↓
Pydantic — schema validation
    ↓
Python business rules — arithmetic, required fields
    ↓
SQLite — persistence
    ↓
Web UI — review, edit, approve/reject
    ↓
CSV / Excel export
```

Each stage is described below.

---

## 1. PDF text extraction

Implementation: `app/pdf.py`, class `PypdfExtractor`.

- Uses **pypdf**, a pure-Python library. No compiled dependencies.
- Reads every page and concatenates the extracted text.
- If the PDF has **no selectable text**, raises `ScannedPDFError`. Voince will tell the user that OCR is required and will not call the AI.
- If the PDF is password-protected or corrupted, raises `PDFExtractionError`.

**Why pypdf and not PyMuPDF?** PyMuPDF is faster but ships as compiled wheels that are not always available for the newest Python versions. pypdf is pure Python, installs everywhere, and is fast enough for 1–2 page invoices.

**Why not OCR?** OCR would introduce a heavy compiled dependency (Tesseract) and slow down the pipeline. It is deliberately excluded from the MVP and listed on the roadmap.

---

## 2. AI extraction

Implementation: `app/ai.py`, class `OllamaInvoiceExtractor`.

The extractor sends two messages to Ollama:

1. A short **system prompt** that describes the exact JSON schema and the rules (dates in ISO format, numbers without symbols, `null` for missing values).
2. The extracted text as the **user message**.

Ollama request options:

| Option | Value | Why |
|---|---|---|
| `format` | `"json"` | Forces Ollama to return syntactically valid JSON. |
| `stream` | `false` | We wait for the full response. |
| `temperature` | `0` | Deterministic extraction. Same input → same output. |
| `num_predict` | `800` | Bounds the response length. Invoice JSON is ~300–600 tokens. |
| `num_ctx` | `4096` | Reduces the context window. Smaller context → faster processing on CPU. |
| `keep_alive` | `"30m"` | Keeps the model in RAM between requests so subsequent invoices do not pay the load-time penalty again. |

The input text is truncated to **8000 characters** before sending. A typical invoice (header, totals, line items) fits well within this limit; Terms & Conditions and second languages do not matter.

**The system prompt does not contain business rules.** It only tells the model what JSON to produce. All numeric and structural checks happen afterwards, in Python.

---

## 3. Schema validation with Pydantic

Implementation: `app/schemas.py`, class `Invoice`.

The JSON returned by the model is parsed into a Pydantic model:

```python
class Invoice(BaseModel):
    supplier_name: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    currency: Optional[str] = None
    subtotal: Optional[float] = None
    tax: Optional[float] = None
    total: Optional[float] = None
    line_items: list[LineItem] = []
```

If the JSON has wrong types, is missing fields, or contains unexpected values, Pydantic raises a `ValidationError`. Voince converts that into a user-friendly message:

> *AI returned JSON that does not match the invoice schema.*

**Why Pydantic here?** It guarantees that downstream code (validator, database, templates) receives a well-typed object. Nothing else in the pipeline has to wonder whether `total` is a number or a string.

---

## 4. Deterministic validation

Implementation: `app/validation.py`.

The validator is **pure Python** — it takes the `Invoice` object and returns a `ValidationResult` with `errors`, `warnings`, and an overall status. It never calls the model.

Rules fall into three groups:

- **Required fields** — supplier name, invoice number, total. Missing → error.
- **Arithmetic** — `subtotal + tax ≈ total`, `sum(line_items) ≈ subtotal`. Mismatch → error or warning.
- **Completeness** — missing date, missing currency, missing line items → warnings.

See [Validation](validation.md) for the full list and tolerances.

---

## 5. Persistence

Implementation: `app/repository.py`.

Everything that survives the request — the document, the invoice header, the line items, the validation result — is written to SQLite. Every query that reads or writes invoice data filters by `user_id`, so users can only see their own data.

---

## 6. Review and export

The result page renders the `Invoice` object and the `ValidationResult`. The user can:

- **Approve** — the document status becomes `approved`.
- **Edit** — a form lets the user fix any field or line item. Saving re-runs the validator.
- **Reject** — the document status becomes `rejected`.

Exports are generated from the stored records, not from the AI output — see [Features](features.md#exports).

---

## What the LLM is not asked to do

The system prompt deliberately avoids asking the model to:

- Validate arithmetic.
- Recommend whether to approve.
- Explain its reasoning.
- Return anything other than JSON.

Every one of those would introduce a new failure mode. The model's only job is to map text to fields.

---

## Swapping the AI provider

`app/ai.py` defines an abstract `AIExtractor`:

```python
class AIExtractor:
    async def extract_invoice(self, text: str) -> Invoice:
        raise NotImplementedError
```

To plug in a different model or provider:

1. Write a class that inherits from `AIExtractor`.
2. Implement `extract_invoice` so that it returns a Pydantic `Invoice`.
3. Replace the module-level singleton at the bottom of `app/ai.py`.

Nothing else in the codebase needs to change. The rest of the pipeline only knows about `Invoice`.

---

## Performance notes

On a typical laptop without a dedicated GPU, timings look roughly like this:

| Stage | Time |
|---|---|
| PDF extraction | 50–300 ms |
| Ollama first request (cold start) | 5–15 s |
| Ollama subsequent requests | 20–90 s |
| Validation + persistence | < 50 ms |

The bottleneck is always Llama. Practical speedups:

- Keep Ollama running — `keep_alive` is already set to 30 minutes.
- Use a smaller model, e.g. `llama3.2:1b`, via `OLLAMA_MODEL` in `.env`.
- Run Ollama on a machine with a GPU — often a 10–20× speedup.

For CPU-only setups, see [Troubleshooting](troubleshooting.md#slow-processing).