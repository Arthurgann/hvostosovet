import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from psycopg.types.json import Json

from app.core.config import SESSION_MAX_TURNS, SESSION_TTL_MIN

logger = logging.getLogger("hvostosovet")


def get_active_session(db, user_id) -> Optional[dict]:
    now = datetime.now(timezone.utc)
    db.execute(
        "select id, session_context, expires_at, updated_at "
        "from sessions "
        "where user_id = %s and expires_at > %s "
        "order by updated_at desc "
        "limit 1",
        (user_id, now),
    )
    row = db.fetchone()
    if not row:
        return None
    session_id, session_context, expires_at, updated_at = row
    return {
        "id": session_id,
        "session_context": session_context or {},
        "expires_at": expires_at,
        "updated_at": updated_at,
    }


def build_context_prefix(session_context) -> str:
    if not session_context or not isinstance(session_context, dict):
        return ""
    turns = session_context.get("turns")
    if not turns or not isinstance(turns, list):
        return ""

    blocks = []
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        q = (turn.get("q") or "").strip()
        a = (turn.get("a") or "").strip()
        if not q and not a:
            continue
        lines = []
        if q:
            lines.append(f"Пользователь: {q}")
        if a:
            lines.append(f"Ассистент: {a}")
        if lines:
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def upsert_session_turn(db, user_id, question, answer) -> None:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=SESSION_TTL_MIN)
    q = "" if question is None else str(question)
    a = "" if answer is None else str(answer)
    new_turn = {"q": q, "a": a}

    active_session = get_active_session(db, user_id)
    if active_session:
        session_context = active_session.get("session_context") or {}
        turns = session_context.get("turns") if isinstance(session_context, dict) else []
        if not isinstance(turns, list):
            turns = []
        turns.append(new_turn)
        if SESSION_MAX_TURNS > 0:
            turns = turns[-SESSION_MAX_TURNS:]
        session_context = {"turns": turns}
        logger.info("SESSION_DEBUG session_context=%s", session_context)
        db.execute(
            "update sessions "
            "set session_context = %s, expires_at = %s, updated_at = %s "
            "where id = %s",
            (Json(session_context), expires_at, now, active_session["id"]),
        )
        return

    session_context = {"turns": [new_turn]}
    logger.info("SESSION_DEBUG session_context=%s", session_context)
    db.execute(
        "insert into sessions (id, user_id, session_context, expires_at, updated_at) "
        "values (%s, %s, %s, %s, %s)",
        (uuid.uuid4(), user_id, Json(session_context), expires_at, now),
    )
