import json
import uuid
from datetime import datetime, timedelta, timezone
import os

from fastapi import APIRouter, Body, Depends, Header, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from psycopg.types.json import Json

from app.core.auth import require_bot_token
from app.core.db import get_connection

router = APIRouter()


class ChatAskUser(BaseModel):
    telegram_user_id: int


class ChatAskPayload(BaseModel):
    user: ChatAskUser
    text: str | None = None


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

            result = {
                "answer_text": "",
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
