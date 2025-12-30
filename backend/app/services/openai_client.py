import json
import os
import socket
from urllib import request
from urllib.error import HTTPError, URLError


class LlmTimeoutError(Exception):
    pass


def call_chat_completions(
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
        try:
            err_body = exc.read().decode("utf-8", errors="replace")[:2000]
        except Exception:
            err_body = "<no_body>"
        raise RuntimeError(f"openai_http_{exc.code}: {err_body}") from exc
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
