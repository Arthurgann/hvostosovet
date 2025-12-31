# Smoke tests (PowerShell)

$env:BOT_BACKEND_TOKEN="devtoken123"

# GET /v1/health
curl http://127.0.0.1:8000/v1/health

# GET /v1/me (Authorization required)
curl -H "Authorization: Bearer $env:BOT_BACKEND_TOKEN" http://127.0.0.1:8000/v1/me

# POST /v1/chat/ask (Authorization + X-Request-Id)
$reqId = [guid]::NewGuid().ToString()
$bodyObj = @{
  user = @{ telegram_user_id = 999001 }   # всегда новый / не лимитный
  text = "Smoke test question"
}
$body = $bodyObj | ConvertTo-Json -Depth 6

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/v1/chat/ask" `
  -Headers @{
    Authorization  = "Bearer $env:BOT_BACKEND_TOKEN"
    "X-Request-Id" = $reqId
  } `
  -ContentType "application/json" `
  -Body $body