# Dating MVP (Flask)

Мини-сайт знакомств с:
- регистрацией и входом,
- лентой анкет,
- лайками и взаимными мэтчами,
- чатом только между мэтчами,
- realtime-обновлением чата (Socket.IO),
- загрузкой аватаров,
- JSON REST API для клиентов.

## Быстрый запуск

1. Создайте виртуальное окружение и установите зависимости из `requirements.txt`.
2. Скопируйте `.env.example` в `.env` и задайте `DATING_APP_SECRET_KEY`.
3. Запустите `app.py`.
4. Откройте `http://127.0.0.1:5000`.

## REST API (сессионная авторизация)

- `GET /api/me`
- `GET /api/profiles?city=&min_age=&max_age=`
- `POST /api/like/<user_id>`
- `GET /api/matches`
- `GET /api/messages/<other_user_id>`
- `POST /api/messages/<other_user_id>` с JSON `{ "body": "..." }`

## Docker

- Есть `Dockerfile` и `.dockerignore`.
- Старт контейнера запускает `python app.py` на порту `5000`.

## Mamba

В проекте есть `mamba_official_adapter.py` — это только легальный каркас для интеграции через официальный API/документацию сервиса.
Автоматизация действий на сторонних сайтах без разрешения не реализована.
