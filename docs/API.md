# API (MVP) — Hvostosovet

## POST /v1/chat/ask

Единая точка общения клиентов (Telegram/Web/PWA) с backend.

### Headers
- `Authorization: Bearer <BOT_BACKEND_TOKEN>` (обязательно)
- `X-Request-Id: <uuid>` (обязательно)

### Request JSON
```json
{
  "user": { "telegram_user_id": 123456789 },
  "text": "У собаки понос второй день, что делать?",
  "mode": "emergency"
}
```

`mode` опционален. Допустимые значения:
- `emergency`
- `care`
- `vaccines`

Если `mode` не передан — backend использует текущий `session_context.active.mode`.

### Response JSON (пример)
```json
{
  "answer": "…текст ответа…",
  "session": {
    "active": { "mode": "emergency", "updated_at": "2026-01-04T12:34:56Z" },
    "expires_at": "2026-01-04T13:34:56Z",
    "turns_count": 3
  },
  "limits": {
    "plan": "free",
    "remaining_today": 7,
    "reset_at": "2026-01-05T00:00:00Z"
  }
}
```

Примечание: поля `expires_at` и `turns_count` могут отличаться от фактической реализации. Главное - сохранить идею: backend возвращает ответ + метаданные сессии.
`limits` возвращается всегда. Если `remaining_today` неизвестен, возвращать `-1` (предпочтительно всегда считать).

Короткий пример ответа с `limits`:
```json
{ "limits": { "plan": "pro", "remaining_today": -1, "reset_at": "2026-01-05T00:00:00Z" } }
```

### Errors
- `401 unauthorized` — неверный/отсутствует токен
- `400 missing_x_request_id` — отсутствует заголовок `X-Request-Id`
- `429 rate_limited` — превышены лимиты
- `500 internal_error` — ошибка backend/LLM

### Smoke-проверка (логика режима)
1) Запрос с `mode=care` → `active.mode` станет `care`
2) Второй запрос **без** `mode` → `active.mode` останется `care`
3) Запрос с `mode=vaccines` → `active.mode` станет `vaccines`
