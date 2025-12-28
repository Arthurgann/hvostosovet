from fastapi import APIRouter

from app.core.config import APP_VERSION

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"ok": True, "version": APP_VERSION}
