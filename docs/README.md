# Voince Documentation

Voince is an AI-powered invoice processing platform that extracts structured data from PDF invoices, validates it and exports it to CSV or Excel.

The AI runs **locally** through [Ollama](https://ollama.com) — your invoices never leave the server that processes them.

> **Local AI processing.** No cloud AI provider. No OpenAI, Anthropic, Google, or any external API.

---

## Quick links

- [Getting started](getting-started.md)
- [Installation](installation.md)
- [Configuration](configuration.md)
- [Architecture](architecture.md)
- [AI pipeline](ai-pipeline.md)
- [Validation](validation.md)
- [Features](features.md)
- [Accounts & billing](accounts-and-billing.md)
- [Privacy & security](privacy-and-security.md)
- [Troubleshooting](troubleshooting.md)
- [FAQ](faq.md)

---

## What is Voince?

Voince turns a PDF invoice into structured, validated data in a few seconds. You upload a PDF, the local AI extracts the fields, a deterministic Python validator checks the numbers, and you review, approve, and export the result.

The full pipeline:

```
PDF invoice
    ↓
pypdf (text extraction)
    ↓
Ollama + Llama 3.2 (local inference)
    ↓
Structured JSON
    ↓
Pydantic (schema validation)
    ↓
Python business rules (arithmetic, required fields)
    ↓
SQLite (persistence)
    ↓
Web UI (review, edit, approve/reject)
    ↓
CSV / Excel export
```

---

## Key features

- **Local AI extraction** — Llama 3.2 runs through Ollama on the same machine.
- **Structured output** — the model returns strict JSON, validated by Pydantic.
- **Deterministic validation** — Python checks the numbers; the AI is never trusted to decide what is correct.
- **Human review** — every invoice can be approved, edited, or rejected before it is saved.
- **Accounts** — email/password, Google OAuth, and GitHub OAuth.
- **Free and Pro plans** — 10 invoices/month free, 100 invoices/month on Pro.
- **Export** — CSV and Excel with one click.
- **Data isolation** — user A never sees user B's invoices.
- **Bilingual UI** — English, Spanish, German, and French.

---

## Local AI processing

The language model runs on the same server that hosts the application. During processing, invoice contents stay on that machine. Nothing is sent to OpenAI, Anthropic, Google, or any other cloud AI provider.

The exact set of models and providers is documented in [AI pipeline](ai-pipeline.md).

---

## Supported documents

**Currently supported:**

- PDF invoices that contain a **selectable text layer**. You should be able to highlight text in any PDF viewer.

**Not yet supported:**

- Scanned PDFs (images without a text layer) — see *Current limitations* below.
- Invoices attached to an email — upload is manual.
- Any non-PDF format (JPG, PNG, DOCX, XLSX, HTML).

---

## Current limitations

Voince is an early MVP. It is honest about what it does and does not do.

- **No OCR.** If a PDF has no text layer, Voince will refuse to process it and tell you clearly. Support for Tesseract / EasyOCR is on the roadmap.
- **The AI can be wrong.** Llama 3.2 is a small model. It handles clean, text-based invoices well, but may occasionally miss line items or produce a wrong total on dense or unusual layouts. That is exactly why deterministic validation and human review exist.
- **Human review is part of the workflow.** Never trust the extracted data without checking it. Voince makes this easy — every field is editable before saving.
- **Processing is slow on CPU.** On a machine without a GPU, a single invoice can take 30–90 seconds. See [Troubleshooting](troubleshooting.md) for performance tips.
- **No accounting integrations yet.** QuickBooks, Xero, and similar systems are not connected.

---

## Documentation conventions

- **Bold** introduces important terms.
- `Code` — filenames, commands, environment variables, endpoint paths.
- Code blocks with `$` prefix are shell commands you can copy-paste.
- All examples use fictional data.