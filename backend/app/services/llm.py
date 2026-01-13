import logging
import os

from app.services.openai_client import call_chat_completions_messages

logger = logging.getLogger("uvicorn.error")


def build_messages(
    prompt_text: str,
    system_prompt: str,
    attachments: list[dict] | None = None,
) -> list[dict]:
    messages = [{"role": "system", "content": system_prompt}]
    if attachments:
        content = [{"type": "text", "text": prompt_text}]
        for attachment in attachments:
            mime = attachment.get("mime") or "image/jpeg"
            data = attachment.get("data") or ""
            data_url = f"data:{mime};base64,{data}"
            content.append({"type": "image_url", "image_url": {"url": data_url}})
        messages.append({"role": "user", "content": content})
        return messages
    messages.append({"role": "user", "content": prompt_text})
    return messages


def ask_llm(
    prompt_text: str,
    system_prompt: str,
    attachments: list[dict] | None = None,
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout_sec: int | None = None,
) -> str:
    provider = provider or "openai"
    if provider == "openrouter":
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("missing_openrouter_api_key")
        base_url = os.getenv(
            "OPENROUTER_BASE_URL",
            "https://openrouter.ai/api/v1/chat/completions",
        )
        model = model or os.getenv("OPENROUTER_VISION_MODEL", "openai/gpt-4o-mini")
    else:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("missing_openai_api_key")
        base_url = "https://api.openai.com/v1/chat/completions"
        model = model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    timeout_sec = timeout_sec or int(os.getenv("LLM_TIMEOUT_S", "60"))
    max_tokens = max_tokens or int(os.getenv("MAX_TOKENS", "800"))
    temperature = temperature if temperature is not None else float(os.getenv("TEMPERATURE", "0.7"))

    messages = build_messages(prompt_text, system_prompt, attachments=attachments)
    has_image_part = False
    image_url_prefix = None
    image_url_len = None
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "image_url":
                    image_url = item.get("image_url") or {}
                    url = image_url.get("url")
                    has_image_part = True
                    if isinstance(url, str):
                        image_url_prefix = url[:30]
                        image_url_len = len(url)
                    break
        if has_image_part:
            break
    logger.info(
        "LLM_MESSAGES_IMAGE has_image_part=%s image_url_prefix=%s image_url_len=%s",
        has_image_part,
        image_url_prefix,
        image_url_len,
    )

    return call_chat_completions_messages(
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_sec=timeout_sec,
        api_key=api_key,
        base_url=base_url,
        provider=provider,
    )
