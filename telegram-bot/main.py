from pyrogram import Client
import config

app = Client(
    "hvostosovet_bot",
    bot_token=config.BOT_TOKEN,
    api_id=config.API_ID,
    api_hash=config.API_HASH
)

# 🔌 Подключение всех хендлеров
from handlers.start import setup_start_handlers
from handlers.menu import setup_menu_handlers
from handlers.question import setup_question_handlers  # ← добавляем анкету

setup_start_handlers(app)
setup_menu_handlers(app)
setup_question_handlers(app)  # ← подключаем анкету

# ▶️ Запуск
print("Бот запущен! 🐾 Жду команд...")
app.run()


