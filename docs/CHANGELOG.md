## 2026-01-03
- DB: Added CHECK users.plan IN ('free','pro')
- DB: sessions.user_id FK -> users.id ON DELETE CASCADE
How to verify: query pg_constraint for users/sessions
