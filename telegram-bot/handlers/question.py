from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ChatAction
import asyncio
import os
import uuid
import config
from flows.pro_flow import (
    is_user_pro,
    is_pro_profile_complete,
    start_pro_flow,
    handle_pet_profile_actions as handle_pet_profile_actions_flow,
    handle_pro_callbacks as handle_pro_callbacks_flow,
    handle_save_profile as handle_save_profile_flow,
    handle_pro_text_step,
)
from services.backend_client import ask_backend
from services.state import (
    get_profile,
    get_pro_profile,
    get_pro_step,
    get_last_limits,
    get_pet_profile,
    set_basic_info,
    set_last_limits,
    set_pending_question,
    set_profile_field,
    set_question,
    set_waiting_question,
    start_profile,
    get_skip_basic_info,
    set_skip_basic_info,
    get_pending_question,
    pop_pending_question,
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


def build_pet_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🐶 Собака", callback_data="pet_dog")],
            [InlineKeyboardButton("🐱 Кошка", callback_data="pet_cat")],
            [InlineKeyboardButton("🐾 Другое", callback_data="pet_other")],
        ]
    )



async def send_backend_response(
    client_tg: Client,
    message: Message,
    user_id: int,
    question_text: str | None = None,
) -> None:
    profile = get_profile(user_id)
    pro_profile = get_pro_profile(user_id)
    pet_profile = get_pet_profile(user_id) or (pro_profile if pro_profile else None)
    question = question_text or (profile.get("question") if profile else None) or ""
    pet_profile_to_send = pet_profile
    if isinstance(pet_profile_to_send, dict):
        pet_profile_keys = sorted(pet_profile_to_send.keys())
        if not pet_profile_to_send.get("type"):
            print(
                "[WARN] Skipping pet_profile: missing type "
                f"user_id={user_id} keys={pet_profile_keys}"
            )
            pet_profile_to_send = None
        else:
            print(f"[BACKEND] pet_profile_keys={pet_profile_keys}")
    elif pet_profile_to_send is not None:
        print(
            "[WARN] Skipping pet_profile: unexpected payload type "
            f"user_id={user_id} type={type(pet_profile_to_send).__name__}"
        )
        pet_profile_to_send = None

    if profile and profile.get("type") and profile.get("basic_info"):
        summary = (
            "📋 Анкета:\n"
            f"Тип питомца: {profile.get('type')}\n"
            f"Описание: {profile.get('basic_info')}\n"
            f"Вопрос: {question}"
        )
    else:
        summary = question

    await message.reply("⌛️ Ваш запрос обрабатывается нейросетью. Пожалуйста, подождите...")

    await client_tg.send_chat_action(message.chat.id, ChatAction.TYPING)

    try:
        if config.BOT_DEBUG:
            print(f"[HTTP] POST /v1/chat/ask user_id={user_id} bytes={len(summary.encode('utf-8'))}")
        current_mode = normalize_mode(profile.get("current_mode") if profile else None)
        base_url = os.getenv("BACKEND_BASE_URL", "")
        token = os.getenv("BOT_BACKEND_TOKEN", "")
        request_id = str(uuid.uuid4())
        print(
            "[BACKEND] calling /v1/chat/ask "
            f"user_id={user_id} rid={request_id} "
            f"has_profile={bool(pro_profile)} has_pet_profile={bool(pet_profile_to_send)} text_len={len(summary)}"
        )
        result = await asyncio.to_thread(
            ask_backend,
            base_url,
            token,
            user_id,
            summary,
            current_mode,
            request_id,
            pro_profile,
            pet_profile_to_send,
        )
        print(f"[BACKEND] status={result.get('status')} ok={result.get('ok')}")
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
            set_last_limits(user_id, limits if isinstance(limits, dict) else None)
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
            set_last_limits(user_id, limits if isinstance(limits, dict) else None)
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


def setup_question_handlers(app: Client):
    @app.on_callback_query(filters.regex("^upsell_pro$"))
    async def handle_upsell_pro(client_tg: Client, callback_query: CallbackQuery):
        await callback_query.answer()
        await callback_query.message.reply("💎 Оформление Pro скоро появится. Спасибо за интерес!")

    @app.on_callback_query(filters.regex("^pet_profile_(ask|update)$"))
    async def handle_pet_profile_actions(client_tg: Client, callback_query: CallbackQuery):
        await handle_pet_profile_actions_flow(client_tg, callback_query, send_backend_response)

    @app.on_callback_query(filters.regex("^pro_save_profile$"))
    async def handle_save_profile(client_tg: Client, callback_query: CallbackQuery):
        await handle_save_profile_flow(client_tg, callback_query)

    @app.on_callback_query(filters.regex("^pro_(?!save_profile$)"))
    async def handle_pro_callbacks(client_tg: Client, callback_query: CallbackQuery):
        await handle_pro_callbacks_flow(client_tg, callback_query, send_backend_response)

    @app.on_callback_query(filters.regex("^(dog|cat|other)_(emergency|care|vaccines|health)$"))
    async def start_unified_form(client_tg: Client, callback_query: CallbackQuery):
        await callback_query.answer()
        user_id = callback_query.from_user.id
        pet_type, context = callback_query.data.split("_")

        context = normalize_mode(context)
        current_mode = context
        start_profile(user_id, pet_type, context, current_mode=current_mode)
        set_profile_field(user_id, "type", pet_type)

        if get_skip_basic_info(user_id):
            set_skip_basic_info(user_id, False)
            set_waiting_question(user_id)
            if context == "care":
                await callback_query.message.edit_text(
                    "💬 Напишите свой вопрос или опишите, что вас интересует:\n\n"
                    "Пример: подбор корма, режим кормления, уход за шерстью, когтями, ушами, гигиена, "
                    "выбор мисок, лежанок и других аксессуаров."
                )
            elif context == "vaccines":
                await callback_query.message.edit_text(
                    "💬 Напишите, о чём вы хотите узнать:\n\n"
                    "Пример: график прививок, профилактика глистов, уход за зубами, обработка от блох и клещей, "
                    "стрижка когтей, чистка ушей, обработка глаз."
                )
            else:
                await callback_query.message.edit_text(
                    "💬 Опишите, что именно беспокоит Вашего питомца, или задайте вопрос:"
                )
            return

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
        pro_step = get_pro_step(user_id)
        pro_profile = get_pro_profile(user_id)
        last_limits = get_last_limits(user_id)

        handled = await handle_pro_text_step(client_tg, message)
        if handled:
            return

        if is_user_pro(last_limits) and not is_pro_profile_complete(pro_profile) and not profile:
            if not get_pending_question(user_id):
                set_pending_question(user_id, message.text)
            await start_pro_flow(message, user_id)
            return

        if not profile:
            start_profile(user_id)
            set_pending_question(user_id, message.text)
            profile = get_profile(user_id)
            if profile:
                profile["step"] = "pending_details"
            await message.reply(
                "📥 Ваш вопрос принят.\n\n"
                "Напоминаю, что на Free-тарифе я не запоминаю данные ваших питомцев. "
                "Для точного ответа нейросети важно знать детали: вид, породу, возраст, пол, "
                "особенности здоровья, прививки и т.д.\n\n"
                "📝 Напишите ниже любые важные детали, которые вы не указали ранее, "
                "одним сообщением — я добавлю их к вашему вопросу.\n\n"
                "Или воспользуйтесь кнопками, чтобы заполнить данные по шагам:",
                reply_markup=build_pet_keyboard(),
            )
            return

        if config.BOT_DEBUG:
            print(f"[Q-HANDLER] user_id={user_id} has_profile={bool(profile)} step={profile.get('step') if profile else None}")

        if not profile:
            return

        step = profile.get("step")
        if step == "done":
            await message.reply("⌛ Я уже готовлю ответ. Пожалуйста, подождите…")
            return
        if not step:
            step = "question"

        if step == "basic_info":
            set_basic_info(user_id, message.text)
            profile = get_profile(user_id)
            pending = get_pending_question(user_id)
            if pending:
                if is_user_pro(last_limits) and not is_pro_profile_complete(get_pro_profile(user_id)):
                    await start_pro_flow(message, user_id)
                    return
                set_question(user_id, pop_pending_question(user_id))
                await send_backend_response(client_tg, message, user_id)
                return

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

        elif step == "pending_details":
            set_basic_info(user_id, message.text)
            pending = get_pending_question(user_id)
            if not pending:
                await message.reply(
                    "💬 Опишите, что именно беспокоит Вашего питомца, или задайте вопрос:"
                )
                return
            if is_user_pro(last_limits) and not is_pro_profile_complete(get_pro_profile(user_id)):
                await start_pro_flow(message, user_id)
                return
            set_question(user_id, pop_pending_question(user_id))
            await send_backend_response(client_tg, message, user_id)

        elif step == "question":
            if is_user_pro(last_limits) and not is_pro_profile_complete(get_pro_profile(user_id)):
                set_pending_question(user_id, message.text)
                await start_pro_flow(message, user_id)
                return
            set_question(user_id, message.text)
            await send_backend_response(client_tg, message, user_id)
