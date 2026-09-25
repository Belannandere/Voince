# Troubleshooting

Common issues and how to diagnose them.

---

## Installation and startup

### `pip: command not found`

Use the module form instead:

```bash
python -m pip install -r requirements.txt
```

### `uvicorn: command not found`

Use the module form:

```bash
python -m uvicorn app.main:app --reload
```

### `ModuleNotFoundError: No module named 'app'`

You are running Python from the wrong directory. Always run commands from the project root — the directory that contains the `app/` folder.

### `RuntimeError: Directory 'app/static' does not exist`

Create the missing folders:

```bash
mkdir app/static app/templates     # Windows
mkdir -p app/static app/templates  # macOS / Linux
```

Then restart the server.

### `address already in use` on port 8000

Another process is using port 8000. Options:

- Stop the process using the port.
- Run on a different port:
  ```bash
  python -m uvicorn app.main:app --reload --port 8001
  ```

---

## Ollama

### `Could not reach Ollama at http://localhost:11434`

Ollama is not running. Start it:

```bash
ollama serve
```

Verify with:

```bash
curl http://localhost:11434
```

Expected output: `Ollama is running`.

### `CUDA error: the provided PTX was compiled with an unsupported toolchain`

Your NVIDIA driver is not compatible with the CUDA version Ollama was built against. Force CPU mode:

```powershell
$env:OLLAMA_LLM_LIBRARY="cpu_avx2"
ollama serve
```

To make this permanent, add `OLLAMA_LLM_LIBRARY=cpu_avx2` to your user environment variables on Windows.

### `bind: Only one usage of each socket address`

Ollama is already running (often as a background service). Stop the background process first:

- Windows: use the tray icon → **Quit**, or kill `ollama.exe` in Task Manager.
- macOS: quit the Ollama app.
- Linux: `pkill ollama`.

Then start it with the CPU-mode command above.

### `model not found`

The model was never downloaded:

```bash
ollama pull llama3.2
```

Verify it is present:

```bash
ollama list
```

---

## AI extraction

### `AI extraction failed. Ollama returned HTTP 500`

This usually means Ollama crashed mid-request, most often because of the CUDA incompatibility above. Check:

1. Is Ollama running on CPU mode?
2. Does a simple `ollama run llama3.2` work?
3. Look at the Ollama logs in the terminal where you started it.

### `AI could not understand the document`

The model returned text that was not valid JSON. Rare when `format: "json"` is used, but can happen on:

- Very dense tables.
- Mixed-language documents.
- Documents with unusual punctuation.

Try again. If it consistently fails, try a larger model: `llama3.2` (default) tends to handle complex layouts better than `llama3.2:1b`.

### Slow processing

On CPU-only setups, a single invoice can take 30–90 seconds. The bottleneck is the model.

Practical options:

- **Do not shut down Ollama between requests.** `keep_alive=30m` is already set; the model stays in memory.
- **Use a smaller model.** Change `OLLAMA_MODEL=llama3.2:1b` in `.env` and restart the app. Expect ~2–3× faster processing at a small accuracy cost.
- **Use a GPU.** Ollama automatically uses the GPU when compatible. A supported GPU gives a 10–20× speedup.

Check the timing log printed by the app:

```
[timing] pdf_extract: 85 ms
[timing] ai_extract: 34210 ms
[timing] db_save: 12 ms
```

If `ai_extract` dominates, the bottleneck is the model, not the PDF code.

### The PDF is a scan

If the PDF has no selectable text, Voince responds with:

> *This PDF appears to be a scanned document. OCR is required.*

OCR is not implemented yet. The roadmap includes Tesseract / EasyOCR support.

Workaround: run the PDF through any external OCR tool first, then upload the resulting PDF.

---

## Uploads

### `Please upload a PDF file`

The file extension is not `.pdf`. Voince also checks that the file content starts with `%PDF` — renaming a `.txt` to `.pdf` will not work.

### `File is too large`

The default upload limit is 10 MB. Raise it in `.env`:

```env
MAX_UPLOAD_MB=20
```

Then restart the server.

---

## Authentication

### "Invalid email or password" every time

- Check for typos.
- If the account was created via Google or GitHub and never had a password, use the corresponding OAuth button instead. You can set a password later in **Settings**.

### Lost session after restarting the server

Sessions are signed with `SECRET_KEY`. If it changes between restarts, all sessions become invalid. Make sure `SECRET_KEY` in `.env` is a stable, non-empty value.

### Google / GitHub OAuth

#### `Error 400: redirect_uri_mismatch`

The callback URL in Google Console or GitHub OAuth App does not match the URL the app is using.

**Check three things:**

1. Which URL are you using? `http://localhost:8000` or something else?
2. What is `PUBLIC_BASE_URL` set to in `.env`?
3. What is the redirect URI registered in the Google/GitHub dashboard?

**All three must match exactly** — including scheme (`http` vs `https`), host, port, and path.

If you switch between `localhost` and a tunnel URL (e.g. Tuna, ngrok, Cloudflare Tunnel), the registered callback must match the URL you are currently using. The simplest approach: create one OAuth App per URL.

#### `Access blocked: <app> has not completed the Google verification process`

Your Google account is not on the **Test users** list of the OAuth consent screen. Add yourself under **Google Cloud Console → APIs & Services → OAuth consent screen → Test users**.

---

## Payments

### `Could not start the payment`

Check the server logs for a line starting with `[nowpayments]`. Common causes:

- `HTTP 401` — wrong API key in `.env`.
- `HTTP 403` — the account is not fully verified on the provider side, or the IP is not whitelisted.
- Missing `NOWPAYMENTS_API_KEY` — set it in `.env` and restart.

### The webhook is not received

1. Is `PUBLIC_BASE_URL` reachable from the internet? Test with `curl <PUBLIC_BASE_URL>/health`.
2. Is the IPN URL registered on the provider side pointing to `<PUBLIC_BASE_URL>/webhooks/nowpayments`?
3. Is the webhook secret (`NOWPAYMENTS_IPN_SECRET`) set in `.env`?
4. Look at the server log for lines starting with `[webhook]`.

If the webhook is not arriving, payments will not credit the balance — even if the user pays.

### Balance was credited twice

This should not happen — the webhook handler is idempotent. If you observe it, please file an issue with:

- The `order_id` involved.
- The two timestamps.
- The contents of the `transactions` table for the affected user.

---

## Database

### `sqlite3.OperationalError: no such table: <name>`

The database was not initialised. This usually means `init_db()` was not called on startup. Restart the app; the startup hook runs migrations.

### Stale or corrupted data

If something looks wrong and you want to start clean:

1. Stop the server.
2. Back up the current database:
   ```bash
   move invoices.db invoices.db.backup       # Windows
   mv invoices.db invoices.db.backup         # macOS / Linux
   ```
3. Start the server. A fresh database is created automatically.

**This deletes all accounts and invoices. Do this only on development machines.**

---

## Performance

### High memory usage

Ollama with `llama3.2` uses about 2–2.5 GB of RAM. The FastAPI process itself uses a few hundred MB. If the machine has less than 4 GB total, consider:

- Using a smaller model (`llama3.2:1b`).
- Running Ollama on a different machine and pointing `OLLAMA_URL` at it.

### Slow page loads

Templating and static files are served by FastAPI in development. For production, put a reverse proxy (Nginx, Caddy, Traefik) in front to serve `/static/*` directly and to enable HTTP compression.

---

## Getting help

When reporting a problem, include:

- The exact error text (copy-paste from the terminal).
- The commands you ran.
- The relevant contents of `.env` **with secrets replaced by `***`**.
- The version of Python, Ollama, and the model.

Never paste real secrets, session cookies, or invoice contents into public chats.