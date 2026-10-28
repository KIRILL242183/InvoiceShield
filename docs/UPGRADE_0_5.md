# Обновление InvoiceShield 0.4.0 → 0.5.0 на macOS

1. Останови сервер `Control+C`.
2. Перейди в текущую папку проекта:
   ```bash
   cd ~/Downloads/invoiceshield-v0.1.0
   ```
3. Сделай резервную копию своей БД **перед обновлением** (если используешь SQLite):
   ```bash
   cp invoiceshield.db ~/Downloads/invoiceshield-backup-before-v05.db
   ```
   Если SQLite-файла нет, проверь переменную `DATABASE_URL`/путь в `app/database.py`, не продолжай наугад.
4. Распакуй `InvoiceShield-v0.5.0-update.zip` **поверх текущей папки**:
   ```bash
   unzip -o ~/Downloads/InvoiceShield-v0.5.0-update.zip -d .
   ```
5. Запусти тесты и приложение:
   ```bash
   source .venv/bin/activate
   python -m pip install -r requirements-dev.txt
   python -m pytest -q
   python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```
6. Войди на `http://127.0.0.1:8000/pdf-import`. Используй текстовый PDF с **синтетическими** реквизитами (не финансовый документ настоящего клиента).

**Миграция БД не требуется:** изменён только алгоритм разбора и интерфейс предпросмотра. Существующие счета и инциденты не пересчитываются и не изменяются.

**Отличие от ZIP:** GitHub-версия доступна в ветке `main` после прохождения CI и merge PR; для работы непосредственно с Git используйте отдельный clone, не накладывая ZIP на рабочее дерево с незакоммиченными изменениями.
