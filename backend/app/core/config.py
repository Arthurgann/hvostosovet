import os

APP_VERSION = os.getenv("APP_VERSION", "0.1.0")
BOT_BACKEND_TOKEN = os.getenv("BOT_BACKEND_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
SESSION_TTL_MIN = int(os.getenv("SESSION_TTL_MIN", "60"))
PRO_SESSION_TTL_MIN = int(os.getenv("PRO_SESSION_TTL_MIN", "43200"))
SESSION_MAX_TURNS = int(os.getenv("SESSION_MAX_TURNS", "6"))
