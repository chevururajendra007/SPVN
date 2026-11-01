"""FastAPI server: one route, POST /api/chat, that calls chat()."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agent import chat

app = FastAPI(title="Ask SPV")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["POST"], allow_headers=["*"])


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[dict] = []


@app.post("/api/chat")
def api_chat(body: ChatIn):
    return {"reply": chat(body.message, body.history)}
