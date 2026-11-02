"""FastAPI routes for the SPV School App (used by main.py locally and api/index.py on Vercel)."""
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app_agent import ROLE_TOOLS, home, role_chat

router = APIRouter(prefix="/api/app")


class RoleChatIn(BaseModel):
    role: str = Field(pattern="^(" + "|".join(ROLE_TOOLS) + ")$")
    message: str = Field(min_length=1, max_length=4000)
    history: list[dict] = []


@router.post("/chat")
def app_chat(body: RoleChatIn):
    return {"reply": role_chat(body.role, body.message, body.history[-10:])}


@router.get("/home")
def app_home(role: str = "parent"):
    return home(role)
