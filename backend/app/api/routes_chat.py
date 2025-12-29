import json
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone
from urllib import request
from urllib.error import HTTPError, URLError

from fastapi import APIRouter, Body, Depends, Header, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from psycopg.types.json import Json

from app.core.auth import require_bot_token
from app.core.db import get_connection

router = APIRouter()


class LlmTimeoutError(Exception):
    pass


class ChatAskUser(BaseModel):
    telegram_user_id: int


class ChatAskPayload(BaseModel):
    user: ChatAskUser
    text: str | None = None


def _call_openai_chat(
    prompt_text: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout_sec: int,
) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("missing_openai_api_key")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a helpful veterinary assistant."},
            {"role": "user", "content": prompt_text},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        with request.urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read().decode("utf-8")
    except HTTPError as exc:
        raise RuntimeError(f"openai_http_{exc.code}") from exc
    except URLError as exc:
        if isinstance(exc.reason, socket.timeout):
            raise LlmTimeoutError("openai_timeout") from exc
        raise RuntimeError("openai_url_error") from exc
    except socket.timeout as exc:
        raise LlmTimeoutError("openai_timeout") from exc

    response_json = json.loads(body)
    choices = response_json.get("choices") or []
    if not choices:
        raise RuntimeError("openai_empty_choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not content:
        raise RuntimeError("openai_empty_content")
    return content.strip()


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
            if telegram_user_id is not None:
                cur.execute(
                    "select id from users where telegram_user_id = %s",
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
                        "select id from users where telegram_user_id = %s",
                        (telegram_user_id,),
                    )
                    user_row = cur.fetchone()
                if user_row:
                    user_id = user_row[0]
                    cur.execute(
                        "update request_dedup set user_id = %s where request_id = %s and user_id is null",
                        (user_id, x_request_id),
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
                        cur.execute(
                            "update request_dedup "
                            "set status = 'failed', error_text = 'rate_limited', finished_at = now() "
                            "where request_id = %s",
                            (x_request_id,),
                        )
                        reset_at_out = window_end_at.isoformat() if window_end_at else None
                        return JSONResponse(
                            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            content={
                                "error": "rate_limited",
                                "cooldown_sec": max(cooldown_left, 0),
                                "reset_at": reset_at_out,
                            },
                        )

                    if count >= daily_limit:
                        cooldown_until = now + timedelta(seconds=cooldown_sec_default)
                        cur.execute(
                            "update rate_limits "
                            "set cooldown_until = %s, last_request_at = %s "
                            "where user_id = %s",
                            (cooldown_until, now, user_id),
                        )
                        cur.execute(
                            "update request_dedup "
                            "set status = 'failed', error_text = 'rate_limited', finished_at = now() "
                            "where request_id = %s",
                            (x_request_id,),
                        )
                        reset_at_out = window_end_at.isoformat() if window_end_at else None
                        return JSONResponse(
                            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            content={
                                "error": "rate_limited",
                                "cooldown_sec": cooldown_sec_default,
                                "reset_at": reset_at_out,
                            },
                        )

                    cur.execute(
                        "update rate_limits "
                        "set window_start_at = %s, window_end_at = %s, "
                        "count = %s, last_request_at = %s, cooldown_until = null "
                        "where user_id = %s",
                        (window_start_at, window_end_at, count + 1, now, user_id),
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
                answer_text = _call_openai_chat(
                    payload.text,
                    model=llm_params["model"],
                    temperature=llm_params["temperature"],
                    max_tokens=llm_params["max_tokens"],
                    timeout_sec=llm_params["timeout_sec"],
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
            except Exception:
                cur.execute(
                    "update request_dedup "
                    "set status = 'failed', error_text = 'llm_failed', finished_at = now() "
                    "where request_id = %s",
                    (x_request_id,),
                )
                return JSONResponse(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    content={"error": "llm_failed"},
                )

            result = {
                "answer_text": answer_text,
                "safety_level": "low",
                "recommended_actions": [],
                "should_go_to_vet": False,
                "followup_question": None,
                "session": {"session_id": None, "expires_at": None},
                "limits": {"remaining_in_window": 0, "cooldown_sec": 0},
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
