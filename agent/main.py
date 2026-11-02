"""FastAPI server: POST /api/chat calls chat(); the chat page is served at /."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent import PROVIDER, chat

app = FastAPI(title="Ask SPV")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["POST"], allow_headers=["*"])


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[dict] = []


@app.post("/api/chat")
def api_chat(body: ChatIn):
    return {"reply": chat(body.message, body.history)}


@app.get("/api/health")
def health():
    return {"ok": True, "provider": PROVIDER}


# Chat page at http://localhost:8000 (must be mounted last)
app.mount("/", StaticFiles(directory=Path(__file__).parent / "web", html=True), name="web")
