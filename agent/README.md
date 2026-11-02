# Ask SPV: AI assistant for Sri Pragathi Vidyaniketan

Agent = Model (free local model via Ollama) + Harness (prompt, tools, loop). No API key, and no school data leaves the laptop.

| File | What it does |
|---|---|
| `.env` | Model settings (Ollama by default; Azure optional). Copy from `.env.example`. Never commit it. |
| `agent.py` | The tools, the model and the agent loop (`chat`). |
| `main.py` | FastAPI server: `POST /api/chat`, plus the chat page at `/`. |
| `web/index.html` | Ready-to-use chat page (no npm needed). |
| `frontend/src/App.jsx` | React version of the chat box (optional, needs npm). |
| `requirements.txt` | langchain-ollama, langchain-core, fastapi, uvicorn, httpx, python-dotenv |
| `data/school.json` | School knowledge (RAG source). Fill in `null` values: contact, timings, fees. |
| `data/words.json` | Word of the Day archive. Add a new entry each day. |
| `evals.py` | Known questions with assertions (incl. "never invent fees"). |

## Tools
- `get_school_info(topic)`: returns only the matching slices of `school.json`
- `get_word_of_the_day(word="")`: latest or a named word
- `save_admission_enquiry(...)`: validates the phone number, saves to `enquiries.db` (SQLite)

## Run locally (free, no API key)
1. Install Ollama from https://ollama.com/download, then:
   ```bash
   ollama pull qwen2.5:3b      # about 2 GB, supports tool calling; runs on 8 GB RAM
   ```
2. Start the agent:
   ```bash
   cd agent
   python -m venv .venv
   .venv\Scripts\activate          # Mac/Linux: source .venv/bin/activate
   pip install -r requirements.txt
   copy .env.example .env          # Mac/Linux: cp .env.example .env
   uvicorn main:app --port 8000
   ```
3. Open http://localhost:8000

**Backup mode:** if Ollama is not running, the agent still answers from the school data
(Word of the Day, address, admissions) without AI. To force it, set `LLM_PROVIDER=offline` in `.env`.

Faster model on a strong laptop: `ollama pull qwen2.5:7b` and set `OLLAMA_MODEL=qwen2.5:7b`.
Check quality with `python evals.py`.
