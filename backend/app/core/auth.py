from fastapi import Header, HTTPException, status

from app.core.config import BOT_BACKEND_TOKEN


def require_bot_token(authorization: str | None = Header(default=None)) -> None:
    if not BOT_BACKEND_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="server_misconfigured",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    token = authorization.removeprefix("Bearer ").strip()
    if token != BOT_BACKEND_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
