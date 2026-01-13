from datetime import timedelta

from fastapi import status
from fastapi.responses import JSONResponse


def apply_rate_limits_or_return(
    cur,
    user_id,
    user_plan,
    now,
    daily_limit,
    cooldown_sec_default,
    window_start,
    window_end,
):
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
                "title": "?? Pro-доступ",
                "text": "С Pro вы можете задавать вопросы без дневных лимитов",
                "cta": "Оформить Pro",
            }
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
                "title": "?? Pro-доступ",
                "text": "С Pro вы можете задавать вопросы без дневных лимитов",
                "cta": "Оформить Pro",
            }
        cur.execute(
            "update rate_limits "
            "set cooldown_until = %s, last_request_at = %s "
            "where user_id = %s",
            (cooldown_until, now, user_id),
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
    limits_remaining_today = -1
    if daily_limit is not None and count is not None:
        limits_remaining_today = max(daily_limit - (count + 1), 0)

    return limits_remaining_today, limits_reset_at
