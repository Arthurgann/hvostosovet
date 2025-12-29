# Backend MVP (Hvostosovet)

Минимальный backend для Telegram-бота:
Telegram-bot → Backend API → DB → LLM

---

## Requirements
- Python 3.11+
- (Optional) Docker — **только если используется локальный Postgres**
- Supabase account — **рекомендуемый вариант для MVP**

---

## Setup

### 1) Environment variables

Скопируйте `.env.example` → `.env` и заполните значения:

```env
BOT_BACKEND_TOKEN=your-secret-token
DATABASE_URL=postgresql://...
```

#### ⚠️ Supabase — важно
В Supabase Dashboard → **Connect → Connection string**:

- Используйте **Method: Session pooler**
- Direct connection может **не работать локально** (не IPv4 compatible)
- Формат URL должен начинаться строго с:

```text
postgresql://
```

Если в строке нет SSL — добавьте:
```text
?sslmode=require
```

---

### 2) Database (выберите один вариант)

#### Option A — Supabase (рекомендуется для MVP)
- Ничего поднимать локально не нужно
- Просто укажите `DATABASE_URL` (Session pooler)

#### Option B — Local Postgres via Docker
```bash
docker compose up -d
```

---

### 3) Run API

Запускать из папки `backend/`:

```bash
uvicorn app.main:app --reload
```

---

## Smoke tests

```bash
curl http://127.0.0.1:8000/v1/health
```

PowerShell пример с токеном:
```powershell
$env:BOT_BACKEND_TOKEN="devtoken123"
curl -H "Authorization: Bearer $env:BOT_BACKEND_TOKEN" http://127.0.0.1:8000/v1/me
```

Доступные эндпоинты:
- `GET /v1/health`
- `GET /v1/me` (Authorization required)
- `POST /v1/chat/ask` (Authorization required)

---

## Notes
- Файл `.env` **не коммитится**
- Для Supabase локально используйте **Session pooler**
- Если `/v1/health` показывает `db: fail` — сначала проверьте `DATABASE_URL`
