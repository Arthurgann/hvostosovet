# handlers/start.py
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from services.state import reset_pro_profile
from ui.labels import (
    BTN_DOG,
    BTN_CAT,
    BTN_OTHER,
    BTN_MY_PET,
    BTN_HOW_IT_WORKS,
)

def setup_start_handlers(app: Client):

    @app.on_message(filters.command(["start", "menu"]))
    async def start_handler(client: Client, message: Message):
        user_id = message.from_user.id if message.from_user else None

        if user_id is not None:
            reset_pro_profile(user_id)
        await message.reply_text(
            "Привет! 🐾 Я - ХвостоСовет, твой помощник по заботе о питомце.\n\n"
            "Выберите, кто ваш питомец:\n\n"
            "Или откройте «Мой питомец», чтобы управлять профилем.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(BTN_DOG, callback_data="pet_dog")],
                [InlineKeyboardButton(BTN_CAT, callback_data="pet_cat")],
                [InlineKeyboardButton(BTN_OTHER, callback_data="pet_other")],
                [InlineKeyboardButton(BTN_MY_PET, callback_data="my_pet")],
                [InlineKeyboardButton(BTN_HOW_IT_WORKS, callback_data="how_it_works")]
            ])
        )
