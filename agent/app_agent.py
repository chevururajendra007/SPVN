"""Ask SPV inside the portal: model + harness, with skills chosen by the logged-in role (skills.py).

  Model   - same provider as agent.py (local Ollama / Ollama Cloud / offline router on Vercel)
  Harness - role system prompt + that role's skills only + loop with MAX_STEPS
  Offline - keyword router over the SAME skills, so answers are correct with no model at all
"""
from agent import PROVIDER, get_llm
from skills import make_skills

MAX_STEPS = 5

ROLE_INFO = {
    "parent": "a parent. Talk only about their own children using the tools. Be warm and simple.",
    "teacher": "a class teacher. Help with their class: attendance, students, marks, circulars, vans.",
    "principal": "the principal. Give short, numbers-first answers about the whole school.",
    "correspondent": "the correspondent (management). Give short, numbers-first answers about the whole school.",
    "admin": "the school admin. Help with students, fees, messages and vans.",
}


def system_prompt(ctx) -> str:
    return f"""You are "Ask SPV" in the portal of Sri Pragathi Vidyaniketan EM High School, Kota.
You are talking to {ROLE_INFO[ctx['role']]} Their name: {ctx.get('name', '')}.
Rules:
- Use tools for every fact. Never guess marks, fees, attendance, dates or phone numbers.
- You only have the tools for this role. If asked for something else, say it is not available for this login.
- You cannot change data. To mark attendance, post homework or send messages, tell them which tab to use.
- Reply in the user's language (English or Telugu). Keep answers short and clear."""


# ---------------------------------------------------------------- offline router
ROUTES = [  # (keywords, skill name) checked in order; only skills the role has are used
    (("van", "bus", "gps", "pickup", "వ్యాన్", "బస్సు"), ("my_van", "all_vans")),
    (("defaulter", "pending fee", "fee pending", "not paid", "balance list"), ("fee_defaulters",)),
    (("fee", "fees", "ఫీజు", "collection"), ("child_report", "fee_overview", "my_class_students")),
    (("last week", "trend", "7 days"), ("attendance_last_week",)),
    (("attendance", "absent", "present", "హాజరు"), ("child_report", "class_attendance_today", "attendance_today")),
    (("mark", "result", "exam", "marks"), ("child_report", "my_class_marks")),
    (("homework", "హోంవర్క్"), ("child_report",)),
    (("update", "news", "announcement"), ("school_updates",)),
    (("circular",), ("staff_circulars",)),
    (("outbox", "whatsapp", "message"), ("message_outbox",)),
    (("student", "class list", "my class"), ("my_class_students",)),
    (("word",), ("word_of_the_day",)),
    (("notice",), ("school_notices",)),
    (("child", "son", "daughter", "kid", "report", "summary", "how is"), ("my_children",)),
    (("overview", "summary", "dashboard", "today"), ("attendance_today", "class_attendance_today")),
]


def offline_answer(ctx, message: str) -> str:
    skills = {f.__name__: f for f in make_skills(ctx)}
    q = message.lower()
    if q.startswith(("search ", "find ")) and "search_students" in skills:
        return skills["search_students"](message.split(" ", 1)[1])
    if "my_class_students" in skills and q.startswith(("search ", "find ")):
        return skills["my_class_students"](message.split(" ", 1)[1])
    for keys, names in ROUTES:
        if any(k in q for k in keys):
            for n in names:
                if n in skills:
                    if n == "child_report":
                        return skills[n]("")
                    return skills[n]()
    if ctx["role"] == "parent":
        return skills["my_children"]()
    return skills["school_information"](message)


def role_chat(ctx: dict, message: str, history: list[dict] | None = None) -> str:
    if PROVIDER == "offline":
        return offline_answer(ctx, message)
    try:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
        from langchain_core.tools import tool
        base, _ = get_llm()
        raw = getattr(base, "bound", base)
        tools = [tool(f) for f in make_skills(ctx)]
        model, by_name = raw.bind_tools(tools), {t.name: t for t in tools}
        msgs = [SystemMessage(system_prompt(ctx))]
        for h in (history or [])[-8:]:
            msgs.append((HumanMessage if h.get("role") == "user" else AIMessage)(h.get("content", "")))
        msgs.append(HumanMessage(message))
        for _ in range(MAX_STEPS):
            ai = model.invoke(msgs)
            msgs.append(ai)
            if not ai.tool_calls:
                return ai.content
            for call in ai.tool_calls:
                fn = by_name.get(call["name"])  # only this role's skills exist here
                try:
                    result = fn.invoke(call["args"]) if fn else "Not available for this login."
                except Exception as e:
                    result = f"Tool error: {e}"
                msgs.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
        return "Sorry, I couldn't finish that. Please try again."
    except Exception as e:
        print(f"[spv-portal] model unavailable ({type(e).__name__}: {e}); offline answer")
        return offline_answer(ctx, message)
