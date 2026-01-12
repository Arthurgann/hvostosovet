# handlers/menu.py

import asyncio
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from services.backend_client import get_active_pet
from services.state import (
    get_pet_profile,
    get_pro_step,
    set_pet_profile,
    set_pet_profile_loaded,
    PRO_STEP_NONE,
)
from flows.pro_flow import guard_dirty_or_execute
from ui.main_menu import show_main_menu
from ui.labels import (
    BTN_DOG,
    BTN_CAT,
    BTN_OTHER,
    BTN_MY_PET,
    BTN_HOW_IT_WORKS,
    BTN_HOME,
    BTN_EMERGENCY,
    BTN_CARE,
    BTN_VACCINES,
    BTN_ASK_QUESTION,
    BTN_UPDATE_PROFILE,
    BTN_SHOW_PROFILE,
    BTN_HIDE_PROFILE,
    BTN_FILL_FORM,
)

def clip(text: str, limit: int) -> str:
    if not text:
        return ""
    cleaned = " ".join(str(text).split())
    if len(cleaned) <= limit:
        return cleaned
    suffix = "..."
    return cleaned[: max(0, limit - len(suffix))].rstrip() + suffix


def normalize_pet_profile(pet_profile: dict) -> dict:
    normalized = {}
    profile = pet_profile.get("profile")
    if isinstance(profile, dict):
        normalized = dict(profile)
    for key in [
        "type",
        "species",
        "name",
        "sex",
        "breed",
        "age_text",
        "bcs",
        "weight_kg",
        "vaccines",
        "parasites",
        "health",
        "owner_note",
        "animal_kind",
    ]:
        if pet_profile.get(key) is not None:
            normalized[key] = pet_profile.get(key)
    normalized.pop("id", None)
    normalized.pop("profile", None)
    return normalized


def format_weight_line(weight_kg) -> str | None:
    try:
        weight = float(weight_kg)
    except (TypeError, ValueError):
        return None
    if weight <= 0:
        return None
    weight = round(weight, 1)
    if abs(weight - int(weight)) < 1e-6:
        weight_text = str(int(weight))
    else:
        weight_text = f"{weight:.1f}".rstrip("0").rstrip(".")
    return f"⚖️ {weight_text} кг"


def format_type_line(profile: dict) -> str:
    pet_type = (profile.get("type") or profile.get("species") or "").strip()
    name = clip(profile.get("name") or "", 30)
    if pet_type == "dog":
        label = "Собака"
    elif pet_type == "cat":
        label = "Кот/кошка"
    elif pet_type == "other":
        kind = clip(profile.get("animal_kind") or "", 40)
        label = f"Другое: {kind}" if kind else "Другое"
    else:
        label = "Питомец"
    line = f"🐾 {label}"
    if name:
        line = f"{line} · {name}"
    return line


def format_vaccines_status(profile: dict) -> str | None:
    vaccines = profile.get("vaccines") or {}
    if isinstance(vaccines, dict):
        status = vaccines.get("status")
    else:
        status = None
    if not status:
        return None
    mapping = {
        "done": "по возрасту",
        "partial": "частично",
        "unknown": "не знаю",
    }
    return mapping.get(status, str(status))


def format_parasites_status(profile: dict) -> str | None:
    parasites = profile.get("parasites") or {}
    if isinstance(parasites, dict):
        status = parasites.get("status")
    else:
        status = None
    if not status:
        return None
    mapping = {
        "regular": "регулярно",
        "irregular": "нерегулярно",
        "unknown": "не знаю",
    }
    return mapping.get(status, str(status))


def format_pet_summary_short(profile: dict) -> str:
    details = [format_type_line(profile)]
    age_text = clip(profile.get("age_text") or "", 40)
    if age_text:
        details.append(f"🎂 {age_text}")
    weight_line = format_weight_line(profile.get("weight_kg"))
    if weight_line:
        details.append(weight_line)
    pet_type = profile.get("type") or profile.get("species")
    breed = clip(profile.get("breed") or "", 40)
    if breed and pet_type != "other":
        details.append(f"🧬 {breed}")
    details = details[:5]
    if details:
        return "⭐ Мой питомец\n\n" + "\n".join(details)
    return "⭐ Мой питомец"


def format_pet_summary_full(profile: dict) -> str:
    details = [format_type_line(profile)]
    age_text = clip(profile.get("age_text") or "", 80)
    if age_text:
        details.append(f"🎂 {age_text}")
    weight_line = format_weight_line(profile.get("weight_kg"))
    if weight_line:
        details.append(weight_line)
    pet_type = profile.get("type") or profile.get("species")
    breed = clip(profile.get("breed") or "", 80)
    if breed and pet_type != "other":
        details.append(f"🧬 {breed}")
    lines = ["📋 Профиль питомца", "", *details]

    vax_status = format_vaccines_status(profile)
    if vax_status:
        lines.append(f"💉 Прививки: {vax_status}")
    par_status = format_parasites_status(profile)
    if par_status:
        lines.append(f"🪲 Паразиты: {par_status}")

    health = profile.get("health") or {}
    notes_by_tag = health.get("notes_by_tag") if isinstance(health, dict) else None
    notes_by_tag = notes_by_tag if isinstance(notes_by_tag, dict) else {}
    tag_labels = {
        "skin_coat": "Кожа/шерсть",
        "gi": "ЖКТ",
        "allergy": "Аллергия",
        "mobility": "Опорно-двигательное",
        "other": "Другое",
    }
    tag_order = ["allergy", "gi", "skin_coat", "mobility", "other"]
    health_items = []
    for tag in tag_order:
        note = notes_by_tag.get(tag)
        if note:
            label = tag_labels.get(tag, tag)
            health_items.append(f"• {label}: {clip(note, 200)}")
    for tag, note in notes_by_tag.items():
        if tag in tag_order or not note:
            continue
        label = tag_labels.get(tag, tag)
        health_items.append(f"• {label}: {clip(note, 200)}")
    max_blocks = 4
    if len(health_items) > max_blocks:
        extra = len(health_items) - max_blocks
        health_items = health_items[:max_blocks]
        health_items.append(f"+ ещё {extra}")
    if health_items:
        lines.append("")
        lines.append("🩺 Здоровье")
        lines.extend(health_items)

    owner_note = clip(profile.get("owner_note") or "", 350)
    if owner_note:
        lines.append("")
        lines.append("📌 Важное")
        lines.append(owner_note)

    return "\n".join(lines)


def build_my_pet_keyboard_short() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_ASK_QUESTION, callback_data="pet_profile_ask")],
            [InlineKeyboardButton(BTN_UPDATE_PROFILE, callback_data="pet_profile_update")],
            [InlineKeyboardButton(BTN_SHOW_PROFILE, callback_data="pet_profile_show")],
            [InlineKeyboardButton(BTN_HOME, callback_data="back_to_main")],
        ]
    )


def build_my_pet_keyboard_full() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_HIDE_PROFILE, callback_data="pet_profile_hide")],
            [InlineKeyboardButton(BTN_ASK_QUESTION, callback_data="pet_profile_ask")],
            [InlineKeyboardButton(BTN_UPDATE_PROFILE, callback_data="pet_profile_update")],
            [InlineKeyboardButton(BTN_HOME, callback_data="back_to_main")],
        ]
    )


async def edit_or_reply(message, text: str, reply_markup: InlineKeyboardMarkup) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        await message.reply(text, reply_markup=reply_markup)

def setup_menu_handlers(app: Client):

    @app.on_callback_query(filters.regex("^pet_(dog|cat|other)$"))
    async def handle_pet_selection(client: Client, callback_query: CallbackQuery):
        await callback_query.answer()
        pet_type = callback_query.data.split("_")[1]  # dog, cat, other

        pet_label = BTN_DOG if pet_type == "dog" else BTN_CAT if pet_type == "cat" else BTN_OTHER
        await callback_query.message.edit_text(
            f"Вы выбрали: {pet_label}\n\nЧто вас интересует?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(BTN_EMERGENCY, callback_data=f"{pet_type}_emergency")],
                [InlineKeyboardButton(BTN_CARE, callback_data=f"{pet_type}_care")],
                [InlineKeyboardButton(BTN_VACCINES, callback_data=f"{pet_type}_vaccines")],
                [InlineKeyboardButton(BTN_HOME, callback_data="back_to_main")]
            ])
        )

    @app.on_callback_query(filters.regex("^how_it_works$"))
    async def how_it_works(client: Client, callback_query: CallbackQuery):
        await callback_query.answer()
        await callback_query.message.edit_text(
            "ℹ️ Как это работает\n\n"
            "🆓 Free: я не запоминаю питомца между сессиями. Для точного ответа важно "
            "описывать питомца в сообщении.\n\n"
            "💎 Pro: можно заполнить профиль питомца один раз — и я буду учитывать его в ответах.\n\n"
            "⭐ Кнопка «Мой питомец» — просмотр/обновление профиля.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(BTN_HOME, callback_data="back_to_main")]
            ])
        )

    @app.on_callback_query(filters.regex("^my_pet$"))
    async def my_pet(client: Client, callback_query: CallbackQuery):
        await callback_query.answer()
        user_id = callback_query.from_user.id if callback_query.from_user else None
        pet_profile = None
        if user_id is not None:
            pet_profile = await asyncio.to_thread(get_active_pet, user_id)

        if pet_profile == "pro_required":
            await callback_query.message.edit_text(
                "💎 Профиль питомца доступен в Pro. Оформите Pro, чтобы заполнить анкету.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💎 Оформить Pro", callback_data="upsell_pro")],
                    [InlineKeyboardButton(BTN_HOME, callback_data="back_to_main")]
                ])
            )
            return

        if pet_profile == "no_active_pet":
            await callback_query.message.edit_text(
                "💎 Pro активен ✅\n"
                "Профиль ещё не заполнен. Заполните анкету, чтобы я запомнил питомца.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(BTN_FILL_FORM, callback_data="pet_profile_update")],
                    [InlineKeyboardButton(BTN_HOME, callback_data="back_to_main")]
                ])
            )
            return

        if pet_profile is None:
            await callback_query.message.edit_text(
                "Сервер временно недоступен, попробуйте позже.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(BTN_HOME, callback_data="back_to_main")]
                ])
            )
            return

        if isinstance(pet_profile, dict):
            normalized = normalize_pet_profile(pet_profile)
            if user_id is not None:
                set_pet_profile(user_id, normalized)
                set_pet_profile_loaded(user_id, True)
            text = format_pet_summary_short(normalized)
            await callback_query.message.edit_text(
                text,
                reply_markup=build_my_pet_keyboard_short(),
            )
            return

        await callback_query.message.edit_text(
            "Сервер временно недоступен, попробуйте позже.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(BTN_HOME, callback_data="back_to_main")]
            ])
        )

    @app.on_callback_query(filters.regex("^pet_profile_show$"))
    async def pet_profile_show(client: Client, callback_query: CallbackQuery):
        await callback_query.answer()
        user_id = callback_query.from_user.id if callback_query.from_user else None
        profile = get_pet_profile(user_id) if user_id is not None else None
        if not isinstance(profile, dict) and user_id is not None:
            active = await asyncio.to_thread(get_active_pet, user_id)
            if isinstance(active, dict):
                profile = normalize_pet_profile(active)
                set_pet_profile(user_id, profile)
                set_pet_profile_loaded(user_id, True)
        if not isinstance(profile, dict):
            await edit_or_reply(
                callback_query.message,
                "Профиль не найден. Откройте ⭐ Мой питомец ещё раз.",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton(BTN_HOME, callback_data="back_to_main")]
                ]),
            )
            return
        text = format_pet_summary_full(profile)
        await edit_or_reply(callback_query.message, text, build_my_pet_keyboard_full())

    @app.on_callback_query(filters.regex("^pet_profile_hide$"))
    async def pet_profile_hide(client: Client, callback_query: CallbackQuery):
        await callback_query.answer()
        user_id = callback_query.from_user.id if callback_query.from_user else None
        profile = get_pet_profile(user_id) if user_id is not None else None
        if not isinstance(profile, dict) and user_id is not None:
            active = await asyncio.to_thread(get_active_pet, user_id)
            if isinstance(active, dict):
                profile = normalize_pet_profile(active)
                set_pet_profile(user_id, profile)
                set_pet_profile_loaded(user_id, True)
        if not isinstance(profile, dict):
            await edit_or_reply(
                callback_query.message,
                "Профиль не найден. Откройте ⭐ Мой питомец ещё раз.",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton(BTN_HOME, callback_data="back_to_main")]
                ]),
            )
            return
        text = format_pet_summary_short(profile)
        await edit_or_reply(callback_query.message, text, build_my_pet_keyboard_short())

    @app.on_callback_query(filters.regex("^back_to_main$"))
    async def back_to_main(client: Client, callback_query: CallbackQuery):
        await callback_query.answer()
        user_id = callback_query.from_user.id if callback_query.from_user else None
        if user_id is not None and get_pro_step(user_id) != PRO_STEP_NONE:
            async def execute_go_menu():
                await show_main_menu(callback_query.message)
            await guard_dirty_or_execute(
                user_id,
                {"type": "go_menu"},
                callback_query.message,
                execute_go_menu,
            )
            return
        await show_main_menu(callback_query.message)
