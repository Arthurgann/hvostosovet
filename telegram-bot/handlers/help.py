from pyrogram import Client, filters
from pyrogram.types import Message


def setup_help_handlers(app: Client):
    @app.on_message(filters.command("help") & filters.private)
    async def help_handler(client: Client, message: Message):
        await message.reply_text(
            "Я помогаю с ориентированием по состоянию питомца.\n"
            "Чтобы ответ был точнее, укажите вид, возраст и симптомы.\n"
            "Free: данные питомца не сохраняются.\n"
            "Это не замена ветеринару; при тяжелых симптомах — срочно к врачу."
        )
