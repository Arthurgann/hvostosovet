# Backend MVP

## Requirements
- Python 3.11+
- Docker (for Postgres)

## Setup
1) Copy `.env.example` to `.env` and adjust values.
2) Start Postgres:
   ```bash
   docker compose -f backend/docker-compose.yml up -d
   ```
3) Run the API:
   ```bash
   uvicorn backend.app.main:app --reload
   ```

## Smoke
- `GET /v1/health`
- `GET /v1/me` (requires `Authorization: Bearer <BOT_BACKEND_TOKEN>`)
- `POST /v1/chat/ask` (requires `Authorization: Bearer <BOT_BACKEND_TOKEN>`)
