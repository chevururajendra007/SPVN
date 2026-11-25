"""Skills (tools) for the Ask SPV agent inside the portal, one set per role.

Least privilege: the logged-in person's identity (phone, role, class) is bound on the SERVER when the
skills are created, so the model can never ask for another family's data - a parent's skills only
ever read that parent's children, a class teacher's only that class.
All skills are read-only. Anything that changes data (attendance, fees, messages) is done with
buttons in the app, where the person confirms it.
"""
import json

import notify
import practicals
import school
import store
import van
from agent import get_notices, get_school_info, get_word_of_the_day


def _rupees(n):
    return f"Rs.{int(n):,}"


def _marks_line(s):
    out = []
    for exam, m in (s.get("marks") or {}).items():
        tot = sum(m.values())
        out.append(f"{exam}: " + ", ".join(f"{k} {v}" for k, v in m.items()) + f" (total {tot}/{len(m) * 100})")
    return "\n".join(out) or "No marks entered yet."


def _child_report(s):
    a = school.student_attendance(s)
    hw = school.homework(s["class"], 3)
    fee = (f"Fees: paid {_rupees(s['fee_paid'])} of {_rupees(s['fee_total'])}, balance {_rupees(school.balance(s))}"
           + (" - REMINDER: more than 30% is pending, please pay at the office." if school.fee_flag(s) else "."))
    att = (f"Attendance (last {a['days']} school days): {a['pct']}% - present {a['present']}, absent {a['absent']}."
           + (f" Today: {'Present' if a['today'] == 'P' else 'Absent'}." if a["today"] else " Today: not marked yet.")
           if a["days"] else "Attendance: no records yet.")
    hws = "; ".join(f"{h['subject']}: {h['text']} ({h['date']})" for h in hw) or "none posted"
    return f"{s['name']} - Class {s['class']}\n{att}\nMarks:\n{_marks_line(s)}\n{fee}\nHomework: {hws}"


def make_skills(ctx: dict) -> list:
    """Return the skill functions for this session. ctx comes from auth.session()."""
    role, phone = ctx["role"], ctx["phone"]

    # ---------------- common
    def school_information(topic: str) -> str:
        """Official school information (about, address, contact, timings, fees, admissions) for a topic."""
        return get_school_info(topic)

    def word_of_the_day(word: str = "") -> str:
        """The school's Word of the Day (latest if empty)."""
        return get_word_of_the_day(word)

    def school_notices(limit: int = 3) -> str:
        """Latest public school notices."""
        return get_notices(limit)

    common = [school_information, word_of_the_day, school_notices]

    # ---------------- parent: only this parent's children
    def my_children() -> str:
        """Report on my children: attendance, marks, fees and homework."""
        kids = school.children(phone)
        return "\n\n".join(_child_report(k) for k in kids) or "No children are linked to this number."

    def child_report(child_name: str = "") -> str:
        """Report on one of my children by name (attendance, marks, fees, homework)."""
        kids = school.children(phone)
        pick = [k for k in kids if child_name.lower() in k["name"].lower()] or kids
        return "\n\n".join(_child_report(k) for k in pick)

    def school_updates() -> str:
        """Latest updates from the school for my children's classes."""
        items = []
        for k in school.children(phone):
            items += school.updates_for(k["class"], 5)
        seen, out = set(), []
        for u in items:
            if u["id"] not in seen:
                seen.add(u["id"])
                out.append(f"{u['date']}: {u['text']}")
        return "\n".join(out) or "No updates yet."

    def my_van() -> str:
        """Where is my child's school van now?"""
        rids = {k["route"] for k in school.children(phone) if k.get("route") not in (None, "", "Own")}
        return van.status_text(van.vans(school.routes(), only_routes=rids)) if rids else \
            "Your child does not use the school van (own transport)."

    # ---------------- teacher: own class
    cls = ctx.get("class")

    def class_attendance_today() -> str:
        """Today's attendance for my class."""
        sh = school.att_sheet(school.today(), cls)
        if not sh:
            return f"Attendance for Class {cls} is not marked yet today. Use the Attendance tab."
        kids = school.class_students(cls)
        ab = [k["name"] for k in kids if sh["marks"].get(k["id"]) == "A"]
        return f"Class {cls} today: {len(kids) - len(ab)} present, {len(ab)} absent ({', '.join(ab) or 'none'})."

    def my_class_students(query: str = "") -> str:
        """Students of my class with parent and fee status. Optional name filter."""
        kids = [k for k in school.class_students(cls) if query.lower() in k["name"].lower()]
        return "\n".join(f"{k['sno']}. {k['name']} - parent {k['parent']} {k['phone']}"
                         f"{' - fee pending' if school.fee_flag(k) else ''}" for k in kids) or "No match."

    def my_class_marks(student_name: str = "") -> str:
        """Marks of my class students (optionally one student)."""
        kids = [k for k in school.class_students(cls) if student_name.lower() in k["name"].lower()]
        return "\n\n".join(f"{k['name']}\n{_marks_line(k)}" for k in kids[:10]) or "No match."

    def staff_circulars() -> str:
        """Latest circulars from the principal to staff."""
        return "\n".join(f"{c['date']} - {c['from']}: {c['text']}" for c in school.circulars(5)) or "No circulars."

    def all_vans() -> str:
        """Live status of all school vans."""
        return van.status_text(van.vans(school.routes()))

    # ---------------- management
    def attendance_today() -> str:
        """Whole-school attendance today by class, with absentees."""
        a = school.attendance_summary()
        lines = [f"Class {r['class']}: " + (f"{r['present']}/{r['strength']} present ({r['pct']}%)"
                 + (f", absent: {', '.join(r['absentees'])}" if r['absentees'] else "") if r["marked"]
                 else "NOT MARKED") for r in a["classes"]]
        head = (f"Today {a['date']}: {a['pct']}% present ({a['present']} present, {a['absent']} absent); "
                f"{a['marked']}/{a['total_classes']} classes marked." if a["pct"] is not None
                else f"Today {a['date']}: no class has marked attendance yet.")
        return head + "\n" + "\n".join(lines)

    def fee_overview() -> str:
        """Fee collection summary by class."""
        f = school.fee_summary()
        lines = [f"Class {c['class']}: {c['pct']}% collected, balance {_rupees(c['balance'])}, "
                 f"{c['flagged']} students above 30% pending" for c in f["classes"]]
        return (f"Collected {_rupees(f['paid'])} of {_rupees(f['total'])} ({f['pct']}%). "
                f"Balance {_rupees(f['balance'])}. {len(f['flagged'])} students get reminders.\n" + "\n".join(lines))

    def fee_defaulters(class_number: int = 0) -> str:
        """Students with more than 30% fee pending (optionally one class)."""
        rows = [x for x in school.fee_summary()["flagged"] if not class_number or x["class"] == int(class_number)]
        return "\n".join(f"{x['name']} (Class {x['class']}) - {_rupees(x['balance'])} pending ({x['pct']}%), "
                         f"last reminder {x['last_reminder'] or 'never'}" for x in rows[:30]) or "No one above 30%."

    def search_students(query: str) -> str:
        """Search all students by name, admission no, parent or phone."""
        fees = role in ("superadmin", "principal", "admin")  # only these roles may see fee amounts
        hits = school.search(query, school.students(), fees)
        return "\n".join(f"{h['name']} ({h['id']}), Class {h['class']} - parent {h['parent']} {h['phone']}"
                         + (f", fee balance {_rupees(h['balance'])}" if fees else "") for h in hits) or "No students found."

    def attendance_last_week() -> str:
        """School attendance % for the last 7 school days."""
        return "\n".join(f"{t['date']}: {t['pct']}%" if t["pct"] is not None else f"{t['date']}: not marked"
                         for t in school.attendance_trend(7))

    def fee_collection() -> str:
        """Fees collected today and in the last 7 days (approved entries only), and pending approvals."""
        c = school.daily_collection(7)
        days = "\n".join(f"{d['date']}: {_rupees(d['total'])} ({d['count']} receipts)" for d in c["days"])
        return (f"Today: {_rupees(c['today']['total'])} from {c['today']['count']} receipts. "
                f"Waiting for principal approval: {len(school.fee_entries('pending'))}.\nLast 7 days:\n{days}")

    def practical_this_week() -> str:
        """This week's practical session (activity) for my class / my child's class / all classes."""
        if role == "parent":
            out = []
            for k in school.children(phone):
                e = practicals.entry(practicals.current_no(school.today()))
                out.append(f"{k['name']} (Class {k['class']}): {e['theme']} - {e['activities'][practicals.band(k['class'])]}")
            return "\n".join(out) or "No children linked."
        if role == "teacher":
            e = practicals.entry(practicals.current_no(school.today()))
            return (f"Week {e['no']} - {e['theme']} ({e['inspired']}; Kota link: {e['local']}).\n"
                    f"Class {cls}: {e['activities'][practicals.band(cls)]}")
        v = practicals.school_view(school.today(), sorted({int(s['class']) for s in school.students()}))
        return (f"Week {v['current']} - {v['week']['theme']}: {v['done_count']}/{v['total']} classes done.\n"
                + "\n".join(f"Class {c['class']}: {'done' if c['done'] else 'pending'}" for c in v["classes"]))

    def message_outbox() -> str:
        """WhatsApp messages waiting to be sent or sent recently."""
        items = store.get("outbox", []) or []
        counts = {}
        for m in items[:200]:
            counts[m["status"]] = counts.get(m["status"], 0) + 1
        mode = "automatic (WhatsApp API)" if notify.api_ready() else "one-tap from the app (no WhatsApp API yet)"
        return f"Sending mode: {mode}. Last 200 messages: {json.dumps(counts)}"

    by_role = {
        "parent": [my_children, child_report, school_updates, my_van, practical_this_week],
        "teacher": [class_attendance_today, my_class_students, my_class_marks, staff_circulars, all_vans,
                    practical_this_week],
        "principal": [attendance_today, attendance_last_week, fee_overview, fee_collection, fee_defaulters,
                      search_students, staff_circulars, all_vans, practical_this_week],
        "correspondent": [attendance_today, attendance_last_week, search_students, all_vans, practical_this_week],
        "admin": [attendance_today, fee_overview, fee_collection, fee_defaulters, search_students, staff_circulars,
                  all_vans, message_outbox],
    }
    by_role["superadmin"] = by_role["principal"] + [message_outbox]
    return common + by_role.get(role, [])
