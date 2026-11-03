"""FastAPI server: POST /api/chat calls chat(); the chat page is served at /."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent import PROVIDER, chat
from app_api import router as app_router
from van import router as van_router

app = FastAPI(title="Ask SPV")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[dict] = []


@app.post("/api/chat")
def api_chat(body: ChatIn):
    return {"reply": chat(body.message, body.history)}


app.include_router(app_router)  # SPV School App: /api/app/chat, /api/app/home
app.include_router(van_router)  # school van GPS: /api/van/loc/<key>, /api/van/latest


@app.get("/api/health")
def health():
    return {"ok": True, "provider": PROVIDER}


# School app at http://localhost:8000/app, chat page at / (mounted last)
app.mount("/app", StaticFiles(directory=Path(__file__).parent.parent / "app", html=True), name="app")
app.mount("/", StaticFiles(directory=Path(__file__).parent / "web", html=True), name="web")
