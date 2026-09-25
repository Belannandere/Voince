"""
Internal-balance billing for Voince.

Model:
    - User holds a `balance` in USD-equivalent.
    - Top-ups arrive via CryptoBot webhooks (see main.py).
    - A daily job (scripts/auto_renew.py) charges users whose Pro period
      is about to expire and who have enough balance.
    - If the balance is insufficient, the user is marked `past_due`
      but keeps Pro access until the current period ends.
    - When the period ends without a successful charge, they are
      downgraded to Free.

Every change to `balance` is written as a Transaction row, so the audit
trail is complete.
"""

import logging
import threading
from datetime import datetime, timedelta

from sqlmodel import Session, select

from app.config import settings
from app.models import TopUp, Transaction, User

logger = logging.getLogger("billing")

PRO_LIMIT = 100
FREE_LIMIT = 10
PRO_PERIOD_DAYS = 30

_balance_lock = threading.Lock()


def _now() -> datetime:
    return datetime.utcnow()


def pro_price() -> float:
    try:
        return float(settings.pro_price)
    except (TypeError, ValueError):
        return 10.0


def min_topup() -> float:
    try:
        return float(settings.min_topup)
    except (TypeError, ValueError):
        return 10.0


def max_topup() -> float:
    try:
        return float(settings.max_topup)
    except (TypeError, ValueError):
        return 500.0


# ---------- balance ----------

def add_to_balance(
    session: Session,
    user: User,
    *,
    amount: float,
    kind: str,
    description: str = "",
    related_id: str | None = None,
) -> Transaction:
    """
    Atomically adjust the user's balance and write a Transaction row.

    `amount` is positive for credit, negative for debit.
    """
    with _balance_lock:
        new_balance = round((user.balance or 0.0) + amount, 2)
        if new_balance < 0:
            raise ValueError("Balance cannot go negative")

        user.balance = new_balance
        tx = Transaction(
            user_id=user.id,
            kind=kind,
            amount=round(amount, 2),
            balance_after=new_balance,
            description=description,
            related_id=related_id,
        )
        session.add(user)
        session.add(tx)
        session.commit()
        session.refresh(user)
        session.refresh(tx)

        logger.info(
            "[billing] user %s %s %.2f -> balance %.2f (%s)",
            user.id,
            "credited" if amount > 0 else "debited",
            abs(amount),
            new_balance,
            kind,
        )
        return tx


# ---------- subscription ----------

def activate_pro_period(
    session: Session,
    user: User,
    *,
    days: int = PRO_PERIOD_DAYS,
) -> User:
    """Extend the Pro period by `days` from max(now, current expiry)."""
    now = _now()
    base = user.subscription_expires_at or now
    if base < now:
        base = now
    user.plan = "pro"
    user.subscription_status = "active"
    user.invoices_limit = PRO_LIMIT
    user.subscription_started_at = user.subscription_started_at or now
    user.subscription_expires_at = base + timedelta(days=days)
    user.subscription_cancelled_at = None

    session.add(user)
    session.commit()
    session.refresh(user)

    logger.info(
        "[billing] user %s Pro until %s",
        user.id,
        user.subscription_expires_at.isoformat(),
    )
    return user


def try_charge_and_activate(session: Session, user: User) -> bool:
    """Charge the Pro price from the balance. Activate if successful."""
    price = pro_price()
    if (user.balance or 0.0) < price:
        return False

    add_to_balance(
        session,
        user,
        amount=-price,
        kind="subscription_charge",
        description=f"Pro subscription ({PRO_PERIOD_DAYS} days)",
    )
    activate_pro_period(session, user)
    return True


def cancel_subscription(session: Session, user: User) -> User:
    """Stop renewals. Keeps Pro until the current period ends."""
    user.subscription_status = "cancelled"
    user.subscription_cancelled_at = _now()
    session.add(user)
    session.commit()
    session.refresh(user)
    logger.info("[billing] user %s cancelled", user.id)
    return user


def mark_past_due(session: Session, user: User) -> User:
    user.subscription_status = "past_due"
    session.add(user)
    session.commit()
    session.refresh(user)
    logger.info("[billing] user %s past_due", user.id)
    return user


def downgrade_to_free(session: Session, user: User) -> User:
    user.plan = "free"
    user.subscription_status = "expired"
    user.invoices_limit = FREE_LIMIT
    session.add(user)
    session.commit()
    session.refresh(user)
    logger.info("[billing] user %s downgraded to Free", user.id)
    return user


def enforce_expiration(session: Session, user: User) -> User:
    """If the paid period has ended, downgrade immediately."""
    if (
        user.plan == "pro"
        and user.subscription_expires_at
        and user.subscription_expires_at < _now()
    ):
        return downgrade_to_free(session, user)
    return user


# ---------- auto-renewal job ----------

def auto_renew(session: Session) -> dict:
    """
    Daily job:
      1. Pro users whose period ends within 24h and who have enough
         balance are charged and extended.
      2. Pro users whose balance is too low are marked `past_due` (they
         keep access until their period ends).
      3. Pro users whose period has already ended are downgraded.

    Returns counts of each action.
    """
    now = _now()
    soon = now + timedelta(hours=24)

    renewed = 0
    past_due = 0
    expired = 0

    # 1. Renewal candidates
    expiring = session.exec(
        select(User).where(
            User.plan == "pro",
            User.subscription_status == "active",
            User.subscription_expires_at <= soon,
        )
    ).all()

    for u in expiring:
        if try_charge_and_activate(session, u):
            renewed += 1
            logger.info("[auto_renew] user %s renewed", u.id)
        else:
            mark_past_due(session, u)
            past_due += 1
            logger.info("[auto_renew] user %s insufficient balance", u.id)

    # 2. Expiry candidates (regardless of status)
    expired_users = session.exec(
        select(User).where(
            User.plan == "pro",
            User.subscription_expires_at < now,
        )
    ).all()

    for u in expired_users:
        downgrade_to_free(session, u)
        expired += 1

    return {"renewed": renewed, "past_due": past_due, "expired": expired}


# ---------- top-up lookups ----------

def find_topup_by_order(session: Session, order_id: str) -> TopUp | None:
    return session.exec(
        select(TopUp).where(TopUp.order_id == order_id)
    ).first()