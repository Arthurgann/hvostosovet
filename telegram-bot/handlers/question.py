from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ChatAction
import asyncio
import os
import uuid
import config
from services.backend_client import ask_backend
from services.state import (
    get_profile,
    start_profile,
    set_basic_info,
    set_question,
    set_waiting_question,
)



VALID_MODES = {"emergency", "care", "vaccines"}



def normalize_mode(value: str | None) -> str:
    if not value:
        return "emergency"
    normalized = value.strip().lower()
    if normalized == "health":
        normalized = "vaccines"
    if normalized not in VALID_MODES:
        return "emergency"
    return normalized


def setup_question_handlers(app: Client):
    @app.on_callback_query(filters.regex("^upsell_pro$"))
    async def handle_upsell_pro(client_tg: Client, callback_query: CallbackQuery):
        await callback_query.answer()
        await callback_query.message.reply("💎 Оформление Pro скоро появится. Спасибо за интерес!")

    @app.on_callback_query(filters.regex("^(dog|cat|other)_(emergency|care|vaccines|health)$"))
    async def start_unified_form(client_tg: Client, callback_query: CallbackQuery):
        await callback_query.answer()
        user_id = callback_query.from_user.id
        pet_type, context = callback_query.data.split("_")

        context = normalize_mode(context)
        current_mode = context
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
        elif context == "vaccines":
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

            context = normalize_mode(profile.get("context") if profile else None)

            if context == "care":
                await message.reply(
                    "📝 Напишите свой вопрос или опишите, что вас интересует:\n\n"
                    "Пример: подбор корма, режим кормления, уход за шерстью, когтями, ушами, гигиена, "
                    "выбор мисок, лежанок и других аксессуаров."
                )

            elif context == "vaccines":
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
                current_mode = normalize_mode(profile.get("current_mode") if profile else None)
                base_url = os.getenv("BACKEND_BASE_URL", "")
                token = os.getenv("BOT_BACKEND_TOKEN", "")
                request_id = str(uuid.uuid4())
                result = await asyncio.to_thread(
                    ask_backend, base_url, token, user_id, summary, current_mode, request_id
                )
                ok = result.get("ok")
                status = result.get("status")
                body = result.get("data") if ok else result.get("error")
                body_keys = ",".join(sorted(body.keys())) if isinstance(body, dict) else ""
                if config.BOT_DEBUG:
                    print(f"[HTTP] status={status} user_id={user_id} ok={ok} body_keys={body_keys}")
                if ok:
                    answer = (body.get("answer_text") or "").strip()
                    if not answer:
                        raise RuntimeError("empty_answer")
                    limits = body.get("limits") if isinstance(body, dict) else None
                    limits_line = None
                    if isinstance(limits, dict):
                        plan = limits.get("plan")
                        if plan == "free":
                            remaining_today = limits.get("remaining_today")
                            limits_line = f"🆓 План: Free · Осталось сегодня: {remaining_today}"
                        elif plan == "pro":
                            limits_line = "💎 План: Pro"
                    if limits_line:
                        answer = f"{answer}\n\n{limits_line}"
                    await message.reply(f"🧠 Ответ:\n\n{answer}")
                elif status == 0 or body == "backend_unreachable":
                    await message.reply("⚠️ Сервер сейчас недоступен. Попробуйте через пару минут.")
                elif status == 429:
                    reset_at = None
                    limits = result.get("limits")
                    upsell = None
                    if isinstance(body, dict):
                        reset_at = body.get("reset_at")
                        limits = body.get("limits") or limits
                    if isinstance(limits, dict):
                        reset_at = reset_at or limits.get("reset_at")
                        upsell = limits.get("upsell")
                    message_text = "🆓 Лимит Free на сегодня исчерпан. Приходите завтра."
                    reply_markup = None
                    if isinstance(upsell, dict):
                        cta = (upsell.get("cta") or "Оформить Pro").strip()
                        reply_markup = InlineKeyboardMarkup(
                            [[InlineKeyboardButton(cta, callback_data="upsell_pro")]]
                        )
                    await message.reply(message_text, reply_markup=reply_markup)
                elif status in (401, 403):
                    await message.reply("Ошибка авторизации между ботом и сервером (BOT_BACKEND_TOKEN).")
                elif isinstance(status, int) and status >= 500:
                    await message.reply("Сервис временно недоступен. Попробуйте позже.")
                else:
                    await message.reply("Не удалось обработать запрос. Попробуйте позже.")

            except Exception as e:
                if config.BOT_DEBUG:
                    print(f"[HTTP] error user_id={user_id} err={e}")
                print(f"[question] Backend error for user_id={user_id}: {e}")
                await message.reply("⚠️ Ошибка, попробуйте позже.")

            finally:
                set_waiting_question(user_id)
