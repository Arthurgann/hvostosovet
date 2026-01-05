import json
from urllib import request
from urllib.error import HTTPError, URLError


def ask_backend(
    base_url: str,
    token: str,
    telegram_user_id: int,
    text: str,
    mode: str | None,
    request_id: str,
    profile: dict | None = None,
) -> dict:
    if not base_url or not token:
        raise RuntimeError("missing_backend_config")

    base_url = base_url.strip().rstrip("/")
    token = token.strip()

    payload = {"user": {"telegram_user_id": telegram_user_id}, "text": text}
    if mode is not None:
        payload["mode"] = mode
    if profile:
        payload["profile"] = profile
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{base_url}/v1/chat/ask",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Request-Id": request_id,
            "Content-Type": "application/json",
        },
    )

    try:
        with request.urlopen(req, timeout=25) as resp:
            status_code = resp.getcode()
            raw = resp.read()
    except HTTPError as exc:
        status_code = exc.code
        raw = exc.read()
    except URLError as exc:
        return {
            "ok": False,
            "status": 0,
            "error": "backend_unreachable",
            "limits": None,
        }

    body = {}
    if raw:
        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            body = {}

    if status_code == 200:
        return {"ok": True, "data": body}

    error = "unknown_error"
    limits = None
    if isinstance(body, dict):
        limits = body.get("limits")
        error = body.get("error") or body or "unknown_error"
    elif body:
        error = body

    return {
        "ok": False,
        "status": status_code,
        "error": error,
        "limits": limits,
    }
