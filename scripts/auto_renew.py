"""
Daily job: charge users for Pro and handle expirations.

Run manually:
    python -m scripts.auto_renew

Cron (recommended):
    0 6 * * *  cd /srv/voince && .venv/bin/python -m scripts.auto_renew \
               >> /var/log/voince-renewals.log 2>&1

What it does:
  1. Users whose Pro period ends within 24h and who have enough balance
     are charged and extended by 30 days.
  2. Users with insufficient balance are marked past_due but keep access
     until their period actually ends.
  3. Users whose Pro period already ended are downgraded to Free.
"""

import logging

from sqlmodel import Session

from app.billing import auto_renew
from app.database import engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("auto_renew")


def main() -> None:
    with Session(engine) as session:
        result = auto_renew(session)
        logger.info(
            "[auto_renew] done: renewed=%d past_due=%d expired=%d",
            result["renewed"],
            result["past_due"],
            result["expired"],
        )


if __name__ == "__main__":
    main()