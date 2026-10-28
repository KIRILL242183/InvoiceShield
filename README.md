# InvoiceShield v0.3.0 🛡️

**Учебный FinTech + Cybersecurity проект на Python**: защищённая веб-платформа анализа счетов и расследования подозрительных платежей.

> **Локальная демонстрация, не production.** Используйте только синтетические реквизиты, не размещайте проект в публичном интернете без отдельного обзора безопасности. Risk score — учебная сумма эвристических баллов, **не** вероятность мошенничества. Нет MFA, rate limiting, многоарендности, полного security review и полноценных Alembic-миграций.

## Возможности

- Реестр поставщиков и счетов, обнаружение смены реквизитов (+70), повторов (+60) и счетов свыше 1 млн рублей (+35), итог ограничен 100.
- Авторизация с Argon2id; серверные отзывные сессии и CSRF-токены, роли `admin` и `analyst`.
- Автоматическое создание инцидентов `OPEN` при `MEDIUM` и `HIGH` риске.
- Статусы: `OPEN → IN_REVIEW → RESOLVED` или `FALSE_POSITIVE`; повторное открытие переводит в `IN_REVIEW`.
- Назначение исполнителей администратором; комментарии и журнал событий кейса; защита от устаревших версий через поле `version` и HTTP 409.
- REST API (`/docs`), тесты Pytest, CI GitHub Actions.

### Стек
Python 3.12+, FastAPI, SQLAlchemy, SQLite (локально) / PostgreSQL (через Docker Compose), Jinja2, HTML/CSS, Pytest, Docker, GitHub Actions.

## Самый быстрый запуск с нуля (macOS / Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m scripts.manage_users add --username admin --role admin
python -m scripts.seed_demo
python -m pytest -q
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Откройте `http://127.0.0.1:8000/login`. Пароль `admin` задаётся при создании пользователя (от 12 символов, не записывается в историю терминала). Администратор может создать аналитика:

```bash
python -m scripts.manage_users add --username analyst --role analyst
```

Создайте счёт с новыми банковскими реквизитами или суммой свыше 1 млн рублей. После анализа появится запись на `/incidents`.

**Если вы обновляете существующую v0.2 на Mac, не следуйте запуску с нуля.** Вместо этого смотрите [инструкцию по обновлению](docs/UPGRADE_0_3.md), чтобы сохранить базу, аккаунты и старые счета. Важная дополнительная команда `python -m scripts.migrate_v03` создаёт кейсы для ранее проверенных подозрительных счетов; её безопасно повторять.

## Доступы и маршруты

| Действие | admin | analyst |
|---|---|---|
| Просмотр счетов, поставщиков, кейсов | Да | Да |
| Проверка счетов | Да | Да |
| Смена статуса кейса, добавление комментария | Да | Да |
| Назначение исполнителя | Да | Нет (403) |
| Создание поставщиков и просмотр общего аудита | Да | Нет (403) |

REST API расследований:

- `GET /api/incidents?status=OPEN` — список с фильтром.
- `GET /api/incidents/{id}` — кейс и события.
- `POST /api/incidents/{id}/status` — JSON `{ "status": "IN_REVIEW", "version": 1 }`.
- `POST /api/incidents/{id}/assign` — JSON `{ "assignee_id": 2, "version": 1 }` (только admin).
- `POST /api/incidents/{id}/comments` — JSON `{ "comment": "Проверено" }`.

Для изменяющих API-запросов нужны cookie авторизованного пользователя и `X-CSRF-Token`. После входа CSRF-токен доступен из `GET /api/auth/me` тому же браузеру. Не публикуйте токен и cookie.

## Основные файлы

```text
app/
  main.py                           # настройка FastAPI
  auth.py                           # хеширование паролей, сессии, CSRF
  models.py                         # таблицы и связи
  routes_api.py                     # счета и поставщики
  routes_incidents.py               # REST API расследований
  routes_investigations_web.py      # HTML-интерфейс инцидентов
  services/risk.py                  # антифрод-правила
  services/invoices.py              # проверка счетов, автоматическое открытие кейса
  services/incidents.py             # инциденты, переходы, проверка версии
  templates/incident_detail.html    # страница расследования
scripts/migrate_v03.py             # создание таблиц и backfill старых счетов
tests/test_incidents.py            # регрессионные и security-тесты
docs/LESSON_03_INCIDENTS.md        # обучающий разбор
```

## Инварианты данных и ограничения

- Один кейс на один подозрительный счёт (`UNIQUE(invoice_id)`).
- Инцидент открывается в одной транзакции с проверкой нового счёта.
- Риск не меняется при закрытии инцидента: это две независимые сущности.
- События можно только добавлять через предоставленное API, но БД **не** обеспечивает криптографическую неизменяемость аудита.
- Конфликт старой формы при изменении статуса/назначении приводит к `409` через API и уведомлению в браузере.
- Старые счета с ошибочным риском автоматически не пересчитываются, чтобы не менять исторические решения молча.
- Запуск `Base.metadata.create_all()` создаёт недостающие таблицы, **не заменяет** полноценные миграции схемы. Для следующего изменения существующих колонок понадобится Alembic.

## Документация

- [Обновление 0.2 → 0.3](docs/UPGRADE_0_3.md)
- [Урок 3: расследования и optimistic concurrency](docs/LESSON_03_INCIDENTS.md)
- [Техническое задание предыдущей версии](docs/TECHNICAL_SPEC.md)
- [Архитектура предыдущей версии](docs/ARCHITECTURE.md)
- [Security model v0.2 (общие ограничения сохраняются)](docs/SECURITY_MODEL.md)
- [Changelog](docs/CHANGELOG.md)

## Тестирование

```bash
python -m pytest -q
python -m compileall -q app scripts
```

Последний запуск разработчика: **38 passed**. Docker + PostgreSQL не проходил полноценную интеграционную проверку в этой среде. При развертывании сначала настройте TLS, `COOKIE_SECURE=true`, миграции, ограничения запросов и мониторинг.
