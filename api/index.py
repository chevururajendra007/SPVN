"""Vercel serverless entry: the same Ask SPV agent behind POST /api/chat."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from fastapi import FastAPI  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from agent import PROVIDER, chat  # noqa: E402
from app_api import router as app_router  # noqa: E402

app = FastAPI(title="Ask SPV")
app.include_router(app_router)  # SPV School App: /api/app/chat, /api/app/home


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[dict] = []


@app.post("/api/chat")
def api_chat(body: ChatIn):
    return {"reply": chat(body.message, body.history[-10:])}


@app.get("/api/health")
def health():
    return {"ok": True, "provider": PROVIDER}
