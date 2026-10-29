# Обновление InvoiceShield v0.7 → v0.8 (Mac / Linux)

Приложение остаётся локальным учебным стендом. Новые функции не меняют колонки или таблицы БД; миграция не требуется.

1. Остановите сервер (`Control+C`).
2. Сохраните резервную копию базы (инструкции [здесь](OPS_BACKUP.md)). Если на старой версии ещё нет модуля backup, копируйте базу **при остановленном сервере**.
3. Распакуйте `InvoiceShield-v0.8.0-update.zip` поверх папки приложения, не удаляя `.venv` и локальную `invoiceshield.db`.
4. Активируйте `.venv` и выполните `python -m pip install -r requirements-dev.txt`.
5. Выполните `python -m pytest -q` — ожидается 107 тестов.
6. Запустите `python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`.
7. Выполните `python -m scripts.smoke_check` в другом терминале.
8. Проверьте вход под ранее созданными аккаунтами и открытие одного инцидента.

Если локальная установленная версия старше v0.7, сначала ознакомьтесь с предыдущими инструкциями (особенно v0.3 backfill и таблицей `login_throttles` для v0.7).

Для Docker: `cp .env.example .env`, задайте **новый** локальный пароль, `docker compose up --build -d --wait`; впервые создайте администратора через `docker compose run --rm web python -m scripts.manage_users add --username admin --role admin`. База Docker/PostgreSQL изолирована от локального SQLite-файла — это разные хранилища и аккаунты.

**Не используйте `docker compose down -v` на своём компьютере**, если хотите сохранить PostgreSQL volume: опция `-v` удаляет том с данными. В CI она используется только на временном стенде.
