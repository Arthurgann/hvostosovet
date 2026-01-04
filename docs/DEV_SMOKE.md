# DEV SMOKE — быстрая локальная проверка backend API

Этот файл используется перед:
- локальным тестированием
- деплоем на сервер
- после изменений в коде backend

Цель: убедиться, что API живое и не сломано, а режимы и сессии работают корректно.

Контракт API: см. docs/API.md

---

## 1) Запуск backend локально (Windows)

Открой PowerShell / Terminal.

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

Ожидаемый результат:
- сервер стартует без ошибок
- в логах есть `Uvicorn running on http://127.0.0.1:8000`

---

## 2) Проверка health-check

```powershell
curl http://127.0.0.1:8000/v1/health
```

Ожидаемо:
```json
{
  "ok": true,
  "version": "...",
  "db": "ok"
}
```

---

## 3) Проверка авторизации (/v1/me)

```powershell
$env:BOT_BACKEND_TOKEN="devtoken123"
curl -H "Authorization: Bearer $env:BOT_BACKEND_TOKEN" http://127.0.0.1:8000/v1/me
```

Ожидаемо:
- HTTP 200
- информация о сервисе / токене

---

## 4) Проверка основного endpoint (/v1/chat/ask)

```powershell
$rid = [guid]::NewGuid().ToString()
$headers = @{
  Authorization = "Bearer $env:BOT_BACKEND_TOKEN"
  "X-Request-Id" = $rid
}
$body = @{
  user = @{ telegram_user_id = 123456 }
  text = "Тестовый вопрос"
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/v1/chat/ask" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

Ожидаемо:
- HTTP 200
- ответ от backend
- без ошибок в логах

---

## 4.1) Проверка режима (mode) и session_context

### Шаг 1 — смена режима на `care`

```powershell
$rid = [guid]::NewGuid().ToString()
$headers = @{ Authorization = "Bearer $env:BOT_BACKEND_TOKEN"; "X-Request-Id" = $rid }
$body = @{
  user = @{ telegram_user_id = 123456 }
  text = "Тест: режим care"
  mode = "care"
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/chat/ask" -Headers $headers -ContentType "application/json" -Body $body
```

Ожидаемо:
- HTTP 200
- в логах backend: `active_mode=care`

### Шаг 2 — запрос без mode (режим должен сохраниться)

```powershell
$rid = [guid]::NewGuid().ToString()
$headers = @{ Authorization = "Bearer $env:BOT_BACKEND_TOKEN"; "X-Request-Id" = $rid }
$body = @{
  user = @{ telegram_user_id = 123456 }
  text = "Тест: без mode, должен остаться care"
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/chat/ask" -Headers $headers -ContentType "application/json" -Body $body
```

Ожидаемо:
- HTTP 200
- режим не меняется
- используется существующая сессия (TTL продлевается)

---

## 5) Если что-то не работает

Проверь:
- `.env` в backend (DATABASE_URL, BOT_BACKEND_TOKEN)
- что токен совпадает с тем, что ждёт backend
- что Supabase доступен
- что каждый POST содержит `X-Request-Id`
- логи backend (`CHAT_PROMPT`, `session_context`)

---

## Статус проверки

- health OK
- /v1/me OK
- /v1/chat/ask OK
- mode / session_context OK

Если все пункты выполнены — backend готов.
