# Хвостосовет (2025–2026)

Чат-бот для помощи владельцам домашних животных.  
Сейчас работает Telegram-бот. В планах — вынести “мозг” в отдельный backend (API + БД) и добавить web/PWA/приложение как альтернативные клиенты (на случай проблем с Telegram).

## Структура репозитория

- telegram-bot/ — рабочий Telegram-бот (Python + Pyrogram + OpenAI)
- backend/ — заготовка под будущий backend (API + БД + storage)
- web/ — заготовка под web/PWA (альтернативный клиент)
- docs/ — документация и заметки по архитектуре/плану
- .gitignore — игнор локальных файлов (.venv, .env, кеши и т.д.)

Важно: у каждого сервиса свой .env в своей папке. Сейчас используется telegram-bot/.env.

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

    BOT_TOKEN=123456:ABCDEF...
    API_ID=12345678
    API_HASH=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    OPENAI_API_KEY=sk-...
    OPENAI_MODEL=gpt-4.1-mini

## Примечания

- .venv/, .env, __pycache__/, *.session — локальные файлы, в git не добавляются.
- Если Telegram временно недоступен, планируется web/PWA-клиент на том же backend.

## Roadmap (кратко)

1. Backend (FastAPI) + БД: пользователи, питомцы, история, лимиты, тарифы
2. Telegram-бот как “тонкий клиент” (бот → API → ответ)
3. Фото/аудио + сохранение контекста (для PRO)
4. Web/PWA как альтернативный канал
