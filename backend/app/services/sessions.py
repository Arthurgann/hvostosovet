import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from psycopg.types.json import Json

from app.core.config import SESSION_MAX_TURNS, SESSION_TTL_MIN

logger = logging.getLogger("hvostosovet")
DEFAULT_MODE = "emergency"


def _iso_now(now: datetime) -> str:
    return now.isoformat()


def normalize_session_context(session_context, now: datetime) -> dict:
    if not isinstance(session_context, dict):
        session_context = {}

    v = session_context.get("v")
    if not isinstance(v, int):
        v = 1

    active = session_context.get("active")
    if not isinstance(active, dict):
        active = {}
    active_mode = active.get("mode")
    if isinstance(active_mode, str) and active_mode.strip():
        active_mode = active_mode.strip().lower()
    else:
        active_mode = DEFAULT_MODE
    updated_at = active.get("updated_at")
    if not isinstance(updated_at, str) or not updated_at:
        updated_at = _iso_now(now)
    active = {"mode": active_mode, "updated_at": updated_at}

    turns = session_context.get("turns")
    if not isinstance(turns, list):
        turns = []
    normalized_turns = []
    now_iso = _iso_now(now)
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        mode = turn.get("mode")
        if isinstance(mode, str) and mode.strip():
            mode = mode.strip().lower()
        else:
            mode = active_mode or DEFAULT_MODE
        t = turn.get("t")
        if not isinstance(t, str) or not t:
            t = now_iso
        normalized_turns.append(
            {
                "t": t,
                "mode": mode,
                "q": turn.get("q"),
                "a": turn.get("a"),
            }
        )

    summary = session_context.get("summary")
    if not isinstance(summary, str):
        summary = ""

    normalized = dict(session_context)
    normalized.update(
        {
            "v": v,
            "active": active,
            "turns": normalized_turns,
            "summary": summary,
        }
    )
    return normalized



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


def build_context_prefix(session_context, active_mode: str | None = None) -> str:
    if not session_context or not isinstance(session_context, dict):
        return ""
    turns = session_context.get("turns") if isinstance(session_context, dict) else None
    if not isinstance(turns, list):
        turns = []
    summary = session_context.get("summary") or ""

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
            lines.append(f"Q: {q}")
        if a:
            lines.append(f"A: {a}")
        if lines:
            blocks.append("\n".join(lines))
    if SESSION_MAX_TURNS > 0 and blocks:
        blocks = blocks[-SESSION_MAX_TURNS:]

    if not blocks and not summary:
        return ""

    parts = []
    if summary:
        parts.append(f"Краткое резюме:\n{summary}")
    if blocks:
        parts.append("Контекст диалога:\n{content}".format(content="\n\n".join(blocks)))
    return "\n\n".join(parts)


def upsert_session_turn(
    db,
    user_id,
    question,
    answer,
    session_context: dict | None = None,
    active_session_id: uuid.UUID | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=SESSION_TTL_MIN)
    q = "" if question is None else str(question)
    a = "" if answer is None else str(answer)
    new_turn = {"t": _iso_now(now), "mode": None, "q": q, "a": a}

    active_session = None
    if active_session_id is None:
        active_session = get_active_session(db, user_id)
        if active_session:
            active_session_id = active_session["id"]
    if active_session_id and session_context is None and active_session:
        session_context = active_session.get("session_context")

    normalized_context = normalize_session_context(session_context, now)
    active_mode = normalized_context.get("active", {}).get("mode") or DEFAULT_MODE
    new_turn["mode"] = active_mode
    turns = normalized_context.get("turns") or []
    if not isinstance(turns, list):
        turns = []
    turns.append(new_turn)
    if SESSION_MAX_TURNS > 0:
        turns = turns[-SESSION_MAX_TURNS:]
    normalized_context["turns"] = turns

    logger.info("SESSION_DEBUG session_context=%s", normalized_context)
    if active_session_id:
        db.execute(
            "update sessions "
            "set session_context = %s, expires_at = %s, updated_at = %s "
            "where id = %s",
            (Json(normalized_context), expires_at, now, active_session_id),
        )
        return

    db.execute(
        "insert into sessions (id, user_id, session_context, expires_at, updated_at) "
        "values (%s, %s, %s, %s, %s)",
        (uuid.uuid4(), user_id, Json(normalized_context), expires_at, now),
    )
