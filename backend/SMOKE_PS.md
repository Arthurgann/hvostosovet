# Smoke tests (PowerShell)

$env:BOT_BACKEND_TOKEN="devtoken123"

# GET /v1/health
curl http://127.0.0.1:8000/v1/health

# GET /v1/me (Authorization required)
curl -H "Authorization: Bearer $env:BOT_BACKEND_TOKEN" http://127.0.0.1:8000/v1/me

# POST /v1/chat/ask (Authorization + X-Request-Id)
$reqId = [guid]::NewGuid().ToString()
$body = @{ user = @{ telegram_user_id = 123456 }; text = "Test smoke question" } | ConvertTo-Json -Depth 4
curl -Method Post -H "Authorization: Bearer $env:BOT_BACKEND_TOKEN" -H "X-Request-Id: $reqId" -H "Content-Type: application/json" -Body $body http://127.0.0.1:8000/v1/chat/ask