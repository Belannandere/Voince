from datetime import datetime, timedelta
from unittest.mock import patch

from app.auth import get_user_by_email
from app.billing import (
    activate_pro_period,
    add_to_balance,
    cancel_subscription,
    downgrade_to_free,
    enforce_expiration,
    find_topup_by_order,
    pro_price,
    try_charge_and_activate,
)
from app.limiter import has_remaining
from app.models import TopUp


def _register(client, email="b@example.com", password="supersecret"):
    client.post(
        "/register",
        data={"email": email, "password": password, "password_confirm": password},
        follow_redirects=False,
    )


# ---- limits ----

def test_free_user_has_10_limit(client, session):
    _register(client)
    user = get_user_by_email(session, "b@example.com")
    assert user.invoices_limit == 10


def test_pro_user_has_100_limit(client, session):
    _register(client)
    user = get_user_by_email(session, "b@example.com")
    activate_pro_period(session, user)
    assert user.plan == "pro"
    assert user.invoices_limit == 100


# ---- balance ----

def test_add_to_balance_writes_transaction(client, session):
    _register(client)
    user = get_user_by_email(session, "b@example.com")
    add_to_balance(session, user, amount=50.0, kind="topup",
                   description="Test top-up")
    assert user.balance == 50.0


def test_add_to_balance_rejects_negative(client, session):
    _register(client)
    user = get_user_by_email(session, "b@example.com")
    try:
        add_to_balance(session, user, amount=-1.0, kind="subscription_charge")
        assert False, "should have raised"
    except ValueError:
        pass


# ---- charge & activate ----

def test_charge_and_activate_succeeds_with_enough_balance(client, session):
    _register(client)
    user = get_user_by_email(session, "b@example.com")
    add_to_balance(session, user, amount=20.0, kind="topup")
    assert try_charge_and_activate(session, user) is True
    assert user.plan == "pro"
    assert round(user.balance, 2) == round(20.0 - pro_price(), 2)


def test_charge_and_activate_fails_without_balance(client, session):
    _register(client)
    user = get_user_by_email(session, "b@example.com")
    assert try_charge_and_activate(session, user) is False
    assert user.plan == "free"


# ---- upgrade requires login ----

def test_topup_requires_login(client):
    r = client.get("/billing/topup", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_upgrade_redirects_to_topup_when_balance_low(client, session):
    _register(client)
    r = client.post("/billing/upgrade", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/billing/topup")


def test_upgrade_activates_when_balance_sufficient(client, session):
    _register(client)
    user = get_user_by_email(session, "b@example.com")
    add_to_balance(session, user, amount=50.0, kind="topup")

    r = client.post("/billing/upgrade", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/account"

    session.refresh(user)
    assert user.plan == "pro"


# ---- webhook security ----

def test_invalid_webhook_signature_rejected(client):
    r = client.post("/webhooks/cryptobot", json={
        "update_type": "invoice_paid",
        "payload": {"payload": "VOINCE-TOPUP-1-x"},
    })
    assert r.status_code == 401


# ---- cancellation & expiry ----

def test_cancelled_keeps_pro_until_expiry(client, session):
    _register(client)
    user = get_user_by_email(session, "b@example.com")
    activate_pro_period(session, user)
    cancel_subscription(session, user)
    assert user.plan == "pro"
    assert user.subscription_status == "cancelled"


def test_expired_user_downgraded(client, session):
    _register(client)
    user = get_user_by_email(session, "b@example.com")
    activate_pro_period(session, user)
    user.subscription_expires_at = datetime.utcnow() - timedelta(days=1)
    session.add(user)
    session.commit()
    session.refresh(user)

    enforce_expiration(session, user)
    assert user.plan == "free"
    assert user.invoices_limit == 10


# ---- security ----

def test_price_comes_from_server_not_client(client, session):
    """Extra form fields must not affect server-side price."""
    _register(client)
    user = get_user_by_email(session, "b@example.com")
    add_to_balance(session, user, amount=10.0, kind="topup")

    # Attempt to pass price=0 as form data — must be ignored.
    r = client.post(
        "/billing/upgrade",
        data={"price": "0", "amount": "0"},
        follow_redirects=False,
    )
    session.refresh(user)
    # Server still charged the configured price.
    assert user.balance == 0.0
    assert user.plan == "pro"