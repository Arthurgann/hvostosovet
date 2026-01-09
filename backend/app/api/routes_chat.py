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


class ChatAskUser(BaseModel):
    telegram_user_id: int


class ChatAskPayload(BaseModel):
    user: ChatAskUser
    text: str | None = None
    mode: str | None = None
    pet: dict | None = None
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
        return

    cur.execute(
        "insert into pets "
        "(user_id, type, name, sex, birth_date, age_text, breed, profile, created_at, updated_at) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s, now(), now())",
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

            now = datetime.now(timezone.utc)
            daily_limit = int(os.getenv("FREE_DAILY_LIMIT", "3"))
            cooldown_sec_default = int(os.getenv("COOLDOWN_SEC", "25"))
            window_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
            window_end = window_start + timedelta(days=1)

            telegram_user_id = payload.user.telegram_user_id
            pet_dict = payload.pet_profile or payload.pet
            pet_dict_for_upsert = pet_dict
            if pet_dict_for_upsert is not None and not pet_dict_for_upsert.get("type"):
                logger.warning(
                    "Skipping pet upsert: missing pet.type request_id=%s user_id=%s",
                    x_request_id,
                    telegram_user_id,
                )
                pet_dict_for_upsert = None
            user_id = None
            user_plan = None
            limits_remaining_today = -1
            limits_reset_at = None
            window_end_at = None
            count = None
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
                    if user_plan == "pro" and pet_dict_for_upsert is not None:
                        savepoint_created = False
                        try:
                            cur.execute("savepoint pet_upsert")
                            savepoint_created = True
                            upsert_active_pet(cur, user_id, pet_dict_for_upsert)
                        except Exception:
                            logger.exception(
                                "Failed to upsert pet profile request_id=%s user_id=%s",
                                x_request_id,
                                user_id,
                            )
                            if savepoint_created:
                                try:
                                    cur.execute("rollback to savepoint pet_upsert")
                                    cur.execute("release savepoint pet_upsert")
                                except Exception:
                                    logger.exception(
                                        "Failed to rollback pet upsert savepoint request_id=%s user_id=%s",
                                        x_request_id,
                                        user_id,
                                    )
                        else:
                            if savepoint_created:
                                cur.execute("release savepoint pet_upsert")

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

            # --- SPECIAL: техническое сохранение профиля, без LLM и без sessions ---
            if payload.text.strip() == "__save_profile__":
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

                pet_to_save = payload.pet_profile or payload.pet
                if not isinstance(pet_to_save, dict):
                    pet_to_save = None

                pet_type = pet_to_save.get("type") if pet_to_save else None
                if not pet_type:
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

                try:
                    # --- MERGE: восстанавливаем полную базу из pets (колонки + profile) и накладываем patch ---
                    active_pet = get_active_pet(cur, user_id)
                    existing_full = build_pet_dict_from_row(active_pet)

                    if pet_to_save is None or not isinstance(pet_to_save, dict):
                        pet_to_save = {}

                    # deep-merge: patch поверх полного existing
                    pet_to_save = deep_merge_dict(existing_full, pet_to_save)

                    # гарантируем type
                    if not pet_to_save.get("type"):
                        pet_to_save["type"] = pet_type
                    # --- END MERGE ---

                    cur.execute("savepoint pet_upsert")
                    upsert_active_pet(cur, user_id, pet_to_save)
                    cur.execute("release savepoint pet_upsert")
                except Exception:
                    logger.exception(
                        "Failed to upsert pet profile in __save_profile__ request_id=%s user_id=%s",
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

                result = {
                    "ok": True,
                    "saved": True,
                    "limits": {
                        "plan": user_plan or "free",
                        "remaining_today": limits_remaining_today,
                        "reset_at": limits_reset_at,
                    },
                }
                cur.execute(
                    "update request_dedup "
                    "set status = 'done', response_json = %s, finished_at = now() "
                    "where request_id = %s",
                    (Json(result), x_request_id),
                )
                return result
            # --- END SPECIAL ---
            effective_pet_profile = pet_dict or None
            if not effective_pet_profile and user_id:
                active_pet = get_active_pet(cur, user_id)
                if active_pet:
                    effective_pet_profile = active_pet[8] or None
            if isinstance(effective_pet_profile, str):
                try:
                    effective_pet_profile = json.loads(effective_pet_profile)
                except json.JSONDecodeError:
                    effective_pet_profile = None
            has_effective_pet_profile = bool(effective_pet_profile)
            pet_profile_keys = (
                list(effective_pet_profile.keys())
                if isinstance(effective_pet_profile, dict)
                else None
            )
            logger.info(
                "CHAT_PET_PROFILE has_effective_pet_profile=%s keys=%s",
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

            policy = "free_default"
            policies = {
                "free_default": {
                    "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                    "temperature": 0.2,
                    "max_tokens": 400,
                    "timeout_sec": 60,
                },
                "pro_default": {
                    "model": os.getenv("OPENAI_MODEL_PRO", "gpt-4o-mini"),
                    "temperature": 0.2,
                    "max_tokens": 600,
                    "timeout_sec": 60,
                },
                "pro_research": {
                    "model": os.getenv("OPENAI_MODEL_RESEARCH", "gpt-4o-mini"),
                    "temperature": 0.1,
                    "max_tokens": 800,
                    "timeout_sec": 90,
                },
            }
            llm_params = policies[policy]

            try:
                answer_text = ask_llm(final_user_text, system_prompt)
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

            if user_id:
                try:
                    upsert_session_turn(
                        cur,
                        user_id,
                        payload.text,
                        answer_text,
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
                },
                "upsell": {"show": False, "reason": None, "cta": None},
                "research": {"used_this_period": 0, "limit": 0, "reset_at": None},
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


@router.get("/pets/active", dependencies=[Depends(require_bot_token)])
def pets_active(telegram_user_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id from users where telegram_user_id = %s",
                (telegram_user_id,),
            )
            user_row = cur.fetchone()
            if not user_row:
                return {"ok": True, "pet": None}
            user_id = user_row[0]
            pet_row = get_active_pet(cur, user_id)
            if not pet_row:
                return {"ok": True, "pet": None}
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
