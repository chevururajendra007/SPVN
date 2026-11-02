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
