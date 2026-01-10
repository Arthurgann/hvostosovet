from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from ui.labels import (
    BTN_DOG,
    BTN_CAT,
    BTN_OTHER,
    BTN_MY_PET,
    BTN_HOW_IT_WORKS,
)


def build_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_DOG, callback_data="pet_dog")],
            [InlineKeyboardButton(BTN_CAT, callback_data="pet_cat")],
            [InlineKeyboardButton(BTN_OTHER, callback_data="pet_other")],
            [InlineKeyboardButton(BTN_MY_PET, callback_data="my_pet")],
            [InlineKeyboardButton(BTN_HOW_IT_WORKS, callback_data="how_it_works")],
        ]
    )


async def show_main_menu(message: Message) -> None:
    await message.edit_text(
        "Привет! 🐾 Я - ХвостоСовет, твой помощник по заботе о питомце.\n\n"
        "Выберите, кто ваш питомец:\n\n"
        "Или откройте <Мой питомец>, чтобы управлять профилем.",
        reply_markup=build_main_menu(),
    )
