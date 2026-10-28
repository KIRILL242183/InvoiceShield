# Changelog

## v0.2.0 — Auth + RBAC + CSRF

- Новые таблицы `users`, `auth_sessions`, `security_events` (старые таблицы без изменений).
- CLI создание пользователя с хешированием Argon2id.
- Безопасные серверные сессии, login/logout, expiration/revocation.
- Две роли — `admin`, `analyst`; запрет неавторизованного доступа к данным через HTML и REST.
- CSRF для форм и API POST, защищён логин.
- CSP и вынос inline JavaScript во внешний `app.js`.
- Новые тесты прав, неавторизованного доступа, CSRF, срока сессии, logout и совместимости с SQLite v0.1.

## v0.1.1 — Race condition hotfix

- SQLite `BEGIN IMMEDIATE` и PostgreSQL `FOR UPDATE` в транзакции проверки счетов.
- Защита от двойного нажатия кнопки, тест параллельных запросов.

## v0.1.0 — MVP

- Поставщики, счета, три антифрод-правила, dashboard и REST API.
