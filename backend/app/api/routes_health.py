from fastapi import APIRouter

from app.core.config import APP_VERSION
from app.core.db import db_ping

router = APIRouter()

@router.get("/health")
def health() -> dict:
    ok, err = db_ping()
    return {
        "ok": True,
        "version": APP_VERSION,
        "db": "ok" if ok else "fail",
        "db_error": err if not ok else None,
    }

