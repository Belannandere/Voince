# Installation

Voince is a self-hosted FastAPI application. You can run it on Windows, macOS, or Linux. The AI runs locally through **Ollama**.

---

## Requirements

| Requirement | Version |
|---|---|
| Python | 3.11 or newer (tested on 3.11, 3.12, and 3.14) |
| Ollama | Latest stable — <https://ollama.com/download> |
| Model | `llama3.2` (~2 GB) |
| Disk space | ~3 GB (mostly the model) |
| RAM | 4 GB minimum; 8 GB recommended for comfortable operation |

No cloud API keys are required. No paid services are used.

---

## Step 1 — Install Ollama

### Windows / macOS

Download and install from <https://ollama.com/download>.

### Linux

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Verify the installation:

```bash
ollama --version
```

---

## Step 2 — Download the model

```bash
ollama pull llama3.2
```

This downloads the model (~2 GB) and caches it locally.

Verify:

```bash
ollama list
```

You should see `llama3.2` in the output.

---

## Step 3 — Get the Voince source code

### Option A — Clone from GitHub

```bash
git clone https://github.com/Belannandere/Virelo.git
cd Virelo
```

### Option B — Download a ZIP

Download the repository as a ZIP and unpack it. Rename the folder to `voince` if you prefer.

---

## Step 4 — Create a virtual environment

### Windows (PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run once:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

### Windows (CMD)

```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

---

## Step 5 — Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If `pip` is not found, always use `python -m pip` instead.

---

## Step 6 — Create the environment file

```bash
copy .env.example .env       # Windows
cp .env.example .env         # macOS / Linux
```

Generate a secret key and paste it into `.env`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Open `.env` and set:

```env
SECRET_KEY=<paste the value from the previous step>
```

The rest of the defaults work out of the box for local development. See [Configuration](configuration.md) for a full list of variables.

---

## Step 7 — Run Ollama

Ollama runs as a background service. If you installed it as a desktop app, it is already running — check by opening <http://localhost:11434>.

If you need to start it manually:

```bash
ollama serve
```

### If Ollama crashes with a CUDA error on Windows

You may see:

```
CUDA error: the provided PTX was compiled with an unsupported toolchain
```

This means your NVIDIA driver is not compatible with the CUDA version Ollama was built against. Run Ollama in CPU mode instead:

```powershell
$env:OLLAMA_LLM_LIBRARY="cpu_avx2"
ollama serve
```

To make this permanent, add `OLLAMA_LLM_LIBRARY=cpu_avx2` to your user environment variables.

---

## Step 8 — Run Voince

You need **two terminals** if Ollama is not already running as a service:

**Terminal 1 — Ollama** (skip if it is running in the background):

```bash
ollama serve
```

**Terminal 2 — Voince**:

```bash
python -m uvicorn app.main:app --reload
```

Open <http://localhost:8000> in your browser.

---

## Running from a different location

If you want to run Voince from a custom directory or under a process manager, keep these points in mind:

- Run `uvicorn` from the project root — the app expects `app/` and `uploads/` to be siblings.
- The SQLite database is created next to the project root as `invoices.db`.
- Uploaded PDFs are stored in `uploads/`.
- The Ollama URL and model are configurable in `.env`.

---

## Verifying the installation

1. Open <http://localhost:8000/health>. It should return `{"status":"ok"}`.
2. Open <http://localhost:8000/pricing>. You should see the Free and Pro plans.
3. Register an account and upload a sample PDF invoice.
4. If AI extraction succeeds, the setup is complete.

---

## Uninstalling

1. Stop Voince (`Ctrl + C` in the uvicorn terminal).
2. Delete the project folder.
3. Optionally, uninstall Ollama and delete its model cache (in `~/.ollama` on Linux/macOS, `%USERPROFILE%\.ollama` on Windows).

---

## Next steps

- [Configuration](configuration.md) — all environment variables.
- [Getting started](getting-started.md) — how to use Voince.
- [Troubleshooting](troubleshooting.md) — common issues.