# 📌 TELEGRAM-БОТ Hvostosovet — ДЕПЛОЙ / ОБНОВЛЕНИЕ / SMOKE (VPS Beget)

## 1) Назначение и принцип
Telegram-бот — **тонкий клиент**.

Он:
- ❌ НЕ имеет `OPENAI_API_KEY`
- ❌ НЕ общается с LLM напрямую
- ✅ ходит ТОЛЬКО в backend API
- ✅ авторизуется через `BOT_BACKEND_TOKEN`

Архитектура:
```
Telegram → Backend API → LLM
```

## 2) Сервер и окружение
- Хостинг: Beget
- Тип: VPS (root)
- Docker: используется для запуска бота
- Backend API: https://api.tailadvice.ru

## 3) Где что лежит на сервере
```
/root/hvostosovet-telegram-bot
├── telegram-bot/
├── upload/
├── docker-compose.yml
└── .env.prod
```
❗ Важно:

- .env.prod НЕ коммитится
- Внутри telegram-bot/ НЕ должно быть .venv, .env
- Бот в проде НЕ запускается руками
```

## 4) Переменные окружения (.env.prod)
```
Минимальный набор:

BOT_TOKEN=xxxxx
BACKEND_BASE_URL=https://api.tailadvice.ru
BOT_BACKEND_TOKEN=тот_же_токен_что_в_backend

❗ OPENAI_API_KEY в боте НЕ нужен и НЕ должен требоваться.
```

## 5) docker-compose.yml
```yaml
services:
  telegram-bot:
    image: python:3.11-slim
    container_name: hvost-telegram-bot
    working_dir: /app/telegram-bot
    command: >
      bash -lc "pip install --no-cache-dir -r requirements.txt &&
      python main.py"
    volumes:
      - ./:/app
    env_file:
      - .env.prod
    restart: unless-stopped
```

## 6) Деплой / обновление (ZIP)
```
Алгоритм всегда одинаковый.

1.Остановить контейнер

cd /root/hvostosovet-telegram-bot
docker compose down

2.Загрузить zip с кодом

- Архивировать папку telegram-bot/ локально
- Без .venv, без .env
- Загрузить в:

/root/hvostosovet-telegram-bot/upload/telegram-bot.zip

3.Распаковать

cd /root/hvostosovet-telegram-bot
unzip -o upload/telegram-bot.zip

⚠️ Ловушка: Если получилось telegram-bot/telegram-bot/...:

mv telegram-bot/telegram-bot/* telegram-bot/
rmdir telegram-bot/telegram-bot

4.Запуск

docker compose up -d

5.Логи

docker compose logs -n 50
```

## 7) Smoke
- Проверка контейнера
docker ps | grep hvost-telegram-bot
Ожидаемо: статус Up.

- Проверка env внутри контейнера (без утечки секретов)
docker exec -it hvost-telegram-bot sh -lc "env | egrep 'BOT_TOKEN|BACKEND_BASE_URL|BOT_BACKEND_TOKEN' | sed 's/=.*/=***masked***/'"

- Открыть бота - /start в Telegram
- любой текст → ответ

## 8) Частые ошибки
- Missing OPENAI_API_KEY → убрать обязательность в config.py
- Бот молчит → проверить BOT_TOKEN и логи
- Контейнер перезапускается → смотреть логи

## 9) Ключевая мысль
Telegram-бот — тонкий клиент, живёт 24/7 в Docker и ходит только в backend.
