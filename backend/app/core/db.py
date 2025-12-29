import psycopg
from app.core.config import DATABASE_URL


def get_connection() -> psycopg.Connection:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    # connect_timeout помогает не зависать
    return psycopg.connect(DATABASE_URL, connect_timeout=5)


def db_ping() -> tuple[bool, str]:
    """
    Возвращает (ok, error_code). error_code безопасен: без паролей/DSN.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
        return True, ""
    except Exception as e:
        # только тип и короткое сообщение (без DSN)
        msg = str(e)
        if DATABASE_URL:
            msg = msg.replace(DATABASE_URL, "<redacted>")
        return False, f"{type(e).__name__}: {msg[:180]}"
