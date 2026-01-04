from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery
from pyrogram.enums import ChatAction
import asyncio
import json
import os
import uuid
from urllib import request
from urllib.error import HTTPError, URLError
import config
from services.state import (
    get_profile,
    start_profile,
    set_basic_info,
    set_question,
    set_waiting_question,
)


def _post_chat_ask(
    telegram_user_id: int,
    text: str,
    timeout_sec: int = 25,
    mode: str | None = None,
) -> tuple[int, dict]:
    base_url = os.getenv("BACKEND_BASE_URL", "").strip().rstrip("/")
    token = os.getenv("BOT_BACKEND_TOKEN", "").strip()
    if not base_url or not token:
        raise RuntimeError("missing_backend_config")

    payload = {"user": {"telegram_user_id": telegram_user_id}, "text": text}
    if mode:
        payload["mode"] = mode
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{base_url}/v1/chat/ask",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Request-Id": str(uuid.uuid4()),
            "Content-Type": "application/json",
        },
    )

    try:
        with request.urlopen(req, timeout=timeout_sec) as resp:
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
    return status_code, body


def setup_question_handlers(app: Client):
    @app.on_callback_query(filters.regex("^(dog|cat|other)_(emergency|care|health)$"))
    async def start_unified_form(client_tg: Client, callback_query: CallbackQuery):
        await callback_query.answer()
        user_id = callback_query.from_user.id
        pet_type, context = callback_query.data.split("_")

        mode_map = {"care": "care", "emergency": "emergency", "health": "vaccines"}
        current_mode = mode_map.get(context)
        start_profile(user_id, pet_type, context, current_mode=current_mode)

        if pet_type == "dog":
            example = "Такса, 3 года, девочка, живёт в квартире, гуляет 2 раза в день, склонна к полноте."
        elif pet_type == "cat":
            example = "Британская короткошёрстная, 4 года, кот, живёт в квартире, не выходит на улицу, стерилизован."
        else:
            example = "Хорёк, 1.5 года, самец, живёт в вольере, активный, питается сухим кормом."

        # Вступление
        if context == "care":
            intro = (
                "🐾 **Правильное питание и регулярный уход — основа здоровья вашего питомца!**\n\n"
                "Я помогу вам подобрать рекомендации по кормлению, гигиене, уходу за шерстью, когтями и другим — "
                "с учётом особенностей вашего любимца.\n\n"
            )
        elif context == "health":
            intro = (
                "🛡 **Регулярные прививки, профилактика и базовая гигиена — важная часть заботы о здоровье питомца.**\n\n"
                "Я помогу вам разобраться, какие прививки нужны, как ухаживать за зубами и ушами, "
                "как предотвратить паразитов, и многое другое.\n\n"
            )
        else:
            intro = ""

        await callback_query.message.edit_text(
            intro +
            "🗓 Пожалуйста, укажите информацию о питомце: порода, возраст, пол и особенности образа жизни\n\n"
            f"Пример: {example}",
            disable_web_page_preview=True
        )

    @app.on_message(filters.private & filters.text & ~filters.regex(r"^/"))
    async def collect_unified_info(client_tg: Client, message: Message):
        user_id = message.from_user.id
        profile = get_profile(user_id)

        if not profile:
            start_profile(user_id)
            profile = get_profile(user_id)

        if config.BOT_DEBUG:
            print(f"[Q-HANDLER] user_id={user_id} has_profile={bool(profile)} step={profile.get('step') if profile else None}")

        if not profile:
            return

        if profile["step"] == "done":
            await message.reply("⌛ Я уже готовлю ответ. Пожалуйста, подождите…")
            return

        step = profile.get("step")

        if step == "basic_info":
            set_basic_info(user_id, message.text)
            profile = get_profile(user_id)

            if profile["context"] == "care":
                await message.reply(
                    "📝 Напишите свой вопрос или опишите, что вас интересует:\n\n"
                    "Пример: подбор корма, режим кормления, уход за шерстью, когтями, ушами, гигиена, "
                    "выбор мисок, лежанок и других аксессуаров."
                )

            elif profile["context"] == "health":
                await message.reply(
                    "📝 Напишите, о чём вы хотите узнать:\n\n"
                    "Пример: график прививок, профилактика глистов, уход за зубами, обработка от блох и клещей, "
                    "стрижка когтей, чистка ушей, обработка глаз."
                )

            else:
                await message.reply(
                    "💬 Опишите, что именно беспокоит Вашего питомца, или задайте вопрос:"
                )

        elif step == "question":
            set_question(user_id, message.text)
            profile = get_profile(user_id)

            summary = f"""📋 Анкета:
Тип питомца: {profile['type']}
Описание: {profile['basic_info']}
Вопрос: {profile['question']}"""

            await message.reply("⌛ Ваш запрос обрабатывается нейросетью. Пожалуйста, подождите...")

            await client_tg.send_chat_action(message.chat.id, ChatAction.TYPING)

            try:
                if config.BOT_DEBUG:
                    print(f"[HTTP] POST /v1/chat/ask user_id={user_id} bytes={len(summary.encode('utf-8'))}")
                current_mode = profile.get("current_mode") if profile else None
                status_code, body = await asyncio.to_thread(
                    _post_chat_ask, user_id, summary, 25, current_mode
                )
                body_keys = ",".join(sorted(body.keys())) if isinstance(body, dict) else ""
                if config.BOT_DEBUG:
                    print(f"[HTTP] status={status_code} user_id={user_id} body_keys={body_keys}")
                if status_code == 200:
                    answer = (body.get("answer_text") or "").strip()
                    if not answer:
                        raise RuntimeError("empty_answer")
                    await message.reply(f"🧠 Ответ:\n\n{answer}")
                elif status_code == 429:
                    cooldown_sec = body.get("cooldown_sec")
                    if isinstance(cooldown_sec, int):
                        await message.reply(f"⚠️ Лимит, подождите {cooldown_sec} сек.")
                    else:
                        await message.reply("⚠️ Лимит, подождите немного.")
                elif status_code == 402:
                    await message.reply("⚠️ Нужен Pro.")
                elif status_code in (401, 403):
                    await message.reply("⚠️ Ошибка авторизации.")
                else:
                    await message.reply("⚠️ Ошибка, попробуйте позже.")

            except Exception as e:
                if config.BOT_DEBUG:
                    print(f"[HTTP] error user_id={user_id} err={e}")
                print(f"[question] Backend error for user_id={user_id}: {e}")
                await message.reply("⚠️ Ошибка, попробуйте позже.")

            finally:
                set_waiting_question(user_id)
