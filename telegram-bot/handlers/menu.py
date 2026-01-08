# handlers/menu.py

import asyncio
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from services.backend_client import get_active_pet
from services.state import set_pet_profile, set_pet_profile_loaded

def setup_menu_handlers(app: Client):

    def build_main_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🐶 Собака", callback_data="pet_dog")],
            [InlineKeyboardButton("🐱 Кошка", callback_data="pet_cat")],
            [InlineKeyboardButton("🐾 Другое", callback_data="pet_other")],
            [InlineKeyboardButton("⭐ Мой питомец", callback_data="my_pet")],
            [InlineKeyboardButton("ℹ️ Как это работает / Тарифы", callback_data="how_it_works")]
        ])

    @app.on_callback_query(filters.regex("^pet_(dog|cat|other)$"))
    async def handle_pet_selection(client: Client, callback_query: CallbackQuery):
        await callback_query.answer()
        pet_type = callback_query.data.split("_")[1]  # dog, cat, other

        await callback_query.message.edit_text(
            f"Вы выбрали: {'?? Собака' if pet_type == 'dog' else '?? Кошка' if pet_type == 'cat' else '?? Другой'}\n\nЧто вас интересует?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚑 Скорая помощь", callback_data=f"{pet_type}_emergency")],
                [InlineKeyboardButton("🍖 Питание и уход", callback_data=f"{pet_type}_care")],
                [InlineKeyboardButton("💉 Прививки и профилактика", callback_data=f"{pet_type}_vaccines")],
                [InlineKeyboardButton("🏠 В главное меню", callback_data="back_to_main")]
            ])
        )

    @app.on_callback_query(filters.regex("^how_it_works$"))
    async def how_it_works(client: Client, callback_query: CallbackQuery):
        await callback_query.answer()
        await callback_query.message.edit_text(
            "?? Как это работает\n\n"
            "?? Free: я не запоминаю питомца между сессиями. Для точного ответа важно "
            "описывать питомца в сообщении.\n\n"
            "?? Pro: можно заполнить профиль питомца один раз — и я буду учитывать его в ответах.\n\n"
            "? Кнопка «Мой питомец» — просмотр/обновление профиля.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("?? В меню", callback_data="back_to_main")]
            ])
        )

    @app.on_callback_query(filters.regex("^my_pet$"))
    async def my_pet(client: Client, callback_query: CallbackQuery):
        await callback_query.answer()
        user_id = callback_query.from_user.id if callback_query.from_user else None
        pet_profile = None
        if user_id is not None:
            pet_profile = await asyncio.to_thread(get_active_pet, user_id)

        if pet_profile:
            name = pet_profile.get("name")
            text = "?? Я помню вашего питомца"
            if name:
                text = f"{text} {name}"
            if user_id is not None:
                normalized = {}
                profile = pet_profile.get("profile")
                if isinstance(profile, dict):
                    normalized = dict(profile)
                for key in ["type", "name", "sex", "breed", "age_text", "bcs", "vaccines", "parasites"]:
                    if pet_profile.get(key) is not None:
                        normalized[key] = pet_profile.get(key)
                normalized.pop("id", None)
                normalized.pop("profile", None)
                set_pet_profile(user_id, normalized)
                set_pet_profile_loaded(user_id, True)
            await callback_query.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❓ Задать вопрос", callback_data="pet_profile_ask")],
                    [InlineKeyboardButton("✏️ Обновить профиль", callback_data="pet_profile_update")],
                    [InlineKeyboardButton("🏠 В меню", callback_data="back_to_main")]
                ])
            )
            return

        await callback_query.message.edit_text(
            "Профиль питомца ещё не заполнен. Хотите заполнить сейчас?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✍️ Заполнить анкету", callback_data="pet_profile_update")],
                [InlineKeyboardButton("🏠 В меню", callback_data="back_to_main")]
            ])
        )

    @app.on_callback_query(filters.regex("^back_to_main$"))
    async def back_to_main(client: Client, callback_query: CallbackQuery):
        await callback_query.answer()
        await callback_query.message.edit_text(
            "Привет! ?? Я - ХвостоСовет, твой помощник по заботе о питомце.\n\n"
            "Выберите, кто ваш питомец:\n\n"
            "Или откройте «Мой питомец», чтобы управлять профилем.",
            reply_markup=build_main_menu()
        )
