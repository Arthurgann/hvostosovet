# handlers/start.py
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from services.state import reset_pro_profile

def setup_start_handlers(app: Client):

    @app.on_message(filters.command(["start", "menu"]))
    async def start_handler(client: Client, message: Message):
        if message.from_user:
            reset_pro_profile(message.from_user.id)
        await message.reply_text(
            "Привет! 🐾 Я — ХвостоСовет, твой помощник по заботе о питомце.\n\nВыберите, кто ваш питомец:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🐶 Собака", callback_data="pet_dog")],
                [InlineKeyboardButton("🐱 Кошка", callback_data="pet_cat")],
                [InlineKeyboardButton("🐠🐹🦎🦜 Другой", callback_data="pet_other")]
            ])
        )
