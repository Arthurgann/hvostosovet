import json
import logging
import os
import traceback
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, Header, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from psycopg.types.json import Json

from app.core import config as cfg
from app.core.auth import require_bot_token
from app.core.db import get_connection
from app.services import LlmTimeoutError, ask_llm
from app.services.sessions import (
    DEFAULT_MODE,
    build_context_prefix,
    get_active_session,
    normalize_session_context,
    upsert_session_turn,
)
from app.services.prompts import PROMPTS_BY_MODE

router = APIRouter()
logger = logging.getLogger("uvicorn.error")

VISION_REFUSAL_MARKERS = [
    "не могу видеть изображ",
    "не вижу изображ",
    "не могу просматривать изображ",
    "я не вижу изображение",
    "i can't see the image",
    "i cannot see the image",
    "cannot view images",
    "can't view images",
    "i can't access images",
    "as a text-based model",
    "i'm unable to view images",
]


class ChatAskUser(BaseModel):
    telegram_user_id: int


class ChatAskPayload(BaseModel):
    user: ChatAskUser
    text: str | None = None
    mode: str | None = None
    pet: dict | None = None
    pet_profile: dict | None = None
    attachments: list[dict] | None = None


class SaveActivePetPayload(BaseModel):
    user: ChatAskUser
    pet_profile: dict | None = None


def deep_merge_dict(base: dict | None, patch: dict | None) -> dict:
    """
    Deep-merge словарей: patch имеет приоритет, base сохраняется.
    Для dict -> рекурсивно.
    Для list/str/int/etc -> patch полностью заменяет значение.
    """
    base = base or {}
    patch = patch or {}
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge_dict(out[k], v)
        else:
            out[k] = v
    return out


def _parse_birth_date(value):
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def get_active_pet(cur, user_id):
    cur.execute(
        "select id, user_id, type, name, sex, birth_date, age_text, breed, profile, "
        "created_at, archived_at, updated_at "
        "from pets "
        "where user_id = %s and archived_at is null "
        "order by created_at desc "
        "limit 1",
        (user_id,),
    )
    return cur.fetchone()


def build_pet_dict_from_row(active_pet_row) -> dict:
    """
    Собирает полный pet_dict из колонок pets + jsonb profile.
    Колонки считаем источником правды для базовых полей.
    """
    if not active_pet_row:
        return {}

    # active_pet_row:
    # 0 id, 1 user_id, 2 type, 3 name, 4 sex, 5 birth_date, 6 age_text, 7 breed, 8 profile, ...
    pet_type = active_pet_row[2]
    name = active_pet_row[3]
    sex = active_pet_row[4]
    birth_date = active_pet_row[5]
    age_text = active_pet_row[6]
    breed = active_pet_row[7]
    profile = active_pet_row[8] or {}

    if isinstance(profile, str):
        try:
            profile = json.loads(profile)
        except json.JSONDecodeError:
            profile = {}
    if not isinstance(profile, dict):
        profile = {}

    base = {
        "type": pet_type,
        "name": name,
        "sex": sex,
        "birth_date": birth_date.isoformat() if birth_date else None,
        "age_text": age_text,
        "breed": breed,
    }

    # profile может содержать те же ключи — но базовые поля из колонок важнее
    merged = dict(profile)
    merged.update({k: v for k, v in base.items() if v is not None})

    # sex может быть "unknown" — это тоже валидно
    if "sex" not in merged and sex:
        merged["sex"] = sex

    return merged


_PET_SERVICE_KEYS = {"step", "context", "current_mode", "question"}


def normalize_pet_dict(pet_dict: dict | None) -> dict | None:
    if not isinstance(pet_dict, dict):
        return None
    return {k: v for k, v in pet_dict.items() if k not in _PET_SERVICE_KEYS}


def normalize_attachments(attachments: list[dict] | None) -> list[dict]:
    if attachments is None:
        return []
    if not isinstance(attachments, list):
        raise ValueError("invalid_attachments")
    if len(attachments) > 1:
        raise ValueError("too_many_attachments")
    normalized = []
    for item in attachments:
        if not isinstance(item, dict):
            raise ValueError("invalid_attachment")
        att_type = item.get("type")
        if att_type != "image":
            raise ValueError("unsupported_attachment_type")
        source = item.get("source")
        if source != "inline":
            raise ValueError("unsupported_attachment_source")
        data = item.get("data")
        if not isinstance(data, str) or not data.strip():
            raise ValueError("invalid_attachment_data")
        mime = item.get("mime") or "image/jpeg"
        normalized.append(
            {
                "type": "image",
                "source": "inline",
                "mime": mime,
                "data": data.strip(),
            }
        )
    return normalized


_HEALTH_ALLOWED_TAGS = {"allergy", "gi", "skin_coat", "mobility", "other"}


def _as_clean_text(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        t = v.strip()
        return t if t else None
    t = str(v).strip()
    return t if t else None


def normalize_health_block(pet_dict: dict | None) -> dict | None:
    """
    Канон хранения health в pets.profile:
      health: { notes_by_tag: {allergy, gi, skin_coat, mobility, other} }
    Правила:
    - health.tags НЕ сохраняем (удаляем).
    - health.notes_by_tag должен быть dict[str, str] только по разрешённым ключам.
    - если пришли неизвестные ключи — аккуратно добавляем их в other (как "key: value"),
      чтобы не терять информацию.
    """
    if not isinstance(pet_dict, dict):
        return pet_dict

    health = pet_dict.get("health")
    if health is None:
        return pet_dict

    if isinstance(health, str):
        t = health.strip()
        if t:
            pet_dict["health"] = {"notes_by_tag": {"other": t}}
        else:
            pet_dict.pop("health", None)
        return pet_dict

    if not isinstance(health, dict):
        pet_dict.pop("health", None)
        return pet_dict

    notes = health.get("notes_by_tag")
    if notes is None:
        notes = {}
    if not isinstance(notes, dict):
        notes = {}

    out_notes: dict[str, str] = {}

    for k in _HEALTH_ALLOWED_TAGS:
        v = _as_clean_text(notes.get(k))
        if v:
            out_notes[k] = v

    extra_lines = []
    for k, v in notes.items():
        if k in _HEALTH_ALLOWED_TAGS:
            continue
        vv = _as_clean_text(v)
        if vv:
            extra_lines.append(f"{k}: {vv}")

    if extra_lines:
        prev_other = out_notes.get("other")
        extra_text = "\n".join(extra_lines)
        out_notes["other"] = f"{prev_other}\n{extra_text}".strip() if prev_other else extra_text

    if out_notes:
        pet_dict["health"] = {"notes_by_tag": out_notes}
    else:
        pet_dict.pop("health", None)

    return pet_dict


def is_minimal_pet_profile(pet_dict: dict | None) -> bool:
    if not isinstance(pet_dict, dict) or not pet_dict:
        return True
    keys_without_type = [k for k in pet_dict.keys() if k != "type"]
    return not keys_without_type


def upsert_active_pet(cur, user_id, pet_dict):
    pet_dict = pet_dict or {}
    active_pet = get_active_pet(cur, user_id)
    if active_pet:
        existing_full = build_pet_dict_from_row(active_pet)
        pet_dict = deep_merge_dict(existing_full, pet_dict)

    pet_type = pet_dict.get("type")
    if not pet_type:
        raise ValueError("missing pet.type")
    name = pet_dict.get("name")
    sex = pet_dict.get("sex") or "unknown"
    birth_date = _parse_birth_date(pet_dict.get("birth_date"))
    age_text = pet_dict.get("age_text")
    breed = pet_dict.get("breed")
    profile = Json(pet_dict)

    if active_pet:
        pet_id = active_pet[0]
        cur.execute(
            "update pets "
            "set type = %s, name = %s, sex = %s, birth_date = %s, age_text = %s, "
            "breed = %s, profile = %s, updated_at = now() "
            "where id = %s",
            (
                pet_type,
                name,
                sex,
                birth_date,
                age_text,
                breed,
                profile,
                pet_id,
            ),
        )
        return pet_id

    cur.execute(
        "insert into pets "
        "(user_id, type, name, sex, birth_date, age_text, breed, profile, created_at, updated_at) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s, now(), now()) "
        "returning id",
        (
            user_id,
            pet_type,
            name,
            sex,
            birth_date,
            age_text,
            breed,
            profile,
        ),
    )
    row = cur.fetchone()
    return row[0] if row else None


@router.post("/chat/ask", dependencies=[Depends(require_bot_token)])
def chat_ask(
    response: Response,
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    payload: ChatAskPayload = Body(...),
):
    if not x_request_id:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "missing_x_request_id"},
        )
    try:
        uuid.UUID(x_request_id)
    except ValueError:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "invalid_x_request_id"},
        )

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select status, response_json from request_dedup where request_id = %s",
                (x_request_id,),
            )
            row = cur.fetchone()
            if row:
                status_value, response_json = row
                if status_value == "done":
                    response.headers["X-Dedup-Hit"] = "1"
                    if isinstance(response_json, str):
                        return json.loads(response_json)
                    return response_json or {}
                return JSONResponse(
                    status_code=status.HTTP_409_CONFLICT,
                    content={"error": "request_in_progress"},
                )

            cur.execute(
                "insert into request_dedup (request_id, user_id, status, created_at, response_json) "
                "values (%s, null, 'started', now(), null) on conflict do nothing",
                (x_request_id,),
            )
            cur.execute(
                "select status, response_json from request_dedup where request_id = %s",
                (x_request_id,),
            )
            row = cur.fetchone()
            if row:
                status_value, response_json = row
                if status_value == "done":
                    response.headers["X-Dedup-Hit"] = "1"
                    if isinstance(response_json, str):
                        return json.loads(response_json)
                    return response_json or {}
                if status_value != "started":
                    return JSONResponse(
                        status_code=status.HTTP_409_CONFLICT,
                        content={"error": "request_in_progress"},
                    )

            if not payload.text or not payload.text.strip():
                cur.execute(
                    "update request_dedup "
                    "set status = 'failed', error_text = 'missing_text', finished_at = now() "
                    "where request_id = %s",
                    (x_request_id,),
                )
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"error": "missing_text"},
                )

            try:
                attachments = normalize_attachments(payload.attachments)
            except ValueError as exc:
                error_text = str(exc) or "invalid_attachments"
                cur.execute(
                    "update request_dedup "
                    "set status = 'failed', error_text = %s, finished_at = now() "
                    "where request_id = %s",
                    (error_text, x_request_id),
                )
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"error": error_text},
                )
            has_image = bool(attachments)

            now = datetime.now(timezone.utc)
            daily_limit = int(os.getenv("FREE_DAILY_LIMIT", "3"))
            cooldown_sec_default = int(os.getenv("COOLDOWN_SEC", "25"))
            window_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
            window_end = window_start + timedelta(days=1)
            vision_limit_month = cfg.PRO_VISION_IMAGE_LIMIT_MONTH
            vision_remaining = None
            vision_reset_at_out = None

            telegram_user_id = payload.user.telegram_user_id
            pet_dict = normalize_pet_dict(payload.pet_profile or payload.pet)
            user_id = None
            user_plan = None
            limits_remaining_today = -1
            limits_reset_at = None
            window_end_at = None
            count = None
            vision_images_used = 0
            vision_images_reset_at = None
            if telegram_user_id is not None:
                cur.execute(
                    "select id, plan, vision_images_used, vision_images_reset_at "
                    "from users where telegram_user_id = %s",
                    (telegram_user_id,),
                )
                user_row = cur.fetchone()
                if not user_row:
                    cur.execute(
                        "insert into users "
                        "(telegram_user_id, created_at, plan, locale, last_seen_at, "
                        "research_used, research_limit, research_reset_at) "
                        "values (%s, now(), 'free', null, null, 0, 2, date_trunc('month', now()) + interval '1 month') "
                        "on conflict (telegram_user_id) do nothing",
                        (telegram_user_id,),
                    )
                    cur.execute(
                        "select id, plan, vision_images_used, vision_images_reset_at "
                        "from users where telegram_user_id = %s",
                        (telegram_user_id,),
                    )
                    user_row = cur.fetchone()
                if user_row:
                    user_id = user_row[0]
                    user_plan = user_row[1]
                    vision_images_used = int(user_row[2] or 0)
                    vision_images_reset_at = user_row[3]
                    cur.execute(
                        "update request_dedup set user_id = %s where request_id = %s and user_id is null",
                        (user_id, x_request_id),
                    )
                    if has_image and user_plan != "pro":
                        cur.execute(
                            "update request_dedup "
                            "set status = 'failed', error_text = 'pro_required', finished_at = now() "
                            "where request_id = %s",
                            (x_request_id,),
                        )
                        return JSONResponse(
                            status_code=status.HTTP_402_PAYMENT_REQUIRED,
                            content={"ok": False, "error": "pro_required"},
                        )
                    # Pro vision quota (monthly) — only for image requests
                    if has_image and user_plan == "pro":
                        # 1) reset if needed (DB time)
                        cur.execute(
                            "update users "
                            "set vision_images_used = 0, "
                            "    vision_images_reset_at = date_trunc('month', now()) + interval '1 month' "
                            "where id = %s and vision_images_reset_at <= now() "
                            "returning vision_images_used, vision_images_reset_at",
                            (user_id,),
                        )
                        row_reset = cur.fetchone()
                        if row_reset:
                            vision_images_used = int(row_reset[0] or 0)
                            vision_images_reset_at = row_reset[1]

                        # 2) check limit
                        if int(vision_images_used or 0) >= int(vision_limit_month):
                            cur.execute(
                                "update request_dedup "
                                "set status = 'failed', error_text = 'vision_limit_exceeded', finished_at = now() "
                                "where request_id = %s",
                                (x_request_id,),
                            )
                            vision_remaining = 0
                            vision_reset_at_out = (
                                vision_images_reset_at.isoformat().replace("+00:00", "Z")
                                if vision_images_reset_at
                                else None
                            )

                            return JSONResponse(
                                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                                content={
                                    "ok": False,
                                    "error": "vision_limit_exceeded",
                                    "limits": {
                                        "plan": user_plan or "free",
                                        "remaining_today": limits_remaining_today,
                                        "reset_at": limits_reset_at,
                                        "vision_images_limit_month": int(vision_limit_month),
                                        "vision_images_used": int(vision_images_used or 0),
                                        "vision_images_remaining": 0,
                                        "vision_images_reset_at": vision_reset_at_out,
                                    },
                                },
                            )

                        vision_remaining = int(vision_limit_month) - int(
                            vision_images_used or 0
                        )
                        vision_reset_at_out = (
                            vision_images_reset_at.isoformat().replace("+00:00", "Z")
                            if vision_images_reset_at
                            else None
                        )
                    cur.execute(
                        "select window_start_at, window_end_at, count, cooldown_until "
                        "from rate_limits where user_id = %s",
                        (user_id,),
                    )
                    rl_row = cur.fetchone()
                    if not rl_row:
                        cur.execute(
                            "insert into rate_limits "
                            "(user_id, window_type, window_start_at, window_end_at, count, last_request_at, cooldown_until) "
                            "values (%s, 'daily_utc', %s, %s, 0, %s, null)",
                            (user_id, window_start, window_end, now),
                        )
                        window_start_at = window_start
                        window_end_at = window_end
                        count = 0
                        cooldown_until = None
                    else:
                        window_start_at, window_end_at, count, cooldown_until = rl_row
                        if window_end_at <= now:
                            window_start_at = window_start
                            window_end_at = window_end
                            count = 0
                            cooldown_until = None

                    if cooldown_until and cooldown_until > now:
                        cooldown_left = int((cooldown_until - now).total_seconds())
                        plan_value = user_plan or "free"
                        reset_at_out = (window_end_at or now).isoformat()
                        limits_payload = {
                            "plan": plan_value,
                            "remaining_today": 0,
                            "reset_at": reset_at_out,
                        }
                        if plan_value == "free":
                            limits_payload["upsell"] = {
                                "type": "pro",
                                "title": "💎 Pro-доступ",
                                "text": "С Pro вы можете задавать вопросы без дневных лимитов",
                                "cta": "Оформить Pro",
                            }
                        cur.execute(
                            "update request_dedup "
                            "set status = 'failed', error_text = 'rate_limited', finished_at = now() "
                            "where request_id = %s",
                            (x_request_id,),
                        )
                        return JSONResponse(
                            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            content={
                                "ok": False,
                                "status": status.HTTP_429_TOO_MANY_REQUESTS,
                                "error": "rate_limited",
                                "cooldown_sec": max(cooldown_left, 0),
                                "limits": limits_payload,
                            },
                        )

                    if count >= daily_limit:
                        cooldown_until = now + timedelta(seconds=cooldown_sec_default)
                        plan_value = user_plan or "free"
                        reset_at_out = (window_end_at or now).isoformat()
                        limits_payload = {
                            "plan": plan_value,
                            "remaining_today": 0,
                            "reset_at": reset_at_out,
                        }
                        if plan_value == "free":
                            limits_payload["upsell"] = {
                                "type": "pro",
                                "title": "💎 Pro-доступ",
                                "text": "С Pro вы можете задавать вопросы без дневных лимитов",
                                "cta": "Оформить Pro",
                            }
                        cur.execute(
                            "update rate_limits "
                            "set cooldown_until = %s, last_request_at = %s "
                            "where user_id = %s",
                            (cooldown_until, now, user_id),
                        )
                        cur.execute(
                            "update request_dedup "
                            "set status = 'failed', error_text = 'daily_limit_exceeded', finished_at = now() "
                            "where request_id = %s",
                            (x_request_id,),
                        )
                        return JSONResponse(
                            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            content={
                                "ok": False,
                                "status": status.HTTP_429_TOO_MANY_REQUESTS,
                                "error": "daily_limit_exceeded",
                                "cooldown_sec": cooldown_sec_default,
                                "limits": limits_payload,
                            },
                        )

                    cur.execute(
                        "update rate_limits "
                        "set window_start_at = %s, window_end_at = %s, "
                        "count = %s, last_request_at = %s, cooldown_until = null "
                        "where user_id = %s",
                        (window_start_at, window_end_at, count + 1, now, user_id),
                    )
                    limits_reset_at = window_end_at.isoformat() if window_end_at else None
                    if daily_limit is not None and count is not None:
                        limits_remaining_today = max(daily_limit - (count + 1), 0)

            effective_pet_profile = None
            pet_profile_source = "none"
            pet_profile_pet_id = None
            if not is_minimal_pet_profile(pet_dict):
                effective_pet_profile = pet_dict
                pet_profile_source = "request"
            else:
                if user_plan == "pro" and user_id:
                    active_pet = get_active_pet(cur, user_id)
                    if active_pet:
                        effective_pet_profile = build_pet_dict_from_row(active_pet)
                        pet_profile_source = "db"
                        pet_profile_pet_id = (
                            str(active_pet[0]) if active_pet[0] is not None else None
                        )
                elif effective_pet_profile is None and user_plan == "pro":
                    pet_profile_source = "none"
                if effective_pet_profile is None and user_plan != "pro":
                    effective_pet_profile = pet_dict or None
                    pet_profile_source = "request" if pet_dict else "none"
            if isinstance(effective_pet_profile, str):
                try:
                    effective_pet_profile = json.loads(effective_pet_profile)
                except json.JSONDecodeError:
                    effective_pet_profile = None
                    pet_profile_source = "none"
            has_effective_pet_profile = bool(effective_pet_profile)
            pet_profile_keys = (
                list(effective_pet_profile.keys())
                if isinstance(effective_pet_profile, dict)
                else None
            )
            logger.info(
                "CHAT_PET_PROFILE source=%s has_effective_pet_profile=%s keys=%s",
                pet_profile_source,
                has_effective_pet_profile,
                pet_profile_keys,
            )

            session_prefix = ""
            session_context = None
            active_session_id = None
            active_mode = DEFAULT_MODE
            if user_id:
                active_session = get_active_session(cur, user_id)
                if active_session:
                    active_session_id = active_session.get("id")
                    session_context = normalize_session_context(
                        active_session.get("session_context"), now
                    )
                else:
                    session_context = normalize_session_context({}, now)

                requested_mode = None
                if payload.mode and payload.mode.strip():
                    requested_mode = payload.mode.strip().lower()
                if requested_mode:
                    session_context["active"]["mode"] = requested_mode
                    session_context["active"]["updated_at"] = now.isoformat()
                    active_mode = requested_mode
                else:
                    active_mode = session_context.get("active", {}).get("mode") or DEFAULT_MODE

                session_prefix = build_context_prefix(session_context, active_mode)
            elif payload.mode and payload.mode.strip():
                active_mode = payload.mode.strip().lower()

            original_text = payload.text
            final_user_text = original_text
            if session_prefix:
                final_user_text = f"{session_prefix}\n\nТекущий вопрос: {original_text}"
            if has_effective_pet_profile:
                pet_profile_json = json.dumps(
                    effective_pet_profile, ensure_ascii=False
                )
                final_user_text = (
                    "ПРОФИЛЬ ПИТОМЦА (из анкеты пользователя):\n"
                    f"{pet_profile_json}\n\n{final_user_text}"
                )
            selected_mode = (
                active_mode if active_mode in PROMPTS_BY_MODE else DEFAULT_MODE
            )
            system_prompt = PROMPTS_BY_MODE.get(
                active_mode, PROMPTS_BY_MODE["emergency"]
            )
            logger.info(
                "CHAT_PROMPT active_mode=%s selected_mode=%s",
                active_mode,
                selected_mode,
            )

            policy_name = "free_default"
            policies = {
                "free_default": {
                    "provider": "openai",
                    "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                    "temperature": 0.2,
                    "max_tokens": 400,
                    "timeout_sec": 60,
                },
                "pro_default": {
                    "provider": "openai",
                    "model": os.getenv("OPENAI_MODEL_PRO")
                    or os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                    "temperature": 0.2,
                    "max_tokens": 600,
                    "timeout_sec": 60,
                },
                "pro_vision": {
                    "provider": "openrouter",
                    "model": os.getenv("OPENROUTER_VISION_MODEL", "openai/gpt-4o-mini"),
                    "temperature": 0.2,
                    "max_tokens": 600,
                    "timeout_sec": 90,
                },
                "pro_research": {
                    "provider": "openai",
                    "model": os.getenv("OPENAI_MODEL_RESEARCH", "gpt-4o-mini"),
                    "temperature": 0.1,
                    "max_tokens": 800,
                    "timeout_sec": 90,
                },
            }
            if has_image:
                policy_name = "pro_vision"
            elif user_plan == "pro":
                policy_name = "pro_default"
            llm_params = policies.get(policy_name, {}).copy()
            if has_image:
                llm_params["provider"] = "openrouter"
                llm_params["model"] = os.getenv(
                    "OPENROUTER_VISION_MODEL", "openai/gpt-4o-mini"
                )
            logger.info(
                "CHAT_HAS_IMAGE=%s policy=%s provider=%s",
                "true" if has_image else "false",
                policy_name,
                llm_params.get("provider"),
            )

            provider = llm_params.get("provider")
            model = llm_params.get("model")
            if has_image and provider == "openrouter":
                if not (os.getenv("OPENROUTER_API_KEY") or "").strip():
                    cur.execute(
                        "update request_dedup "
                        "set status = 'failed', error_text = 'openrouter_not_configured', "
                        "finished_at = now() "
                        "where request_id = %s",
                        (x_request_id,),
                    )
                    return JSONResponse(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        content={"error": "openrouter_not_configured"},
                    )

            logger.info(
                "CHAT_POLICY policy=%s provider=%s model=%s has_image=%s",
                policy_name,
                provider,
                model,
                has_image,
            )

            try:
                answer_text = ask_llm(
                    final_user_text,
                    system_prompt,
                    attachments=attachments if has_image else None,
                    provider=provider,
                    model=model,
                    temperature=llm_params.get("temperature"),
                    max_tokens=llm_params.get("max_tokens"),
                    timeout_sec=llm_params.get("timeout_sec"),
                )
            except LlmTimeoutError:
                cur.execute(
                    "update request_dedup "
                    "set status = 'failed', error_text = 'llm_timeout', finished_at = now() "
                    "where request_id = %s",
                    (x_request_id,),
                )
                return JSONResponse(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    content={"error": "llm_timeout"},
                )
            except Exception as e:
                logger.exception(
                    "LLM failed request_id=%s user=%s err=%r",
                    x_request_id,
                    payload.user.telegram_user_id,
                    e,
                )
                traceback.print_exc()
                error_text = str(e)[:200]
                cur.execute(
                    "update request_dedup "
                    "set status = 'failed', error_text = %s, finished_at = now() "
                    "where request_id = %s",
                    (error_text, x_request_id),
                )
                return JSONResponse(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    content={"error": "llm_failed"},
                )

            if has_image and answer_text:
                answer_lower = answer_text.lower()
                refused = any(marker in answer_lower for marker in VISION_REFUSAL_MARKERS)
                if refused:
                    logger.info(
                        "VISION_GUARD refused=True rid=%s excerpt=%s",
                        x_request_id,
                        (answer_text or "")[:250],
                    )
                    cur.execute(
                        "update request_dedup "
                        "set status = 'failed', error_text = 'vision_not_processed', finished_at = now() "
                        "where request_id = %s",
                        (x_request_id,),
                    )
                    limits_payload = {
                        "plan": user_plan or "free",
                        "remaining_today": limits_remaining_today,
                        "reset_at": limits_reset_at,
                        "vision_images_limit_month": int(vision_limit_month)
                        if (has_image and user_plan == "pro")
                        else None,
                        "vision_images_used": int(vision_images_used or 0)
                        if (has_image and user_plan == "pro")
                        else None,
                        "vision_images_remaining": int(vision_remaining)
                        if (has_image and user_plan == "pro" and vision_remaining is not None)
                        else None,
                        "vision_images_reset_at": vision_reset_at_out
                        if (has_image and user_plan == "pro")
                        else None,
                    }
                    return JSONResponse(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        content={
                            "ok": False,
                            "error": "vision_not_processed",
                            "message": "Не удалось проанализировать фото. "
                            "Попробуйте отправить другое фото или повторить запрос.",
                            "limits": limits_payload,
                        },
                    )

            # increment monthly vision usage only after successful LLM response
            if has_image and user_plan == "pro":
                cur.execute(
                    "update users "
                    "set vision_images_used = vision_images_used + 1 "
                    "where id = %s "
                    "returning vision_images_used, vision_images_reset_at",
                    (user_id,),
                )
                row_inc = cur.fetchone()
                if row_inc:
                    vision_images_used = int(row_inc[0] or 0)
                    vision_images_reset_at = row_inc[1]
                    vision_remaining = max(
                        0, int(vision_limit_month) - int(vision_images_used or 0)
                    )
                    vision_reset_at_out = (
                        vision_images_reset_at.isoformat().replace("+00:00", "Z")
                        if vision_images_reset_at
                        else None
                    )

            if user_id:
                try:
                    upsert_session_turn(
                        cur,
                        user_id,
                        payload.text,
                        answer_text,
                        user_plan=user_plan,
                        session_context=session_context,
                        active_session_id=active_session_id,
                    )
                except Exception:
                    logger.exception(
                        "Failed to update session request_id=%s user_id=%s",
                        x_request_id,
                        user_id,
                    )

            result = {
                "answer_text": answer_text,
                "safety_level": "low",
                "recommended_actions": [],
                "should_go_to_vet": False,
                "followup_question": None,
                "session": {"session_id": None, "expires_at": None},
                "limits": {
                    "plan": user_plan or "free",
                    "remaining_today": limits_remaining_today,
                    "reset_at": limits_reset_at,
                    "vision_images_limit_month": int(vision_limit_month)
                    if (has_image and user_plan == "pro")
                    else None,
                    "vision_images_used": int(vision_images_used or 0)
                    if (has_image and user_plan == "pro")
                    else None,
                    "vision_images_remaining": int(vision_remaining)
                    if (has_image and user_plan == "pro")
                    else None,
                    "vision_images_reset_at": vision_reset_at_out
                    if (has_image and user_plan == "pro")
                    else None,
                },
                "upsell": {"show": False, "reason": None, "cta": None},
                "research": {"used_this_period": 0, "limit": 0, "reset_at": None},
                "meta": {
                    "pet_profile_source": pet_profile_source,
                    "pet_profile_pet_id": pet_profile_pet_id,
                    "llm_provider": provider,
                    "llm_model": model,
                    "policy_name": policy_name,
                },
            }

            try:
                cur.execute(
                    "update request_dedup "
                    "set status = 'done', response_json = %s, finished_at = now() "
                    "where request_id = %s",
                    (Json(result), x_request_id),
                )
            except Exception as exc:
                error_text = str(exc).splitlines()[0][:200]
                cur.execute(
                    "update request_dedup "
                    "set status = 'failed', error_text = %s, finished_at = now() "
                    "where request_id = %s",
                    (error_text, x_request_id),
                )
                raise

    return result


@router.post("/pets/upsert", dependencies=[Depends(require_bot_token)])
def pets_upsert():
    return JSONResponse(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        content={"error": "pro_required"},
    )


@router.post("/pets/active/save", dependencies=[Depends(require_bot_token)])
def pets_active_save(
    response: Response,
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    payload: SaveActivePetPayload = Body(...),
):
    if not x_request_id:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "missing_x_request_id"},
        )
    try:
        uuid.UUID(x_request_id)
    except ValueError:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "invalid_x_request_id"},
        )

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select status, response_json from request_dedup where request_id = %s",
                (x_request_id,),
            )
            row = cur.fetchone()
            if row:
                status_value, response_json = row
                if status_value == "done":
                    response.headers["X-Dedup-Hit"] = "1"
                    if isinstance(response_json, str):
                        return json.loads(response_json)
                    return response_json or {}
                return JSONResponse(
                    status_code=status.HTTP_409_CONFLICT,
                    content={"error": "request_in_progress"},
                )

            cur.execute(
                "insert into request_dedup (request_id, user_id, status, created_at, response_json) "
                "values (%s, null, 'started', now(), null) on conflict do nothing",
                (x_request_id,),
            )
            cur.execute(
                "select status, response_json from request_dedup where request_id = %s",
                (x_request_id,),
            )
            row = cur.fetchone()
            if row:
                status_value, response_json = row
                if status_value == "done":
                    response.headers["X-Dedup-Hit"] = "1"
                    if isinstance(response_json, str):
                        return json.loads(response_json)
                    return response_json or {}
                if status_value != "started":
                    return JSONResponse(
                        status_code=status.HTTP_409_CONFLICT,
                        content={"error": "request_in_progress"},
                    )

            telegram_user_id = payload.user.telegram_user_id
            user_id = None
            user_plan = None
            if telegram_user_id is not None:
                cur.execute(
                    "select id, plan from users where telegram_user_id = %s",
                    (telegram_user_id,),
                )
                user_row = cur.fetchone()
                if not user_row:
                    cur.execute(
                        "insert into users "
                        "(telegram_user_id, created_at, plan, locale, last_seen_at, "
                        "research_used, research_limit, research_reset_at) "
                        "values (%s, now(), 'free', null, null, 0, 2, date_trunc('month', now()) + interval '1 month') "
                        "on conflict (telegram_user_id) do nothing",
                        (telegram_user_id,),
                    )
                    cur.execute(
                        "select id, plan from users where telegram_user_id = %s",
                        (telegram_user_id,),
                    )
                    user_row = cur.fetchone()
                if user_row:
                    user_id = user_row[0]
                    user_plan = user_row[1]
                    cur.execute(
                        "update request_dedup set user_id = %s where request_id = %s and user_id is null",
                        (user_id, x_request_id),
                    )

            if user_plan != "pro":
                cur.execute(
                    "update request_dedup "
                    "set status = 'failed', error_text = 'pro_required', finished_at = now() "
                    "where request_id = %s",
                    (x_request_id,),
                )
                return JSONResponse(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    content={"ok": False, "error": "pro_required"},
                )

            pet_to_save = payload.pet_profile
            if not isinstance(pet_to_save, dict):
                cur.execute(
                    "update request_dedup "
                    "set status = 'failed', error_text = 'invalid_pet_profile', finished_at = now() "
                    "where request_id = %s",
                    (x_request_id,),
                )
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"ok": False, "error": "invalid_pet_profile"},
                )

            pet_to_save = normalize_pet_dict(pet_to_save)
            pet_to_save = normalize_health_block(pet_to_save)

            try:
                active_pet = get_active_pet(cur, user_id)
                existing_full = build_pet_dict_from_row(active_pet)
                pet_to_save = deep_merge_dict(existing_full, pet_to_save or {})

                if not pet_to_save.get("type"):
                    cur.execute(
                        "update request_dedup "
                        "set status = 'failed', error_text = 'missing_pet_type', finished_at = now() "
                        "where request_id = %s",
                        (x_request_id,),
                    )
                    return JSONResponse(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        content={"ok": False, "error": "missing_pet_type"},
                    )

                cur.execute("savepoint pet_upsert")
                pet_id = upsert_active_pet(cur, user_id, pet_to_save)
                cur.execute("release savepoint pet_upsert")
            except Exception:
                logger.exception(
                    "Failed to upsert pet profile request_id=%s user_id=%s",
                    x_request_id,
                    user_id,
                )
                try:
                    cur.execute("rollback to savepoint pet_upsert")
                    cur.execute("release savepoint pet_upsert")
                except Exception:
                    pass
                cur.execute(
                    "update request_dedup "
                    "set status = 'failed', error_text = 'pet_upsert_failed', finished_at = now() "
                    "where request_id = %s",
                    (x_request_id,),
                )
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={"ok": False, "error": "pet_upsert_failed"},
                )

            result = {"ok": True, "pet_id": str(pet_id) if pet_id is not None else None}
            logger.info(
                "PETS_ACTIVE_SAVE ok=True user_id=%s pet_id=%s",
                telegram_user_id,
                result.get("pet_id"),
            )
            cur.execute(
                "update request_dedup "
                "set status = 'done', response_json = %s, finished_at = now() "
                "where request_id = %s",
                (Json(result), x_request_id),
            )
            return result


@router.get("/pets/active", dependencies=[Depends(require_bot_token)])
def pets_active(telegram_user_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id, plan from users where telegram_user_id = %s",
                (telegram_user_id,),
            )
            user_row = cur.fetchone()
            if not user_row:
                return {"ok": True, "pet": None}
            user_id = user_row[0]
            user_plan = user_row[1]
            if user_plan != "pro":
                return JSONResponse(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    content={"ok": False, "error": "pro_required"},
                )
            pet_row = get_active_pet(cur, user_id)
            if not pet_row:
                return JSONResponse(
                    status_code=status.HTTP_404_NOT_FOUND,
                    content={"ok": False, "error": "no_active_pet"},
                )
            pet = {
                "id": pet_row[0],
                "type": pet_row[2],
                "name": pet_row[3],
                "sex": pet_row[4],
                "birth_date": pet_row[5],
                "age_text": pet_row[6],
                "breed": pet_row[7],
                "profile": pet_row[8],
                "updated_at": pet_row[11],
            }
            return {"ok": True, "pet": pet}


@router.get("/history", dependencies=[Depends(require_bot_token)])
def history():
    return JSONResponse(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        content={"error": "pro_required"},
    )


@router.post("/media/init", dependencies=[Depends(require_bot_token)])
def media_init():
    return JSONResponse(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        content={"error": "pro_required"},
    )


@router.post("/data/delete", dependencies=[Depends(require_bot_token)])
def data_delete():
    return JSONResponse(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        content={"error": "pro_required"},
    )
