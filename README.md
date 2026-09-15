# Career Copilot

A two-sided hiring platform. Students get a job board scored against their
profile and the tools to close the gaps; employers post roles and see who
applied, ranked and explained. Every number is deterministic and auditable —
models read job descriptions and résumés, they never decide anything.

## Three roles

**Student** — upload a résumé and it fills in the profile for you. Then: a job
board with employer-posted and sourced roles, each scored against your skills;
applying and tracking; your own private tracker for roles you found elsewhere;
an action centre, skill ROI and funnel analytics; interview practice; a
learning roadmap.

**Employer** — paste a job description and it is read into structured
requirements for you to check before publishing. Then: the applicants, ranked
against those requirements with a per-skill breakdown, stage controls, and a
spreadsheet export. Plus search across students who have opted into being
found.

**Administrator** — approve the organizations allowed to recruit. Until an
organization is approved it cannot post a role, parse a description, or see a
candidate. That gate is what stops anyone registering as a household name and
collecting students' contact details behind a role that does not exist.

## Two consent rules, deliberately separate

These look similar and are not, and the distinction is load-bearing:

- **Applying** to a role shows your details to that one employer, for that one
  role. It is what puts you on their applicant list.
- **Being findable** is a switch on your own profile, off by default, that lets
  approved employers search for you. Uploading a résumé does not set it.
  Applying does not set it. Only you do, and switching it off removes you
  immediately.

Collapsing those two into one flag is how a career tool quietly becomes a
database of people who never agreed to be in one.

## Architecture

```
Frontend (React + Vite) — one shell per role
  student   /profile /jobs /applications /add /opportunities
            /action-center /skill-roi /analytics /interview /learning
  employer  /roles /roles/:id (candidates) /post /find
  admin     /organizations
        |
FastAPI backend (:8000)
  /api/auth/*      registration, sign-in, sessions
  /api/board/*     the student's board and applications
  /api/employer/*  postings, candidates, CSV export, search
  /api/admin/*     organization approval
  /api/extract/*   /api/profile  /api/analytics/*  /api/simulation/what-if
        |
  +-- Ingestion pipeline: parser/OCR -> Extraction Agent -> Validation Agent
  +-- Career Analytics Engine (deterministic)
  |     alignment scorer (70% requirements / 30% preferences)
  |     skill ROI  |  what-if simulator  |  application funnel
  |     candidate search — the same scorer, inverted
  +-- Career Intelligence Agent ("what should I do next?")
        |
  SQLite (dev) -> PostgreSQL (prod)
```

**Design rule:** all scoring and analytics are deterministic and reproducible.
LLMs are used only for extraction, validation, and narrative recommendations —
never for computing a number, and never for deciding an outcome. A score ranks
a list of candidates; it never shortens one. Advancing or declining an
applicant is always a person's action.

**Provider:** OpenAI or Anthropic, switched with `LLM_PROVIDER` in `.env`. All
seven agents call one function, so that seam is a single file. Everything that
doesn't call a model — scoring, the board, candidate search, skill ROI,
what-if, analytics — works with no credentials at all.

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

**Before putting it on a public URL,** set `APP_PASSWORD` and `SECRET_KEY` in
`.env`. The password gate is off when `APP_PASSWORD` is empty, which keeps
local development frictionless but leaves a deployment wide open. With it set,
every `/api/*` route needs a session, and the AI routes are separately capped
so nobody can burn your API credit. See [`docs/DEPLOY.md`](docs/DEPLOY.md).

## License

MIT
