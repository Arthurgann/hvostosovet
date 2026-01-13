# Smoke tests (PowerShell)

$env:BOT_BACKEND_TOKEN="YOUR_DEV_TOKEN"

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

# TTL sessions (set SESSION_TTL_MIN=1 for quick expiry checks)
$reqIdA = [guid]::NewGuid().ToString()
$bodyA = @{
  user = @{ telegram_user_id = 999002 }
  text = "У собаки болит лапа, что можно сделать дома?"
} | ConvertTo-Json -Depth 6
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/v1/chat/ask" `
  -Headers @{
    Authorization  = "Bearer $env:BOT_BACKEND_TOKEN"
    "X-Request-Id" = $reqIdA
  } `
  -ContentType "application/json" `
  -Body $bodyA

$reqIdB = [guid]::NewGuid().ToString()
$bodyB = @{
  user = @{ telegram_user_id = 999002 }
  text = "А если собака еще хромает, стоит ли срочно в клинику?"
} | ConvertTo-Json -Depth 6
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/v1/chat/ask" `
  -Headers @{
    Authorization  = "Bearer $env:BOT_BACKEND_TOKEN"
    "X-Request-Id" = $reqIdB
  } `
  -ContentType "application/json" `
  -Body $bodyB
