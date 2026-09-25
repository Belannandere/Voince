import threading
from datetime import datetime

from fastapi import HTTPException, status
from sqlmodel import Session

from app.models import User


_reserve_lock = threading.Lock()


def _same_month(a: datetime, b: datetime) -> bool:
    return (a.year, a.month) == (b.year, b.month)


def ensure_usage_period(user: User, session: Session) -> None:
    now = datetime.utcnow()
    if not _same_month(user.usage_period_start, now):
        user.invoices_used = 0
        user.usage_period_start = now
        session.add(user)
        session.commit()
        session.refresh(user)


def has_remaining(user: User) -> bool:
    return user.invoices_used < user.invoices_limit


def reserve_slot(user: User, session: Session) -> None:
    with _reserve_lock:
        ensure_usage_period(user, session)
        if not has_remaining(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="limit_reached",
            )
        user.invoices_used += 1
        session.add(user)
        session.commit()
        session.refresh(user)


def release_slot(user: User, session: Session) -> None:
    with _reserve_lock:
        user.invoices_used = max(0, user.invoices_used - 1)
        session.add(user)
        session.commit()
        session.refresh(user)


def remaining(user: User) -> int:
    return max(0, user.invoices_limit - user.invoices_used)


def usage_percent(user: User) -> int:
    if user.invoices_limit <= 0:
        return 0
    return min(100, round(user.invoices_used * 100 / user.invoices_limit))