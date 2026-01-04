import os

from app.services.openai_client import call_chat_completions


def ask_llm(prompt_text: str, system_prompt: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("missing_openai_api_key")

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    timeout_sec = int(os.getenv("LLM_TIMEOUT_S", "60"))
    max_tokens = int(os.getenv("MAX_TOKENS", "800"))
    temperature = float(os.getenv("TEMPERATURE", "0.7"))

    return call_chat_completions(
        prompt_text=prompt_text,
        system_prompt=system_prompt,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_sec=timeout_sec,
    )
