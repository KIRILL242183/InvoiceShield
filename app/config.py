"""Local-first application settings."""
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./invoiceshield.db")
# False is ONLY for local http://127.0.0.1 development. Real deployment requires HTTPS + True.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
SESSION_SECONDS = 8 * 60 * 60
