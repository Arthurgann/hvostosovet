import asyncio
import os
import re
import uuid
from pyrogram import Client
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
import config
from services.backend_client import ask_backend, get_active_pet
from services.state import (
    get_pro_profile,
    get_pro_step,
    get_pro_temp,
    get_profile_created_shown,
    get_pet_profile,
    get_pet_profile_loaded,
    is_awaiting_button,
    is_profile_dirty,
    is_profile_saving,
    set_health_note,
    set_health_category,
    get_health_category,
    set_owner_note,
    set_profile_dirty,
    set_profile_created_shown,
    set_profile_field,
    set_profile_saving,
    set_pet_profile,
    set_pet_profile_loaded,
    set_skip_basic_info,
    set_pro_step,
    set_pro_temp_field,
    add_health_tag,
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


def build_pet_profile_loaded_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("❓ Задать вопрос", callback_data="pet_profile_ask")],
            [InlineKeyboardButton("✏️ Обновить профиль", callback_data="pet_profile_update")],
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


def build_post_menu_keyboard(include_save: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if include_save:
        rows.append([InlineKeyboardButton("💾 Сохранить изменения", callback_data="pro_save_profile")])
    rows.extend(
        [
            [InlineKeyboardButton("✅ Вернуться к вопросу", callback_data="pro_post:continue")],
            [InlineKeyboardButton("📝 Изменить базовые данные", callback_data="pro_edit_basic")],
            [InlineKeyboardButton("🩺 Особенности здоровья", callback_data="pro_post:health")],
            [InlineKeyboardButton("💉 Прививки/паразиты", callback_data="pro_post:vaccines")],
            [InlineKeyboardButton("📝 Важное о питомце", callback_data="pro_post:note")],
        ]
    )
    return InlineKeyboardMarkup(rows)


def build_mode_keyboard(pet_type: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🚑 Скорая помощь", callback_data=f"{pet_type}_emergency")],
            [InlineKeyboardButton("🍖 Питание и уход", callback_data=f"{pet_type}_care")],
            [InlineKeyboardButton("💉 Прививки и профилактика", callback_data=f"{pet_type}_vaccines")],
            [InlineKeyboardButton("🏠 В главное меню", callback_data="back_to_main")],
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
        return "Если знаете точный вес - хотите указать?", build_after_bcs_keyboard()
    if step in (PRO_STEP_DONE, PRO_STEP_POST_MENU):
        pro_profile = get_pro_profile(user_id)
        name = (pro_profile.get("name") or "").strip()
        if is_profile_dirty(user_id):
            title = f"✨ Обновление профиля: {name}" if name else "✨ Обновление профиля"
            return (
                f"{title}\n\n"
                "Изменения внесены и ждут подтверждения.\n"
                "Нажмите «💾 Сохранить изменения», чтобы обновить данные в базе, или продолжайте редактирование.\n\n"
                "Вы также всегда можете вернуться к вопросу.",
                build_post_menu_keyboard(include_save=True),
            )
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


async def maybe_load_pet_profile(message: Message, user_id: int) -> bool:
    if get_pet_profile_loaded(user_id):
        return get_pet_profile(user_id) is not None

    pet_profile = await asyncio.to_thread(get_active_pet, user_id)
    if pet_profile is None:
        return False

    set_pet_profile(user_id, pet_profile)
    set_pet_profile_loaded(user_id, True)
    name = (pet_profile.get("name") or "").strip()
    title_name = f" {name}" if name else ""
    await message.reply(
        f"🐾 Я уже помню вашего питомца{title_name}\n"
        "Могу сразу помочь с вопросом или вы можете обновить профиль.",
        reply_markup=build_pet_profile_loaded_keyboard(),
    )
    return True


async def start_pro_flow(message: Message, user_id: int, force: bool = False) -> None:
    if not force:
        loaded = await maybe_load_pet_profile(message, user_id)
        if loaded:
            return
    set_pro_step(user_id, PRO_STEP_SPECIES, True)
    await message.reply("Кто у вас?", reply_markup=build_species_keyboard())


async def show_post_menu(message: Message, user_id: int) -> None:
    prompt = get_pro_prompt_and_keyboard(user_id, PRO_STEP_POST_MENU)
    if prompt:
        text, keyboard = prompt
        await message.reply(text, reply_markup=keyboard)
    if not get_profile_created_shown(user_id):
        set_profile_created_shown(user_id, True)


async def handle_pet_profile_actions(
    client_tg: Client,
    callback_query: CallbackQuery,
    send_backend_response_cb,
) -> None:
    await callback_query.answer()
    user_id = callback_query.from_user.id
    action = (callback_query.data or "").split("_")[-1]
    if action == "ask":
        set_skip_basic_info(user_id, True)
        profile = get_pet_profile(user_id) or get_pro_profile(user_id)
        pet_type = (profile.get("type") if isinstance(profile, dict) else None) or "other"
        await callback_query.message.edit_text(
            "Что вас интересует?",
            reply_markup=build_mode_keyboard(pet_type),
        )
        return
    if action == "update":
        pet_profile = get_pet_profile(user_id)
        if get_pet_profile_loaded(user_id) and pet_profile:
            set_pro_step(user_id, PRO_STEP_POST_MENU, True)
            await show_post_menu(callback_query.message, user_id)
            return
    await start_pro_flow(callback_query.message, user_id, force=True)


async def handle_pro_callbacks(
    client_tg: Client,
    callback_query: CallbackQuery,
    send_backend_response_cb,
) -> None:
    await callback_query.answer()
    user_id = callback_query.from_user.id
    data = callback_query.data or ""

    if data == "pro_edit_basic":
        await start_pro_flow(callback_query.message, user_id, force=True)
        return

    if data.startswith("pro_species:"):
        value = data.split(":", 1)[1]
        set_profile_field(user_id, "species", value)
        set_profile_field(user_id, "type", value)
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
                await send_backend_response_cb(client_tg, callback_query.message, user_id, pending)
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
        set_health_category(user_id, value)
        set_pro_step(user_id, PRO_STEP_HEALTH_NOTE, False)
        await callback_query.message.reply(
            "Опишите, что именно беспокоит (коротко, без лекарств/дозировок)."
        )
        return

    if data.startswith("pro_vax:"):
        value = data.split(":", 1)[1]
        if value == "skip":
            set_profile_field(user_id, "vaccines", None)
        else:
            set_profile_field(user_id, "vaccines.status", value)
        set_profile_dirty(user_id, True)
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
        set_profile_dirty(user_id, True)
        set_pro_step(user_id, PRO_STEP_POST_MENU, True)
        await show_post_menu(callback_query.message, user_id)
        return


async def handle_save_profile(
    client_tg: Client,
    callback_query: CallbackQuery,
) -> None:
    user_id = callback_query.from_user.id
    if is_profile_saving(user_id):
        await callback_query.answer("Сохраняю… подождите", show_alert=False)
        return
    await callback_query.answer()
    set_profile_saving(user_id, True)
    profile = get_pet_profile(user_id) or {}
    if not isinstance(profile, dict):
        profile = {}
    if not profile.get("type") and profile.get("species"):
        profile["type"] = profile["species"]
    if not profile.get("type"):
        set_profile_saving(user_id, False)
        await callback_query.message.reply_text(
            "Не удалось сохранить: не вижу тип питомца. Откройте «⭐ Мой питомец» и попробуйте снова."
        )
        return

    base_url = os.getenv("BACKEND_BASE_URL", "")
    token = os.getenv("BOT_BACKEND_TOKEN", "")
    request_id = str(uuid.uuid4())
    if config.BOT_DEBUG:
        print(f"[HTTP] POST /v1/chat/ask save_profile user_id={user_id}")
    try:
        await callback_query.message.reply("⌛️ Сохраняю изменения профиля… Пожалуйста, подождите.")
        result = await asyncio.to_thread(
            ask_backend,
            base_url,
            token,
            user_id,
            "__save_profile__",
            "care",
            request_id,
            None,
            profile,
        )
        ok = result.get("ok")
        if config.BOT_DEBUG:
            status = result.get("status")
            print(f"[BACKEND] save_profile status={status} ok={ok}")
        if not ok:
            await callback_query.message.reply("❗ Не удалось сохранить профиль. Попробуйте позже.")
            return

        set_profile_dirty(user_id, False)
        set_profile_saving(user_id, False)
        await callback_query.message.reply("✅ Профиль сохранён")
        await show_post_menu(callback_query.message, user_id)
    except Exception as exc:
        if config.BOT_DEBUG:
            print(f"[BACKEND] save_profile error user_id={user_id} err={exc}")
        await callback_query.message.reply("❗ Не удалось сохранить профиль. Попробуйте позже.")
        return
    finally:
        set_profile_saving(user_id, False)


async def handle_pro_text_step(client_tg: Client, message: Message) -> bool:
    user_id = message.from_user.id
    pro_step = get_pro_step(user_id)

    if pro_step == PRO_STEP_NONE or not pro_step.startswith("pro_"):
        return False

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
        return True

    if pro_step == PRO_STEP_NAME:
        raw_name = message.text.strip()
        lowered = raw_name.lower()
        if lowered in ("пропустить", "skip", "-", "—", "нет"):
            set_profile_field(user_id, "name", None)
            set_pro_step(user_id, PRO_STEP_AGE, False)
            await message.reply(
                "Сколько лет питомцу? Например: 2 года / 6 месяцев"
            )
            return True
        cleaned = raw_name.strip()
        if not cleaned:
            await message.reply(
                "Введите имя или напишите \"пропустить\"."
            )
            return True
        cleaned = cleaned[:30]
        set_profile_field(user_id, "name", cleaned)
        set_pro_step(user_id, PRO_STEP_AGE, False)
        await message.reply(
            "Сколько лет питомцу? Например: 2 года / 6 месяцев"
        )
        return True

    if pro_step == PRO_STEP_AGE:
        set_profile_field(user_id, "age_text", message.text.strip())
        set_pro_step(user_id, PRO_STEP_SEX, True)
        await message.reply("Пол питомца:", reply_markup=build_sex_keyboard())
        return True

    if pro_step == PRO_STEP_BREED:
        set_profile_field(user_id, "breed", message.text.strip())
        set_pro_step(user_id, PRO_STEP_WEIGHT_MODE, True)
        await message.reply(
            "Вес питомца (опционально). Что удобнее?",
            reply_markup=build_weight_mode_keyboard(),
        )
        return True

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
            return True
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
        return True

    if pro_step == PRO_STEP_HEALTH_NOTE:
        tag = get_health_category(user_id)
        if tag:
            add_health_tag(user_id, tag)
            set_health_note(user_id, tag, message.text.strip())
            set_profile_dirty(user_id, True)
        set_health_category(user_id, None)
        set_pro_step(user_id, PRO_STEP_POST_MENU, True)
        await show_post_menu(message, user_id)
        return True

    if pro_step == PRO_STEP_OWNER_NOTE:
        note = message.text.strip()
        if note.lower() not in ("пропустить", "/skip"):
            set_owner_note(user_id, note)
            set_profile_dirty(user_id, True)
        set_pro_step(user_id, PRO_STEP_POST_MENU, True)
        await show_post_menu(message, user_id)
        return True

    return True
