# BACKEND_MVP.md — Хвостосовет (Telegram bot → Backend(API) → DB → LLM)

Дата: 2025-12-28  
Версия: 0.1 (проектирование, без реализации)
⚠️ Документ проектирования (2025).
Фактическая реализация может отличаться.
Актуальные контракты: docs/API.md, docs/STATUS.md.

## 1) Цель и границы MVP

### Цель
Спроектировать backend так, чтобы:
- Telegram-бот был “тонким клиентом” (UI + пересылка сообщений),
- вся логика (лимиты, сессии, Pro-память, вызовы LLM, хранение) жила в backend,
- дальше можно было спокойно реализовать backend без больших переделок.

### Что входит в MVP backend
- 7 API эндпоинтов (см. раздел 3)
- Минимальные таблицы БД (см. раздел 5)
- Поддержка планов Free/Pro:
  - Free: временная сессия (TTL), лимиты, upsell-события
  - Pro: питомцы, история (сводки), медиа, удаление данных
- Выбор модели по тарифу:
  - Free → дешёвая модель
  - Pro → модель качественнее
  - Pro Research → отдельный режим по кнопке, 1–2 раза в месяц

### Что НЕ делаем в MVP (чтобы не раздувать)
- Платёжная система/подписки (пока `users.plan = pro` выставляется вручную или простым админ-скриптом позже)
- Сложная авторизация пользователей (OAuth и т.п.)
- Сырые логи всего чата (храним только вопрос/ответ + summary)
- Авто-эвристики “сложного вопроса” (research включается только вручную пользователем)

---

## 2) Компоненты и поток данных

### Компоненты
- `telegram-bot/` — UI, кнопки, отправка запросов на backend
- `backend/` — API + бизнес-логика + LLM вызовы
- DB (Postgres / Supabase / любой Postgres) — хранение state/истории/медиа-метаданных
- LLM провайдер:
  - OpenAI (прямо)
  - OpenRouter (опционально)
  - Выбирается политикой `llm_policies`

### Поток (высокоуровневый)
1) Пользователь пишет боту
2) Бот шлёт `POST /v1/chat/ask` + `request_id`
3) Backend:
   - проверяет user/plan
   - проверяет лимиты (Free/Pro)
   - подтягивает контекст (Free TTL / Pro история)
   - вызывает LLM
   - сохраняет результаты (session / interactions / media refs)
4) Backend возвращает готовый `answer_text` + `upsell` + состояние лимитов
5) Бот показывает ответ пользователю

---

## 3) API (ровно 7 эндпоинтов)

Базовый префикс: `/v1`

### 3.1 `GET /v1/health`
Для мониторинга/деплоя.

**Response 200**
```json
{ "ok": true, "version": "0.1.0" }
```

---

### 3.2 `POST /v1/chat/ask`  (главный)
Вопрос пользователя → ответ + обновление сессии/истории/лимитов.

#### Request
```json
{
  "request_id": "uuid",
  "user": {
    "telegram_user_id": 123,
    "telegram_chat_id": 456,
    "locale": "ru"
  },
  "context": {
    "scenario": "emergency|care|prevention|other",
    "pet_id": "uuid-or-null",
    "mode": "normal|research",
    "free_ttl_hint_sec": 3600
  },
  "message": {
    "text": "У собаки рвота...",
    "reply_to_message_id": 111,
    "client_message_id": "tg:optional"
  },
  "attachments": [
    { "type": "photo|audio", "media_id": "uuid", "mime": "image/jpeg" }
  ]
}
```

#### Response 200
```json
{
  "answer_text": "…",
  "safety_level": "low|medium|high",
  "recommended_actions": ["..."],
  "should_go_to_vet": true,
  "followup_question": "Сколько раз была рвота за последние 2 часа?",
  "session": { "session_id": "uuid", "expires_at": "ISO-8601" },
  "limits": { "remaining_in_window": 2, "cooldown_sec": 20 },
  "upsell": { "show": true, "reason": "after_2nd_answer", "cta": "Открыть Pro" },
  "research": { "used_this_period": 1, "limit": 2, "reset_at": "ISO-8601" }
}
```

#### Ошибки (типовые)
- `401 unauthorized` — неверный BOT_BACKEND_TOKEN
- `429 rate_limited` — превышен лимит или активен cooldown
- `402 plan_required` — попытка `mode=research` или медиа в Free
- `400 bad_request` — пустой текст и нет медиа, некорректный payload

---

### 3.3 `GET /v1/me`
Отдать боту минимальный “профиль” для меню:
- plan
- лимиты
- питомцы (минимально)
- флаги consent

**Response 200**
```json
{
  "plan": "free|pro",
  "limits": { "remaining_in_window": 3, "cooldown_sec": 20, "reset_at": "ISO-8601" },
  "pets": [{ "id": "uuid", "type": "dog", "name": "Ричи" }],
  "consents": { "terms_accepted": true, "data_policy_accepted": true },
  "research": { "available": true, "used_this_period": 0, "limit": 2, "reset_at": "ISO-8601" }
}
```

---

### 3.4 `POST /v1/pets/upsert`  (Pro)
Создать/обновить питомца.

**Request**
```json
{
  "user": { "telegram_user_id": 123 },
  "pet": {
    "id": "uuid-or-null",
    "type": "cat|dog|other",
    "name": "optional",
    "sex": "male|female|unknown",
    "birth_date": "YYYY-MM-DD or null",
    "age_text": "optional",
    "breed": "optional"
  }
}
```

**Response 200**
```json
{ "pet_id": "uuid" }
```

**Response 402** если пользователь Free.

---

### 3.5 `GET /v1/history?pet_id=...&limit=20`  (Pro)
История обращений (сводки).

**Response 200**
```json
{
  "items": [
    { "id":"uuid", "created_at":"ISO", "topic":"Рвота", "summary":"Коротко..." }
  ]
}
```

---

### 3.6 `POST /v1/media/init`  (Pro)
Инициализация загрузки медиа (фото/аудио).  
Механика 2-шага сохраняется для будущего S3/MinIO.

**Request**
```json
{
  "user": { "telegram_user_id": 123 },
  "type":"photo|audio",
  "mime":"image/jpeg",
  "size_bytes": 123456,
  "pet_id": "uuid-or-null"
}
```

**Response 200**
```json
{
  "media_id": "uuid",
  "upload_url": "https://... (presigned or backend upload endpoint later)",
  "expires_at": "ISO-8601"
}
```

**Примечание MVP:** можно временно сделать `upload_url` = null и грузить через Telegram → bot → backend (stream). Но сам API контракт оставляем “init”, чтобы потом не ломать.

---

### 3.7 `POST /v1/data/delete`
Удаление данных пользователем.

**Request**
```json
{
  "user": { "telegram_user_id": 123 },
  "scope": "all|pet",
  "pet_id": "uuid-or-null"
}
```

**Response 200**
```json
{ "deleted": true }
```

---

## 4) Протокол bot ↔ backend

### 4.1 Аутентификация запросов (bot → backend)
MVP: статический секрет для связи сервис-сервис.

- Header: `Authorization: Bearer <BOT_BACKEND_TOKEN>`
- Секрет хранить только в `.env` (не коммитить)

**Требование:** backend доступен только по HTTPS.

Важно (MVP-стандарт безопасности):

- Backend **НЕ должен** принимать HTTP-запросы — только HTTPS (TLS).
- Статический Bearer Token считается безопасным **только при наличии TLS**.
- Рекомендуется:
  - либо полностью закрыть backend от внешнего мира и пускать трафик только из внутренней Docker-сети,
  - либо ограничить вход по firewall allowlist (IP сервера Telegram-бота).
- В логах backend **запрещено логировать** заголовок `Authorization`.

Рекомендация по инфраструктуре:
- либо закрыть backend от внешнего мира и пускать только бота (внутренняя сеть Docker),
- либо оставить наружу, но обязательно HTTPS + firewall allowlist (если возможно).

### 4.2 Идемпотентность
Бот генерирует `request_id` (UUID) на каждый входящий пользовательский запрос.  
Backend сохраняет `request_id` → результат, чтобы:
- повторная доставка апдейта Telegram
- ретраи из-за сети
не списывали лимит дважды и не портили историю.

Реализация на уровне БД: таблица `request_dedup` (см. ниже).

---

## 5) Минимальная БД-схема (MVP)

Ниже минимальный набор таблиц, покрывающий Free + Pro + медиа + research + идемпотентность.

### 5.1 `users`
- `id` uuid pk
- `telegram_user_id` bigint unique not null
- `created_at` timestamptz not null
- `plan` text not null (`free`/`pro`)
- `locale` text null
- `last_seen_at` timestamptz null

**Research квота (MVP прямо в users):**
- `research_used` int not null default 0
- `research_limit` int not null default 2
- `research_reset_at` timestamptz not null  (например, 1-е число месяца 00:00 UTC)

---

### 5.2 `rate_limits`
Счётчик запросов и cooldown.

- `user_id` uuid pk fk(users.id)
- `window_type` text not null (`daily_utc` | future: `rolling_24h`)
 Примечание (MVP):

 - В MVP всегда используется `daily_utc`.
 - Окно лимита фиксировано и обновляется в 00:00 UTC.
 - Тип `rolling_24h` зарезервирован для будущих версий и в MVP не используется.

- `window_start_at` timestamptz not null
- `window_end_at` timestamptz not null  (это и есть reset_at)
- `count` int not null
- `last_request_at` timestamptz not null
- `cooldown_until` timestamptz null

Индексы:
- pk(user_id)
- (window_end_at) — для обслуживания/чисток

---

### 5.3 `sessions`
TTL-контекст для Free (и можно использовать как “последний контекст” для Pro).

- `id` uuid pk
- `user_id` uuid fk(users.id)
- `session_context` jsonb not null
- `expires_at` timestamptz not null
- `updated_at` timestamptz not null

**Рекомендуемая структура `session_context` (пример):**
```json
{
  "scenario": "emergency",
  "pet_snapshot": { "type": "dog", "age_text": "5 лет", "breed": "..." },
  "conversation_summary": "Кратко: рвота 2 раза, вялость…",
  "last_turns": [
    { "role":"user", "text":"..." },
    { "role":"assistant", "text":"..." }
  ],
  "expected_reply_to": {
    "question": "Сколько раз была рвота за 2 часа?",
    "last_bot_message_id": 777
  },
  "marketing_state": {
    "free_answers_count": 2,
    "last_upsell_at": "ISO-8601",
    "seen_flags": ["upsell_after_1"]
  }
}
```

Индексы:
- (user_id)
- (expires_at)

---

### 5.4 `pets` (Pro)
- `id` uuid pk
- `user_id` uuid fk(users.id)
- `type` text not null
- `name` text null
- `sex` text not null
- `birth_date` date null
- `age_text` text null
- `breed` text null
- `created_at` timestamptz not null
- `archived_at` timestamptz null

Индекс: (user_id)

---

### 5.5 `interactions` (Pro)
История обращений. Храним вопрос/ответ + короткую сводку (для будущего контекста).

- `id` uuid pk
- `user_id` uuid fk(users.id)
- `pet_id` uuid fk(pets.id) null
- `scenario` text not null
- `mode` text not null (`normal`|`research`)
- `question_text` text not null
- `answer_text` text not null
- `summary` text not null
- `created_at` timestamptz not null

Индексы:
- (pet_id, created_at desc)
- (user_id, created_at desc)

---

### 5.6 `media_assets` (Pro)
Ссылка на хранение медиа + сроки хранения.

- `id` uuid pk
- `user_id` uuid fk(users.id)
- `pet_id` uuid fk(pets.id) null
- `type` text not null (`photo`|`audio`)
- `storage_url` text not null
- `mime` text not null
- `size_bytes` int not null
- `created_at` timestamptz not null
- `expires_at` timestamptz null
- `deleted_at` timestamptz null

Индексы:
- (user_id, created_at desc)
- (expires_at)

---

### 5.7 `llm_policies`
Гибкая смена провайдера/модели без кода.

- `key` text pk  (`free_default`, `pro_default`, `pro_research`)
- `provider` text not null (`openai`|`openrouter`)
- `model` text not null
- `temperature` numeric not null
- `max_tokens` int not null
- `enabled` bool not null default true
- `updated_at` timestamptz not null

---

### 5.8 `request_dedup`
Идемпотентность (анти-двойной списание лимита/двойное сохранение).

- `request_id` uuid pk
- `user_id` uuid fk(users.id)
- `created_at` timestamptz not null
- `response_json` jsonb not null  (сохранить ответ целиком для повторной выдачи)

Индекс: (user_id, created_at desc)

---

## 6) Логика тарифов и лимитов

### 6.1 Free
- Контекст: только TTL `sessions` (например 60 минут)
- Лимит: по количеству `chat/ask` в окне (например 2–3/сутки)
- Cooldown: 20–30 сек между запросами
- Медиа: запрещено (возвращать `402 plan_required`)
- Research: запрещено (возвращать `402 plan_required`)

### 6.2 Pro
- Контекст: профиль питомца + последние `interactions.summary` (например 5–10) + (опционально) TTL session
- Медиа: разрешено
- Research: отдельный режим `mode=research` по кнопке, ограничен квотой

### 6.3 Pro Research (по кнопке)
- Пользователь сам включает режим (никаких эвристик)
- Backend:
  - проверяет `users.plan == pro`
  - проверяет квоту `research_used < research_limit` и `now < research_reset_at`
  - выбирает политику `llm_policies.key = pro_research`
  - инкрементит `research_used`

---

## 7) Выбор модели и провайдера (routing)

Единственная точка выбора — сервис `select_llm_policy(plan, mode)`:

- Free + normal → `free_default`
- Pro + normal → `pro_default`
- Pro + research → `pro_research`

Политика (`llm_policies`) возвращает:
- provider (openai/openrouter)
- model
- temperature, max_tokens

---

## 8) Upsell/прогрев внутри ответов (без рассылок)

Backend возвращает в response объект:
```json
"upsell": { "show": true, "reason": "...", "cta": "..." }
```

События (пример):
- после 1-го ответа
- после 2-го ответа
- при попытке отправить фото/аудио (free)
- при достижении лимита
- не чаще 1 раза в сутки (`marketing_state.last_upsell_at`)

Хранить минимально внутри `sessions.session_context.marketing_state` (для Free),
а для Pro можно (по желанию) вести отдельные флаги в `users`.

---

## 9) Ошибки и коды ответа (конвенция)

- `200` — успех
- `400` — неверный payload
- `401` — неверный BOT_BACKEND_TOKEN
- `402` — требуется Pro (медиа/research)
- `404` — pet_id не найден или не принадлежит пользователю
- `409` — конфликт (например, повтор request_id с другим payload)
- `429` — лимит или cooldown
- `500` — внутренняя ошибка

---

## 10) Конфигурация (env, без секретов в git)

Backend `.env` (пример ключей):
- `APP_ENV=prod|dev`
- `APP_VERSION=0.1.0`
- `BOT_BACKEND_TOKEN=...`
- `DATABASE_URL=postgres://...`
- `OPENAI_API_KEY=...`
- `OPENROUTER_API_KEY=...` (если используешь)
- `DEFAULT_FREE_TTL_SEC=3600`
- `FREE_DAILY_LIMIT=3`
- `COOLDOWN_SEC=25`
- `PRO_RESEARCH_LIMIT=2`

Примечание:
- ключи провайдеров хранятся только на backend
- бот хранит только `BACKEND_URL` и `BOT_BACKEND_TOKEN`

---

## 11) Мини-диаграмма последовательности

### Free normal
User → Bot → Backend(chat/ask) → DB(sessions/rate_limits) → LLM → DB(update session) → Backend → Bot → User

### Pro research
User нажал “Глубокий разбор” → Bot → Backend(chat/ask mode=research) →
DB(check quota + decrement) → LLM(pro_research) → DB(interactions summary) → ответ

---

## 12) Вопросы, которые остаются на будущее (не блокируют MVP)
- Подписки/оплата/продление Pro
- Админ-панель для установки `users.plan`
- Хранилище медиа (S3/MinIO) и фоновые очистки по `expires_at`
- Web/PWA как резервный канал (тот же backend)

---

## 13) Чеклист готовности дизайна к реализации
- [ ] Определены 7 эндпоинтов
- [ ] Определены 8 таблиц (включая `llm_policies`, `request_dedup`)
- [ ] Зафиксирован режим Research (только по кнопке, квота)
- [ ] Зафиксирован выбор модели по тарифу (без эвристик)
- [ ] Есть идемпотентность `request_id`
- [ ] Есть безопасная связь bot ↔ backend через Bearer token + HTTPS
- [ ] Free имеет TTL сессию для UX, но без долговременной памяти

Конец документа.
