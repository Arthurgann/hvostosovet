# config.py
import os

try:
    # pip install python-dotenv
    from dotenv import load_dotenv
    load_dotenv()  # загрузит переменные из .env, если файл есть
except Exception:
    # Если python-dotenv не установлен — просто читаем из окружения
    pass


def _need(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


BOT_TOKEN = _need("BOT_TOKEN")

# API_ID должен быть числом
API_ID = int(_need("API_ID"))

API_HASH = _need("API_HASH")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Модель можно не задавать - будет дефолт
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()

BOT_DEBUG = os.getenv("BOT_DEBUG", "0") == "1"
