# Обновление InvoiceShield до 1.0.0 (macOS/Linux)

**База и аккаунты должны сохраниться.**

1. Остановите Uvicorn (Control+C) и перейдите в папку установленного проекта.
2. Активируйте окружение: `source .venv/bin/activate`.
3. Создайте резервную копию SQLite при помощи SQLite API (не простым копированием работающего .db файла):

   `python -m scripts.backup_sqlite backup --output "$HOME/Downloads/invoiceshield-before-v1.db"`

   Если файл уже существует, выберите другое уникальное имя. При PostgreSQL используйте pg_dump.
4. Распакуйте поверх существующей папки `InvoiceShield-v1.0.0-update.zip`:

   `unzip -o ~/Downloads/InvoiceShield-v1.0.0-update.zip -d .`

5. Обновите зависимости: `python -m pip install -r requirements-dev.txt`.
6. Запустите `python -m pytest -q` и `python -m compileall -q app scripts`.
7. Запустите `python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`.
8. Проверьте `http://127.0.0.1:8000/ready` и войдите через `/login`.

Между v0.9 и v1.0 структура БД **не менялась**. При обновлении из версии до v0.3 сначала выполните миграцию `python -m scripts.migrate_v03`. Никогда не коммитьте .env, .db, пароли и резервные копии в GitHub.
