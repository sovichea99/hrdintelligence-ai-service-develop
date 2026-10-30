from fastapi import APIRouter

from app.api.endpoints import chat

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(chat.router)
