# InvoiceShield 🛡️

**InvoiceShield** — учебный B2B FinTech/Cybersecurity проект, который обнаруживает риски оплаты подозрительных счетов поставщиков. Написан на Python + FastAPI, с PostgreSQL/SQLite, веб-панелью, объяснимыми правилами и автоматическими тестами.

> ⚠️ **DEMO ONLY.** Нет логина, CSRF, TLS и полного набора security controls. Запускать только на `127.0.0.1` со **синтетическими данными**. Никаких реальных счетов, банковских реквизитов или платёжных операций. Баллы — эвристика, не вероятность мошенничества.

## Возможности v0.1.0

- Реестр поставщиков.
- Проверка счетов: **смена реквизитов +70**, **дубликат номера +60**, **сумма больше 1 млн ₽ +35**.
- Риск: `LOW` (0–29), `MEDIUM` (30–59), `HIGH` (60–100), максимум 100.
- Веб-панель на `/`, Swagger на `/docs`, REST API.
- Журнал операций в БД, без хранения реквизитов в описаниях событий.
- Запуск локально с SQLite или Docker Compose с PostgreSQL.
- Тесты с отдельной SQLite базой.

## Вариант A — быстрый запуск без Docker (Linux / macOS)

```bash
python3 --version                   # требуется Python 3.12+
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m scripts.seed_demo           # пример данных (запуск из корня проекта)
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Открой: http://127.0.0.1:8000 — сайт, http://127.0.0.1:8000/docs — API.

Локальная база: `invoiceshield.db` (игнорируется Git). Чтобы начать с пустой БД, **останови сервер** и удали `invoiceshield.db` (потеря локальных демоданных).

## Вариант B — Docker + PostgreSQL

```bash
cp .env.example .env
# Смени POSTGRES_PASSWORD на длинное случайное буквенно-цифровое значение.
docker compose up --build -d
# После запуска, в отдельной команде:
docker compose exec web python -m scripts.seed_demo
```

**Важно:** образ контейнера должен включать папку `scripts/`. Если меняешь пароль в `.env` после создания тома PostgreSQL, он не сменится автоматически внутри БД. Приложение доступно только по `http://127.0.0.1:8000`.

Остановить: `docker compose down`. Удалить **все локальные данные БД**: `docker compose down -v`.

## Тесты

```bash
python -m pytest -q
python -m compileall -q app
ruff check .
```

На GitHub Actions тесты и статическая проверка запускаются при каждом push/PR.

## REST API — пример

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/api/suppliers \
  -H 'Content-Type: application/json' \
  -d '{"name":"ООО Пример","bank_account":"RU-DEMO-12345"}'

curl -X POST http://127.0.0.1:8000/api/invoices \
  -H 'Content-Type: application/json' \
  -d '{"supplier_id":1,"invoice_number":"DEMO-001","amount_rub":"120000.00","bank_account":"RU-DEMO-99999","issued_on":"2026-10-28"}'
```

Для новых реквизитов при верном `supplier_id` получится высокий риск. Если предварительно выполнялся `seed_demo`, `supplier_id=1` относится к демо-поставщику, а не к `ООО Пример`: используй ID из ответа API или списка `/api/suppliers`.

## Структура репозитория

```text
app/
  main.py              # FastAPI entrypoint
  config.py            # DATABASE_URL
  database.py          # Engine, Session, Base
  models.py            # ORM-модели
  schemas.py           # API-валидация
  routes_api.py        # REST
  routes_web.py        # HTML endpoints
  services/
    invoices.py        # Бизнес-операции
    risk.py            # Антифрод-правила
  templates/index.html # Веб-страница
  static/styles.css    # Стили
scripts/seed_demo.py   # Демоданные
tests/                 # API/UI тесты
docs/                  # ТЗ, архитектура, обучение
compose.yaml, Dockerfile, .github/workflows/ci.yml
```

## Архитектура и план

- [Техническое задание](docs/TECHNICAL_SPEC.md)
- [Архитектура и модель угроз](docs/ARCHITECTURE.md)
- [Учебный план по файлам](docs/LEARNING_PATH.md)

**Следующая версия (v0.2):** авторизация, роли, Alembic, адекватная CSRF-защита, проверка прав доступа и журналирование security-событий. Затем — безопасный импорт PDF, OCR, ML на синтетическом датасете и CI с проверками PostgreSQL.

## GitHub — первая публикация

```bash
git init -b main
git add .
git commit -m "feat: build first invoice fraud risk dashboard"
git remote add origin git@github.com:YOUR_USERNAME/invoiceshield.git
git push -u origin main
```

Создай **пустой** репозиторий `invoiceshield` в своём GitHub и подставь свой логин. Не публикуй `.env`, `*.db`, приватный SSH-ключ или реальные банковские данные. Для доступа к GitHub используется публичная часть SSH-ключа, приватная хранится только локально.
