import json
import uuid

from fastapi import Response, status
from fastapi.responses import JSONResponse
from psycopg.types.json import Json


def validate_x_request_id(x_request_id: str | None) -> JSONResponse | None:
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
    return None


def dedup_begin_or_return(
    cur, response: Response, x_request_id: str
) -> dict | JSONResponse | None:
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

    return None


def dedup_mark_failed(cur, x_request_id: str, error_text: str) -> None:
    cur.execute(
        "update request_dedup "
        "set status = 'failed', error_text = %s, finished_at = now() "
        "where request_id = %s",
        (error_text, x_request_id),
    )


def dedup_mark_done(cur, x_request_id: str, result: dict) -> None:
    cur.execute(
        "update request_dedup "
        "set status = 'done', response_json = %s, finished_at = now() "
        "where request_id = %s",
        (Json(result), x_request_id),
    )


def dedup_attach_user(cur, x_request_id: str, user_id) -> None:
    cur.execute(
        "update request_dedup set user_id = %s where request_id = %s and user_id is null",
        (user_id, x_request_id),
    )
