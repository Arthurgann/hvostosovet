# handlers/menu.py

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

def setup_menu_handlers(app: Client):

    @app.on_callback_query(filters.regex("^pet_"))
    async def handle_pet_selection(client: Client, callback_query: CallbackQuery):
        await callback_query.answer()
        pet_type = callback_query.data.split("_")[1]  # dog, cat, other

        await callback_query.message.edit_text(
            f"Вы выбрали: {'🐶 Собака' if pet_type == 'dog' else '🐱 Кошка' if pet_type == 'cat' else '🐾 Другой'}\n\nЧто вас интересует?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚑 Скорая помощь", callback_data=f"{pet_type}_emergency")],
                [InlineKeyboardButton("🍖 Питание и уход", callback_data=f"{pet_type}_care")],
                [InlineKeyboardButton("💉 Прививки, профилактика, гигиена", callback_data=f"{pet_type}_health")],
                [InlineKeyboardButton("🏠 В главное меню", callback_data="back_to_main")]
            ])
        )

    @app.on_callback_query(filters.regex("^back_to_main$"))
    async def back_to_main(client: Client, callback_query: CallbackQuery):
        await callback_query.answer()
        await callback_query.message.edit_text(
            "Привет! 🐾 Я — ХвостоСовет, твой помощник по заботе о питомце.\n\nВыберите, кто ваш питомец:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🐶 Собака", callback_data="pet_dog")],
                [InlineKeyboardButton("🐱 Кошка", callback_data="pet_cat")],
                [InlineKeyboardButton("🐠🐹🦎🦜 Другой", callback_data="pet_other")]
            ])
        )
