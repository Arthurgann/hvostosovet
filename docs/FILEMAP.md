# FILEMAP

Короткая карта проекта: только ключевые узлы и основные потоки.

## Telegram-bot
- telegram-bot/main.py — входная точка, запуск Pyrogram.
- telegram-bot/config.py — загрузка env, флаги.
- telegram-bot/handlers/start.py — /start и главный вход в UX.
- telegram-bot/handlers/menu.py — навигация по режимам.
- telegram-bot/handlers/question.py — сбор вопроса, фото, вызов backend.
- telegram-bot/flows/pro_flow.py — Pro-анкетирование, post-меню, сохранение профиля.
- telegram-bot/services/backend_client.py — единственная HTTP-точка к backend.
- telegram-bot/services/state.py — локальное состояние диалога.
- telegram-bot/ui/*.py — тексты, лейблы, клавиатуры и меню.

## Backend
- backend/app/main.py — FastAPI app.
- backend/app/api/routes_chat.py — /v1/chat/ask, /v1/pets/active, /v1/pets/active/save.
- backend/app/api/routes_health.py — health эндпоинт.
- backend/app/api/routes_me.py — /v1/me.
- backend/app/core/config.py — конфиги/ENV.
- backend/app/core/auth.py — BOT_BACKEND_TOKEN auth.
- backend/app/core/db.py — подключение к БД.
- backend/app/services/llm.py — сбор сообщений и вызов LLM.
- backend/app/services/openai_client.py — HTTP к провайдерам LLM.
- backend/app/services/prompts.py — system prompts (в т.ч. vision prefix).
- backend/app/services/pet_profile_service.py — pet_profile merge, minimal profile.
- backend/app/services/limits_service.py — планы/лимиты/Pro.
- backend/app/services/sessions.py — session_context, TTL.
- backend/app/services/request_dedup.py — idempotency.
- backend/app/sql/*.sql — миграции (users.plan, pets.profile, vision limits).
- backend/scripts/smoke_min_profile_contract.ps1 — smoke контракта minimal profile.

## Главные потоки
- chat_ask: telegram-bot/handlers/question.py → telegram-bot/services/backend_client.py → backend/app/api/routes_chat.py (/v1/chat/ask) → backend/app/services/pet_profile_service.py → backend/app/services/prompts.py + llm.py + openai_client.py → ответ в бот.
- pets_active_save: telegram-bot/flows/pro_flow.py (save_profile_now) → telegram-bot/services/backend_client.py → backend/app/api/routes_chat.py (/v1/pets/active/save) → backend/app/services/pet_profile_service.py → DB pets.profile.
- pro vision: telegram-bot/handlers/question.py (photo → attachments) → telegram-bot/services/backend_client.py → backend/app/api/routes_chat.py (policy=pro_vision) → backend/app/services/prompts.py + openai_client.py → обработка ошибок в telegram-bot/handlers/question.py.

## Где менять X
- Тексты/кнопки UI: telegram-bot/ui/texts.py, telegram-bot/ui/labels.py, telegram-bot/ui/keyboards.py, telegram-bot/ui/main_menu.py.
- Старт и меню: telegram-bot/handlers/start.py, telegram-bot/handlers/menu.py.
- Отправка вопроса и ответы/ошибки: telegram-bot/handlers/question.py.
- Pro анкета/сохранение профиля: telegram-bot/flows/pro_flow.py, telegram-bot/services/state.py.
- HTTP к backend: telegram-bot/services/backend_client.py.
- Контракт /v1/chat/ask: docs/API.md, backend/app/api/routes_chat.py.
- Промпты/LLM провайдеры: backend/app/services/prompts.py, backend/app/services/llm.py, backend/app/services/openai_client.py.
- Профиль питомца и merge: backend/app/services/pet_profile_service.py, backend/app/sql/004_patch_pets_profile.sql.
- Лимиты/Pro/vision: backend/app/services/limits_service.py, backend/app/api/routes_chat.py.
- Idempotency и дедуп: backend/app/services/request_dedup.py.
- Сессии/контекст: backend/app/services/sessions.py.
- Деплой: docs/DEPLOY_TELEGRAM_BOT.md, docs/DEPLOY_BACKEND.md.
- Smoke и минимальный профиль: docs/DEV_SMOKE.md, backend/scripts/smoke_min_profile_contract.ps1.


> Актуальный статус и зафиксированное поведение см. docs/STATUS.md
