from pyrogram import Client, filters
from pyrogram.types import Message
import config

app = Client(
    "hvostosovet_bot",
    bot_token=config.BOT_TOKEN,
    api_id=config.API_ID,
    api_hash=config.API_HASH
)

@app.on_message(filters.private & filters.text, group=-1)
async def log_incoming_private(client_tg: Client, message: Message):
    user_id = message.from_user.id if message.from_user else None
    text = message.text or ""
    if config.BOT_DEBUG:
        preview = text.replace("\n", " ").replace("\r", " ")[:80]
        has_photo = bool(message.photo)
        has_voice = bool(message.voice)
        has_audio = bool(message.audio)
        has_document = bool(message.document)
        print(
            f"[IN] user_id={user_id} text_len={len(text)} preview=\"{preview}\" "
            f"has_photo={has_photo} has_voice={has_voice} "
            f"has_audio={has_audio} has_document={has_document}"
        )

# ▶️ Подключение всех хендлеров
from handlers.start import setup_start_handlers
from handlers.menu import setup_menu_handlers
from handlers.help import setup_help_handlers
from handlers.question import setup_question_handlers  #  добавляем анкету

setup_start_handlers(app)
setup_menu_handlers(app)
setup_help_handlers(app)
setup_question_handlers(app)  #  подключаем анкету

# ▶️ Запуск
print("Бот запущен! 🐾 Жду команд...")
app.run()
