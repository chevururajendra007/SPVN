"""SPV School App agent: one agent, six roles.

Same pattern as agent.py (model + harness), plus role-based access:
each role gets its own system prompt and ONLY its own tools. The server
decides which tools a role can use, so the model cannot reach another
role's data even if a user asks it to.

Roles: student, parent, teacher, staff, admin, correspondent.
Data: data/demo.json is DEMO data until the school database is connected.
"""
import json
import re

from agent import (HERE, PROVIDER, WORDS, get_notices, get_school_info,
                   get_word_of_the_day, offline_answer)

DEMO = json.loads((HERE / "data" / "demo.json").read_text(encoding="utf-8"))
MAX_STEPS = 6
DEMO_TAG = "(demo data)"


# ---------------------------------------------------------------- role tools
def get_my_timetable() -> str:
    """Student: today's periods."""
    s = DEMO["student"]
    return f"{s['class']} today {DEMO_TAG}: " + " → ".join(s["timetable_today"])


def get_my_homework() -> str:
    """Student: pending homework and upcoming tests."""
    s = DEMO["student"]
    hw = "\n".join(f"- {h['subject']}: {h['task']} (due {h['due']})" for h in s["homework"])
    tests = "\n".join(f"- {t['subject']} test on {t['topic']}: {t['date']}" for t in s["tests"])
    return f"Homework {DEMO_TAG}:\n{hw}\nUpcoming tests:\n{tests}"


def make_word_quiz(word: str = "") -> str:
    """Student: a 3-question quiz on a Word of the Day (latest if empty)."""
    known = any(x["word"].lower() == word.strip().lower() for x in WORDS)
    w = json.loads(get_word_of_the_day(word if known else ""))
    return (f"Quiz on '{w['word']}' ({w['telugu']}):\n"
            f"1. What does '{w['word']}' mean?\n"
            f"2. Give one synonym. (Hint: {w['synonyms'][0][0]}…)\n"
            f"3. Give one antonym. (Hint: {w['antonyms'][0][0]}…)\n"
            f"Answers: {w['meaning']} | {', '.join(w['synonyms'][:3])} | {', '.join(w['antonyms'][:3])}")


def summarize_chapter(text: str) -> str:
    """Student/teacher: short revision summary of chapter text (paste the text)."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.split()) > 3]
    if len(sentences) < 2:
        return "Please paste at least a few sentences from the chapter."
    words = re.findall(r"[a-zA-Z]{5,}", text.lower())
    freq = {w: words.count(w) for w in set(words)}
    ranked = sorted(sentences, key=lambda s: -sum(freq.get(w, 0) for w in re.findall(r"[a-zA-Z]{5,}", s.lower())))
    keep = [s for s in sentences if s in ranked[:4]]  # keep original order
    keys = sorted(freq, key=freq.get, reverse=True)[:5]
    return "Summary:\n" + "\n".join(f"- {s}" for s in keep) + f"\nKey words: {', '.join(keys)}"


def get_child_summary() -> str:
    """Parent: own child's attendance, homework, fees and teacher remark."""
    p = DEMO["parent"]
    hw = "; ".join(f"{h['subject']}: {h['task']}" for h in DEMO["student"]["homework"])
    return (f"{p['child']}, {p['class']} {DEMO_TAG}\nAttendance: {p['attendance']}\n"
            f"Homework: {hw}\nFees: {p['fees']}\nTeacher's remark: {p['remark']}")


def get_my_classes() -> str:
    """Teacher: today's periods and class list."""
    t = DEMO["teacher"]
    cls = t["class_teacher_of"]
    return (f"Periods today {DEMO_TAG}: " + ", ".join(t["periods_today"]) +
            f"\nClass teacher of {cls}: " + ", ".join(t["class_list"][cls]))


def mark_attendance(class_name: str, absent_rolls: str = "") -> str:
    """Teacher: mark attendance. Give the class and absent roll numbers (e.g. '3, 5')."""
    roster = DEMO["teacher"]["class_list"].get(class_name.strip()) or DEMO["teacher"]["class_list"]["Class 5-A"]
    absent = {r.strip() for r in re.split(r"[,\s]+", absent_rolls) if r.strip()}
    names = [s for s in roster if s.split()[0] in absent]
    return (f"Attendance draft for {class_name or 'Class 5-A'}: {len(roster) - len(names)} present, "
            f"{len(names)} absent ({', '.join(names) or 'none'}). Parents of absent students would get an SMS. "
            "This demo does not save it yet; saving goes live when the school database is connected.")


def draft_notice(title: str, text: str, audience: str = "all parents") -> str:
    """Teacher/admin: draft a notice or homework post for approval."""
    return (f"Draft notice for {audience}:\n{title.strip()}\n{text.strip()}\n"
            "Status: waiting for admin approval (publishing goes live when the school database is connected).")


def get_office_tasks() -> str:
    """Staff: pending admission enquiries, fee reminders and visitors."""
    s = DEMO["staff"]
    enq = "\n".join(f"- {e['parent']}, {e['class']} (since {e['since']})" for e in s["pending_enquiries"])
    return (f"Office today {DEMO_TAG}:\nCall back these enquiries:\n{enq}\n"
            f"Fee reminders due: {s['fee_reminders_due']}\nVisitors today: {s['visitors_today']}")


def get_admin_overview() -> str:
    """Admin: users by role and pending approvals."""
    a = DEMO["admin"]
    users = ", ".join(f"{v} {k}" for k, v in a["users"].items())
    return f"App users {DEMO_TAG}: {users}. Pending approvals: {a['pending_approvals']}."


def get_school_overview() -> str:
    """Correspondent: whole-school dashboard (strength, attendance, fees, admissions)."""
    c = DEMO["correspondent"]
    return (f"School today {DEMO_TAG}:\nStrength: {c['strength']} students\n"
            f"Attendance today: {c['attendance_today_pct']}%\nStaff present: {c['staff_present']}\n"
            f"Fee collection this term: {c['fee_collection_pct']}%\n"
            f"Enquiries this month: {c['enquiries_this_month']}, admissions: {c['admissions_this_month']}\n"
            f"Highlight: {c['highlight']}")


COMMON = [get_school_info, get_word_of_the_day, get_notices]
ROLE_TOOLS = {
    "student": COMMON + [get_my_timetable, get_my_homework, make_word_quiz, summarize_chapter],
    "parent": COMMON + [get_child_summary],
    "teacher": COMMON + [get_my_classes, mark_attendance, draft_notice, summarize_chapter, make_word_quiz],
    "staff": COMMON + [get_office_tasks],
    "admin": COMMON + [get_admin_overview, draft_notice],
    "correspondent": COMMON + [get_school_overview, get_admin_overview],
}
ROLE_INFO = {
    "student": "a student. Be encouraging and simple. Help with homework, revision and vocabulary; never give answers to tests.",
    "parent": "a parent. Share only their own child's information from get_child_summary.",
    "teacher": "a teacher. Help with attendance, homework posts, lesson summaries and quizzes.",
    "staff": "office staff. Help with enquiries, fee reminders and visitors.",
    "admin": "the school admin. Help manage users, notices and approvals.",
    "correspondent": "the school correspondent (management). Give short, numbers-first summaries of the whole school.",
}


def system_prompt(role: str) -> str:
    return f"""You are "Ask SPV" inside the SPV School App of Sri Pragathi Vidyaniketan EM High School, Kota.
You are talking to {ROLE_INFO[role]}
Rules:
- Use tools for facts. Never guess fees, dates, marks or phone numbers.
- You can only use the tools given to you. If asked for something outside this role, say it is not available for this role.
- Data marked (demo data) is sample data; mention that if asked whether it is real.
- Reply in the user's language (English or Telugu). Keep answers short and clear."""


# ---------------------------------------------------------------- offline router (no model needed)
ROUTES = {  # (keywords, tool) checked in order, only within the role's tools
    "student": [(("timetable", "period", "today class", "schedule"), get_my_timetable),
                (("homework", "test", "exam", "assignment", "హోంవర్క్"), get_my_homework),
                (("quiz",), make_word_quiz)],
    "parent": [(("child", "attendance", "homework", "fee", "remark", "progress", "my son", "my daughter", "హాజరు", "ఫీజు"), get_child_summary)],
    "teacher": [(("period", "class list", "my class", "today"), get_my_classes),
                (("quiz",), make_word_quiz)],
    "staff": [(("enquir", "inquir", "call back", "fee reminder", "visitor", "office", "task"), get_office_tasks)],
    "admin": [(("user", "approval", "overview", "dashboard"), get_admin_overview)],
    "correspondent": [(("overview", "summary", "dashboard", "strength", "attendance", "fee", "collection", "admission", "today", "report"), get_school_overview),
                      (("user", "app usage"), get_admin_overview)],
}


def offline_role_answer(role: str, message: str) -> str:
    q = message.lower()
    named = next((w["word"] for w in WORDS if w["word"].lower() in q), "")
    if "quiz" in q and role in ("student", "teacher"):
        return make_word_quiz(named)
    if role in ("student", "teacher") and len(message.split()) > 40:
        return summarize_chapter(message)
    if role == "teacher" and ("attendance" in q or "absent" in q):
        rolls = " ".join(re.findall(r"\b\d{1,2}\b", message))
        return mark_attendance("Class 5-A", rolls) if rolls else get_my_classes() + \
            "\nTell me the absent roll numbers, e.g. 'absent 3, 5'."
    if role in ("teacher", "admin") and q.startswith(("notice:", "post:")):
        body = message.split(":", 1)[1].strip()
        return draft_notice(body.split(".")[0][:60], body)
    for keys, fn in ROUTES.get(role, []):
        if any(k in q for k in keys):
            return fn()
    for other, routes in ROUTES.items():  # role-based access: say so instead of guessing
        for keys, fn in routes:
            if fn not in ROLE_TOOLS[role] and any(k in q for k in keys) and len(q.split()) <= 6:
                return f"That is not available for the {role} role. Please ask the school {other} team."
    return offline_answer(message)


# ---------------------------------------------------------------- model + loop
_models = {}


def _role_llm(role: str):
    if role not in _models:
        from langchain_core.tools import tool
        from agent import get_llm
        base, _ = get_llm()  # bound model; rebind with this role's tools only
        raw = getattr(base, "bound", base)
        tools = [tool(f) for f in ROLE_TOOLS[role]]
        _models[role] = (raw.bind_tools(tools), {t.name: t for t in tools})
    return _models[role]


def role_chat(role: str, message: str, history: list[dict] | None = None) -> str:
    role = role if role in ROLE_TOOLS else "parent"
    if PROVIDER == "offline":
        return offline_role_answer(role, message)
    try:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
        model, tools = _role_llm(role)
        msgs = [SystemMessage(system_prompt(role))]
        for h in (history or [])[-10:]:
            msgs.append((HumanMessage if h.get("role") == "user" else AIMessage)(h.get("content", "")))
        msgs.append(HumanMessage(message))
        for _ in range(MAX_STEPS):
            ai = model.invoke(msgs)
            msgs.append(ai)
            if not ai.tool_calls:
                return ai.content
            for call in ai.tool_calls:
                fn = tools.get(call["name"])  # only this role's tools exist here
                try:
                    result = fn.invoke(call["args"]) if fn else "Not available for this role."
                except Exception as e:
                    result = f"Tool error: {e}"
                msgs.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
        return "Sorry, I couldn't finish that. Please try again."
    except Exception as e:
        print(f"[spv-app] model unavailable ({type(e).__name__}: {e}); offline answer")
        return offline_role_answer(role, message)


# ---------------------------------------------------------------- home screen data
def home(role: str) -> dict:
    role = role if role in ROLE_TOOLS else "parent"
    cards = {
        "student": lambda: [("Attendance", f"{DEMO['student']['attendance_pct']}%"),
                            ("Homework", str(len(DEMO['student']['homework']))),
                            ("Next test", DEMO['student']['tests'][0]['subject'])],
        "parent": lambda: [("Child", DEMO['parent']['child']), ("Today", "Present"), ("Term 2 fee", "Due 15 Dec")],
        "teacher": lambda: [("Periods today", str(len(DEMO['teacher']['periods_today']))),
                            ("Class teacher", DEMO['teacher']['class_teacher_of']), ("Subject", DEMO['teacher']['subject'])],
        "staff": lambda: [("Enquiries", str(len(DEMO['staff']['pending_enquiries']))),
                          ("Fee reminders", str(DEMO['staff']['fee_reminders_due'])), ("Visitors", str(DEMO['staff']['visitors_today']))],
        "admin": lambda: [("Students", str(DEMO['admin']['users']['students'])),
                          ("Teachers", str(DEMO['admin']['users']['teachers'])), ("Approvals", str(DEMO['admin']['pending_approvals']))],
        "correspondent": lambda: [("Strength", str(DEMO['correspondent']['strength'])),
                                  ("Attendance", f"{DEMO['correspondent']['attendance_today_pct']}%"),
                                  ("Fees collected", f"{DEMO['correspondent']['fee_collection_pct']}%")],
    }[role]()
    word = json.loads(get_word_of_the_day(""))
    notices = [dict(zip(("date", "title", "text"), (n.split(" | ", 1)[0], *n.split(" | ", 1)[1].split(": ", 1))))
               for n in get_notices(5).split("\n") if " | " in n]
    return {"role": role, "demo": True, "cards": [{"label": l, "value": v} for l, v in cards],
            "word": {k: word[k] for k in ("word", "telugu", "meaning")}, "notices": notices,
            "tools": [f.__name__ for f in ROLE_TOOLS[role]]}
