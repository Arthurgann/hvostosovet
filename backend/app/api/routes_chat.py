import json
import logging
import os
import traceback
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, Header, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core import config as cfg
from app.core.auth import require_bot_token
from app.core.db import get_connection
from app.services import LlmTimeoutError, ask_llm
from app.services.limits_service import apply_rate_limits_or_return
from app.services.pet_profile_service import (
    build_pet_dict_from_row,
    deep_merge_dict,
    get_active_pet,
    normalize_health_block,
    normalize_pet_dict,
    resolve_effective_pet_profile,
    upsert_active_pet,
)
from app.services.request_dedup import (
    dedup_attach_user,
    dedup_begin_or_return,
    dedup_mark_done,
    dedup_mark_failed,
    validate_x_request_id,
)
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




@router.post("/chat/ask", dependencies=[Depends(require_bot_token)])
def chat_ask(
    response: Response,
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    payload: ChatAskPayload = Body(...),
):
    validation_response = validate_x_request_id(x_request_id)
    if validation_response:
        return validation_response

    with get_connection() as conn:
        with conn.cursor() as cur:
            dedup_response = dedup_begin_or_return(cur, response, x_request_id)
            if dedup_response is not None:
                return dedup_response

            if not payload.text or not payload.text.strip():
                dedup_mark_failed(cur, x_request_id, "missing_text")
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"error": "missing_text"},
                )

            try:
                attachments = normalize_attachments(payload.attachments)
            except ValueError as exc:
                error_text = str(exc) or "invalid_attachments"
                dedup_mark_failed(cur, x_request_id, error_text)
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
                    dedup_attach_user(cur, x_request_id, user_id)
                    if has_image and user_plan != "pro":
                        dedup_mark_failed(cur, x_request_id, "pro_required")
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
                            dedup_mark_failed(
                                cur, x_request_id, "vision_limit_exceeded"
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
                    limits_result = apply_rate_limits_or_return(
                        cur,
                        user_id,
                        user_plan,
                        now,
                        daily_limit,
                        cooldown_sec_default,
                        window_start,
                        window_end,
                    )
                    if isinstance(limits_result, JSONResponse):
                        try:
                            error_payload = json.loads(limits_result.body.decode("utf-8"))
                            error_text = error_payload.get("error") or "rate_limited"
                        except Exception:
                            error_text = "rate_limited"
                        dedup_mark_failed(cur, x_request_id, error_text)
                        return limits_result
                    limits_remaining_today, limits_reset_at = limits_result

            (
                effective_pet_profile,
                pet_profile_source,
                pet_profile_pet_id,
            ) = resolve_effective_pet_profile(cur, user_plan, user_id, pet_dict)
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
                    dedup_mark_failed(cur, x_request_id, "openrouter_not_configured")
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
                dedup_mark_failed(cur, x_request_id, "llm_timeout")
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
                dedup_mark_failed(cur, x_request_id, error_text)
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
                    dedup_mark_failed(cur, x_request_id, "vision_not_processed")
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
                dedup_mark_done(cur, x_request_id, result)
            except Exception as exc:
                error_text = str(exc).splitlines()[0][:200]
                dedup_mark_failed(cur, x_request_id, error_text)
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
    validation_response = validate_x_request_id(x_request_id)
    if validation_response:
        return validation_response

    with get_connection() as conn:
        with conn.cursor() as cur:
            dedup_response = dedup_begin_or_return(cur, response, x_request_id)
            if dedup_response is not None:
                return dedup_response

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
                    dedup_attach_user(cur, x_request_id, user_id)

            if user_plan != "pro":
                dedup_mark_failed(cur, x_request_id, "pro_required")
                return JSONResponse(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    content={"ok": False, "error": "pro_required"},
                )

            pet_to_save = payload.pet_profile
            if not isinstance(pet_to_save, dict):
                dedup_mark_failed(cur, x_request_id, "invalid_pet_profile")
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
                    dedup_mark_failed(cur, x_request_id, "missing_pet_type")
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
                dedup_mark_failed(cur, x_request_id, "pet_upsert_failed")
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
            dedup_mark_done(cur, x_request_id, result)
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
