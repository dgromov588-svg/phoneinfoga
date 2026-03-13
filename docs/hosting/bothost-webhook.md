# Автообновление на Bothost через Webhook (GitHub/GitLab)

Bothost умеет автоматически пересобирать и перезапускать проект при пуше в репозиторий.

Ниже — минимальные настройки вебхука.

## GitHub

1. Откройте репозиторий → **Settings** → **Webhooks** → **Add webhook**.
2. Заполните:
   - **Payload URL**: `http://agent.bothost.ru/api/webhooks/github`
   - **Content type**: `application/json`
   - **Secret**: по возможности задайте секрет (см. ниже).
   - **Which events would you like to trigger this webhook?**: **Just the push event**
   - **Active**: включено.
3. Нажмите **Add webhook**.

Проверка:
 - В **Webhooks → Deliveries** должна появиться успешная доставка (обычно HTTP 200/204).
 - Сделайте `git push` в нужную ветку (например, `main`) и проверьте, что Bothost начал сборку/перезапуск.

## GitLab

1. Откройте репозиторий → **Settings** → **Webhooks**.
2. Заполните:
   - **URL**: `http://agent.bothost.ru/api/webhooks/gitlab`
   - **Secret token**: по возможности задайте секрет (см. ниже).
   - **Trigger**: включите **Push events** (и при необходимости **Tag push events**).
3. Нажмите **Add webhook**.

Проверка:
 - Используйте кнопку **Test** для push event (если доступна) или просто сделайте реальный `git push`.
 - Проверьте, что Bothost начал деплой.

## Секрет (рекомендуется)

Если Bothost позволяет указать secret/токен в настройках Git Deploys, включите его — это защищает от поддельных запросов.

Как сгенерировать секрет:
 - PowerShell: `[guid]::NewGuid().ToString('N')`
 - Python: `python -c "import secrets; print(secrets.token_hex(32))"`

Затем:
 - вставьте этот secret в настройки вебхука в GitHub/GitLab;
 - и укажите тот же secret в настройках деплоя в Bothost (если поле предусмотрено).
