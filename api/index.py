"""Vercel serverless entry.

Public:  POST /api/chat (Ask SPV on the website), GET /api/health, GET|POST /api/van/loc/<key> (van phones)
Login:   /api/auth/*, /api/portal/* (parents, teachers, principal, correspondent, admin)
Cron:    /api/cron/fee-reminders (daily, Vercel Cron)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from fastapi import FastAPI  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from agent import PROVIDER, chat  # noqa: E402
from portal_api import router as portal_router  # noqa: E402
from van import router as van_router  # noqa: E402

app = FastAPI(title="SPV School")
app.include_router(portal_router)
app.include_router(van_router)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[dict] = []


@app.post("/api/chat")
def api_chat(body: ChatIn):
    return {"reply": chat(body.message, body.history[-10:])}


@app.get("/api/health")
def health():
    return {"ok": True, "provider": PROVIDER}
