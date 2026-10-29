"""Operations and backup regression tests; never touch a user's live database."""
from app.version import APP_VERSION
import logging
import os
import sqlite3
import stat
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from scripts.backup_sqlite import BackupError, create_backup, restore_to_new_file, verify_database


def test_sqlite_backup_contains_users_and_is_readable(client, tmp_path):
    source = Path(client.test_engine.url.database)
    dest = tmp_path / "backups" / "snapshot.sqlite3"
    result = create_backup(source, dest)
    assert result == dest
    verify_database(dest)
    with sqlite3.connect(dest) as conn:
        assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 1
        assert conn.execute("SELECT username FROM users").fetchone()[0] == "admin"
        assert conn.execute("SELECT password_hash FROM users").fetchone()[0].startswith("$argon2id$")
    if os.name == "posix":
        assert stat.S_IMODE(dest.stat().st_mode) == 0o600


def test_backup_rejects_existing_target_even_if_different_content(client, tmp_path):
    dest = tmp_path / "already.sqlite"
    dest.write_text("private file", encoding="utf-8")
    with pytest.raises(BackupError, match="существует"):
        create_backup(Path(client.test_engine.url.database), dest)
    assert dest.read_text(encoding="utf-8") == "private file"


def test_backup_refuses_symlinks_and_invalid_source(client, tmp_path):
    source = Path(client.test_engine.url.database)
    symlink = tmp_path / "link.db"
    symlink.symlink_to(source)
    with pytest.raises(BackupError):
        create_backup(symlink, tmp_path / "out.db")
    destlink = tmp_path / "dest.db"
    destlink.symlink_to(tmp_path / "nonexistent.db")
    with pytest.raises(BackupError):
        create_backup(source, destlink)
    bad = tmp_path / "text.db"
    bad.write_text("wrong format", encoding="utf-8")
    with pytest.raises(BackupError, match="не является"):
        verify_database(bad)


def test_restore_to_new_file_without_changing_live_db(client, tmp_path):
    source = Path(client.test_engine.url.database)
    snapshot = create_backup(source, tmp_path / "snapshot.db")
    with Session(client.test_engine) as db:
        db.add(User(username="newuser", role="analyst", password_hash="not-a-real-hash"))
        db.commit()
    restored = restore_to_new_file(snapshot, tmp_path / "restored.db")
    with sqlite3.connect(restored) as conn:
        assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 1
    with Session(client.test_engine) as db:
        assert db.scalar(select(User).where(User.username == "newuser")) is not None
    with pytest.raises(BackupError, match="существует"):
        restore_to_new_file(snapshot, restored)
    with pytest.raises(BackupError, match="существует"):
        restore_to_new_file(snapshot, source)


def test_backup_refuses_database_without_invoice_tables(tmp_path):
    empty = tmp_path / "random.db"
    with sqlite3.connect(empty) as conn:
        conn.execute("CREATE TABLE unrelated (id INTEGER)")
    with pytest.raises(BackupError, match="таблицы"):
        verify_database(empty)


def test_backup_handles_live_wal_connection(client, tmp_path):
    src = Path(client.test_engine.url.database)
    with sqlite3.connect(src) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("INSERT INTO audit_events (action,entity_type,entity_id,details,created_at) "
                   "VALUES ('BACKUP_TEST','test',0,'hello',CURRENT_TIMESTAMP)")
        db.commit()
        # Keep the connection open and confirm backup API sees all committed rows.
        snapshot = create_backup(src, tmp_path / "online.db")
    with sqlite3.connect(snapshot) as check:
        assert check.execute("SELECT count(*) FROM audit_events "
                             "WHERE action='BACKUP_TEST'").fetchone()[0] == 1


def test_correlation_ids_and_no_sensitive_request_logging(client, caplog):
    with caplog.at_level(logging.INFO, logger="invoiceshield.requests"):
        first = client.get("/health?secret_password=do_not_log", headers={"X-Request-ID": "attacker"})
        second = client.get("/health")
        third = client.get("/api/incidents/999999?token=do_not_log")
    assert first.status_code == 200 and second.status_code == 200
    ids = [x.headers["X-Request-ID"] for x in (first, second, third)]
    assert len(set(ids)) == len(ids)
    assert all(len(value) == 32 and all(c in "0123456789abcdef" for c in value) for value in ids)
    logs = caplog.text
    assert "secret_password" not in logs
    assert "do_not_log" not in logs
    assert "attacker" not in logs
    assert "/api/incidents/{incident_id}" in logs


def test_readiness_still_protected_with_request_id(client):
    for path in ("/ready", "/health"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Request-ID"]
        assert response.json()["version"] == APP_VERSION
