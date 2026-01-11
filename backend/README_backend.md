# Backend MVP (Hvostosovet)

Минимальный backend для Telegram-бота:
Telegram-bot → Backend API → DB → LLM

---

## Prod deploy
См. docs/DEPLOY_BACKEND.md (VPS Beget, Docker, Traefik, .env.prod, smoke).

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
SESSION_TTL_MIN=60
SESSION_MAX_TURNS=6
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
- `POST /v1/chat/ask` — основной endpoint для получения ответа от LLM  
  Используется Telegram-ботом (и в будущем web/PWA).
- `GET /v1/pets/active?telegram_user_id=...` — возвращает активного питомца/профиль  (используется ботом в “⭐ Мой питомец”; для Free может возвращать `402 Pro required`).

Требуемые заголовки:
- `Authorization: Bearer <BOT_BACKEND_TOKEN>`
- `X-Request-Id: UUID` (idempotency)
---

## Режимы и session_context (v1)

Backend поддерживает режимы диалога (`mode`), которые влияют **только** на system-prompt LLM:

- `emergency` — экстренные ситуации  
- `care` — уход и содержание  
- `vaccines` — прививки и профилактика  

Режим может быть передан клиентом в `POST /v1/chat/ask` опционально.
Если `mode` не передан — используется текущий `session_context.active.mode`.

Контекст диалога хранится в таблице `sessions` в формате `session_context v1`:

- `active: { mode, updated_at }`
- `turns: [{ t, mode, q, a }, ...]`
- `summary` — заготовка, пока не используется

⚠️ Принято архитектурное решение:  
**контекст диалога единый** — при формировании prompt используются последние `SESSION_MAX_TURNS` пар `q/a` **по всем режимам**, без фильтрации по `mode`.

```
### POST /v1/chat/ask

### POST /v1/chat/ask

Поддержка профиля питомца (effective pet profile):

- `pet_profile` может быть передан в payload — **имеет приоритет** над данными из БД (request > db).
- Backend определяет “минимальный профиль” (`minimal`): пустой профиль или фактически только `{type}` (служебные поля игнорируются).
- **Только для Pro-пользователей:** если `pet_profile` отсутствует или является `minimal`,
  backend автоматически подтягивает активного питомца из БД и использует его для prompt.
- **Для Free-пользователей:** backend **не подтягивает** анкету из БД — используется только то,
  что пришло от клиента.

Отладка:
- В логах backend печатается `CHAT_PET_PROFILE source=request|db|none keys=[...]`.

### POST /v1/chat/ask (Windows PowerShell)
Рекомендуется Invoke-RestMethod (curl.exe часто ломает JSON):


```powershell
$rid = [guid]::NewGuid().ToString()
$headers = @{ Authorization = "Bearer $env:BOT_BACKEND_TOKEN"; "X-Request-Id" = $rid }
$body = @{ user = @{ telegram_user_id = 999002 }; text = "test" } | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/chat/ask" -Headers $headers -ContentType "application/json" -Body $body

---

## Notes
- Файл `.env` **не коммитится**
- Для Supabase локально используйте **Session pooler**
- Если `/v1/health` показывает `db: fail` — сначала проверьте `DATABASE_URL`
- Для `POST /v1/chat/ask` используется idempotency по заголовку `X-Request-Id`
- Таблица `request_dedup` расширена (response_json nullable, status/finished_at/error_text) - изменения применены через Supabase SQL Editor
- Повторный запрос с тем же `X-Request-Id` возвращает сохранённый ответ с заголовком `X-Dedup-Hit: 1`
- Для POST /v1/chat/ask применяются rate limits (daily_utc + cooldown), при превышении возвращается HTTP 429
- При `llm_failed` пишется traceback в logs, а причина сохраняется в `request_dedup.error_text`
- Telegram-бот использует backend `/v1/chat/ask` вместо прямого вызова OpenAI
- LLM слой вынесен в app/services (llm.py + openai_client.py), routes_chat.py только роутер.
- TTL-сессии: память диалога хранится в `sessions.session_context (v1)` и включает `active.mode` и `turns[{t, mode, q, a}]`; TTL и размер хвоста управляются `SESSION_TTL_MIN` и `SESSION_MAX_TURNS`.

## Сохранение профиля питомца (Pro)

- Сохранение выполняется отдельным endpoint: POST /v1/pets/active/save.
- Endpoint не вызывает LLM и не пишет в sessions (это не чат).
- Семантика сохранения: PATCH/merge (частичные обновления не затирают профиль целиком).
- После сохранения профиль используется в POST /v1/chat/ask (Pro может подтягиваться из БД, если пришёл   minimal {type}).

--Free: профиль из БД не подтягивается.
--Pro: при minimal профиле backend может подтянуть активного питомца из БД
