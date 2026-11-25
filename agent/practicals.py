"""Weekly practical sessions for every class (June-March, 4 weeks a month = 40 weeks).

Each week borrows one proven practice from Japan or Europe and turns it into a low-cost activity
rooted in India and in Kota (Tirupati district, AP): paddy fields, the Gudur lemon market, Pulicat
lake and the Nelapattu bird sanctuary, ISRO Sriharikota, the Bay of Bengal coast and its cyclones,
Telugu festivals and the people who run our town.

Class bands: "1-2", "3-5", "6-8", "9-10". Teachers mark a week done for their class; the principal
sees completion per class.
"""
import time
from datetime import date, timedelta

import store

BANDS = ("1-2", "3-5", "6-8", "9-10")
MONTHS = ["Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"]

# (theme, inspired by, Kota / India link, {band: activity})
PLAN = {
 "Jun": [
  ("Our class, our duty", "Japan: o-soji - students clean their own classroom every day",
   "Swachh Bharat; keeping our Kota school and street clean",
   {"1-2": "10-minute class cleaning song: each child has one job (dusting, arranging chappals, watering plants).",
    "3-5": "Make a weekly duty chart in groups of 4 (board, bins, plants, books) and rotate it every Monday.",
    "6-8": "Audit the school for 3 problems (litter, taps, broken desks); present fixes to the principal.",
    "9-10": "Lead the junior classes' cleaning time as mentors; write a one-page 'clean school' rule book."}),
  ("Serving lunch together", "Japan: kyushoku toban - pupils serve lunch to classmates",
   "Mid-day meal tradition in AP schools; sharing food at home",
   {"1-2": "Practise washing hands properly and saying a thank-you line before eating; draw your lunch box.",
    "3-5": "Lunch duty team: serve, wipe tables, collect plates; discuss 'mottainai' - no food waste.",
    "6-8": "Measure one week's food waste in the school bin; make a bar chart and a plan to halve it.",
    "9-10": "Plan a balanced Rs.30 lunch with local food (rice, dal, greens, egg); calculate nutrients."}),
  ("Walking to school safely", "Netherlands: children learn traffic rules and take a cycling exam",
   "Kota bus stand road, school vans, two-wheelers on the main road",
   {"1-2": "Traffic light game in the ground: red/yellow/green, zebra crossing, holding hands to cross.",
    "3-5": "Draw a safe route map from home to school; mark danger spots and the safest crossing.",
    "6-8": "Count vehicles at the school gate for 15 minutes; suggest a safer drop-off plan for vans.",
    "9-10": "Bicycle safety check and road-rule quiz; invite a traffic police officer for a Q&A."}),
  ("Class meeting", "Japan: gakkyu-kai class meetings; Denmark: weekly 'class hour' on feelings",
   "Respecting each other like a family; panchayat-style decision making",
   {"1-2": "Circle time: each child says one happy and one sad thing from the week; practise listening.",
    "3-5": "Students choose a class rule by voting; write it on a chart and sign it.",
    "6-8": "Run a class meeting with chairperson and minutes; solve one real class problem.",
    "9-10": "Model gram sabha: debate a village issue (water, roads) and pass a resolution."}),
 ],
 "Jul": [
  ("Rain and water", "Netherlands: living with water - dykes, canals and smart drains",
   "Monsoon in Kota, village tanks, paddy irrigation, wells and borewells",
   {"1-2": "Collect rainwater in cups across the ground; compare which spot got most; float paper boats.",
    "3-5": "Visit the nearest tank or canal; draw where the water comes from and where it goes.",
    "6-8": "Build a simple rain gauge from a bottle; record rainfall daily for a month.",
    "9-10": "Map school roof area and calculate rainwater that could be harvested; propose a pit."}),
  ("Planting rice", "Japan: schools plant and harvest rice in a small paddy (taue taiken)",
   "Nellore/Kota is a rice bowl: nurseries, transplanting, monsoon crop",
   {"1-2": "Sow paddy seeds in a tray; watch them sprout and draw the seedling each day.",
    "3-5": "Field visit to a paddy farm: watch transplanting; interview a farmer with 5 questions.",
    "6-8": "Compare transplanting vs direct seeding: water used, labour, cost (ask farmers); make a table.",
    "9-10": "Study one rice variety grown near Kota; calculate cost and profit per acre from farmer data."}),
  ("Save every drop", "Switzerland/Germany: water meters and saving habits at home",
   "Summer water shortages; bore-well levels in AP villages",
   {"1-2": "Turn-off-the-tap game: count how many cups a running tap wastes in one minute.",
    "3-5": "Home water diary for 3 days: how many buckets does the family use and for what?",
    "6-8": "Find and report leaking taps in school; calculate litres wasted per day.",
    "9-10": "Test water samples (school tap, well, RO) for smell, colour, pH strips; write a report."}),
  ("Weather watchers", "Finland: phenomenon-based learning - study one real thing from all subjects",
   "Bay of Bengal monsoon, cyclone season in coastal AP",
   {"1-2": "Daily weather chart with stickers (sunny, cloudy, rainy) for the whole week.",
    "3-5": "Make a wind vane and read wind direction every morning; link to the newspaper weather box.",
    "6-8": "Track a week's temperature and rainfall from the news; draw graphs and predict next week.",
    "9-10": "Explain how a cyclone forms; read IMD warnings and prepare a family preparedness checklist."}),
 ],
 "Aug": [
  ("Freedom and our country", "Europe: children's parliaments and youth councils",
   "Independence Day; freedom fighters from Andhra Pradesh",
   {"1-2": "Make flags with paper and colours; learn the meaning of the three colours.",
    "3-5": "Act out a short story of a freedom fighter from Andhra Pradesh.",
    "6-8": "Hold a mock election for class leader with campaign speeches and secret ballot.",
    "9-10": "Read the Preamble; debate 'one right and one duty every student must practise'."}),
  ("Healthy food from our soil", "Japan: shokuiku - food education about where food comes from",
   "Local vegetables, Gudur lemons, Nellore rice, fish and prawn farming",
   {"1-2": "Fruit and vegetable colour day: bring one local item and say its Telugu and English name.",
    "3-5": "Visit the local market (santa); list 10 items, prices, and which village they came from.",
    "6-8": "Trace one food (lemon or prawn) from farm to plate; make a supply-chain poster.",
    "9-10": "Study food prices over a month; explain why prices rise and fall (rain, transport, demand)."}),
  ("School garden", "Europe: school gardens and allotments; Montessori 'care of the environment'",
   "Kitchen gardens in Kota homes; curry leaves, drumstick, tomato",
   {"1-2": "Plant a seed in a cup with your name; water it daily and measure with a paper strip.",
    "3-5": "Make a small vegetable bed; each group takes care of one plant and keeps a growth log.",
    "6-8": "Compost pit from school leaves and food waste; check temperature and decay weekly.",
    "9-10": "Design a drip system from used bottles for the garden; compare water use with hand watering."}),
  ("Festivals and togetherness", "Japan: school festivals (bunkasai) run by students",
   "Vinayaka Chavithi; clay idols vs plastic and paint in water bodies",
   {"1-2": "Make a small clay Ganesha or clay toy with natural colours.",
    "3-5": "Group project: why natural clay is better for tanks and fish; make a poster in Telugu.",
    "6-8": "Survey 20 families on eco-friendly celebration habits; present the results as a chart.",
    "9-10": "Plan a low-waste school festival: budget, roles, waste plan; present to the principal."}),
 ],
 "Sep": [
  ("People who help us", "Finland: life skills and visiting workplaces",
   "Kota post office, PHC, police station, fire service, bank, panchayat office",
   {"1-2": "Dress-up day as a helper (doctor, farmer, postman); say one line about their work.",
    "3-5": "Visit the post office: buy a postcard, write to a grandparent, post it yourself.",
    "6-8": "Interview a PHC nurse or ANM about vaccines; prepare a health awareness chart.",
    "9-10": "Visit a bank: learn about savings accounts, UPI safety and fraud calls; write a guide for parents."}),
  ("Money smart", "Netherlands/UK: pocket-money and financial literacy lessons",
   "Weekly market buying, UPI payments in Kota shops",
   {"1-2": "Play shop with toy coins: buy and give change up to Rs.20.",
    "3-5": "Make a family budget for one week's vegetables; compare plan and actual spending.",
    "6-8": "Compare cash, UPI and card; role-play spotting a fraud message or call.",
    "9-10": "Simple interest vs compound interest on a Rs.1,000 deposit; visit or invite a bank officer."}),
  ("Teachers' and elders' wisdom", "Japan: respect for teachers and elders (keiro no hi)",
   "Teachers' Day (Dr. S. Radhakrishnan); grandparents' stories in Telugu",
   {"1-2": "Make a thank-you card for a teacher or grandparent.",
    "3-5": "Record (write) a story told by a grandparent; share it in class.",
    "6-8": "Interview an elder about Kota 50 years ago: roads, school, farming; compare with today.",
    "9-10": "Teach one lesson to a junior class for 20 minutes; reflect on what makes teaching hard."}),
  ("Waste is a resource", "Switzerland/Germany: strict waste sorting and recycling",
   "Plastic in Kota drains and fields; scrap dealers (kabadiwala)",
   {"1-2": "Sort a basket of clean waste into dry, wet and plastic bins.",
    "3-5": "Make one useful thing from waste (pen stand, planter) and explain it.",
    "6-8": "Weigh the school's dry waste for a week; find out the scrap price and potential income.",
    "9-10": "Plan a school recycling system with a local scrap dealer; calculate monthly savings."}),
 ],
 "Oct": [
  ("Space next door", "Europe: ESA science centres and space camps",
   "ISRO Satish Dhawan Space Centre, Sriharikota - India's launch pad near us",
   {"1-2": "Make a paper rocket and launch it by blowing through a straw; who flies farthest?",
    "3-5": "Watch a recorded ISRO launch; draw the rocket stages and name them.",
    "6-8": "Build a water-bottle rocket (with teacher supervision); measure height and change one variable.",
    "9-10": "Explain how satellites help farmers and fishermen (weather, GPS); present one ISRO mission."}),
  ("Measure everything", "Finland: maths outdoors - measuring real things",
   "Measuring land in acres/cents, weights at the market",
   {"1-2": "Measure the classroom with hand spans and footsteps; compare answers.",
    "3-5": "Measure the school ground with a rope and metre scale; calculate its area.",
    "6-8": "Find the height of a tree using its shadow and your own shadow.",
    "9-10": "Survey a small plot and calculate area in square metres, cents and acres."}),
  ("Science of the kitchen", "Montessori (Italy): practical-life science",
   "Tamarind, lemon, turmeric and lime in Andhra cooking",
   {"1-2": "Taste test sweet, sour, salty, bitter with safe foods; name them in Telugu.",
    "3-5": "Turmeric as an indicator: test soap water and lemon juice and see the colour change.",
    "6-8": "Make curd at home and observe; explain bacteria and fermentation.",
    "9-10": "Acids and bases with kitchen items; measure pH with strips and record a table."}),
  ("Dasara: stories and skills", "Japan: traditional arts (origami, calligraphy)",
   "Dasara, Bommala Koluvu (doll display), Telugu handwriting",
   {"1-2": "Origami animals; arrange them in a class doll display.",
    "3-5": "Telugu handwriting practice like Japanese calligraphy: one beautiful page.",
    "6-8": "Geometry in origami: fold and find angles, symmetry and fractions.",
    "9-10": "Write and perform a short play from a Dasara story with a modern message."}),
 ],
 "Nov": [
  ("Birds of our lake", "Europe: forest school and bird counts (e.g. Big Garden Birdwatch)",
   "Pulicat lake flamingos, Nelapattu pelicans, birds in Kota fields",
   {"1-2": "Bird watching for 15 minutes in the school ground; draw the birds you see.",
    "3-5": "Make a bird feeder from a bottle; record which birds come each day.",
    "6-8": "Learn about migratory flamingos at Pulicat; map their journey on a world map.",
    "9-10": "Bird count project: record species near school for a week; compare with Nelapattu data."}),
  ("Children's rights", "Europe: UN Convention on the Rights of the Child taught in schools",
   "Children's Day (Nov 14); child helpline 1098",
   {"1-2": "Draw 'what makes me happy and safe'; learn the number 1098.",
    "3-5": "Good touch / bad touch and trusted adults (teacher-led, age-appropriate).",
    "6-8": "Debate: 'every child must finish school'; collect facts from AP.",
    "9-10": "Survey child labour signs in the area (shops, fields); write to the panchayat respectfully."}),
  ("Forest and trees", "Germany/Denmark: Waldkindergarten - learning outdoors in all weather",
   "Neem, tamarind, palm and coconut trees around Kota",
   {"1-2": "Hug-a-tree: feel the bark, collect leaves, make a leaf collage.",
    "3-5": "Name 10 local trees and their uses (neem twig, tamarind, palm leaves).",
    "6-8": "Measure tree girth and estimate age; calculate how much carbon one tree stores.",
    "9-10": "Plan a tree-planting drive: species, spots, watering rota; get panchayat permission."}),
  ("Fishermen and the sea", "Norway/Netherlands: learning from the sea and coastal life",
   "Bay of Bengal fishing villages, prawn farms near Kota and Nellore",
   {"1-2": "Fish shapes with paper; learn names of 5 local fish in Telugu.",
    "3-5": "Visit or invite a fisherman or prawn farmer; list their daily work.",
    "6-8": "Study prawn farming: water, feed, salt; pros and cons for the environment.",
    "9-10": "How weather alerts and GPS save fishermen's lives; prepare a safety leaflet."}),
 ],
 "Dec": [
  ("Disaster ready", "Japan: regular earthquake and evacuation drills (hinan kunren)",
   "Cyclones and floods in coastal AP; school safety plan",
   {"1-2": "Practise 'duck, cover, hold' and lining up quietly during a drill.",
    "3-5": "Make an emergency bag list for home (water, torch, medicines, documents).",
    "6-8": "Map exits and assembly point of the school; time a full evacuation drill.",
    "9-10": "First-aid basics (bleeding, burns, fainting) with a PHC or Red Cross volunteer."}),
  ("Healthy body", "Finland: daily physical activity and free school health care",
   "Yoga, kabaddi, kho-kho; mosquito season in Kota",
   {"1-2": "Five-minute morning stretches every day this week; count jumping jacks.",
    "3-5": "Check for mosquito breeding spots at school; empty water containers safely.",
    "6-8": "Measure pulse before and after running; draw a graph.",
    "9-10": "Plan and run a 'yoga and kabaddi' session for junior classes."}),
  ("Kindness week", "Denmark: empathy lessons (Klassens tid)",
   "Helping neighbours, sharing in Telugu families",
   {"1-2": "Do one kind act every day and draw it in a kindness diary.",
    "3-5": "Write a thank-you note to a school helper (ayah, watchman, driver).",
    "6-8": "Buddy system: help a junior with reading for 15 minutes a day.",
    "9-10": "Organise a book and clothes collection for children who need them."}),
  ("Winter science fair", "Europe: student science fairs (e.g. Jugend forscht in Germany)",
   "Problems in Kota that science can solve",
   {"1-2": "Floating and sinking experiment with things from home.",
    "3-5": "Simple circuits with a battery and bulb; make a quiz board.",
    "6-8": "Project: solar water heater or mosquito trap from waste materials.",
    "9-10": "Solve one local problem with science (water filter, crop pest, power cut) and present it."}),
 ],
 "Jan": [
  ("Sankranti and the harvest", "Japan: harvest festivals; thanking farmers",
   "Sankranti, rangoli, kites, harvested paddy in Kota fields",
   {"1-2": "Make rangoli patterns with chalk; count dots and lines.",
    "3-5": "Visit a harvest field or threshing; learn the steps from paddy to rice.",
    "6-8": "Kite science: build a kite and test different tail lengths.",
    "9-10": "Calculate a farmer's income from harvest: yield, price, costs; discuss MSP."}),
  ("Sports day", "Japan: undokai - the whole school runs the sports day together",
   "Kabaddi, kho-kho, tug of war, relay",
   {"1-2": "Practise relay and sack race with team cheering.",
    "3-5": "Each class designs a team flag and cheer in Telugu and English.",
    "6-8": "Run the scoring desk and timing for the sports day with stopwatches.",
    "9-10": "Plan the full sports day: events list, timings, first aid, judges."}),
  ("Republic and rules", "Europe: student councils that decide school matters",
   "Republic Day; panchayat and mandal offices in Kota",
   {"1-2": "Learn the national anthem and its meaning with pictures.",
    "3-5": "Visit the panchayat office; ask what they do for water and roads.",
    "6-8": "Elect a student council and give it one real task for the month.",
    "9-10": "Read a page of the Constitution on fundamental duties; write a short speech."}),
  ("Coding and logic", "Estonia/Finland: coding taught from early classes",
   "Mobile phones in every Kota home; digital safety",
   {"1-2": "Unplugged coding: guide a friend through a maze using arrow cards.",
    "3-5": "Write step-by-step instructions to make tea; spot the 'bugs'.",
    "6-8": "Block coding (Scratch or similar) on the school computer or teacher's phone.",
    "9-10": "Digital safety: passwords, OTP fraud, fake news check; teach it to parents."}),
 ],
 "Feb": [
  ("Makers and repairers", "Netherlands: Repair Cafés; Germany: vocational workshops",
   "Kota mechanics, tailors, electricians, carpenters",
   {"1-2": "Sewing a button with a big needle (with help); practise tying laces.",
    "3-5": "Visit a local tailor or carpenter; list their tools and what each does.",
    "6-8": "Repair day: fix a broken chair, change a fuse (supervised), patch a bag.",
    "9-10": "Shadow a local worker for 2 hours; write about skills and income."}),
  ("Young entrepreneurs", "Europe: school mini-companies (e.g. Junior Achievement)",
   "Village shops, Sharvai-style home food businesses, weekly santa",
   {"1-2": "Shop game: set prices for 5 items and sell to classmates.",
    "3-5": "Make and sell a small craft or snack at a school stall; count profit.",
    "6-8": "Business plan for a small stall: costs, price, profit, risks.",
    "9-10": "Run a one-day school market: accounts, UPI QR, profit for a class cause."}),
  ("Our language, our stories", "Europe: multilingual schools; Japan: storytelling (kamishibai)",
   "Telugu stories, Vemana padyalu, local folk songs",
   {"1-2": "Picture-card storytelling (kamishibai style) of a Telugu tale.",
    "3-5": "Learn and recite one Vemana padyam with meaning.",
    "6-8": "Translate a short English story into Telugu and act it out.",
    "9-10": "Make a short podcast or radio show in Telugu on a local topic."}),
  ("Energy and power", "Germany/Denmark: solar and wind energy in every town",
   "Power cuts, solar panels on Kota rooftops, farm motors",
   {"1-2": "Sun and shade: feel temperatures of black and white paper in sunlight.",
    "3-5": "Make a solar oven from a box and foil; melt chocolate or warm water.",
    "6-8": "Read the school electricity bill; find ways to cut units by 10%.",
    "9-10": "Calculate solar panel needs and payback for the school roof."}),
 ],
 "Mar": [
  ("Project month", "Finland: phenomenon-based projects across subjects",
   "Pick one Kota topic: water, rice, birds, roads or space",
   {"1-2": "Class picture book on 'My Kota'.",
    "3-5": "Group model of Kota village with roads, tank, fields and school.",
    "6-8": "Research project with interviews, photos and a chart on one Kota topic.",
    "9-10": "Research report with data, a field visit and recommendations to the panchayat."}),
  ("Ugadi: new beginnings", "Japan: new school year traditions and goals",
   "Ugadi pachadi - six tastes for the six feelings of life",
   {"1-2": "Taste the six flavours of Ugadi pachadi and name the feelings.",
    "3-5": "Write three goals for next year and put them in a class time capsule.",
    "6-8": "Make a Telugu calendar page with festivals and seasons.",
    "9-10": "Write a letter to yourself to open after Class 10 results."}),
  ("Exam calm", "Finland/Denmark: less stress, more sleep and play",
   "Exam season in AP schools",
   {"1-2": "Breathing game: smell the flower, blow the candle.",
    "3-5": "Make a simple study timetable with play and sleep time.",
    "6-8": "Teach a classmate one hard topic; teaching is the best revision.",
    "9-10": "Plan revision with Pomodoro (25 min study + 5 min break); track for a week."}),
  ("Showcase day", "Japan: bunkasai culture festival; Europe: open school day for parents",
   "Parents and Kota community visit the school",
   {"1-2": "Show your best drawing and sing one song for parents.",
    "3-5": "Display projects and explain them to parents.",
    "6-8": "Run stalls on science and practical work; guide visitors.",
    "9-10": "Host the showcase: anchoring, guiding, collecting parent feedback."}),
 ],
}


def band(cls) -> str:
    c = int(cls)
    return "1-2" if c <= 2 else "3-5" if c <= 5 else "6-8" if c <= 8 else "9-10"


def week_for(d: date) -> dict:
    """Plan week for a date: month theme by calendar month, week of month 1-4 (5th week repeats 4).
    April/May use the March plan (showcase / summer)."""
    m = d.strftime("%b")
    if m not in MONTHS:
        m = "Mar"
    w = min(4, (d.day - 1) // 7 + 1)
    return {"month": m, "week": w, "no": MONTHS.index(m) * 4 + w}


def entry(no: int) -> dict:
    m, w = MONTHS[(no - 1) // 4], (no - 1) % 4 + 1
    theme, inspired, local, acts = PLAN[m][w - 1]
    return {"no": no, "month": m, "week": w, "theme": theme, "inspired": inspired, "local": local, "activities": acts}


def all_weeks() -> list[dict]:
    return [entry(n) for n in range(1, 41)]


def current_no(today: str) -> int:
    return week_for(date.fromisoformat(today))["no"]


def mark_done(no: int, cls: int, by_name: str, note: str = "") -> dict:
    if not 1 <= int(no) <= 40:
        raise ValueError("Unknown week")
    rec = store.get(f"prac:{no}", {}) or {}
    rec[str(int(cls))] = {"by": by_name, "at": int(time.time()), "note": (note or "").strip()[:300]}
    store.set(f"prac:{no}", rec)
    return rec[str(int(cls))]


def done_for(no: int) -> dict:
    return store.get(f"prac:{no}", {}) or {}


def class_view(cls: int, today: str) -> dict:
    no = current_no(today)
    b = band(cls)
    done = store.get_many([f"prac:{n}" for n in range(1, 41)])
    weeks = []
    for n in range(1, 41):
        e = entry(n)
        weeks.append({k: e[k] for k in ("no", "month", "week", "theme", "inspired", "local")}
                     | {"activity": e["activities"][b], "done": (done.get(f"prac:{n}") or {}).get(str(int(cls)))})
    return {"class": int(cls), "band": b, "current": no, "weeks": weeks}


def school_view(today: str, classes: list[int]) -> dict:
    no = current_no(today)
    d = done_for(no)
    e = entry(no)
    return {"current": no, "week": e, "classes": [{"class": c, "band": band(c), "activity": e["activities"][band(c)],
                                                   "done": d.get(str(c))} for c in classes],
            "done_count": sum(1 for c in classes if str(c) in d), "total": len(classes)}
