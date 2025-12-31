# Хвостосовет (2025–2026)

Чат-бот/сервис помощи владельцам домашних животных.

Текущая архитектура (MVP):
**Telegram-бот → Backend API → Supabase (Postgres) → LLM → Backend → Telegram-бот**

- **Telegram-бот** — “тонкий клиент”: собирает ввод и отправляет запрос в backend.
- **Backend** — “мозг”: лимиты, дедуп, тарифы/политики LLM, работа с БД, вызов LLM.
- В планах: **web/PWA** как альтернативный клиент.

## Структура репозитория

- telegram-bot/ — Telegram-бот (Python + Pyrogram), **ходит в backend API**
- backend/ — Backend API (FastAPI) + Supabase(Postgres) + LLM
- web/ — заготовка под web/PWA (альтернативный клиент)
- docs/ — документация и заметки по архитектуре/плану
- .gitignore — игнор локальных файлов (.venv, .env, кеши и т.д.)

Важно: у каждого сервиса свой `.env` в своей папке.  
**`.env` не коммитим**, коммитим только `.env.example`.

## Быстрый старт: Telegram-бот (Windows + VS Code)

1. Открой папку проекта в VS Code.

2. Перейди в папку бота:

    cd telegram-bot

3. Создай виртуальное окружение (если ещё нет):

    python -m venv .venv

4. Активируй окружение:

    .\.venv\Scripts\Activate.ps1

5. Установи зависимости:

    python -m pip install -U pip  
    python -m pip install -r requirements.txt

6. Создай файл telegram-bot/.env и запусти бота:

    python main.py

## Пример telegram-bot/.env

 ⚠️ В текущей архитектуре бот не использует OPENAI_API_KEY напрямую.
 Вся работа с LLM — внутри backend.

    BOT_TOKEN=123456:ABCDEF...
    API_ID=12345678
    API_HASH=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    BACKEND_BASE_URL=http://127.0.0.1:8000
    BOT_BACKEND_TOKEN=devtoken123

## Backend (API)

Backend реализован на FastAPI и используется Telegram-ботом как основной источник логики.

Что делает backend (MVP):

- Bearer Auth (bot → backend) через BOT_BACKEND_TOKEN
- Idempotency (дедуп) по заголовку X-Request-Id и таблице request_dedup
- Rate limit (daily window + cooldown) через таблицу rate_limits
- Вызов LLM по политикам (llm_policies: free_default, pro_default, pro_research)
- Заглушки Pro-эндпоинтов (402) для будущих фич: профиль питомца/история/медиа/удаление данных

## Примечания

- Не коммитить: .env, .venv/, __pycache__/, *.session
- Токены/ключи — только через .env (локально/на сервере)
- BOT_BACKEND_TOKEN в проде должен быть уникальным и секретным
- Если Telegram временно недоступен, планируется web/PWA-клиент на том же backend.

## Документация
- docs/DEPLOY_BACKEND.md — деплой/обновление backend + smoke
- docs/DEPLOY_TELEGRAM_BOT.md — деплой/обновление telegram-bot + smoke

## Roadmap (кратко)

1. Backend MVP (API + Supabase + LLM policies + лимиты + дедуп) ✅ 
2. Деплой backend на VPS + smoke на проде ✅
3. Деплой Telegram-бота на VPS (тонкий клиент) ✅
4. Pro-фичи: профиль питомца/история/память → фото → аудио
5. Web/PWA как альтернативный канал
