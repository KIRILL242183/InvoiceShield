"""Remove long-expired login counters. Does not reset active lockouts."""
from datetime import timedelta

from sqlalchemy import delete

from app.auth import LOGIN_WINDOW_SECONDS, utc_now_naive
from app.database import SessionLocal
from app.models import LoginThrottle


def prune_old_login_throttles() -> int:
    cutoff = utc_now_naive() - timedelta(days=1, seconds=LOGIN_WINDOW_SECONDS)
    with SessionLocal() as db:
        count = db.execute(delete(LoginThrottle).where(
            LoginThrottle.window_started_at < cutoff,
            (LoginThrottle.blocked_until.is_(None) | (LoginThrottle.blocked_until < cutoff)),
        )).rowcount
        db.commit()
        return count


if __name__ == "__main__":
    print(f"Удалено устаревших счётчиков входа: {prune_old_login_throttles()}")
