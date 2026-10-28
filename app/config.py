"""Configuration for a localhost-only teaching environment."""
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./invoiceshield.db")
