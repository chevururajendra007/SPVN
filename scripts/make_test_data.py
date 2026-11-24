"""Build the TEST student workbook (classes 1-10, 10 students each) for the SPV portal.

Run: python scripts/make_test_data.py <staff.xlsx> <out.xlsx> <seed.json> [real_families.json]
Random students get fake parent numbers starting with 5 (not valid Indian mobiles), so the
app never messages a stranger. Real test families are passed in REAL below at run time.
"""
import json
import random
import sys

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

random.seed(2026)
BOYS = ["Arjun", "Charan", "Eswar", "Harsha", "Karthik", "Manoj", "Nikhil", "Praveen", "Rahul", "Sai Teja",
        "Srinivas", "Tarun", "Varun", "Vamsi", "Yeshwanth", "Akhil", "Bharath", "Dinesh", "Ganesh", "Kiran",
        "Lokesh", "Mahesh", "Naveen", "Pavan", "Ravi", "Sandeep", "Suresh", "Vinay", "Jagadeesh", "Abhiram"]
GIRLS = ["Ananya", "Bhavya", "Charitha", "Divya", "Harika", "Keerthi", "Lahari", "Mounika", "Navya", "Pooja",
         "Ramya", "Sahithi", "Sravani", "Swathi", "Tejaswi", "Varshini", "Vennela", "Yamini", "Deepika", "Gayathri",
         "Hasini", "Jahnavi", "Likhitha", "Meghana", "Nandini", "Pranathi", "Sindhu", "Sowmya", "Tanvi", "Vaishnavi"]
SURNAMES = ["Reddy", "Naidu", "Kumar", "Chowdary", "Yadav", "Rao", "Varma", "Setty", "Goud", "Raju"]
FATHERS = ["Ramesh", "Suresh", "Venkatesh", "Srinivasa Rao", "Prasad", "Nagaraju", "Ravi Kumar", "Mohan",
           "Krishna", "Murali", "Sekhar", "Babu", "Anil", "Satish", "Gopal", "Chandra"]
SUBJECTS = ["Telugu", "Hindi", "English", "Maths", "Science", "Social"]
FEE = {1: 18000, 2: 18000, 3: 19000, 4: 19000, 5: 20000, 6: 22000, 7: 22000, 8: 23000, 9: 26000, 10: 28000}
ROUTES = [
    {"id": "R1", "name": "Route 1 · Vidyanagar", "stops": ["Kota bus stand", "NCR Nagar", "Vidyanagar"],
     "device_id": "", "driver": "", "driver_phone": ""},
    {"id": "R2", "name": "Route 2 · Gudur Road", "stops": ["School", "Gudur road junction", "Chittedu"],
     "device_id": "", "driver": "", "driver_phone": ""},
    {"id": "R3", "name": "Route 3 · Vakadu Road", "stops": ["School", "Vakadu road", "Kotapolur"],
     "device_id": "", "driver": "", "driver_phone": ""},
]
# Real test families (name, class, gender, parent, phone) come from a PRIVATE json file passed as the
# 4th argument - never commit real children's names or phone numbers to this public repo.
REAL = []


def marks_for(level):
    out = {}
    for exam, bump in (("FA1", 0), ("SA1", 4)):
        out[exam] = {s: max(28, min(100, round(random.gauss(level + bump, 9)))) for s in SUBJECTS}
    return out


def build(staff_path):
    wb = openpyxl.load_workbook(staff_path, data_only=True)
    staff = []
    for row in list(wb.active.iter_rows(values_only=True))[1:]:
        if row and row[0]:
            staff.append({"name": str(row[0]).strip(), "role": "teacher", "class": int(row[1]),
                          "phone": str(row[2]).strip()})
    students, fake, used = [], 0, set()
    for cls in range(1, 11):
        rows = [r for r in REAL if r["class"] == cls]
        while len(rows) < 10:
            g = random.choice("MF")
            first = random.choice(BOYS if g == "M" else GIRLS)
            sur = random.choice(SURNAMES)
            if (first, sur) in used:
                continue
            used.add((first, sur))
            fake += 1
            rows.append({"name": f"{first} {sur}", "class": cls, "gender": g,
                         "parent": f"{random.choice(FATHERS)} {sur}", "phone": f"50000{fake:05d}"})
        rows.sort(key=lambda r: r["name"])
        for i, r in enumerate(rows, 1):
            total = FEE[cls]
            paid = random.choice([total, total, round(total * random.choice([.4, .5, .6, .75]), -2), round(total * .25, -2)])
            route = random.choice(["R1", "R2", "R3", "Own"])
            if r in REAL:
                paid = round(total * (.5 if r["class"] in (3, 10) else 1.0), -2)  # two real kids get a fee reminder
                route = "R2" if r["class"] == 10 else "R1"  # Rajendra's three children share one van
            students.append({
                "id": f"SPV{cls:02d}{i:02d}", "sno": i, "name": r["name"], "class": cls, "section": "A",
                "gender": r["gender"], "parent": r["parent"], "phone": r["phone"],
                "route": route, "fee_total": total, "fee_paid": int(paid),
                "marks": marks_for(random.choice([58, 66, 74, 82, 88])), "test": r not in REAL,
            })
    circular = {"id": "C1", "date": "2026-11-25", "from": "Principal", "to": "staff",
                "text": "Dear staff, pls inform about fees to the students. Thanks, Principal"}
    return {"students": students, "staff": staff, "routes": ROUTES, "circulars": [circular]}


def write_xlsx(seed, path):
    wb = openpyxl.Workbook()
    head = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="16204A")

    def sheet(title, cols, rows, widths):
        ws = wb.create_sheet(title)
        ws.append(cols)
        for c in ws[1]:
            c.font, c.fill, c.alignment = head, fill, Alignment(horizontal="center")
        for r in rows:
            ws.append(r)
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A2"
        return ws

    rname = {r["id"]: r["name"] for r in seed["routes"]} | {"Own": "Own transport"}
    ws = sheet("Students", ["S.No", "Admission No", "Student Name", "Class", "Section", "Gender", "Parent Name",
                            "Parent Mobile", "Route", "Annual Fee", "Fee Paid", "Balance", "Balance %"], [], 
               [6, 13, 26, 7, 8, 8, 22, 14, 22, 11, 10, 10, 10])
    for s in seed["students"]:
        n = ws.max_row + 1
        ws.append([s["sno"], s["id"], s["name"], s["class"], s["section"], s["gender"], s["parent"], s["phone"],
                   rname[s["route"]], s["fee_total"], s["fee_paid"], f"=J{n}-K{n}", f"=IF(J{n}=0,0,L{n}/J{n})"])
        ws[f"M{n}"].number_format = "0%"
    sheet("Marks", ["Admission No", "Student Name", "Class", "Exam", *SUBJECTS, "Total", "Percent"],
          [], [13, 26, 7, 7, 8, 8, 8, 8, 8, 8, 8, 9])
    wm = wb["Marks"]
    for s in seed["students"]:
        for exam, m in s["marks"].items():
            n = wm.max_row + 1
            wm.append([s["id"], s["name"], s["class"], exam, *[m[x] for x in SUBJECTS],
                       f"=SUM(E{n}:J{n})", f"=K{n}/{len(SUBJECTS) * 100}"])
            wm[f"L{n}"].number_format = "0%"
    sheet("Staff", ["Name", "Role", "Class Teacher Of", "Mobile"],
          [[t["name"], "Class teacher", t["class"], t["phone"]] for t in seed["staff"]], [16, 16, 16, 14])
    sheet("Routes", ["Route ID", "Route Name", "Stops", "GPS Device ID (Traccar)", "Driver", "Driver Mobile"],
          [[r["id"], r["name"], " → ".join(r["stops"]), r["device_id"], r["driver"], r["driver_phone"]]
           for r in seed["routes"]], [9, 24, 44, 22, 14, 14])
    rd = wb.active
    rd.title = "Read me"
    for line in ["SPV School Portal - TEST DATA (not real students)",
                 "Classes 1-10, 10 students each. Four real test families use real mobile numbers.",
                 "Random students have fake parent numbers starting with 5, so no message is ever sent to them.",
                 "Marks: FA1 and SA1, out of 100 per subject (random).",
                 "To load into the app: Admin login → Data → Import Excel (this same format).",
                 "Fill GPS Device ID with the Traccar Client device identifier for each van."]:
        rd.append([line])
    rd.column_dimensions["A"].width = 100
    rd["A1"].font = Font(bold=True, size=14, color="16204A")
    wb.save(path)


if __name__ == "__main__":
    if len(sys.argv) > 4:
        REAL.extend(json.load(open(sys.argv[4], encoding="utf-8")))
    seed = build(sys.argv[1])
    write_xlsx(seed, sys.argv[2])
    with open(sys.argv[3], "w", encoding="utf-8") as f:
        json.dump(seed, f, ensure_ascii=False)
    print(len(seed["students"]), "students,", len(seed["staff"]), "staff")
