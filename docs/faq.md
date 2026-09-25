# FAQ

Short answers to the questions users ask most.

---

### What files are supported?

PDF invoices with a selectable text layer. You should be able to highlight text in any PDF viewer. Scanned documents (images without a text layer) are not supported yet.

---

### How accurate is the extraction?

Extraction is powered by a local Llama model and validated with deterministic business rules. Accuracy is high on clean, text-based invoices, but you can always review and edit the result before saving.

---

### Can I edit extracted data?

Yes. Every invoice can be reviewed and edited — fields and line items alike — before you approve it.

---

### Can I export to CSV or Excel?

Yes. You can export a single invoice or all of your invoices to CSV, and a single invoice to Excel. Excel export for the full list is on the roadmap.

---

### What happens when I reach my monthly limit?

Processing stops for the rest of the calendar month. The limit resets automatically on the first day of the next month (UTC).

---

### How does the Pro plan work?

Pro is $10 per month and raises your limit to 100 invoices per month. You top up your internal balance with crypto, and the subscription is charged automatically from that balance every month.

---

### Where does my data go?

Your invoices stay on the server that runs Voince. The AI runs locally through Ollama — nothing is sent to OpenAI, Anthropic, Google, or any other cloud AI provider. See [Privacy & security](privacy-and-security.md).

---

### Do I need to be online?

No. Voince runs entirely on your machine (or your server). The only optional outbound connections are OAuth sign-in (if you choose it) and payments.

---

### Can I run Voince without Ollama?

Not for AI extraction. Ollama is how Voince talks to the model. If Ollama is not running, uploads will still be accepted but AI extraction will fail with a clear error.

---

### Can I use a different model?

Yes. Change `OLLAMA_MODEL` in `.env` to any model that Ollama supports and restart the app. Smaller models are faster; larger models are usually more accurate.

---

### Can I run Voince on a server?

Yes. See the main `README.md` for deployment notes. The same code runs locally and in production — the difference is which `.env` values you set.

---

### Is there a mobile app?

No. The web interface is responsive and works well on phones and tablets. There is no native iOS or Android app.

---

### Can I delete my account?

Yes. Account deletion is available in **Settings → Danger zone**. It removes your account, all your documents, all your invoices, and all your uploaded PDF files. This cannot be undone.

---

### How do I cancel Pro?

Open **Account → Subscription → Cancel subscription**. You keep Pro access until the end of the current paid period; after that, your account returns to the Free plan.

---

### Where do I report a bug?

Open an issue on the GitHub repository. Include the exact error text, the commands you ran, and the values in your `.env` with any secrets masked.

---

### Can I contribute?

Yes. Contributions are welcome — see the main `README.md` for the license and contact info. Please keep the following principles in mind:

- The AI extracts, Python validates. Do not move business rules into the model.
- Keep the pipeline simple: one process, one database, no microservices.
- Document what changed and why.