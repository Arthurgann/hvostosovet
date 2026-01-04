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
) -> dict:
    if not base_url or not token:
        raise RuntimeError("missing_backend_config")

    base_url = base_url.strip().rstrip("/")
    token = token.strip()

    payload = {"user": {"telegram_user_id": telegram_user_id}, "text": text}
    if mode is not None:
        payload["mode"] = mode
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
        raise RuntimeError("backend_unreachable") from exc

    body = {}
    if raw:
        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            body = {}
    return {"status_code": status_code, "body": body}
