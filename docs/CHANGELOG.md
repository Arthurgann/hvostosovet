## Запуск backend (Windows)
```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload

## Запуск Telegram-бота (Windows)
```powershell
cd telegram-bot
.\.venv\Scripts\Activate.ps1
python main.py


## 2026-01-03
- DB: Added CHECK users.plan IN ('free','pro')
- DB: sessions.user_id FK -> users.id ON DELETE CASCADE
How to verify: query pg_constraint for users/sessions
- “Supabase UI режет jsonb превью; проверять q через jsonb_path_exists / #>>.”

