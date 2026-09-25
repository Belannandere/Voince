import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from starlette.middleware.sessions import SessionMiddleware

from app.ai import (
    AIExtractionError,
    ai_extractor,
    close_ai_http_client,
    warmup_ollama,
)
from app.auth import (
    RequiresLogin,
    get_current_user,
    get_current_user_optional,
    get_or_create_oauth_user,
    get_user_by_email,
    hash_password,
    login_user,
    logout_user,
    verify_password,
)
from app.billing import (
    activate_pro_period,
    add_to_balance,
    cancel_subscription,
    enforce_expiration,
    find_topup_by_order,
    max_topup,
    min_topup,
    pro_price,
    try_charge_and_activate,
)
from app.config import settings
from app.database import get_session, init_db
from app.export import records_to_csv
from app.export_excel import records_to_xlsx
from app.i18n import LANGUAGES, get_lang, t
from app.limiter import (
    release_slot,
    remaining as remaining_slots,
    reserve_slot,
)
from app.models import Document, InvoiceRecord, TopUp, Transaction, User
from app.oauth import oauth
from app.pdf import PDFExtractionError, ScannedPDFError, pdf_extractor
from app.providers import PaymentError, trybit_provider
from app.repository import (
    delete_document_for_user,
    delete_user_and_data,
    get_document_for_user,
    list_documents,
    list_invoice_records_for_user,
    save_extraction,
    set_document_status,
    update_invoice,
)
from app.schemas import Invoice, LineItem
from app.timing import timer
from app.validation import ValidationResult, validate_invoice

# ---------- Logging ----------

logger = logging.getLogger("voince")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


BASE_DIR = Path(__file__).resolve().parent


# ---------- DB migration (idempotent) ----------

def _ensure_topup_columns() -> None:
    """Add new TopUp columns to an existing SQLite DB.

    SQLModel.create_all() does not ALTER existing tables, so this function
    fills that gap without touching any data. Safe to run on every boot.

    Non-SQLite databases are skipped — run the equivalent ALTER manually:
      ALTER TABLE topups ADD COLUMN provider VARCHAR DEFAULT 'cryptobot';
      ALTER TABLE topups ADD COLUMN provider_payment_id VARCHAR;
      ALTER TABLE topups ADD COLUMN purpose VARCHAR DEFAULT 'topup';
    """
    import sqlite3

    url = settings.database_url or ""
    if not url.startswith("sqlite"):
        return

    path = url.replace("sqlite:///", "").replace("sqlite://", "")
    if not path or path == ":memory:":
        return

    try:
        con = sqlite3.connect(path)
        cur = con.cursor()
        cur.execute("PRAGMA table_info(topups)")
        cols = {row[1] for row in cur.fetchall()}
        if not cols:
            # Table doesn't exist yet; create_all() will create it fresh.
            con.close()
            return

        if "provider" not in cols:
            cur.execute(
                "ALTER TABLE topups ADD COLUMN provider VARCHAR DEFAULT 'cryptobot'"
            )
        if "provider_payment_id" not in cols:
            cur.execute(
                "ALTER TABLE topups ADD COLUMN provider_payment_id VARCHAR"
            )
        if "purpose" not in cols:
            cur.execute(
                "ALTER TABLE topups ADD COLUMN purpose VARCHAR DEFAULT 'topup'"
            )
        con.commit()
        con.close()
        logger.info("[migration] topups columns checked")
    except Exception as exc:
        logger.warning("[migration] topup column check skipped: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ensure_topup_columns()
    init_db()
    await warmup_ollama()
    try:
        yield
    finally:
        await close_ai_http_client()


app = FastAPI(
    title="Voince",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="voince_session",
    max_age=settings.session_max_age,
    same_site="lax",
    https_only=settings.https_only,
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# ---------- Jinja2 with automatic i18n context ----------

from starlette.templating import Jinja2Templates as _BaseTemplates


class I18nTemplates(_BaseTemplates):
    """Automatically injects lang, available_langs and t() into every template context."""

    def TemplateResponse(self, request, name, context=None, **kwargs):
        context = dict(context or {})
        lang = get_lang(request.cookies.get("voince_lang"))
        context.setdefault("lang", lang)
        context.setdefault("available_langs", LANGUAGES)
        context.setdefault("t", lambda key: t(key, lang))
        return super().TemplateResponse(request, name, context, **kwargs)


templates = I18nTemplates(directory=BASE_DIR / "templates")


# =============================================================
# Auth exception handler
# =============================================================

@app.exception_handler(RequiresLogin)
def requires_login_handler(request: Request, exc: RequiresLogin):
    return RedirectResponse(url="/login", status_code=303)


# =============================================================
# Public: landing, health, pricing, legal
# =============================================================

@app.get("/set-language/{lang}")
def set_language(lang: str, request: Request, next: str = "/"):
    response = RedirectResponse(url=next, status_code=303)
    if lang in LANGUAGES:
        response.set_cookie(
            "voince_lang",
            lang,
            max_age=60 * 60 * 24 * 365,  # 1 year
            httponly=False,
            samesite="lax",
        )
    return response


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    user: User | None = Depends(get_current_user_optional),
):
    return templates.TemplateResponse(
        request,
        "index.html",
        {"title": "Voince", "current_user": user},
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/pricing", response_class=HTMLResponse)
def pricing(
    request: Request,
    user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    if user is not None:
        user = enforce_expiration(session, user)

    return templates.TemplateResponse(
        request,
        "pricing.html",
        {
            "title": "Pricing",
            "current_user": user,
            "settings": settings,
        },
    )

@app.get("/docs", response_class=HTMLResponse)
def docs_page(
    request: Request,
    user: User | None = Depends(get_current_user_optional),
):
    return templates.TemplateResponse(
        request,
        "docs.html",
        {"title": "Documentation", "current_user": user},
    )


@app.get("/privacy", response_class=HTMLResponse)
def privacy_page(
    request: Request,
    user: User | None = Depends(get_current_user_optional),
):
    return templates.TemplateResponse(
        request,
        "privacy.html",
        {"title": "Privacy Policy", "current_user": user},
    )


@app.get("/terms", response_class=HTMLResponse)
def terms_page(
    request: Request,
    user: User | None = Depends(get_current_user_optional),
):
    return templates.TemplateResponse(
        request,
        "terms.html",
        {"title": "Terms of Service", "current_user": user},
    )


# =============================================================
# Auth: register / login / logout
# =============================================================

@app.get("/register", response_class=HTMLResponse)
def register_form(
    request: Request,
    user: User | None = Depends(get_current_user_optional),
):
    if user is not None:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        "register.html",
        {"title": "Sign up", "error": None, "current_user": None},
    )


@app.post("/register", response_class=HTMLResponse)
def register_submit(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    password_confirm: str = Form(""),
    session: Session = Depends(get_session),
):
    email_clean = (email or "").strip().lower()

    def _fail(message: str):
        return templates.TemplateResponse(
            request,
            "register.html",
            {"title": "Sign up", "error": message, "current_user": None},
            status_code=400,
        )

    if "@" not in email_clean or len(email_clean) < 5:
        return _fail("Please enter a valid email address.")
    if not password or len(password) < 8:
        return _fail("Password must be at least 8 characters long.")
    if password != password_confirm:
        return _fail("Passwords do not match.")
    if len(password.encode("utf-8")) > 72:
        return _fail("Password is too long.")
    if get_user_by_email(session, email_clean) is not None:
        return _fail("This email is already registered.")

    user = User(email=email_clean, password_hash=hash_password(password))
    session.add(user)
    session.commit()
    session.refresh(user)

    login_user(request, user)
    return RedirectResponse("/", status_code=303)


_LOGIN_ERRORS = {
    "oauth_failed": "OAuth authentication failed. Please try again.",
    "oauth_unavailable": "This sign-in method is not configured.",
    "oauth_link_failed": "This email is already registered. Please log in with your password.",
}


@app.get("/login", response_class=HTMLResponse)
def login_form(
    request: Request,
    user: User | None = Depends(get_current_user_optional),
):
    if user is not None:
        return RedirectResponse("/", status_code=303)
    error = _LOGIN_ERRORS.get(request.query_params.get("error") or "")
    return templates.TemplateResponse(
        request,
        "login.html",
        {"title": "Log in", "error": error, "current_user": None},
    )


@app.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    session: Session = Depends(get_session),
):
    email_clean = (email or "").strip().lower()
    user = get_user_by_email(session, email_clean)

    if user is None or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "title": "Log in",
                "error": "Invalid email or password.",
                "current_user": None,
            },
            status_code=401,
        )

    login_user(request, user)
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
def logout(request: Request):
    logout_user(request)
    return RedirectResponse("/login", status_code=303)


# =============================================================
# OAuth: Google
# =============================================================

def _oauth_configured(provider: str) -> bool:
    if provider == "google":
        return bool(settings.google_client_id and settings.google_client_secret)
    if provider == "github":
        return bool(settings.github_client_id and settings.github_client_secret)
    return False


@app.get("/auth/google")
async def auth_google(request: Request):
    if not _oauth_configured("google"):
        return RedirectResponse("/login?error=oauth_unavailable", status_code=303)
    redirect_uri = str(request.url_for("auth_google_callback"))
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/google/callback")
async def auth_google_callback(
    request: Request,
    session: Session = Depends(get_session),
):
    if not _oauth_configured("google"):
        return RedirectResponse("/login?error=oauth_unavailable", status_code=303)

    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception:
        return RedirectResponse("/login?error=oauth_failed", status_code=303)

    userinfo = token.get("userinfo")
    if not userinfo:
        try:
            userinfo = await oauth.google.parse_id_token(request, token)
        except Exception:
            userinfo = None

    if not userinfo or not userinfo.get("email") or not userinfo.get("sub"):
        return RedirectResponse("/login?error=oauth_failed", status_code=303)

    try:
        user = get_or_create_oauth_user(
            session,
            provider="google",
            provider_id=str(userinfo["sub"]),
            email=userinfo["email"],
        )
    except Exception:
        return RedirectResponse("/login?error=oauth_link_failed", status_code=303)

    login_user(request, user)
    return RedirectResponse("/", status_code=303)


# =============================================================
# OAuth: GitHub
# =============================================================

@app.get("/auth/github")
async def auth_github(request: Request):
    if not _oauth_configured("github"):
        return RedirectResponse("/login?error=oauth_unavailable", status_code=303)
    redirect_uri = str(request.url_for("auth_github_callback"))
    return await oauth.github.authorize_redirect(request, redirect_uri)


@app.get("/auth/github/callback")
async def auth_github_callback(
    request: Request,
    session: Session = Depends(get_session),
):
    if not _oauth_configured("github"):
        return RedirectResponse("/login?error=oauth_unavailable", status_code=303)

    try:
        token = await oauth.github.authorize_access_token(request)
    except Exception:
        return RedirectResponse("/login?error=oauth_failed", status_code=303)

    try:
        profile_resp = await oauth.github.get("user", token=token)
        profile = profile_resp.json()
    except Exception:
        return RedirectResponse("/login?error=oauth_failed", status_code=303)

    github_id = str(profile.get("id") or "")
    email = profile.get("email")

    if not email:
        try:
            emails_resp = await oauth.github.get("user/emails", token=token)
            for e in emails_resp.json():
                if e.get("primary") and e.get("verified"):
                    email = e["email"]
                    break
        except Exception:
            email = None

    if not email or not github_id:
        return RedirectResponse("/login?error=oauth_failed", status_code=303)

    try:
        user = get_or_create_oauth_user(
            session,
            provider="github",
            provider_id=github_id,
            email=email,
        )
    except Exception:
        return RedirectResponse("/login?error=oauth_link_failed", status_code=303)

    login_user(request, user)
    return RedirectResponse("/", status_code=303)


# =============================================================
# Account
# =============================================================

@app.get("/account", response_class=HTMLResponse)
def account(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    user = enforce_expiration(session, user)

    used = int(user.invoices_used or 0)
    limit = int(user.invoices_limit or 0)
    remaining = max(0, limit - used)
    pct = min(100, round(used * 100 / limit)) if limit > 0 else 0

    transactions = list(
        session.exec(
            select(Transaction)
            .where(Transaction.user_id == user.id)
            .order_by(Transaction.created_at.desc())
            .limit(10)
        ).all()
    )

    return templates.TemplateResponse(
        request,
        "account.html",
        {
            "title": "Account",
            "current_user": user,
            "usage_used": used,
            "usage_limit": limit,
            "usage_remaining": remaining,
            "usage_pct": pct,
            "transactions": transactions,
            "settings": settings,
        },
    )


# =============================================================
# Settings: password / email / delete
# =============================================================

@app.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "title": "Settings",
            "current_user": user,
            "error": None,
            "success": None,
            "has_password": bool(user.password_hash),
        },
    )


@app.post("/settings/password", response_class=HTMLResponse)
def settings_password(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    current_password: str = Form(""),
    new_password: str = Form(""),
    new_password_confirm: str = Form(""),
):
    def _render(error=None, success=None, status_code=200):
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "title": "Settings",
                "current_user": user,
                "error": error,
                "success": success,
                "has_password": bool(user.password_hash),
            },
            status_code=status_code,
        )

    if user.password_hash:
        if not verify_password(current_password, user.password_hash):
            return _render(error="Current password is incorrect.", status_code=400)

    if not new_password or len(new_password) < 8:
        return _render(
            error="New password must be at least 8 characters long.",
            status_code=400,
        )
    if new_password != new_password_confirm:
        return _render(error="New passwords do not match.", status_code=400)
    if len(new_password.encode("utf-8")) > 72:
        return _render(error="Password is too long.", status_code=400)

    user.password_hash = hash_password(new_password)
    session.add(user)
    session.commit()
    session.refresh(user)

    if current_password:
        return _render(success="Password updated.")
    return _render(
        success="Password set. You can now log in with email and password too."
    )


@app.post("/settings/email", response_class=HTMLResponse)
def settings_email(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    new_email: str = Form(""),
    current_password: str = Form(""),
):
    def _render(error=None, success=None, status_code=200):
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "title": "Settings",
                "current_user": user,
                "error": error,
                "success": success,
                "has_password": bool(user.password_hash),
            },
            status_code=status_code,
        )

    if user.password_hash:
        if not verify_password(current_password, user.password_hash):
            return _render(error="Current password is incorrect.", status_code=400)

    new_email_clean = (new_email or "").strip().lower()
    if "@" not in new_email_clean or len(new_email_clean) < 5:
        return _render(error="Please enter a valid email address.", status_code=400)
    if new_email_clean == user.email:
        return _render(success="Email is unchanged.")
    if get_user_by_email(session, new_email_clean) is not None:
        return _render(error="This email is already registered.", status_code=400)

    user.email = new_email_clean
    session.add(user)
    session.commit()
    session.refresh(user)
    return _render(success="Email updated.")


@app.post("/settings/delete")
def settings_delete(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    confirm_email: str = Form(""),
    current_password: str = Form(""),
):
    def _render(error=None, status_code=400):
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "title": "Settings",
                "current_user": user,
                "error": error,
                "success": None,
                "has_password": bool(user.password_hash),
            },
            status_code=status_code,
        )

    confirm = (confirm_email or "").strip().lower()
    if confirm != user.email.lower():
        return _render(error="Confirmation email does not match your account email.")

    if user.password_hash:
        if not verify_password(current_password, user.password_hash):
            return _render(error="Current password is incorrect.")

    user_id = user.id
    filepaths = delete_user_and_data(session, user_id)

    for fp in filepaths:
        try:
            Path(fp).unlink(missing_ok=True)
        except OSError:
            pass

    logout_user(request)
    return RedirectResponse("/", status_code=303)


# =============================================================
# Billing: balance, top-up, subscription (Trybit)
# =============================================================

@app.get("/billing/topup", response_class=HTMLResponse)
def billing_topup_page(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    needed: float = 0,
):
    user = enforce_expiration(session, user)
    return templates.TemplateResponse(
        request,
        "billing_topup.html",
        {
            "title": "Add funds",
            "current_user": user,
            "settings": settings,
            "needed": needed,
            "min_topup": min_topup(),
            "max_topup": max_topup(),
            "pro_price": pro_price(),
            "error": None,
        },
    )


@app.post("/billing/topup", response_class=HTMLResponse)
async def billing_topup_create(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    amount: str = Form(""),
):
    user = enforce_expiration(session, user)

    def _render(error: str, status_code: int = 400):
        return templates.TemplateResponse(
            request,
            "billing_topup.html",
            {
                "title": "Add funds",
                "current_user": user,
                "settings": settings,
                "needed": 0,
                "min_topup": min_topup(),
                "max_topup": max_topup(),
                "pro_price": pro_price(),
                "error": error,
            },
            status_code=status_code,
        )

    # Amount is validated server-side. Never trust the client.
    try:
        amount_val = float((amount or "").strip().replace(",", "."))
    except ValueError:
        return _render("Please enter a valid amount.")

    if amount_val < min_topup():
        return _render(f"Minimum top-up is ${min_topup():.0f}.")
    if amount_val > max_topup():
        return _render(f"Maximum top-up is ${max_topup():.0f}.")

    order_id = f"VOINCE-TOPUP-{user.id}-{uuid.uuid4().hex[:12]}"

    try:
        result = await trybit_provider.create_payment(
            amount=amount_val,
            order_id=order_id,
            email=user.email,
            purpose="topup",
        )
    except PaymentError:
        logger.error("[billing] topup creation failed for user %s", user.id)
        return _render(
            "Payment service is temporarily unavailable. Please try again later.",
            status_code=502,
        )

    topup = TopUp(
        user_id=user.id,
        order_id=order_id,
        provider="trybit",
        provider_payment_id=result["provider_payment_id"],
        purpose="topup",
        amount=amount_val,
        currency="USD",
        status="pending",
    )
    session.add(topup)
    session.commit()
    session.refresh(topup)

    logger.info(
        "[billing] trybit topup %s for user %s (%.2f USD) → %s",
        order_id,
        user.id,
        amount_val,
        result["provider_payment_id"],
    )

    return templates.TemplateResponse(
        request,
        "billing_pay.html",
        {
            "title": "Complete payment",
            "current_user": user,
            "settings": settings,
            "topup": topup,
            "amount": amount_val,
            "asset": "USD",
            "payment_url": result.get("payment_url"),
        },
    )


@app.post("/billing/upgrade")
async def billing_upgrade(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """
    Upgrade to Pro.

    Path A: user already has enough balance → charge immediately, activate.
    Path B: otherwise → create a direct Trybit payment for the Pro price.
    Price is always server-side.
    """
    user = enforce_expiration(session, user)

    if user.plan == "pro" and user.subscription_status in ("active", "past_due"):
        return RedirectResponse("/account", status_code=303)

    # Path A — instant activation from internal balance
    if (user.balance or 0.0) >= pro_price():
        if try_charge_and_activate(session, user):
            logger.info("[billing] user %s upgraded using balance", user.id)
            return RedirectResponse("/account", status_code=303)

    # Path B — direct Pro payment via Trybit
    order_id = f"VOINCE-PRO-{user.id}-{uuid.uuid4().hex[:12]}"

    try:
        result = await trybit_provider.create_payment(
            amount=pro_price(),
            order_id=order_id,
            email=user.email,
            purpose="subscription",
        )
    except PaymentError:
        logger.error(
            "[billing] Pro payment creation failed for user %s", user.id
        )
        return templates.TemplateResponse(
            request,
            "billing_topup.html",
            {
                "title": "Upgrade to Pro",
                "current_user": user,
                "settings": settings,
                "needed": 0,
                "min_topup": min_topup(),
                "max_topup": max_topup(),
                "pro_price": pro_price(),
                "error": "Payment service is temporarily unavailable. Please try again later.",
            },
            status_code=502,
        )

    topup = TopUp(
        user_id=user.id,
        order_id=order_id,
        provider="trybit",
        provider_payment_id=result["provider_payment_id"],
        purpose="subscription",
        amount=pro_price(),
        currency="USD",
        status="pending",
    )
    session.add(topup)
    session.commit()
    session.refresh(topup)

    logger.info(
        "[billing] trybit Pro payment %s for user %s → %s",
        order_id,
        user.id,
        result["provider_payment_id"],
    )

    return templates.TemplateResponse(
        request,
        "billing_pay.html",
        {
            "title": "Complete payment",
            "current_user": user,
            "settings": settings,
            "topup": topup,
            "amount": pro_price(),
            "asset": "USD",
            "payment_url": result.get("payment_url"),
        },
    )


@app.post("/billing/cancel-subscription")
def billing_cancel_subscription(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    user = enforce_expiration(session, user)
    if user.plan == "pro" and user.subscription_status == "active":
        cancel_subscription(session, user)
    return RedirectResponse(url="/account", status_code=303)


@app.get("/billing/success", response_class=HTMLResponse)
def billing_success(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    order_id: str = "",
):
    """
    Landing page after Trybit checkout.

    IMPORTANT: this page does NOT activate Pro and does NOT credit the
    balance — the webhook does. We only reflect what the database already
    knows. A user who manually hits this URL cannot grant themselves
    anything.
    """
    user = enforce_expiration(session, user)

    topup_status = "unknown"
    if order_id:
        topup = find_topup_by_order(session, order_id)
        if topup is not None and topup.user_id == user.id:
            topup_status = topup.status

    return templates.TemplateResponse(
        request,
        "billing_success.html",
        {
            "title": "Payment",
            "current_user": user,
            "order_id": order_id,
            "topup_status": topup_status,
        },
    )


@app.get("/billing/cancel", response_class=HTMLResponse)
def billing_cancel(
    request: Request,
    user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(
        request,
        "billing_cancel.html",
        {
            "title": "Payment cancelled",
            "current_user": user,
            "error": None,
        },
    )


@app.post("/api/billing/trybit/webhook")
async def trybit_webhook(
    request: Request,
    session: Session = Depends(get_session),
):
    """
    Receive a Trybit Postback.

    Trybit sends a JWT (HS256, signed with the project Secret Key).
    The JWT payload may be minimal — {"id": "...", "exp": ...} — in
    which case we call the Trybit API to fetch the actual invoice
    status. This is also the safer pattern: an attacker cannot fake
    payment status by intercepting the webhook.

    Verification:
      - JWT-HS256 with TRYBIT_WEBHOOK_SECRET (primary).
      - RSA-SHA256 with TRYBIT_WEBHOOK_PUBLIC_KEY (fallback, unused).
      - Fail-closed: unverifiable → 401. Never activate Pro unverified.
    """
    raw_body = await request.body()
    signature = request.headers.get("signature", "")
    headers_dict = dict(request.headers)



    if not trybit_provider.verify_webhook_signature(
        raw_body, signature, headers_dict
    ):
        logger.warning("[trybit-webhook] invalid or unverifiable signature")
        return Response(status_code=401)

    # Extract data from JWT payload (primary) and JSON body (if any).
    jwt_payload: dict | None = None
    token = trybit_provider._extract_jwt(raw_body, signature, headers_dict)
    if token:
        jwt_payload = trybit_provider._verify_jwt_hs256(
            token, trybit_provider._webhook_secret
        )

    body_json: dict | None = None
    try:
        parsed = json.loads(raw_body)
        if isinstance(parsed, dict):
            inner = (
                parsed.get("data")
                if isinstance(parsed.get("data"), dict)
                else parsed
            )
            if isinstance(inner, dict):
                body_json = inner
    except Exception:
        pass

    merged: dict = {}
    if isinstance(jwt_payload, dict):
        merged.update(jwt_payload)
    if isinstance(body_json, dict):
        # JSON body usually carries more fields; let it override JWT.
        merged.update(body_json)

    logger.info(
        "[trybit-webhook] received: jwt_keys=%s body_keys=%s",
        sorted(jwt_payload.keys()) if isinstance(jwt_payload, dict) else None,
        sorted(body_json.keys()) if isinstance(body_json, dict) else None,
    )

    # --- extract identifiers ---
    provider_payment_id = (
        merged.get("uuid")
        or merged.get("invoice_uuid")
        or merged.get("invoice_id")
        or merged.get("id")
    )
    order_id = merged.get("order_id") or merged.get("orderId")
    status_value = str(
        merged.get("status")
        or merged.get("invoice_status")
        or merged.get("payment_status")
        or merged.get("state")
        or ""
    ).lower()
    amount_value = merged.get("amount_usd") or merged.get("amount")

    if not provider_payment_id and not order_id:
        logger.warning("[trybit-webhook] no provider id or order_id in payload")
        return Response(status_code=400)

    # --- normalise UUID and locate local TopUp ---
    uuid_candidates: list[str] = []
    if provider_payment_id:
        raw_uuid = str(provider_payment_id).strip()
        uuid_candidates.append(raw_uuid)
        if raw_uuid.upper().startswith("INV-"):
            uuid_candidates.append(raw_uuid[4:])
        else:
            uuid_candidates.append(f"INV-{raw_uuid}")

    topup: TopUp | None = None
    for candidate in uuid_candidates:
        topup = session.exec(
            select(TopUp).where(TopUp.provider_payment_id == candidate)
        ).first()
        if topup is not None:
            break

    if topup is None and order_id:
        topup = session.exec(
            select(TopUp).where(TopUp.order_id == str(order_id))
        ).first()

    if topup is None:
        logger.warning(
            "[trybit-webhook] unknown payment (order_id=%s uuid=%s)",
            order_id, provider_payment_id,
        )
        return Response(status_code=404)

    if topup.provider != "trybit":
        logger.warning("[trybit-webhook] payment %s is not Trybit", topup.id)
        return Response(status_code=409)

    # --- If the webhook payload was minimal, fetch status from the API ---
    if not status_value:
        try:
            api_data = await trybit_provider.get_payment_status(
                topup.provider_payment_id
            )
            logger.info(
                "[trybit-webhook] API status for %s: %r",
                topup.provider_payment_id, api_data,
            )
            if isinstance(api_data, dict):
                status_value = str(
                    api_data.get("status")
                    or api_data.get("invoice_status")
                    or api_data.get("payment_status")
                    or ""
                ).lower()
                if amount_value is None:
                    amount_value = (
                        api_data.get("amount_usd") or api_data.get("amount")
                    )
        except Exception as exc:
            logger.warning(
                "[trybit-webhook] API lookup failed: %s: %s",
                exc.__class__.__name__, exc,
            )

    # --- amount sanity check ---
    if amount_value is not None:
        try:
            if abs(float(amount_value) - float(topup.amount)) > 0.01:
                logger.warning(
                    "[trybit-webhook] amount mismatch for %s: got %s expected %s",
                    topup.order_id, amount_value, topup.amount,
                )
                return Response(status_code=400)
        except (TypeError, ValueError):
            return Response(status_code=400)

    user = session.get(User, topup.user_id)
    if user is None:
        return Response(status_code=404)

    # --- idempotency ---
    if topup.status == "paid":
        logger.info("[trybit-webhook] %s already processed", topup.order_id)
        return Response(content="OK", media_type="text/plain")

    # --- status gate ---
    PAID_STATUSES = {
        "paid", "success", "successful", "completed", "complete", "confirmed",
    }
    if status_value not in PAID_STATUSES:
        logger.info(
            "[trybit-webhook] status=%r for %s (no-op)",
            status_value, topup.order_id,
        )
        return Response(content="OK", media_type="text/plain")

    # --- mark paid first (idempotency barrier) ---
    topup.status = "paid"
    topup.paid_at = datetime.utcnow()
    session.add(topup)
    session.commit()

    if topup.purpose == "subscription":
        activate_pro_period(session, user)
        logger.info("[trybit-webhook] Pro activated for user %s", user.id)
    else:
        add_to_balance(
            session, user,
            amount=topup.amount,
            kind="topup",
            description=f"Top-up via Trybit (${topup.amount:.2f})",
            related_id=topup.order_id,
        )
        if (
            user.plan != "pro"
            or user.subscription_status in ("expired", "past_due")
        ):
            if try_charge_and_activate(session, user):
                logger.info(
                    "[trybit-webhook] auto-activated Pro for user %s", user.id
                )

    return Response(content="OK", media_type="text/plain")


# =============================================================
# Invoices list
# =============================================================

@app.get("/invoices", response_class=HTMLResponse)
def invoices_list(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    user = enforce_expiration(session, user)
    documents = list_documents(session, user.id)
    return templates.TemplateResponse(
        request,
        "invoices.html",
        {"title": "Invoices", "documents": documents, "current_user": user},
    )


# =============================================================
# Export routes (must be BEFORE /invoices/{document_id})
# =============================================================

@app.get("/invoices/export.csv")
def export_all_csv(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    user = enforce_expiration(session, user)
    records = list_invoice_records_for_user(session, user.id)
    csv_text = records_to_csv(records)
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="invoices.csv"'},
    )


@app.get("/invoices/export.xlsx")
def export_all_xlsx(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    user = enforce_expiration(session, user)
    records = list_invoice_records_for_user(session, user.id)
    content = records_to_xlsx(records)
    return Response(
        content=content,
        media_type=(
            "application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": 'attachment; filename="invoices.xlsx"'},
    )


# =============================================================
# Invoice detail
# =============================================================

@app.get("/invoices/{document_id}", response_class=HTMLResponse)
def invoice_detail(
    document_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    user = enforce_expiration(session, user)
    document = get_document_for_user(session, document_id, user.id)
    if document is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    invoice: Invoice | None = None
    validation: ValidationResult | None = None

    if document.invoice:
        record = document.invoice
        invoice = Invoice(
            supplier_name=record.supplier_name,
            invoice_number=record.invoice_number,
            invoice_date=record.invoice_date,
            due_date=record.due_date,
            currency=record.currency,
            subtotal=record.subtotal,
            tax=record.tax,
            total=record.total,
            line_items=[
                LineItem(
                    description=li.description,
                    quantity=li.quantity,
                    unit_price=li.unit_price,
                    total=li.total,
                )
                for li in record.line_items
            ],
        )
        if record.validation:
            validation = ValidationResult(
                status=record.validation.status,
                errors=json.loads(record.validation.errors or "[]"),
                warnings=json.loads(record.validation.warnings or "[]"),
            )

    size_kb: float | None = None
    try:
        size_kb = round(Path(document.filepath).stat().st_size / 1024, 1)
    except OSError:
        pass

    ctx = {
        "filename": document.filename,
        "saved_as": Path(document.filepath).name,
        "size_kb": size_kb,
        "extraction": None,
        "invoice": invoice,
        "validation": validation,
        "pdf_error": None,
        "ai_error": None,
        "document_id": document.id,
        "status": document.status,
        "current_user": user,
    }
    return templates.TemplateResponse(
        request, "result.html", {**ctx, "title": "Saved invoice"}
    )


# =============================================================
# Single-invoice exports
# =============================================================

@app.get("/invoices/{document_id}/export.csv")
def export_invoice_csv(
    document_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    user = enforce_expiration(session, user)
    document = get_document_for_user(session, document_id, user.id)
    if document is None or document.invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    csv_text = records_to_csv([document.invoice])
    filename = f"invoice_{document_id}.csv"
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/invoices/{document_id}/export.xlsx")
def export_invoice_xlsx(
    document_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    user = enforce_expiration(session, user)
    document = get_document_for_user(session, document_id, user.id)
    if document is None or document.invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    content = records_to_xlsx([document.invoice])
    filename = f"invoice_{document_id}.xlsx"
    return Response(
        content=content,
        media_type=(
            "application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# =============================================================
# Approve / Reject
# =============================================================

@app.post("/invoices/{document_id}/approve")
def invoice_approve(
    document_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    user = enforce_expiration(session, user)
    document = get_document_for_user(session, document_id, user.id)
    if document is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    set_document_status(session, document, "approved")
    return RedirectResponse(url=f"/invoices/{document_id}", status_code=303)


@app.post("/invoices/{document_id}/reject")
def invoice_reject(
    document_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    user = enforce_expiration(session, user)
    document = get_document_for_user(session, document_id, user.id)
    if document is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    set_document_status(session, document, "rejected")
    return RedirectResponse(url=f"/invoices/{document_id}", status_code=303)

@app.post("/invoices/{document_id}/delete")
def invoice_delete(
    document_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Delete an invoice: DB records + file on disk.

    Ownership is enforced by get_document_for_user (scoped to user_id).
    """
    user = enforce_expiration(session, user)
    document = get_document_for_user(session, document_id, user.id)
    if document is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    filepath = delete_document_for_user(session, document_id, user.id)

    if filepath:
        try:
            Path(filepath).unlink(missing_ok=True)
        except OSError:
            logger.warning("[delete] could not unlink file %s", filepath)

    logger.info("[delete] invoice %s deleted by user %s", document_id, user.id)
    return RedirectResponse(url="/invoices", status_code=303)


# =============================================================
# Edit
# =============================================================

@app.get("/invoices/{document_id}/edit", response_class=HTMLResponse)
def invoice_edit_form(
    document_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    user = enforce_expiration(session, user)
    document = get_document_for_user(session, document_id, user.id)
    if document is None or document.invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    return templates.TemplateResponse(
        request,
        "edit.html",
        {
            "title": "Edit invoice",
            "document_id": document_id,
            "record": document.invoice,
            "current_user": user,
        },
    )


@app.post("/invoices/{document_id}/edit")
def invoice_edit_submit(
    document_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    supplier_name: str = Form(""),
    invoice_number: str = Form(""),
    invoice_date: str = Form(""),
    due_date: str = Form(""),
    currency: str = Form(""),
    subtotal: str = Form(""),
    tax: str = Form(""),
    total: str = Form(""),
    li_description: list[str] = Form(default=[]),
    li_quantity: list[str] = Form(default=[]),
    li_unit_price: list[str] = Form(default=[]),
    li_total: list[str] = Form(default=[]),
):
    user = enforce_expiration(session, user)
    document = get_document_for_user(session, document_id, user.id)
    if document is None or document.invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    def to_float(s: str) -> float | None:
        s = (s or "").strip()
        if not s:
            return None
        try:
            return float(s.replace(",", "."))
        except ValueError:
            return None

    def to_str(s: str) -> str | None:
        s = (s or "").strip()
        return s or None

    line_items: list[LineItem] = []
    n = max(
        len(li_description),
        len(li_quantity),
        len(li_unit_price),
        len(li_total),
    )
    for i in range(n):
        desc = li_description[i] if i < len(li_description) else ""
        qty = li_quantity[i] if i < len(li_quantity) else ""
        price = li_unit_price[i] if i < len(li_unit_price) else ""
        total_raw = li_total[i] if i < len(li_total) else ""

        desc_clean = to_str(desc)
        qty_clean = to_float(qty)
        price_clean = to_float(price)
        total_clean = to_float(total_raw)

        if (
            desc_clean is None
            and qty_clean is None
            and price_clean is None
            and total_clean is None
        ):
            continue

        line_items.append(
            LineItem(
                description=desc_clean,
                quantity=qty_clean,
                unit_price=price_clean,
                total=total_clean,
            )
        )

    edited = Invoice(
        supplier_name=to_str(supplier_name),
        invoice_number=to_str(invoice_number),
        invoice_date=to_str(invoice_date),
        due_date=to_str(due_date),
        currency=to_str(currency),
        subtotal=to_float(subtotal),
        tax=to_float(tax),
        total=to_float(total),
        line_items=line_items,
    )

    validation = validate_invoice(edited)

    update_invoice(
        session,
        document_id=document_id,
        invoice=edited,
        validation=validation,
    )
    return RedirectResponse(url=f"/invoices/{document_id}", status_code=303)


# =============================================================
# Upload
# =============================================================

@app.get("/upload", response_class=HTMLResponse)
def upload_form(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    user = enforce_expiration(session, user)
    limit_reached = user.invoices_used >= user.invoices_limit
    return templates.TemplateResponse(
        request,
        "upload.html",
        {
            "title": "Upload Invoice",
            "error": None,
            "current_user": user,
            "limit_reached": limit_reached,
            "remaining": remaining_slots(user),
        },
    )


@app.post("/upload", response_class=HTMLResponse)
async def upload_submit(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    user = enforce_expiration(session, user)

    try:
        reserve_slot(user, session)
    except HTTPException:
        return templates.TemplateResponse(
            request,
            "upload.html",
            {
                "title": "Upload Invoice",
                "error": "You've reached your monthly limit.",
                "current_user": user,
                "limit_reached": True,
                "remaining": 0,
            },
            status_code=403,
        )

    slot_reserved = True

    def _release():
        nonlocal slot_reserved
        if slot_reserved:
            release_slot(user, session)
            slot_reserved = False

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        _release()
        return _upload_error(request, user, "Please upload a PDF file.")

    content = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        _release()
        return _upload_error(
            request, user,
            f"File is too large. Max size is {settings.max_upload_mb} MB.",
        )
    if len(content) == 0:
        _release()
        return _upload_error(request, user, "The file is empty.")
    if not content.startswith(b"%PDF"):
        _release()
        return _upload_error(
            request, user, "This file does not look like a valid PDF."
        )

    safe_name = Path(file.filename).name
    unique_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
    filepath = settings.upload_path / unique_name
    filepath.write_bytes(content)

    ctx: dict = {
        "filename": safe_name,
        "saved_as": unique_name,
        "size_kb": round(len(content) / 1024, 1),
        "extraction": None,
        "invoice": None,
        "validation": None,
        "pdf_error": None,
        "ai_error": None,
        "document_id": None,
        "status": None,
        "current_user": user,
    }

    with timer("pdf_extract"):
        try:
            extraction = pdf_extractor.extract_text(filepath)
            ctx["extraction"] = extraction
        except ScannedPDFError as exc:
            ctx["pdf_error"] = str(exc)
            doc = save_extraction(
                session, user_id=user.id, filename=safe_name,
                filepath=filepath, invoice=None, validation=None,
            )
            ctx["document_id"] = doc.id
            ctx["status"] = doc.status
            _release()
            return templates.TemplateResponse(
                request, "result.html", {**ctx, "title": "Scanned PDF"}
            )
        except PDFExtractionError as exc:
            ctx["pdf_error"] = f"Could not extract text: {exc}"
            doc = save_extraction(
                session, user_id=user.id, filename=safe_name,
                filepath=filepath, invoice=None, validation=None,
            )
            ctx["document_id"] = doc.id
            ctx["status"] = doc.status
            _release()
            return templates.TemplateResponse(
                request, "result.html", {**ctx, "title": "Extraction failed"}
            )

    invoice = None
    validation = None
    try:
        invoice = await ai_extractor.extract_invoice(extraction.text)
    except AIExtractionError as exc:
        ctx["ai_error"] = str(exc)

    if invoice is not None:
        with timer("validation"):
            validation = validate_invoice(invoice)
        ctx["invoice"] = invoice
        ctx["validation"] = validation

    with timer("db_save"):
        doc = save_extraction(
            session, user_id=user.id, filename=safe_name,
            filepath=filepath, invoice=invoice, validation=validation,
        )
    ctx["document_id"] = doc.id
    ctx["status"] = doc.status

    if invoice is None:
        _release()

    return templates.TemplateResponse(
        request, "result.html", {**ctx, "title": "Extraction result"}
    )


# =============================================================
# Helpers
# =============================================================

def _upload_error(request: Request, user: User, message: str):
    return templates.TemplateResponse(
        request,
        "upload.html",
        {
            "title": "Upload Invoice",
            "error": message,
            "current_user": user,
            "limit_reached": user.invoices_used >= user.invoices_limit,
            "remaining": remaining_slots(user),
        },
        status_code=400,
    )