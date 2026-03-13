# Docker Compose hosting guide

Этот гайд описывает быстрый запуск через `Dockerfile.hosting` + `docker-compose.hosting.yml`.

## Что уже подготовлено

- `Dockerfile.hosting` — контейнер с авто-клоном/авто-обновлением репозитория.
- `docker-compose.hosting.yml` — orchestration для хостинга.
- `.env.hosting.example` — шаблон env-переменных.

## Быстрый старт

1. Скопируйте шаблон:

```bash
cp .env.hosting.example .env.hosting
```

2. Откройте `.env.hosting` и заполните минимум:

- `REPO_URL`
- `REPO_BRANCH` (обычно `master` или `main`)
- `APP_CMD` (что запускать в контейнере)

3. Поднимите сервис:

```bash
docker compose -f docker-compose.hosting.yml --env-file .env.hosting up -d --build
```

4. Посмотрите логи:

```bash
docker compose -f docker-compose.hosting.yml --env-file .env.hosting logs -f
```

## Сценарии APP_CMD

### 1) HTTP API (по умолчанию)

```dotenv
APP_CMD=python universal_search_system.py
```

### 2) Основной Telegram-бот

```dotenv
APP_CMD=python osint_cli.py telegram-bot
```

### 3) Копия Telegram-бота

```dotenv
APP_CMD=python osint_cli.py telegram-bot-copy
```

## Запуск двух ботов параллельно

Вариант A (рекомендуется): поднимите два сервиса с разными env-файлами.

- `APP_CMD=python osint_cli.py telegram-bot`
- `APP_CMD=python osint_cli.py telegram-bot-copy`

Для copy-бота укажите отдельные переменные:

- `TELEGRAM_BOT_TOKEN_COPY`
- `TELEGRAM_ALLOWED_CHAT_IDS_COPY`
- `FSSP_API_TOKEN_COPY` (опционально)

## Обновление кода на хостинге

Если `AUTO_UPDATE=true`, контейнер на каждом старте делает `fetch/reset` на `origin/${REPO_BRANCH}`.

Перезапуск для принудительного обновления:

```bash
docker compose -f docker-compose.hosting.yml --env-file .env.hosting restart
```

## Полезные команды

Остановить:

```bash
docker compose -f docker-compose.hosting.yml --env-file .env.hosting down
```

Остановить с удалением volume (чистый старт):

```bash
docker compose -f docker-compose.hosting.yml --env-file .env.hosting down -v
```

## Примечания

- Для приватного репозитория используйте `REPO_URL` с токеном/доступом deploy key.
- Не коммитьте `.env.hosting` с реальными секретами.
- Для production желательно закреплять конкретный branch/tag и ограничивать токены по правам.
