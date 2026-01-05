from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ChatAction
import asyncio
import os
import re
import uuid
import config
from services.backend_client import ask_backend
from services.state import (
    get_profile,
    get_pro_profile,
    get_pro_step,
    get_pro_temp,
    get_last_limits,
    get_profile_created_shown,
    is_awaiting_button,
    set_basic_info,
    set_health_note,
    set_last_limits,
    set_owner_note,
    set_pending_question,
    set_profile_created_shown,
    set_profile_field,
    set_pro_step,
    set_pro_temp_field,
    set_question,
    set_waiting_question,
    start_profile,
    add_health_tag,
    get_pending_question,
    pop_pending_question,
    PRO_STEP_NONE,
    PRO_STEP_SPECIES,
    PRO_STEP_NAME,
    PRO_STEP_AGE,
    PRO_STEP_SEX,
    PRO_STEP_BREED,
    PRO_STEP_WEIGHT_MODE,
    PRO_STEP_WEIGHT_KG,
    PRO_STEP_WEIGHT_BCS,
    PRO_STEP_WEIGHT_AFTER_BCS_ASK_KG,
    PRO_STEP_DONE,
    PRO_STEP_POST_MENU,
    PRO_STEP_HEALTH_PICK,
    PRO_STEP_HEALTH_NOTE,
    PRO_STEP_VACCINES,
    PRO_STEP_PARASITES,
    PRO_STEP_OWNER_NOTE,
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


def is_user_pro(last_limits: dict | None) -> bool:
    if isinstance(last_limits, dict) and last_limits.get("plan") == "pro":
        return True
    return os.getenv("FORCE_PRO", "").strip() == "1"


def is_pro_profile_complete(profile: dict) -> bool:
    if not isinstance(profile, dict):
        return False
    required = ("species", "age_text", "sex", "breed")
    return all(profile.get(key) for key in required)


def build_species_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🐶 Собака", callback_data="pro_species:dog")],
            [InlineKeyboardButton("🐱 Кошка", callback_data="pro_species:cat")],
            [InlineKeyboardButton("🐾 Другое", callback_data="pro_species:other")],
        ]
    )


def build_sex_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("♂ Самец", callback_data="pro_sex:male")],
            [InlineKeyboardButton("♀ Самка", callback_data="pro_sex:female")],
            [InlineKeyboardButton("❓ Не знаю", callback_data="pro_sex:unknown")],
        ]
    )


def build_weight_mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⚖️ Ввести вес (кг)", callback_data="pro_weight_mode:kg")],
            [InlineKeyboardButton("📏 Оценить на глаз", callback_data="pro_weight_mode:bcs")],
            [InlineKeyboardButton("⏭ Пропустить", callback_data="pro_weight_mode:skip")],
        ]
    )


def build_bcs_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("худой", callback_data="pro_bcs:thin")],
            [InlineKeyboardButton("норм", callback_data="pro_bcs:normal")],
            [InlineKeyboardButton("полный", callback_data="pro_bcs:overweight")],
            [InlineKeyboardButton("не знаю", callback_data="pro_bcs:unknown")],
            [InlineKeyboardButton("⏭ Пропустить", callback_data="pro_bcs:skip")],
        ]
    )


def build_after_bcs_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⚖️ Ввести кг", callback_data="pro_after_bcs:kg")],
            [InlineKeyboardButton("⏭ Пропустить", callback_data="pro_after_bcs:skip")],
        ]
    )


def build_post_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Вернуться к вопросу", callback_data="pro_post:continue")],
            [InlineKeyboardButton("🩺 Особенности здоровья", callback_data="pro_post:health")],
            [InlineKeyboardButton("💉 Прививки/паразиты", callback_data="pro_post:vaccines")],
            [InlineKeyboardButton("📝 Важное о питомце", callback_data="pro_post:note")],
        ]
    )


def build_health_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🧴 Кожа/шерсть", callback_data="pro_health:skin_coat")],
            [InlineKeyboardButton("🍽 ЖКТ/питание", callback_data="pro_health:gi")],
            [InlineKeyboardButton("🌾 Аллергии/реакции", callback_data="pro_health:allergy")],
            [InlineKeyboardButton("🦴 Опорно-двигательное", callback_data="pro_health:mobility")],
            [InlineKeyboardButton("📝 Другое", callback_data="pro_health:other")],
            [InlineKeyboardButton("⏭ Пропустить", callback_data="pro_health:skip")],
            [InlineKeyboardButton("✅ Готово", callback_data="pro_health:done")],
        ]
    )


def build_vax_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💉 Делались по возрасту", callback_data="pro_vax:done")],
            [InlineKeyboardButton("⚠️ Частично", callback_data="pro_vax:partial")],
            [InlineKeyboardButton("❓ Не знаю", callback_data="pro_vax:unknown")],
            [InlineKeyboardButton("⏭ Пропустить", callback_data="pro_vax:skip")],
        ]
    )


def build_parasites_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🟢 Регулярно", callback_data="pro_par:regular")],
            [InlineKeyboardButton("🟡 Нерегулярно", callback_data="pro_par:irregular")],
            [InlineKeyboardButton("❓ Не знаю", callback_data="pro_par:unknown")],
            [InlineKeyboardButton("⏭ Пропустить", callback_data="pro_par:skip")],
        ]
    )


def get_pro_prompt_and_keyboard(user_id: int, step: str) -> tuple[str, InlineKeyboardMarkup] | None:
    if step == PRO_STEP_SPECIES:
        return "Кто у вас?", build_species_keyboard()
    if step == PRO_STEP_SEX:
        return "Пол питомца:", build_sex_keyboard()
    if step == PRO_STEP_WEIGHT_MODE:
        return "Вес питомца (опционально). Что удобнее?", build_weight_mode_keyboard()
    if step == PRO_STEP_WEIGHT_BCS:
        return "По виду сейчас он скорее...", build_bcs_keyboard()
    if step == PRO_STEP_WEIGHT_AFTER_BCS_ASK_KG:
        return "Если знаете точный вес — хотите указать?", build_after_bcs_keyboard()
    if step in (PRO_STEP_DONE, PRO_STEP_POST_MENU):
        pro_profile = get_pro_profile(user_id)
        name = (pro_profile.get("name") or "").strip()
        title_name = f" {name}" if name else ""
        if get_profile_created_shown(user_id):
            status_line = f"Профиль питомца{title_name} обновлён ✅"
        else:
            status_line = f"Профиль питомца{title_name} успешно создан! 🐾"
        if get_profile_created_shown(user_id):
            status_hint = (
                "Спасибо, эта информация поможет мне отвечать точнее.\n\n"
                "Вы можете продолжить заполнять профиль\n"
                "или вернуться к своему вопросу в любой момент."
            )
        else:
            status_hint = (
                "Я запомнил базовую информацию.\n"
                "Теперь могу учитывать её в ответах и рекомендациях.\n\n"
                "Вы можете вернуться к своему вопросу\n"
                "или дополнить профиль — это поможет мне отвечать точнее."
            )
        return (
            f"{status_line}\n{status_hint}\n",
            build_post_menu_keyboard(),
        )
    if step == PRO_STEP_HEALTH_PICK:
        return "Особенности (если известно). Выберите пункт или нажмите Пропустить.", build_health_keyboard()
    if step == PRO_STEP_VACCINES:
        return "Прививки:", build_vax_keyboard()
    if step == PRO_STEP_PARASITES:
        return "Обработка от паразитов:", build_parasites_keyboard()
    return None


async def start_pro_flow(message: Message, user_id: int) -> None:
    set_pro_step(user_id, PRO_STEP_SPECIES, True)
    await message.reply("Кто у вас?", reply_markup=build_species_keyboard())


async def show_post_menu(message: Message, user_id: int) -> None:
    prompt = get_pro_prompt_and_keyboard(user_id, PRO_STEP_POST_MENU)
    if prompt:
        text, keyboard = prompt
        await message.reply(text, reply_markup=keyboard)
    if not get_profile_created_shown(user_id):
        set_profile_created_shown(user_id, True)


async def send_backend_response(
    client_tg: Client,
    message: Message,
    user_id: int,
    question_text: str | None = None,
) -> None:
    profile = get_profile(user_id)
    pro_profile = get_pro_profile(user_id)
    question = question_text or (profile.get("question") if profile else None) or ""

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
            f"has_profile={bool(pro_profile)} text_len={len(summary)}"
        )
        result = await asyncio.to_thread(
            ask_backend, base_url, token, user_id, summary, current_mode, request_id, pro_profile
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

    @app.on_callback_query(filters.regex("^pro_"))
    async def handle_pro_callbacks(client_tg: Client, callback_query: CallbackQuery):
        await callback_query.answer()
        user_id = callback_query.from_user.id
        data = callback_query.data or ""

        if data.startswith("pro_species:"):
            value = data.split(":", 1)[1]
            set_profile_field(user_id, "species", value)
            set_pro_step(user_id, PRO_STEP_NAME, False)
            await callback_query.message.reply("Как зовут питомца? (можно пропустить)")
            return

        if data.startswith("pro_sex:"):
            value = data.split(":", 1)[1]
            set_profile_field(user_id, "sex", value)
            set_pro_step(user_id, PRO_STEP_BREED, False)
            await callback_query.message.reply(
                "Порода питомца? Можно: йорк / метис / не знаю"
            )
            return

        if data.startswith("pro_weight_mode:"):
            value = data.split(":", 1)[1]
            set_pro_temp_field(user_id, "weight_mode", value)
            if value == "kg":
                set_pro_step(user_id, PRO_STEP_WEIGHT_KG, False)
                await callback_query.message.reply(
                    "Напишите вес в кг (например: 6.2). Можно приблизительно."
                )
                return
            if value == "bcs":
                set_pro_step(user_id, PRO_STEP_WEIGHT_BCS, True)
                await callback_query.message.reply(
                    "По виду сейчас он скорее...",
                    reply_markup=build_bcs_keyboard(),
                )
                return
            set_profile_field(user_id, "weight_kg", None)
            set_profile_field(user_id, "bcs", None)
            set_pro_step(user_id, PRO_STEP_POST_MENU, True)
            await show_post_menu(callback_query.message, user_id)
            return

        if data.startswith("pro_bcs:"):
            value = data.split(":", 1)[1]
            if value == "skip":
                set_profile_field(user_id, "bcs", None)
                set_pro_step(user_id, PRO_STEP_POST_MENU, True)
                await show_post_menu(callback_query.message, user_id)
                return
            set_profile_field(user_id, "bcs", value)
            temp = get_pro_temp(user_id)
            if temp.get("weight_mode") == "bcs":
                set_pro_step(user_id, PRO_STEP_WEIGHT_AFTER_BCS_ASK_KG, True)
                await callback_query.message.reply(
                    "Если знаете точный вес — хотите указать?",
                    reply_markup=build_after_bcs_keyboard(),
                )
            else:
                set_pro_step(user_id, PRO_STEP_POST_MENU, True)
                await show_post_menu(callback_query.message, user_id)
            return

        if data.startswith("pro_after_bcs:"):
            value = data.split(":", 1)[1]
            if value == "kg":
                set_pro_temp_field(user_id, "weight_mode", "after_bcs")
                set_pro_step(user_id, PRO_STEP_WEIGHT_KG, False)
                await callback_query.message.reply(
                    "Напишите вес в кг (например: 6.2). Можно приблизительно."
                )
            else:
                set_pro_step(user_id, PRO_STEP_POST_MENU, True)
                await show_post_menu(callback_query.message, user_id)
            return

        if data.startswith("pro_post:"):
            value = data.split(":", 1)[1]
            if value == "continue":
                set_pro_step(user_id, PRO_STEP_NONE, False)
                pending = pop_pending_question(user_id)
                if pending:
                    await send_backend_response(client_tg, callback_query.message, user_id, pending)
                else:
                    await callback_query.message.reply("Напишите свой вопрос.")
                return
            if value == "health":
                set_pro_step(user_id, PRO_STEP_HEALTH_PICK, True)
                await callback_query.message.reply(
                    "Особенности (если известно). Выберите пункт или нажмите Пропустить.",
                    reply_markup=build_health_keyboard(),
                )
                return
            if value == "vaccines":
                set_pro_step(user_id, PRO_STEP_VACCINES, True)
                await callback_query.message.reply(
                    "Прививки:",
                    reply_markup=build_vax_keyboard(),
                )
                return
            if value == "note":
                set_pro_step(user_id, PRO_STEP_OWNER_NOTE, False)
                await callback_query.message.reply(
                    "Напишите одним сообщением важные особенности (до 500 символов).\n"
                    "Например: 'реакция на курицу', 'боится фена', 'переедает'.\n"
                    "Можно написать 'пропустить'."
                )
                return

        if data.startswith("pro_health:"):
            value = data.split(":", 1)[1]
            if value in ("skip", "done"):
                set_pro_step(user_id, PRO_STEP_POST_MENU, True)
                await show_post_menu(callback_query.message, user_id)
                return
            add_health_tag(user_id, value)
            set_pro_temp_field(user_id, "health_tag", value)
            set_pro_step(user_id, PRO_STEP_HEALTH_NOTE, False)
            await callback_query.message.reply(
                "Опишите одним сообщением, что именно (коротко, без лекарств/дозировок)."
            )
            return

        if data.startswith("pro_vax:"):
            value = data.split(":", 1)[1]
            if value == "skip":
                set_profile_field(user_id, "vaccines", None)
            else:
                set_profile_field(user_id, "vaccines.status", value)
            set_pro_step(user_id, PRO_STEP_PARASITES, True)
            await callback_query.message.reply(
                "Обработка от паразитов:",
                reply_markup=build_parasites_keyboard(),
            )
            return

        if data.startswith("pro_par:"):
            value = data.split(":", 1)[1]
            if value == "skip":
                set_profile_field(user_id, "parasites", None)
            else:
                set_profile_field(user_id, "parasites.status", value)
            set_pro_step(user_id, PRO_STEP_POST_MENU, True)
            await show_post_menu(callback_query.message, user_id)
            return

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
        pro_step = get_pro_step(user_id)
        pro_profile = get_pro_profile(user_id)
        last_limits = get_last_limits(user_id)

        if pro_step != PRO_STEP_NONE and pro_step.startswith("pro_"):
            if is_awaiting_button(user_id):
                prompt = get_pro_prompt_and_keyboard(user_id, pro_step)
                if prompt:
                    text, keyboard = prompt
                    await message.reply(
                        f"Пожалуйста, нажмите кнопку ниже 🙂\n\n{text}",
                        reply_markup=keyboard,
                    )
                else:
                    await message.reply("Пожалуйста, нажмите кнопку ниже 🙂")
                return

            if pro_step == PRO_STEP_NAME:
                raw_name = message.text.strip()
                lowered = raw_name.lower()
                if lowered in ("пропустить", "skip", "-", "—", "нет"):
                    set_profile_field(user_id, "name", None)
                    set_pro_step(user_id, PRO_STEP_AGE, False)
                    await message.reply(
                        "Сколько лет питомцу? Например: 2 года / 6 месяцев"
                    )
                    return
                cleaned = raw_name.strip()
                if not cleaned:
                    await message.reply(
                        "Введите имя или напишите \"пропустить\"."
                    )
                    return
                cleaned = cleaned[:30]
                set_profile_field(user_id, "name", cleaned)
                set_pro_step(user_id, PRO_STEP_AGE, False)
                await message.reply(
                    "Сколько лет питомцу? Например: 2 года / 6 месяцев"
                )
                return

            if pro_step == PRO_STEP_AGE:
                set_profile_field(user_id, "age_text", message.text.strip())
                set_pro_step(user_id, PRO_STEP_SEX, True)
                await message.reply("Пол питомца:", reply_markup=build_sex_keyboard())
                return

            if pro_step == PRO_STEP_BREED:
                set_profile_field(user_id, "breed", message.text.strip())
                set_pro_step(user_id, PRO_STEP_WEIGHT_MODE, True)
                await message.reply(
                    "Вес питомца (опционально). Что удобнее?",
                    reply_markup=build_weight_mode_keyboard(),
                )
                return

            if pro_step == PRO_STEP_WEIGHT_KG:
                raw = message.text.strip().lower().replace(",", ".")
                match = re.search(r"(\d+(?:\.\d+)?)", raw)
                weight = None
                if match:
                    try:
                        weight = float(match.group(1))
                    except ValueError:
                        weight = None
                if weight is None or not (0.1 <= weight <= 200):
                    await message.reply(
                        "Введите вес числом, например 6.2 (можно '6 кг')."
                    )
                    return
                set_profile_field(user_id, "weight_kg", weight)
                temp = get_pro_temp(user_id)
                if temp.get("weight_mode") == "kg":
                    set_pro_step(user_id, PRO_STEP_WEIGHT_BCS, True)
                    await message.reply(
                        "По виду сейчас он скорее...",
                        reply_markup=build_bcs_keyboard(),
                    )
                else:
                    set_pro_step(user_id, PRO_STEP_POST_MENU, True)
                    await show_post_menu(message, user_id)
                return

            if pro_step == PRO_STEP_HEALTH_NOTE:
                tag = get_pro_temp(user_id).get("health_tag")
                if tag:
                    set_health_note(user_id, tag, message.text.strip())
                    set_pro_temp_field(user_id, "health_tag", None)
                set_pro_step(user_id, PRO_STEP_HEALTH_PICK, True)
                await message.reply(
                    "Особенности (если известно). Выберите пункт или нажмите Пропустить.",
                    reply_markup=build_health_keyboard(),
                )
                return

            if pro_step == PRO_STEP_OWNER_NOTE:
                note = message.text.strip()
                if note.lower() not in ("пропустить", "/skip"):
                    set_owner_note(user_id, note)
                set_pro_step(user_id, PRO_STEP_POST_MENU, True)
                await show_post_menu(message, user_id)
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
