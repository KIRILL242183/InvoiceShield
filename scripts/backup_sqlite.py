"""Safe offline verification and online SQLite snapshots for local demos.

Backups include private supplier details, password hashes and sessions. Keep
files offline, restrict access and never commit/upload them to the repository.
PostgreSQL installations must use pg_dump/pg_restore instead.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path
from urllib.parse import quote

from app.database import engine

REQUIRED_TABLES = frozenset({"suppliers", "invoices", "users", "incidents"})
SQLITE_MAGIC = b"SQLite format 3\x00"


class BackupError(ValueError):
    """An unsafe or invalid backup operation was requested."""


def _source_file(path: Path) -> Path:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise BackupError("Исходная база не существует или является ссылкой")
    with path.open("rb") as stream:
        if stream.read(16) != SQLITE_MAGIC:
            raise BackupError("Файл не является базой SQLite")
    return path


def _readonly(path: Path) -> sqlite3.Connection:
    uri = "file:" + quote(str(path), safe="/") + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=10)


def verify_database(path: Path) -> None:
    """Check physical integrity and minimal expected InvoiceShield schema."""
    source = _source_file(path)
    try:
        with _readonly(source) as db:
            result = db.execute("PRAGMA integrity_check").fetchone()
            if result is None or result[0] != "ok":
                raise BackupError("Проверка целостности SQLite завершилась ошибкой")
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if not REQUIRED_TABLES.issubset(tables):
                raise BackupError("Отсутствуют таблицы InvoiceShield")
    except sqlite3.DatabaseError as exc:
        raise BackupError("Повреждённая или несовместимая база SQLite") from exc


def _new_destination(path: Path) -> Path:
    path = path.expanduser().absolute()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or path.exists():
        raise BackupError("Файл назначения уже существует; перезапись запрещена")
    return path


def _copy_sqlite(source: Path, destination: Path) -> Path:
    source = _source_file(source)
    destination = _new_destination(destination)
    # O_EXCL prevents accidental overwrites and symlink redirection.
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with _readonly(source) as source_db:
            with sqlite3.connect(destination, timeout=20) as target_db:
                source_db.backup(target_db, pages=100)
        os.chmod(destination, 0o600)
        verify_database(destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def create_backup(source: Path, destination: Path) -> Path:
    """Use SQLite's online backup API; copying live *.db with cp is unsafe."""
    return _copy_sqlite(source, destination)


def restore_to_new_file(backup: Path, destination: Path) -> Path:
    """Never replace the live database or an existing target in-place."""
    verify_database(backup)
    return _copy_sqlite(backup, destination)


def _configured_sqlite() -> Path:
    if engine.dialect.name != "sqlite" or engine.url.database in (None, ":memory:"):
        raise BackupError("Команда работает только с файловой SQLite, не с PostgreSQL")
    return Path(engine.url.database)


def main() -> None:
    parser = argparse.ArgumentParser(description="Проверка и резервные копии SQLite InvoiceShield")
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup", help="Создать новый непрерывный онлайн-снимок")
    backup.add_argument("--output", required=True, type=Path)
    check = sub.add_parser("verify", help="Проверить ранее созданную копию")
    check.add_argument("--input", required=True, type=Path)
    restore = sub.add_parser("restore", help="Восстановить только в НОВЫЙ файл")
    restore.add_argument("--input", required=True, type=Path)
    restore.add_argument("--to", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "backup":
            output = create_backup(_configured_sqlite(), args.output)
            print(f"Копия создана и проверена: {output}")
        elif args.command == "verify":
            verify_database(args.input)
            print("Целостность и таблицы InvoiceShield проверены")
        else:
            output = restore_to_new_file(args.input, args.to)
            print(f"Восстановлено в новый файл: {output}")
            print("Остановите сервер и отдельно настройте DATABASE_URL для переключения базы")
    except (BackupError, OSError, sqlite3.Error) as exc:
        parser.exit(1, f"Ошибка: {exc}\n")


if __name__ == "__main__":
    main()
