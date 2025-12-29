from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI

from app.api.routes_health import router as health_router
from app.api.routes_me import router as me_router
from app.api.routes_chat import router as chat_router


def create_app() -> FastAPI:
    app = FastAPI(title="hvostosovet-backend")
    app.include_router(health_router, prefix="/v1")
    app.include_router(me_router, prefix="/v1")
    app.include_router(chat_router, prefix="/v1")
    return app


app = create_app()
