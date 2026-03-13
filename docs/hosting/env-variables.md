# Переменные окружения для хостинга PhoneInfoga

Этот документ объясняет, какие переменные окружения нужно задать при деплое (Telegram-бот, CLI и веб-интерфейс), а также как их конфигурировать на популярных хостингах.

## Обязательные переменные

| Переменная | Назначение |
|------------|------------|
| `TELEGRAM_BOT_TOKEN` | Токен вашего Telegram-бота (получается у BotFather). Без него бот не стартует. |
| `DIRECTORY_DB_PATH` | Путь к файлу `business_directory.db`. Относителен к рабочей директории; по умолчанию `business_directory.db`. |

## Варианты поиска (функционал России / соцсети)

| Переменная | Описание |
|------------|----------|
| `NUMVERIFY_API_KEY` | API-ключ Numverify (Apilayer) предоставляет расширенную валидацию номера. Бесплатный тариф доступен. |
| `ABSTRACT_API_KEY` | API-ключ AbstractAPI Phone Validation. Позволяет получать информацию по номеру (carrier, timezone). |
| `IPAPI_API_KEY` | Ключ `ipapi.com` (до 1000 бесплатных запросов в месяц). Используется для дополнительного lookup по номеру. |
| `IPINFO_TOKEN` | Токен `ipinfo.io` (бесплатный на ограниченном тарифе). |
| `IPQUALITYSCORE_API_KEY` | Ключ IPQualityScore (для проверки репутации номера). |
| `VONAGE_API_KEY` / `VONAGE_API_SECRET` | Пара ключ/секрет для номера Vonage (Nexmo). Позволяет использовать их lookup API. |
| `GOOGLECSE_CX`, `GOOGLE_API_KEY`, `GOOGLECSE_MAX_RESULTS` | Параметры Google Custom Search Engine (используются при включении GoogleCSE-сканера). |
| `LOG_LEVEL` | Уровень логов (`info`, `warn`, `debug`, и т.п.). |
| `FSSP_API_TOKEN` | Токен для вызова официального API ФССП (`/fssp` команда). |
| `TELEGRAM_ALLOWED_CHAT_IDS` | Опциональный список chat_id через запятую (если хотите ограничить доступ к боту). |

> Если некоторые ключи не заданы, соответствующие сканеры автоматически пропускаются. Это позволяет использовать PhoneInfoga с минимальной конфигурацией и расширять позже.

## Пример `.env`

```dotenv
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_CHAT_IDS=
FSSP_API_TOKEN=
NUMVERIFY_API_KEY=
ABSTRACT_API_KEY=
IPAPI_API_KEY=
IPINFO_TOKEN=
IPQUALITYSCORE_API_KEY=
VONAGE_API_KEY=
VONAGE_API_SECRET=
GOOGLECSE_CX=
GOOGLE_API_KEY=
GOOGLECSE_MAX_RESULTS=10
DIRECTORY_DB_PATH=business_directory.db
LOG_LEVEL=info
```

Разместите `.env` рядом с `telegram_bot.py` (файл игнорируется git) или установите переменные через панель хостинга.

## Деплой на Railway

1. Создайте новый проект и подключите репозиторий `phoneinfoga`.
2. В разделе **Variables** добавьте перечисленные выше переменные (Railway сериализует их автоматически).
3. Укажите команду запуска, например: `python telegram_bot.py` для бота или `gunicorn --bind 0.0.0.0:5000 universal_search_system:app` для веб-интерфейса.
4. При необходимости подпишитесь на бесплатные API (Numverify, AbstractAPI, ipapi) и вставьте ключи.

Railway также позволяет загрузить `.env` файл с помощью `railway variables import` или CLI.

## Деплой с Docker

1. Подготовьте `Dockerfile` (в корне есть готовый) и создайте `docker-compose.yml` с:

```yaml
version: '3.8'
services:
  phoneinfoga:
    build: .
    env_file:
      - .env
    ports:
      - '5000:5000'
    command: python universal_search_system.py
```

2. Создайте `.env` (как выше) рядом с `docker-compose.yml`. Docker автоматически подставит переменные.
3. Запустите `docker compose up --build`.

Если вы деплоите только Telegram-бота, используйте команду `python telegram_bot.py`, а для API-фронта — `gunicorn --bind 0.0.0.0:5000 universal_search_system:app`.

## Общие рекомендации

- Не коммитьте реальные токены — `.env` добавлен в `.gitignore`.
- Используйте отдельные ключи для продакшена и тестовой среды.
- Следите за лимитами бесплатных API и при необходимости используйте прокси или кеширование.
- Для проверки доступности API можно запускать `python osint_cli.py phone-check +79001234567 --no-breaches`.

## Автообновление (Bothost Git Deploys)

Если вы хостите проект на Bothost и хотите, чтобы бот/сервис автоматически обновлялся при `git push`, настройте webhook в GitHub/GitLab.

Инструкция: см. `docs/hosting/bothost-webhook.md`.

