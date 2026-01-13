import json
import os
import uuid
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
    pet_profile: dict | None = None,
    attachments: list[dict] | None = None,
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
    if pet_profile is not None:
        payload["pet_profile"] = pet_profile
    if attachments:
        payload["attachments"] = attachments
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


def save_active_pet_profile(telegram_user_id: int, pet_profile: dict) -> dict:
    """
    Calls POST /v1/pets/active/save and returns response dict.
    """
    base_url = os.getenv("BACKEND_BASE_URL", "").strip().rstrip("/")
    token = os.getenv("BOT_BACKEND_TOKEN", "").strip()
    if not base_url or not token:
        print("[BACKEND] missing config for save_active_pet_profile")
        return {"ok": False, "status": 0, "error": "missing_backend_config"}

    payload = {
        "user": {"telegram_user_id": telegram_user_id},
        "pet_profile": pet_profile,
    }
    data = json.dumps(payload).encode("utf-8")
    request_id = str(uuid.uuid4())
    req = request.Request(
        f"{base_url}/v1/pets/active/save",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Request-Id": request_id,
            "Content-Type": "application/json",
        },
    )

    try:
        with request.urlopen(req, timeout=15) as resp:
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
    if isinstance(body, dict):
        error = body.get("error") or body or "unknown_error"
    elif body:
        error = body

    return {
        "ok": False,
        "status": status_code,
        "error": error,
    }


def get_active_pet(telegram_user_id: int) -> dict | str | None:
    """
    Calls GET /v1/pets/active and returns pet dict, status string, or None.
    """
    base_url = os.getenv("BACKEND_BASE_URL", "").strip().rstrip("/")
    token = os.getenv("BOT_BACKEND_TOKEN", "").strip()
    if not base_url or not token:
        print("[BACKEND] missing config for get_active_pet")
        return None

    url = f"{base_url}/v1/pets/active?telegram_user_id={telegram_user_id}"
    req = request.Request(
        url,
        method="GET",
        headers={"Authorization": f"Bearer {token}"},
    )

    try:
        with request.urlopen(req, timeout=10) as resp:
            status_code = resp.getcode()
            raw = resp.read()
    except HTTPError as exc:
        status_code = exc.code
        raw = exc.read()
    except URLError as exc:
        print(f"[BACKEND] get_active_pet unreachable user_id={telegram_user_id} err={exc}")
        return None

    body = {}
    if raw:
        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            print(f"[BACKEND] get_active_pet invalid json user_id={telegram_user_id}")
            return None

    if status_code == 200:
        if isinstance(body, dict) and body.get("ok") is True:
            pet = body.get("pet")
            if pet is not None:
                return pet
            return "no_active_pet"
        return None

    if status_code == 402:
        if isinstance(body, dict) and body.get("error") == "pro_required":
            return "pro_required"
        print(f"[BACKEND] get_active_pet status=402 user_id={telegram_user_id} err={body}")
        return None

    if status_code == 404:
        if isinstance(body, dict) and body.get("error") == "no_active_pet":
            return "no_active_pet"
        print(f"[BACKEND] get_active_pet status=404 user_id={telegram_user_id} err={body}")
        return None

    print(f"[BACKEND] get_active_pet status={status_code} user_id={telegram_user_id} err={body}")
    return None
