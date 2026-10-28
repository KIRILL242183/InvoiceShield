"""Interactive local admin utility. Never store passwords in shell history."""
import argparse
import getpass

from sqlalchemy.exc import IntegrityError

from app.auth import create_user
from app.database import Base, SessionLocal, engine
from app import models  # noqa: F401


def main() -> None:
    parser = argparse.ArgumentParser(description="Создать пользователя InvoiceShield")
    parser.add_argument("add", choices=["add"])
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", choices=["admin", "analyst"], required=True)
    args = parser.parse_args()
    password = getpass.getpass("Новый пароль (не менее 12 символов): ")
    if password != getpass.getpass("Повторите пароль: "):
        parser.error("Пароли не совпадают")
    Base.metadata.create_all(bind=engine)  # only creates NEW tables, preserves existing data
    with SessionLocal() as db:
        try:
            user = create_user(db, args.username, password, args.role)
        except (ValueError, IntegrityError) as exc:
            db.rollback()
            parser.error(str(exc))
    print(f"Пользователь {user.username} создан; роль: {user.role}")


if __name__ == "__main__":
    main()
