import json
import uuid

from fastapi import APIRouter, Depends, Header, Response, status
from fastapi.responses import JSONResponse
from psycopg.types.json import Json

from app.core.auth import require_bot_token
from app.core.db import get_connection

router = APIRouter()


@router.post("/chat/ask", dependencies=[Depends(require_bot_token)])
def chat_ask(
    response: Response,
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
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
