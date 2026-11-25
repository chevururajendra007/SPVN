"""Scan or upload a lesson -> simple summary for students (and optionally send it to parents).

Input: up to 4 photos (phone camera), a PDF, or pasted text.
AI:    Vercel AI Gateway (OpenAI-compatible), default model google/gemini-2.5-flash (reads photos).
       Auth: AI_GATEWAY_API_KEY, or the Vercel OIDC token the platform gives every function.
Without AI (or for text/PDF with a text layer when AI is down) a simple extractive summary is made,
so the feature never breaks. Lesson pages are textbook content, not personal data.
"""
import base64
import io
import json
import os
import re
import time
import urllib.request

import notify
import store

GATEWAY = "https://ai-gateway.vercel.sh/v1/chat/completions"
MODEL = os.getenv("LESSON_MODEL", "google/gemini-2.5-flash")
MAX_IMAGES = 4
SCHOOL = "Sri Pragathi Vidyaniketan"

PROMPT = """You help school children in Kota, Andhra Pradesh understand a lesson.
Class: {cls}. Subject: {subject}.
Summarise ONLY the lesson content given (photos or text). If a page is unreadable, say which part.
Write in simple English for this class level. Use this exact format:

TITLE: <lesson title>
KEY POINTS:
- <5 to 8 short points>
KEY WORDS:
- <word> - <simple meaning> (Telugu: <Telugu word>)
REMEMBER IT:
- <2 or 3 memory tips or a short rhyme>
QUICK QUIZ:
1. <question> - Answer: <answer>
(5 questions)
Keep it under 350 words. Do not add facts that are not in the lesson."""


def _token(oidc_header: str | None) -> str | None:
    return os.getenv("AI_GATEWAY_API_KEY") or oidc_header or os.getenv("VERCEL_OIDC_TOKEN")


def ai_ready(oidc_header: str | None = None) -> bool:
    return bool(_token(oidc_header))


def _call_ai(content: list, oidc_header: str | None) -> str:
    body = {"model": MODEL, "messages": [{"role": "user", "content": content}], "max_tokens": 1400,
            "temperature": 0.2}
    req = urllib.request.Request(GATEWAY, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {_token(oidc_header)}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=50) as r:
        out = json.loads(r.read())
    return out["choices"][0]["message"]["content"].strip()


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages[:15]).strip()


def simple_summary(text: str) -> str:
    """No-AI fallback: pick the most important sentences and words."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.split()) > 3]
    if len(sentences) < 2:
        raise ValueError("Not enough text to summarise. Add a photo or paste more of the lesson.")
    words = re.findall(r"[A-Za-z]{5,}", text.lower())
    freq = {w: words.count(w) for w in set(words)}
    score = lambda s: sum(freq.get(w, 0) for w in re.findall(r"[A-Za-z]{5,}", s.lower())) / (len(s.split()) ** .5)
    top = set(sorted(sentences, key=score, reverse=True)[:6])
    keys = sorted(freq, key=freq.get, reverse=True)[:6]
    return ("TITLE: Lesson summary\nKEY POINTS:\n" + "\n".join(f"- {s}" for s in sentences if s in top)
            + "\nKEY WORDS:\n" + "\n".join(f"- {k}" for k in keys)
            + "\n(Simple summary without AI. Photos need the AI service.)")


def _data_url_bytes(u: str) -> tuple[str, bytes]:
    m = re.match(r"data:([\w/+.-]+);base64,(.+)", u or "", re.S)
    if not m:
        raise ValueError("Unreadable file")
    return m.group(1), base64.b64decode(m.group(2))


def summarize(cls: int, subject: str, images: list[str] | None, pdf: str | None, text: str | None,
              oidc_header: str | None = None) -> dict:
    images = (images or [])[:MAX_IMAGES]
    text = (text or "").strip()
    if pdf:
        mime, data = _data_url_bytes(pdf)
        if mime != "application/pdf":
            raise ValueError("Only PDF files are accepted here")
        extracted = pdf_text(data)
        if len(extracted) < 80 and not images:
            raise ValueError("This PDF looks like a scan with no text. Upload photos of the pages instead.")
        text = (text + "\n" + extracted).strip()
    if not images and not text:
        raise ValueError("Take a photo, upload a PDF, or paste the lesson text")
    for u in images:
        mime, data = _data_url_bytes(u)
        if not mime.startswith("image/") or len(data) > 2_500_000:
            raise ValueError("Each photo must be an image under 2.5 MB")
    if ai_ready(oidc_header):
        content = [{"type": "text", "text": PROMPT.format(cls=cls, subject=subject or "General")}]
        if text:
            content.append({"type": "text", "text": "LESSON TEXT:\n" + text[:20000]})
        content += [{"type": "image_url", "image_url": {"url": u}} for u in images]
        try:
            return {"summary": _call_ai(content, oidc_header), "source": "ai", "pages": len(images)}
        except Exception as e:
            print(f"[lessons] AI failed: {type(e).__name__}: {e}")
            if not text:
                raise ValueError("The AI service is busy. Please try again in a minute.")
    elif not text:
        raise ValueError("Reading photos needs the AI service, which is not switched on yet. Paste the text instead.")
    return {"summary": simple_summary(text), "source": "simple", "pages": len(images)}


def save_note(cls, subject, summary, by_phone, by_name, send=True) -> dict:
    summary = (summary or "").strip()
    if not summary:
        raise ValueError("Nothing to save")
    title = next((l.split(":", 1)[1].strip() for l in summary.splitlines() if l.upper().startswith("TITLE:")),
                 subject or "Lesson")
    item = {"id": f"l{int(time.time() * 1000)}", "class": int(cls), "subject": (subject or "").strip()[:40],
            "title": title[:120], "summary": summary[:6000], "by": by_name, "at": int(time.time())}
    from school import class_students, today
    item["date"] = today()
    store.push(f"lessons:{int(cls)}", item, cap=150)
    res = {"item": item}
    if send:
        msg = (f"Lesson notes - Class {cls} ({item['subject']}): {item['title']}\n"
               f"Open the SPV app (My children) to read the full summary.\n- {by_name}, {SCHOOL}")
        sent = [notify.send(s["phone"], msg, "homework", {"class": int(cls), "lesson": item["id"]})
                for s in class_students(cls)]
        res["messages"] = {k: sum(m["status"] == k for m in sent) for k in ("sent", "queued", "skipped", "failed")}
        res["group_link"] = notify.wa_link(None, msg + "\n\n" + item["summary"][:1500])
    return res


def notes(cls, limit=10) -> list[dict]:
    return (store.get(f"lessons:{int(cls)}", []) or [])[:limit]
