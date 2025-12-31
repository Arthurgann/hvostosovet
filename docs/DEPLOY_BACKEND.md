
# 📌 BACKEND Hvostosovet — ДЕПЛОЙ / ОБНОВЛЕНИЕ / SMOKE (VPS Beget)

## 1) Сервер и окружение

- Хостинг: Beget  
- Тип: VPS (root)
- IP: 2.58.98.6
- Домен API: `api.tailadvice.ru`
- HTTPS: Traefik + Let’s Encrypt
- Docker: backend запускается в Docker
- Reverse-proxy: Traefik (общая сеть `n8n_default`)

## 2) Где что лежит на сервере

Рабочая директория:

`/root/hvostosovet-backend/`

Структура:

```
/root/hvostosovet-backend
├── backend/                 # Python-код FastAPI (requirements.txt + app/)
├── upload/                  # сюда кладём zip для обновления
├── docker-compose.yml       # compose для backend
└── .env.prod                # прод-ключи (BOT_BACKEND_TOKEN, DB, OPENAI_API_KEY, ...)
```

❗ Важно:
- `.env.prod` НЕ трогаем при обновлениях кода.
- Внутри `backend/` НЕ должно быть `.venv`, `.env`, `docker-compose.yml`.
- Backend в проде НЕ запускается руками — только через Docker.

## 3) Как backend запускается в проде (принцип)

- `working_dir: /app/backend`
- `pip install -r requirements.txt` (внутри контейнера)
- `uvicorn app.main:app`
- `volumes: - ./:/app`
- `env_file: .env.prod`
- сеть `n8n_default` (external)

## 4) Как обновлять backend (алгоритм — всегда одинаковый)

### Вариант A: ZIP

1) Остановить контейнер:
```bash
cd /root/hvostosovet-backend
docker compose down
```

2) Проверить имя zip:
```bash
ls upload
```

3) Распаковать zip в `backend/`:
```bash
unzip -o upload/ИМЯ_ФАЙЛА.zip -d backend
```

⚠️ Если получилось `backend/backend/...`:
```bash
mv backend/backend/* backend/
rmdir backend/backend
```

4) Проверка:
В `backend/` должны быть `requirements.txt` и папка `app/`.

5) Запуск:
```bash
docker compose up -d
```

6) Логи:
```bash
docker compose logs -n 50
```

### Вариант B: Git pull

```bash
cd /root/hvostosovet-backend
git pull
docker compose down
docker compose up -d
docker compose logs -n 50
```

## 5) Smoke-тесты (Windows PowerShell)

### /v1/health
```powershell
curl.exe -i https://api.tailadvice.ru/v1/health
```

### /v1/me
```powershell
curl.exe -i -H "Authorization: Bearer ТОКЕН_ИЗ_ПРОДА" https://api.tailadvice.ru/v1/me
```

### /v1/chat/ask (рекомендуется Invoke-RestMethod)
```powershell
$rid = [guid]::NewGuid().ToString()
$headers = @{ Authorization = "Bearer ТОКЕН_ИЗ_ПРОДА"; "X-Request-Id" = $rid }
$body = @{ user = @{ telegram_user_id = 999002 }; text = "test" } | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Uri "https://api.tailadvice.ru/v1/chat/ask" -Headers $headers -ContentType "application/json" -Body $body
```

Ожидаемо: ответ с `answer_text`.

## 6) Частые ошибки

- **401 Unauthorized** — неверный токен.
- **422 Unprocessable Entity** — битый JSON (использовать `Invoke-RestMethod`).
- **502 llm_failed** — проблема с `OPENAI_API_KEY`.

Логи:
```bash
docker compose logs -n 100
```

## 7) Ключевая мысль

Backend в проде:
- без venv
- без `.env` внутри `backend/`
- всё через Docker + `.env.prod`
- обновление = код → restart → smoke
