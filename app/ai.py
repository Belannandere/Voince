"""Ollama-based invoice extraction.

Optimized for a small VPS (4 vCPU / 4 GB RAM) with llama3.2:1b.

Key design choices:
  - Only ONE inference runs at a time (asyncio.Semaphore). This prevents
    OOM/swap when multiple users upload simultaneously. Other users wait
    in queue — the UI shows "processing", not an error.
  - One shared httpx.AsyncClient (connection reuse).
  - Input is truncated by keeping head AND tail, because invoice totals
    live at the bottom of the document, not the top.
  - Output tokens are capped; invoice JSON never needs 800 tokens.
  - Low temperature / top_k=1 for deterministic extraction.
"""

import asyncio
import json
import logging
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import settings
from app.schemas import Invoice
from app.timing import timer

logger = logging.getLogger("ai")


SYSTEM_PROMPT = (
    "Extract invoice data from the text. "
    "Return ONLY JSON, no explanations, no markdown. "
    'Schema: {"supplier_name":str|null,"invoice_number":str|null,'
    '"invoice_date":str|null,"due_date":str|null,"currency":str|null,'
    '"subtotal":num|null,"tax":num|null,"total":num|null,'
    '"line_items":[{"description":str|null,"quantity":num|null,'
    '"unit_price":num|null,"total":num|null}]}. '
    "Rules: null for missing; never invent values; dates as YYYY-MM-DD; "
    "currency as 3-letter code; numbers without symbols."
)


class AIExtractionError(Exception):
    """Base error for AI extraction problems."""


class OllamaUnavailableError(AIExtractionError):
    """Ollama is not reachable."""


class AIBadResponseError(AIExtractionError):
    """Llama returned something we could not turn into an Invoice."""


class AIExtractor:
    """Abstract interface. Swap implementation without touching the rest of the app."""

    async def extract_invoice(self, text: str) -> Invoice:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Shared HTTP client (module-level singleton)
# ---------------------------------------------------------------------------

_http_client: httpx.AsyncClient | None = None


def _get_http_client(timeout: float) -> httpx.AsyncClient:
    """Return a shared AsyncClient, creating it on first use."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(
                max_connections=4,
                max_keepalive_connections=2,
            ),
        )
    return _http_client


async def close_ai_http_client() -> None:
    """Close the shared client (call from FastAPI lifespan shutdown)."""
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
    _http_client = None


# ---------------------------------------------------------------------------
# Text preprocessing
# ---------------------------------------------------------------------------

def _truncate_for_model(text: str, max_chars: int) -> str:
    """Keep head + tail of the text.

    Invoices put key fields at the top (vendor, number, dates) AND at the
    bottom (subtotal, tax, total, amount due). A naive `text[:N]` slice
    loses totals entirely on long documents.

    We keep ~45% head and ~55% tail, joined by a marker so the model can
    tell there's a gap. No NLP, no regex, no keyword scanning — simple and
    predictable.
    """
    if len(text) <= max_chars:
        return text

    head_chars = int(max_chars * 0.45)
    tail_chars = max_chars - head_chars - 8  # room for the separator
    return f"{text[:head_chars]}\n...\n{text[-tail_chars:]}"


def _extract_json_object(s: str) -> str:
    """Best-effort extraction of a JSON object from raw model output.

    Ollama's format="json" usually returns clean JSON, but small models
    occasionally wrap it in prose ("Here is the JSON: {...}"). We do NOT
    use regex — we simply find the outermost braces.
    """
    s = s.strip()

    # Strip markdown fences if present.
    if s.startswith("```"):
        first_newline = s.find("\n")
        if first_newline != -1:
            s = s[first_newline + 1:]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()

    # Fallback: find the outermost {...}.
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        return s[start:end + 1]
    return s


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------

class OllamaInvoiceExtractor(AIExtractor):
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: float = 90.0,
        num_ctx: int = 2048,
        num_predict: int = 600,
        keep_alive: str = "15m",
        num_thread: int = 2,
        max_input_chars: int = 8000,
        concurrency: int = 1,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        self.keep_alive = keep_alive
        self.num_thread = num_thread
        self.max_input_chars = max_input_chars
        # Single inference at a time. On a 4 GB VPS two parallel runs
        # would swap the machine to death.
        self._semaphore = asyncio.Semaphore(concurrency)

    async def extract_invoice(self, text: str) -> Invoice:
        text = _truncate_for_model(text, self.max_input_chars)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "format": "json",
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": 0,
                "top_k": 1,
                "top_p": 0.1,
                "repeat_penalty": 1.0,
                "num_predict": self.num_predict,
                "num_ctx": self.num_ctx,
                "num_thread": self.num_thread,
            },
        }

        client = _get_http_client(self.timeout)

        # One inference at a time. Other callers await here.
        with timer("ai_queue_wait"):
            await self._semaphore.acquire()
        try:
            with timer("ai_request"):
                try:
                    response = await client.post(
                        f"{self.base_url}/api/chat", json=payload
                    )
                    response.raise_for_status()
                except httpx.ConnectError as exc:
                    raise OllamaUnavailableError(
                        f"Could not reach Ollama at {self.base_url}. Is it running?"
                    ) from exc
                except httpx.TimeoutException as exc:
                    raise AIExtractionError(
                        "Ollama took too long to respond. "
                        "Try a smaller document or a smaller model."
                    ) from exc
                except httpx.HTTPStatusError as exc:
                    body = ""
                    try:
                        body = exc.response.text[:300]
                    except Exception:
                        pass
                    raise AIExtractionError(
                        f"Ollama returned HTTP {exc.response.status_code}. "
                        f"Details: {body or 'no body'}"
                    ) from exc
        finally:
            self._semaphore.release()

        with timer("ai_parse"):
            data = response.json()
            content = (data.get("message") or {}).get("content", "")
            if not content:
                raise AIBadResponseError("AI returned an empty response.")

            raw = _extract_json_object(content)

            try:
                parsed: Any = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise AIBadResponseError(
                    "AI could not understand the document. "
                    "Please try again or edit the data manually."
                ) from exc

            try:
                return Invoice.model_validate(parsed)
            except ValidationError as exc:
                raise AIBadResponseError(
                    "AI returned JSON that does not match the invoice schema."
                ) from exc


# Module-level singleton used by the app.
ai_extractor: AIExtractor = OllamaInvoiceExtractor(
    base_url=settings.ollama_url,
    model=settings.ollama_model,
    timeout=settings.ollama_timeout,
    num_ctx=settings.ollama_num_ctx,
    num_predict=settings.ollama_num_predict,
    keep_alive=settings.ollama_keep_alive,
    num_thread=settings.ollama_num_thread,
    max_input_chars=settings.ollama_max_input_chars,
    concurrency=1,
)

async def warmup_ollama() -> None:
    """Send a tiny request so the model is loaded into RAM before
    the first real user request. Called from the FastAPI lifespan.
    """
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            await client.post(
                f"{settings.ollama_url}/api/chat",
                json={
                    "model": settings.ollama_model,
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": False,
                    "keep_alive": settings.ollama_keep_alive,
                    "options": {
                        "num_predict": 1,
                        "num_ctx": settings.ollama_num_ctx,
                    },
                },
            )
            logger.info(
                "[ai] ollama warmed up (model=%s, num_ctx=%d)",
                settings.ollama_model,
                settings.ollama_num_ctx,
            )
    except Exception as exc:
        logger.warning("[ai] ollama warmup failed: %s", exc)