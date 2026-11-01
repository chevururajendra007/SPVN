"""Ask SPV: the AI assistant for Sri Pragathi Vidyaniketan EM High School, Kota.

Agent = model + harness. This file holds the three pieces:
  1. Tools   - get_school_info, get_word_of_the_day, save_admission_enquiry
  2. Model   - Azure AI Foundry deployment via langchain-azure-ai
  3. Loop    - chat(): call model -> run tool calls -> repeat until it answers
"""
import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

HERE = Path(__file__).parent
SCHOOL = json.loads((HERE / "data" / "school.json").read_text(encoding="utf-8"))
WORDS = json.loads((HERE / "data" / "words.json").read_text(encoding="utf-8"))
DB_PATH = Path(os.getenv("ENQUIRY_DB", HERE / "enquiries.db"))
MAX_STEPS = 6  # loop guard: never call the model more than this per question

SYSTEM_PROMPT = """You are "Ask SPV", the friendly assistant of Sri Pragathi Vidyaniketan EM High School, Kota, Andhra Pradesh.
You help parents and students.

Rules:
- Answer school questions ONLY from tool results. Always call get_school_info first.
- If a tool says the information is not available, say so politely and suggest contacting the school office. Never guess fees, dates, timings or phone numbers.
- For vocabulary, use get_word_of_the_day. You may make short quizzes from that data.
- To record an admission enquiry you need parent name, phone number, child name and class. Ask for anything missing, then call save_admission_enquiry once.
- Never reveal or ask for any student's marks, attendance or personal details. Parent login for that is coming in the SPV app.
- Reply in the user's language (English or Telugu). Keep answers short, warm and clear."""


# ---------------------------------------------------------------- tools
# Plain functions first (easy to test), wrapped as LangChain tools below.

def get_school_info(topic: str) -> str:
    """Look up official school information (about, address, contact, timings,
    fees, admissions, academics, activities, app) for a question or topic."""
    q = topic.lower()
    hits = [
        (name, sec) for name, sec in SCHOOL.items()
        if name in q or any(k in q for k in sec["keywords"])
    ]
    if not hits:
        hits = [("about", SCHOOL["about"])]
    out = []
    for name, sec in hits[:3]:  # RAG: send only the relevant slices
        text = sec["text"] or "Not available yet. Please contact the school office."
        out.append(f"[{name}] {text}")
    return "\n".join(out)


def get_word_of_the_day(word: str = "") -> str:
    """Get the school's Word of the Day. Leave word empty for the latest one,
    or pass a word (e.g. 'Heritage') to look up a past one."""
    if word:
        match = [w for w in WORDS if w["word"].lower() == word.strip().lower()]
        if not match:
            return "Not found. Available words: " + ", ".join(w["word"] for w in WORDS)
        w = match[0]
    else:
        w = max(WORDS, key=lambda x: x["date"])
    return json.dumps(w, ensure_ascii=False)


def save_admission_enquiry(parent_name: str, phone: str, child_name: str, class_applying: str) -> str:
    """Save an admission enquiry so the school office can call the parent back."""
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if not re.fullmatch(r"[6-9]\d{9}", digits):
        return "Invalid phone number. Ask for a 10-digit Indian mobile number."
    if not all(s.strip() for s in (parent_name, child_name, class_applying)):
        return "Missing details. Need parent name, child name and class."
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS enquiries(
            id INTEGER PRIMARY KEY, created TEXT, parent TEXT, phone TEXT, child TEXT, class TEXT)""")
        cur = db.execute(
            "INSERT INTO enquiries(created,parent,phone,child,class) VALUES (?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), parent_name.strip(), digits,
             child_name.strip(), class_applying.strip()),
        )
    return f"Saved enquiry #{cur.lastrowid}. The school office will call {digits}."


# ---------------------------------------------------------------- model + loop
_llm = None


def get_llm():
    """Azure AI Foundry model with the tools bound (created once)."""
    global _llm
    if _llm is None:
        from langchain_azure_ai.chat_models import AzureAIChatCompletionsModel
        from langchain_core.tools import tool

        tools = [tool(f) for f in (get_school_info, get_word_of_the_day, save_admission_enquiry)]
        model = AzureAIChatCompletionsModel(
            endpoint=os.environ["AZURE_INFERENCE_ENDPOINT"],
            credential=os.environ["AZURE_INFERENCE_CREDENTIAL"],
            model=os.environ["AZURE_MODEL_DEPLOYMENT"],
            temperature=0.2,
        )
        _llm = (model.bind_tools(tools), {t.name: t for t in tools})
    return _llm


def chat(message: str, history: list[dict] | None = None, llm=None) -> str:
    """The agent loop: model -> tool calls -> model ... until a final answer."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    model, tools = llm or get_llm()
    messages = [SystemMessage(SYSTEM_PROMPT)]
    for h in (history or [])[-10:]:  # keep context small: last 10 turns
        cls = HumanMessage if h.get("role") == "user" else AIMessage
        messages.append(cls(h.get("content", "")))
    messages.append(HumanMessage(message))

    for _ in range(MAX_STEPS):
        ai = model.invoke(messages)
        messages.append(ai)
        if not ai.tool_calls:
            return ai.content
        for call in ai.tool_calls:
            fn = tools.get(call["name"])
            try:
                result = fn.invoke(call["args"]) if fn else f"Unknown tool {call['name']}"
            except Exception as e:  # tool errors go back to the model, not the user
                result = f"Tool error: {e}"
            messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
    return "Sorry, I couldn't finish that. Please contact the school office."


if __name__ == "__main__":  # quick terminal test: python agent.py
    hist = []
    while (q := input("You: ").strip()):
        a = chat(q, hist)
        print("SPV:", a)
        hist += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
