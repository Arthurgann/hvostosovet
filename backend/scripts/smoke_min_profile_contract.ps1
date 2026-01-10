$ErrorActionPreference = "Stop"

if (-not $env:BOT_BACKEND_TOKEN) {
  Write-Error "BOT_BACKEND_TOKEN is not set"
  exit 1
}

$TG_FREE = $env:TG_FREE
$TG_PRO = $env:TG_PRO

if (-not $TG_FREE -or -not $TG_PRO) {
  Write-Error "TG_FREE and TG_PRO must be set"
  exit 1
}

function Invoke-Ask {
  param(
    [Parameter(Mandatory = $true)][int64]$TelegramUserId,
    [Parameter(Mandatory = $true)][hashtable]$PetProfile,
    [Parameter(Mandatory = $true)][string]$Label
  )

  $rid = [guid]::NewGuid().ToString()
  $headers = @{
    Authorization = "Bearer $env:BOT_BACKEND_TOKEN"
    "X-Request-Id" = $rid
  }
  $body = @{
    user = @{ telegram_user_id = $TelegramUserId }
    text = "Smoke: $Label"
    pet_profile = $PetProfile
  } | ConvertTo-Json -Depth 8

  return Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8000/v1/chat/ask" `
    -Headers $headers `
    -ContentType "application/json" `
    -Body $body
}

function Assert-Source {
  param(
    [Parameter(Mandatory = $true)]$Response,
    [Parameter(Mandatory = $true)][string]$Expected,
    [Parameter(Mandatory = $true)][string]$Label
  )

  if ($null -eq $Response.meta) {
    Write-Error "${Label}: missing meta in response"
    exit 1
  }

  $actual = $Response.meta.pet_profile_source
  if ($actual -ne $Expected) {
    Write-Error "${Label}: expected meta.pet_profile_source='$Expected', got '$actual'"
    exit 1
  }
}

$resp = Invoke-Ask -TelegramUserId $TG_PRO -PetProfile @{ type = "dog" } -Label "Pro + minimal {type}"
Assert-Source -Response $resp -Expected "db" -Label "Pro + minimal {type}"

$resp = Invoke-Ask -TelegramUserId $TG_FREE -PetProfile @{ type = "dog" } -Label "Free + minimal {type}"
Assert-Source -Response $resp -Expected "request" -Label "Free + minimal {type}"

$resp = Invoke-Ask `
  -TelegramUserId $TG_PRO `
  -PetProfile @{ type = "dog"; name = "SmokeName"; health = @{ status = "ok" } } `
  -Label "Pro + rich payload"
Assert-Source -Response $resp -Expected "request" -Label "Pro + rich payload"

Write-Host "OK: minimal profile contract"
exit 0
