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

## SPV School App (installable, /app)
`app/` is a separate installable mobile app (PWA) at `/app/`, with the Ask SPV agent for six roles:
student, parent, teacher, office staff, admin and correspondent.

- Open `https://<site>/app/` on a phone → browser menu → **Add to Home screen** (iPhone: Share → Add to Home Screen).
- `agent/app_agent.py`: role-based agent. Each role gets its own system prompt and only its own tools
  (e.g. parents: own child's summary; teachers: attendance and notice drafts; correspondent: whole-school dashboard).
- `agent/app_api.py`: `POST /api/app/chat {role, message, history}` and `GET /api/app/home?role=`.
- `agent/data/demo.json`: **demo data only** (fictional names and numbers). Attendance marking and notices are drafts
  and are not saved yet. Real login (parent phone number + OTP) and the school database come next.
