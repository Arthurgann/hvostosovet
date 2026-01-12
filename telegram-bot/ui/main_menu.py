from pyrogram.types import Message
from ui.keyboards import kb_main_menu
from ui.texts import TEXT_MAIN_MENU


async def show_main_menu(message: Message) -> None:
    await message.edit_text(
        TEXT_MAIN_MENU,
        reply_markup=kb_main_menu(),
    )
