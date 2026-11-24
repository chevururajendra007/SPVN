# Sri Pragathi Vidyaniketan EM High School, Kota

Static website for Sri Pragathi Vidyaniketan EM High School, Kota, Andhra Pradesh 524411.

- `index.html`: the full site (HTML, CSS and JS in one file)
- `assets/`: logo, Word of the Day posters, student video and photos

- `api/index.py`: Ask SPV agent as a Vercel serverless function (`POST /api/chat`, `GET /api/health`)
- `agent/`: the agent (tools, model, loop) and its school data; also runs fully offline on a laptop

Deploy: import this repo in Vercel (framework preset "Other", no build command). Every push to `main` redeploys.

## Ask SPV on Vercel
The chat bubble on the site calls `/api/chat`. With no model configured it answers from school data only (no AI, no cost).
To switch on the AI model, add these in Vercel → Project → Settings → Environment Variables, then redeploy:

| Option | Variables |
|---|---|
| Ollama Cloud | `OLLAMA_URL=https://ollama.com`, `OLLAMA_API_KEY`, `OLLAMA_MODEL` (e.g. `gpt-oss:120b`) |
| Azure AI Foundry | `AZURE_INFERENCE_ENDPOINT`, `AZURE_INFERENCE_CREDENTIAL`, `AZURE_MODEL_DEPLOYMENT` (and add `langchain-azure-ai` to `requirements.txt`) |

Admission enquiries are not stored on Vercel (no durable disk); the agent points parents to the enquiry form.
School content to fill in: `agent/data/school.json` (contact, timings, fees, transport, uniform, calendar, safety) and `agent/data/notices.json`.

## Two separate parts
| Part | URL | Who |
|---|---|---|
| Public website + Ask SPV chat | `/` | anyone |
| **SPV School Portal** (login only) | `/app/` (also `/login`) | parents, class teachers, principal, correspondent, admin |

## SPV School Portal (`app/`, `agent/`)
Login with mobile number + OTP. One number can hold several roles (e.g. a teacher who is also a parent).

| Role | Can do |
|---|---|
| Parent | Own children only: attendance, marks, fees + reminder, homework, updates, live van, Ask SPV |
| Class teacher | Own class: mark attendance P/A (absent → WhatsApp to parent), post homework (→ parents), class list & marks, circulars, bus routes |
| Principal | Dashboard (attendance + fees), fees list, payments, reminders, search, bus routes + live map, circulars to staff, parent updates, attendance for any class |
| Correspondent | Dashboard, fees, search, bus routes, circulars |
| Admin | Parent updates, WhatsApp outbox, fees, search, bus routes, team & logins, Excel import |

Code (class framework: Model + Harness = Agent):
- `agent/store.py` Vercel Neon Postgres, TLS-verified, every record AES-256-GCM encrypted (local file only for laptop tests) · `agent/auth.py` OTP + roles
- `agent/school.py` rules and data · `agent/notify.py` WhatsApp (Cloud API or one-tap wa.me)
- `agent/skills.py` the agent's skills per role (identity bound on the server, read-only)
- `agent/app_agent.py` Ask SPV loop for the portal · `agent/portal_api.py` routes · `agent/van.py` GPS receiver
- `tests/test_portal.py` 17 evaluation tests · `scripts/make_test_data.py` builds the test workbook
- `docs/HANDOVER.md` setup, rules and runbook · `docs/SECURITY.md` database security and paid private-network options

No student data or phone numbers are in this repo (it is public). Test data is loaded from the private
`SEED_DATA` Vercel setting or with Admin → Team & data → Import Excel.

## School van GPS (Traccar Client)
Phone app server URL: `https://spvn.vercel.app/api/van/loc/<VAN_KEY>` (interval 10–15 s, accuracy High).
A new phone shows as "Unassigned phone" under Bus routes; link it to a route there.
