# Career Copilot

AI career platform that turns any job post — text, URL, PDF, or screenshot — into an alignment score, a skill-gap map, and a concrete next move.

## What it does

You paste a job post in whatever form you have it. Career Copilot extracts the real requirements, scores them against your profile with math you can audit, shows you exactly which skills you're missing, and tells you what to do next — tailor the resume, learn a skill, or prep for the interview.

## Architecture

```
Frontend (React + Vite)
  /profile  /add  /opportunities  /skill-roi  /analytics  /action-center
        |
FastAPI backend (:8000)
  /api/extract/*   /api/profile   /api/opportunities/*
  /api/simulation/what-if         /api/analytics/*
        |
  +-- Ingestion pipeline: parser/OCR -> Extraction Agent -> Validation Agent
  +-- Career Analytics Engine (deterministic)
  |     alignment scorer (70% requirements / 30% preferences)
  |     skill ROI  |  what-if simulator  |  application funnel
  +-- Career Intelligence Agent ("what should I do next?")
        |
  SQLite (dev) -> PostgreSQL (prod)
```

**Design rule:** all scoring and analytics are deterministic and reproducible. LLMs are used only for extraction, validation, and narrative recommendations — never for computing a number.

**Provider:** OpenAI or Anthropic, switched with `LLM_PROVIDER` in `.env`. All seven agents call one function, so that seam is a single file. Everything that doesn't call a model — scoring, the board, skill ROI, what-if, analytics — works with no credentials at all.

## Branches

| Branch | Purpose |
|---|---|
| `main` | Stable baseline. |
| `vinay_v1` | Active development. |

## Getting started

Needs only Python 3.11+ and Node 18+. No API key required to run it — the whole
scoring half is pure computation.

```powershell
git clone -b vinay_v1 https://github.com/vinay2277/career-copilot.git
cd career-copilot

# terminal 1 — backend
cd backend
python -m venv venv
.\venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
Copy-Item .env.example .env      # macOS/Linux: cp .env.example .env
python -m uvicorn app.main:app --port 8000

# terminal 2 — frontend
cd frontend
npm ci
npm run dev
```

Then open http://localhost:5173 (use `localhost`, not `127.0.0.1` — Vite binds
IPv6 only).

On Windows, clone to a short path such as `C:\dev\` — the `openai` package has
filenames that exceed the 260-character limit from a deeply nested directory.

Full instructions, the AI-feature setup, and troubleshooting:
[`docs/SETUP.md`](docs/SETUP.md).

## Deploying

Builds to a single image that serves the API and the frontend on one port, so
any Docker host works:

```bash
docker compose up --build     # app + PostgreSQL, on :8000
```

**Before putting it on a public URL:** there is no authentication and no rate
limiting, so anyone with the link can read the profile and spend your API
credit. See [`docs/DEPLOY.md`](docs/DEPLOY.md) for the details and what has
actually been tested.

## License

MIT
