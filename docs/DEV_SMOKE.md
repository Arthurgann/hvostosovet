# DEV SMOKE — быстрая локальная проверка backend API

Этот файл используется перед:
- локальным тестированием
- деплоем на сервер
- после изменений в коде backend

Цель: убедиться, что API живое и не сломано.

---

## 1) Запуск backend локально (Windows)

Открой PowerShell / Terminal.

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload

Ожидаемый результат:

- сервер стартует без ошибок
- в логах есть Uvicorn running on http://127.0.0.1:8000

## 2) Проверка health-check

curl http://127.0.0.1:8000/v1/health

Ожидаемо:

{
  "ok": true,
  "version": "...",
  "db": "ok"
}

## 3) Проверка авторизации (/v1/me)

$env:BOT_BACKEND_TOKEN="devtoken123"
curl -H "Authorization: Bearer $env:BOT_BACKEND_TOKEN" http://127.0.0.1:8000/v1/me

Ожидаемо:

- HTTP 200
- информация о сервисе / токене

## 4) Проверка основного endpoint (/v1/chat/ask)

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

Ожидаемо:

- HTTP 200
- ответ от backend (LLM или stub)
- без ошибок в логах

## 5) Если что-то не работает

Проверь:

- .env в backend (DATABASE_URL, BOT_BACKEND_TOKEN)
- что токен совпадает с тем, что ждёт backend
- что Supabase доступен
- что запрос содержит X-Request-Id

Статус проверки

 health OK

 /v1/me OK

 /v1/chat/ask OK

Если все пункты выполнены — backend готов.