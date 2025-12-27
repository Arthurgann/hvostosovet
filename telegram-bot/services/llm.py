import asyncio
import openai

import config
from services.prompts import prompts_by_context

_client = openai.OpenAI(api_key=config.OPENAI_API_KEY)

LLM_TIMEOUT_S = 60  # секунды

async def ask_llm(context: str, summary: str) -> str:
    system_prompt = prompts_by_context.get(context, "")

    def _call_openai():
        return _client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": summary},
            ],
            temperature=0.7,
            max_tokens=800,
        )

    try:
        resp = await asyncio.wait_for(
            asyncio.to_thread(_call_openai),
            timeout=LLM_TIMEOUT_S
        )
        return resp.choices[0].message.content

    except asyncio.TimeoutError:
        return "⌛ Я не смог сформировать ответ. Попробуйте ещё раз чуть позже."