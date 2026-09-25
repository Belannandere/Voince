from collections.abc import Iterator

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

connect_args = {"check_same_thread": False}
engine = create_engine(settings.database_url, echo=False, connect_args=connect_args)


# =============================================================
# Migration helpers
# =============================================================

def _table_info(table: str) -> list:
    with engine.connect() as conn:
        return conn.execute(text(f"PRAGMA table_info({table})")).fetchall()


def _column_names(table: str) -> set[str]:
    return {row[1] for row in _table_info(table)}


def _add_column_if_missing(
    table: str, column: str, sqltype: str = "VARCHAR"
) -> None:
    names = _column_names(table)
    if not names:
        return
    if column in names:
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sqltype}"))
    print(f"[migration] added {table}.{column}")


def _rename_column_if_exists(table: str, old: str, new: str) -> None:
    names = _column_names(table)
    if old in names and new not in names:
        with engine.begin() as conn:
            conn.execute(
                text(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")
            )
        print(f"[migration] renamed {table}.{old} -> {new}")


def _drop_table_if_exists(table: str) -> None:
    names = {row[0] for row in _table_info(table)} if False else None
    # SQLite's PRAGMA table_info returns empty for nonexistent tables,
    # so check via sqlite_master instead.
    with engine.connect() as conn:
        exists = conn.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name=:name"
            ),
            {"name": table},
        ).first()
    if not exists:
        return
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE {table}"))
    print(f"[migration] dropped table {table}")


def _recreate_users_table_if_password_not_nullable() -> None:
    info = _table_info("users")
    if not info:
        return
    pw = next((row for row in info if row[1] == "password_hash"), None)
    if pw is None or pw[3] == 0:
        return

    print("[migration] recreating users (password_hash -> nullable)")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE users_new (
                id INTEGER NOT NULL PRIMARY KEY,
                email VARCHAR NOT NULL,
                password_hash VARCHAR,
                created_at DATETIME NOT NULL,
                plan VARCHAR NOT NULL,
                invoices_used INTEGER NOT NULL,
                invoices_limit INTEGER NOT NULL,
                usage_period_start DATETIME NOT NULL
            )
        """))
        conn.execute(text("""
            INSERT INTO users_new
                (id, email, password_hash, created_at, plan,
                 invoices_used, invoices_limit, usage_period_start)
            SELECT id, email, password_hash, created_at, plan,
                   invoices_used, invoices_limit, usage_period_start
            FROM users
        """))
        conn.execute(text("DROP TABLE users"))
        conn.execute(text("ALTER TABLE users_new RENAME TO users"))
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email "
                "ON users (email)"
            )
        )


# =============================================================
# Migrations
# =============================================================

def _run_migrations() -> None:
    _add_column_if_missing("documents", "user_id", "INTEGER")
    _recreate_users_table_if_password_not_nullable()

    _add_column_if_missing("users", "google_id", "VARCHAR")
    _add_column_if_missing("users", "github_id", "VARCHAR")

    # Subscription + balance
    _add_column_if_missing("users", "subscription_status", "VARCHAR")
    _add_column_if_missing("users", "subscription_started_at", "DATETIME")
    _add_column_if_missing("users", "subscription_expires_at", "DATETIME")
    _add_column_if_missing("users", "subscription_cancelled_at", "DATETIME")
    _add_column_if_missing("users", "balance", "REAL")

    # TopUp — migration from NOWPayments column name
    _rename_column_if_exists(
        "topups", "nowpayments_payment_id", "cryptobot_invoice_id"
    )
    _add_column_if_missing("topups", "cryptobot_invoice_id", "INTEGER")

    _drop_table_if_exists("payments")


def init_db() -> None:
    import app.models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _run_migrations()


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session