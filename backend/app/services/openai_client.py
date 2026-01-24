import json
import logging
import os
import socket
import time
from urllib import request
from urllib.error import HTTPError, URLError

logger = logging.getLogger("uvicorn.error")


class LlmTimeoutError(Exception):
    pass


def call_chat_completions_messages(
    messages: list[dict],
    model: str,
    temperature: float,
    max_tokens: int,
    timeout_sec: int,
    api_key: str,
    base_url: str,
    provider: str = "openai",
    extra_headers: dict | None = None,
) -> str:
    if not api_key:
        raise RuntimeError(f"missing_{provider}_api_key")

    base = (base_url or "").rstrip("/")
    if base.endswith("/chat/completions"):
        url = base
    else:
        url = f"{base}/chat/completions"

    payload = {
        "model": model,
        "messages": messages,
    }

    # GPT-5*: temperature поддерживает только default — не передаем параметр
    if not (provider == "openai" and (model or "").startswith("gpt-5")):
        payload["temperature"] = temperature
    
    # OpenAI GPT-5* требует max_completion_tokens вместо max_tokens
    if provider == "openai" and (model or "").startswith("gpt-5"):
        payload["max_completion_tokens"] = max_tokens
    else:
        payload["max_tokens"] = max_tokens

    has_multimodal = any(
        isinstance(message.get("content"), list) for message in messages
    )
    logger.info(
        "LLM_HTTP provider=%s model=%s url=%s multimodal=%s",
        provider,
        model,
        url,
        has_multimodal,
    )
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = request.Request(
        url,
        data=data,
        method="POST",
        headers=headers,
    )

    t0 = time.perf_counter()
    try:
        with request.urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read().decode("utf-8")
    except HTTPError as exc:
        try:
            err_body = exc.read().decode("utf-8", errors="replace")[:2000]
        except Exception:
            err_body = "<no_body>"
        raise RuntimeError(f"{provider}_http_{exc.code}: {err_body}") from exc
    except URLError as exc:
        if isinstance(exc.reason, socket.timeout):
            raise LlmTimeoutError(f"{provider}_timeout") from exc
        raise RuntimeError(f"{provider}_url_error") from exc
    except socket.timeout as exc:
        raise LlmTimeoutError(f"{provider}_timeout") from exc
    finally:
        dt = time.perf_counter() - t0
        logger.info(
            "LLM_DONE provider=%s model=%s seconds=%.2f timeout=%s",
            provider,
            model,
            dt,
            timeout_sec,
        )
    
    response_json = json.loads(body)
    choices = response_json.get("choices") or []
    if not choices:
        raise RuntimeError(f"{provider}_empty_choices")

    choice0 = choices[0] or {}
    message = choice0.get("message") or {}

    # 1) Обычный текстовый ответ
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()

    # 2) Некоторые модели/режимы могут вернуть refusal отдельным полем
    refusal = message.get("refusal")
    if isinstance(refusal, str) and refusal.strip():
        return refusal.strip()

    # 3) Если модель попыталась вызвать tool/function — контента может не быть
    if message.get("tool_calls") or message.get("function_call"):
        logger.warning(
            "LLM_NON_TEXT_RESPONSE provider=%s model=%s finish_reason=%s message_keys=%s",
            provider,
            model,
            choice0.get("finish_reason"),
            list(message.keys()),
        )
        raise RuntimeError(f"{provider}_non_text_response")

    # 4) Ничего не нашли — залогируем кусок ответа для диагностики
    logger.warning(
        "LLM_EMPTY_CONTENT provider=%s model=%s finish_reason=%s body_prefix=%s",
        provider,
        model,
        choice0.get("finish_reason"),
        body[:500],
    )
    raise RuntimeError(f"{provider}_empty_content")


def call_chat_completions(
    prompt_text: str,
    system_prompt: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout_sec: int,
) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("missing_openai_api_key")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt_text},
    ]
    return call_chat_completions_messages(
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_sec=timeout_sec,
        api_key=api_key,
        base_url="https://api.openai.com/v1/chat/completions",
        provider="openai",
    )
