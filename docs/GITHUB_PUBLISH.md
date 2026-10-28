# Как опубликовать на GitHub

Для проекта `KIRILL242183/InvoiceShield` создайте **пустой** публичный репозиторий через `https://github.com/new`:
без автоматически добавленных README, `.gitignore` и лицензии.

Если публикация через подключение GitHub в ChatGPT недоступна,
историю можно перенести самостоятельно из файла `InvoiceShield-v0.3.0-history.bundle`.

## Команды на macOS

Разместите bundle-файл в `~/Downloads`, затем выполните:

```bash
cd ~/Downloads
git clone InvoiceShield-v0.3.0-history.bundle InvoiceShield-public
cd InvoiceShield-public
git remote remove origin
git remote add origin git@github.com:KIRILL242183/InvoiceShield.git
git push -u origin main
git push origin --tags
```

Если SSH не настроен, замените адрес `git@github.com:KIRILL242183/InvoiceShield.git`
на `https://github.com/KIRILL242183/InvoiceShield.git` и используйте
разрешённый GitHub способ аутентификации (например Git Credential Manager).
**Никогда не передавайте приватный SSH-ключ или персональный токен в чат.**

Это новая копия **кода без старой локальной базы данных**; текущая папка
`~/Downloads/invoiceshield-v0.1.0` и её SQLite-база не изменяются.

После публикации в разделе Tags должны отображаться версии
`v0.1.0`, `v0.1.1`, `v0.2.0`, `v0.3.0`.
Коммиты истории импортированы в текущую дату; это не исходные старые коммиты.
