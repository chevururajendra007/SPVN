# Ask SPV: AI assistant for Sri Pragathi Vidyaniketan

Agent = Model (Azure AI Foundry) + Harness (prompt, tools, loop).

| File | What it does |
|---|---|
| `.env` | Azure AI Foundry endpoint, API key, model deployment name. Copy from `.env.example`. Never commit it. |
| `agent.py` | The tools, the model and the agent loop (`chat`). |
| `main.py` | FastAPI server with one route, `POST /api/chat`. |
| `frontend/src/App.jsx` | React chat box. Sends message + history, shows the answer. |
| `requirements.txt` | langchain-azure-ai, fastapi, uvicorn, httpx, python-dotenv |
| `data/school.json` | School knowledge (RAG source). Fill in `null` values: contact, timings, fees. |
| `data/words.json` | Word of the Day archive. Add a new entry each day. |
| `evals.py` | Known questions with assertions (incl. "never invent fees"). |

## Tools
- `get_school_info(topic)`: returns only the matching slices of `school.json`
- `get_word_of_the_day(word="")`: latest or a named word
- `save_admission_enquiry(...)`: validates the phone number, saves to `enquiries.db` (SQLite)

## Run locally
```bash
cd agent
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # then fill in your Azure values
python agent.py             # quick terminal chat
uvicorn main:app --reload --port 8000

# second terminal
cd frontend && npm install && npm run dev   # open http://localhost:5173
```
Check quality any time with `python evals.py`.
