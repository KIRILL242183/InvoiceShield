# InvoiceShield v0.2.0 🛡️

Учебный B2B FinTech / Cybersecurity проект на Python + FastAPI: выявляет риски оплаты счетов поставщиков, объясняет сработавшие правила, сохраняет историю проверок и защищает доступ к данным.

> **ЛОКАЛЬНОЕ ДЕМО, НЕ PRODUCTION.** Только синтетические счета и поставщики, не обрабатывать реальные банковские реквизиты. Нет MFA, rate limiting, полноценной политики паролей, автоматической миграции схемы Alembic, TLS и security review. Демо-счетчики риска **не являются вероятностями мошенничества**. Запускайте только на `127.0.0.1`.

## Что нового в v0.2.0

- **Авторизация:** вход с паролем, Argon2id для хранения хешей, случайные revocable sessions на сервере. В БД сохраняется SHA-256 от токена сессии, не сам токен.
- **Разделение прав:** `admin` управляет поставщиками, проверяет счета и читает аудит; `analyst` может читать реестр и проверять счета, но не создавать поставщиков и не читать журнал действий.
- **CSRF:** скрытые токены на всех HTML POST-формах и заголовок `X-CSRF-Token` для изменяющих API-запросов.
- **Security Events:** события авторизации, выхода и финансовых операций связаны с пользовательским ID.
- **CSP + заголовки:** нет встроенного JavaScript; session cookies `HttpOnly` и `SameSite=Strict`; `Secure` включается через `COOKIE_SECURE=true` **только на HTTPS**.
- **Сохранение старых данных:** существующие таблицы `suppliers`, `invoices`, `audit_events` не менялись; новая версия добавляет таблицы `users`, `auth_sessions`, `security_events`.

## Важные файлы

```text
app/
  main.py              # сборка FastAPI, security headers
  auth.py              # пароль, сессии, CSRF, проверки ролей
  routes_auth.py       # логин, логаут, /api/auth/me
  routes_api.py        # защищенные REST endpoints
  routes_web.py        # защищенные веб-формы
  models.py            # SQLAlchemy, включая User / AuthSession
  services/risk.py     # три антифрод-правила
  services/invoices.py # транзакции, антифрод-проверки и журнал
  templates/login.html # логин
  templates/index.html # dashboard
  static/app.js        # внешний JavaScript, совместим с CSP
scripts/manage_users.py # интерактивное создание пользователей
tests/test_auth.py       # проверки отказов, прав, CSRF, сессий
docs/SECURITY_MODEL.md   # модель безопасности и ограничения
docs/LESSON_02_AUTH.md   # учебный разбор авторизации
```

## Новый локальный запуск (macOS / Linux)

Python 3.12+:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt

# Создайте первого администратора ДО первого входа.
# Пароль будет запрошен интерактивно и не попадёт в историю команд.
python -m scripts.manage_users add --username admin --role admin

# НЕ запускать повторно, если уже есть данные и вы не хотите демоданные:
python -m scripts.seed_demo

python -m pytest -q
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Открой `http://127.0.0.1:8000/login`, войди логином `admin` и паролем, который ты выбрал. Данные из v0.1.x остаются в `invoiceshield.db`.

Создать аналитика (в другом терминале из корня проекта с активным `.venv`):

```bash
python -m scripts.manage_users add --username analyst --role analyst
```

Проверяйте права доступа, войдя каждым пользователем по очереди. Доступ к `/api/*` также требует входа; Swagger `/docs` показывает документацию, но не обходит проверку прав.

### Обновление существующего проекта без потери данных

Для пользователя, уже запускавшего `~/Downloads/invoiceshield-v0.1.0`, есть отдельный архив `invoiceshield-upgrade-v0.2.0.zip` без базы данных и `.venv`. Остановите приложение (`Control+C`), **сделайте копию** `invoiceshield.db`, распакуйте обновление поверх файлов, затем переустановите зависимости и создайте администратора. Подробные команды включены в `docs/UPGRADE_0_2.md`.

## Работа с REST API после логина

Сессия cookie-based; для `POST /api/suppliers` и `POST /api/invoices` требуется **дополнительно** заголовок `X-CSRF-Token`. Локальный браузер, выполнивший вход, может получить token через:

```bash
# Ввести в адресной строке браузера уже после авторизации:
http://127.0.0.1:8000/api/auth/me
```

Ответ содержит текущую роль и CSRF-токен. Для API-клиента необходимо передавать обе вещи: действительный cookie сессии и CSRF-токен. Не передавайте их другим людям и не публикуйте скриншоты с токеном.

## Роли

| Операция | admin | analyst | без входа |
|---|---|---|---|
| Просмотреть панель | ✓ | ✓ | ✗ |
| Просмотреть поставщиков | ✓ | ✓ | ✗ |
| Создать поставщика | ✓ | ✗ | ✗ |
| Проверить счёт | ✓ | ✓ | ✗ |
| Просмотреть аудит (`/api/audit`) | ✓ | ✗ | ✗ |
| Посмотреть `/health` | ✓ | ✓ | ✓ |

## Запуск с Docker Compose (опционально)

```bash
cp .env.example .env
# Поменяйте POSTGRES_PASSWORD на длинный случайный пароль.
docker compose up --build -d
docker compose exec web python -m scripts.manage_users add --username admin --role admin
docker compose exec web python -m scripts.seed_demo
```

Контейнер слушает только `127.0.0.1:8000`. `docker compose down` сохраняет БД, `docker compose down -v` **удаляет данные**.

## Проверки

```bash
python -m pytest -q
python -m compileall -q app scripts
ruff check .
```

CI запускает тесты и Ruff на push/PR. Историю исправлений см. `docs/BUGFIX_0_1_1.md`.

## Следующие этапы

1. Надёжные миграции Alembic + rollback/backup перед обновлением схемы.
2. Ограничение скорости попыток логина и MFA; более подробный аудит админ-действий.
3. Изоляция файлов, импорт PDF, проверки типа/размера/содержимого.
4. Бизнес-функции: расследование подозрительных счетов, назначение аналитика, статусы и подтверждение поставщика.
5. Проверка и развёртывание с HTTPS, PostgreSQL, безопасными секретами и средствами наблюдаемости.

Не вводите пароли, токены и настоящие данные в публичные репозитории. Учётные данные и `.db` игнорируются в `.gitignore`.
