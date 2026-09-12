# Setup

Verified on Windows 11, Python 3.13.5, Node 22.14.

## Prerequisites

| Tool | Needed for |
|---|---|
| Python 3.11+ | Backend |
| Node 18+ | Frontend |
| An OpenAI **or** Anthropic API key | The agents |
| [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) | Screenshot ingestion only |

Everything except the agents and OCR works without any credentials — scoring,
the board, skill ROI, what-if, and analytics are pure computation.

## Choosing a provider

Both are supported. `LLM_PROVIDER` in `.env` picks one:

```ini
# OpenAI (default)
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o          # must support structured outputs
OPENAI_REASONING_EFFORT=     # reasoning models only; blank for gpt-4o

# Anthropic
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...  # or leave blank and run `ant auth login`
ANTHROPIC_MODEL=claude-opus-5
```

`GET /health` reports which provider is active and whether its credentials
resolve. The UI reads that and warns on the pages that need the model, rather
than failing after you've filled in a form.

All seven agents call one function — `structured_call` in
`app/agents/client.py` — so the provider seam is that single file. Two
differences it absorbs:

- **Effort.** The agents tune Anthropic's `output_config.effort` per task.
  OpenAI has no equivalent on general models; reasoning models take
  `reasoning_effort`, which is opt-in so it is never sent to a model that
  would reject it.
- **Prompt caching.** Anthropic needs an explicit `cache_control` breakpoint;
  OpenAI caches long prefixes automatically, so that argument is a no-op there.

## Backend

```powershell
cd backend
python -m venv venv
.\venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
Copy-Item .env.example .env      # macOS/Linux: cp .env.example .env
```

Put your key in `.env` — `OPENAI_API_KEY=...` by default, or set
`LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY=...`. See *Choosing a
provider* above.

Create the schema and start the server:

```powershell
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --port 8000
```

`http://localhost:8000/docs` is the interactive API reference.

> On a completely empty database the app provisions the schema itself at
> startup and stamps the Alembic head, so a fresh clone runs without the
> migration step. Once tables exist it leaves them strictly alone — migrations
> are the only thing that may alter an existing schema.

### Demo data

The app opens empty. To populate a profile and a six-job board:

```powershell
python scripts/seed_demo.py
```

No credentials needed — it posts pre-validated payloads to
`/api/extract/confirm`, so the ingestion agents stay out of the path. To start
over, stop the server and delete `career_copilot.db`.

## Frontend

```powershell
cd frontend
npm install
npm run dev
```

`http://localhost:5173`. Vite proxies `/api` to `:8000`, so there is no CORS to
configure in development.

## Tests

```powershell
cd backend
python -m pytest          # 73 tests, no API key or network needed
python -m ruff check app tests
```

```powershell
cd frontend
npm run typecheck
npm run build
```

The backend suite covers the deterministic engine (alignment, skill ROI,
what-if, funnel) and the full HTTP surface. It drives `/api/extract/confirm`
with a pre-validated payload, which keeps the two agent calls out of the test
path — so the suite is fast, free, and offline.

## Database

SQLite by default (`backend/career_copilot.db`). For PostgreSQL, uncomment
`psycopg` in `requirements.txt` and set:

```
DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/career_copilot
```

Then `python -m alembic upgrade head` against the new database.

### Migrations

```powershell
python -m alembic revision --autogenerate -m "what changed"
python -m alembic upgrade head
python -m alembic downgrade -1        # roll back one
```

`migrations/env.py` reads `DATABASE_URL` from the app settings, so `alembic.ini`
holds no connection string. It also renders `EnumStr` columns as `sa.String` —
that type needs an enum class autogenerate cannot serialize, and at the database
level it is a VARCHAR anyway.

## OCR (screenshot ingestion)

Only needed for the Screenshot tab on the Add-a-job page.

1. Install Tesseract. On Windows the usual path is
   `C:\Program Files\Tesseract-OCR\tesseract.exe`.
2. Set `TESSERACT_CMD` in `.env` to that path.

Without it, the other three ingestion routes work normally and the screenshot
route returns a message saying what to install.

## Layout

```
career-copilot/
├── backend/
│   ├── app/
│   │   ├── agents/            # one module per prompt; no arithmetic here
│   │   ├── api/routes/        # HTTP surface
│   │   ├── core/config.py     # settings from the environment
│   │   ├── db/                # engine, session, EnumStr column type
│   │   ├── models/            # SQLAlchemy models
│   │   ├── services/
│   │   │   ├── analytics/     # the deterministic engine — pure, no ORM
│   │   │   ├── ingestion/     # parsers + the extract→validate pipeline
│   │   │   ├── context.py     # renders the numbers for the agent
│   │   │   └── scoring.py     # the only ORM↔analytics translation layer
│   │   ├── schemas.py         # request/response contracts
│   │   └── main.py
│   ├── migrations/            # Alembic
│   └── tests/
├── frontend/
│   └── src/
│       ├── pages/             # one per route
│       ├── api.ts             # typed client
│       ├── components.tsx     # shared UI
│       ├── hooks.ts           # useAsync / useAction
│       └── types.ts           # mirrors backend/app/schemas.py
└── docs/
```

## Resume → profile

Uploading a resume (`POST /api/resume`) parses it, reads the candidate's
details out of it, merges them into the profile, and re-scores every tracked
job. Two rules govern the merge:

- **The resume may add a skill or raise its level. It never removes one or
  lowers it.** A level read off a resume is an inference; one the user typed is
  a statement. So re-uploading is always safe — it cannot demote a correction
  made by hand. `POST /api/resume/{id}/to-profile` re-runs it on a stored
  resume, and running it twice is a no-op the second time.
- **A field the resume doesn't mention is left alone, never blanked.** An
  absent email means the resume listed none.

Scalar fields the resume *does* state (name, headline, total years) are
replaced, so the response returns a changeset the UI displays rather than
rewriting the profile silently. Every extracted skill needs a supporting quote
from the resume; one without evidence is dropped and reported, which is the
same anti-hallucination discipline the job pipeline uses.

Degrees and certifications are captured separately and never become skills —
see the note on screening criteria above.

Pass `?update_profile=false` to upload and score without touching the profile.

## The one architectural rule

**Agents never compute numbers.** Alignment scores, skill ROI, conversion
rates, and simulation deltas are all produced by `services/analytics/`, which
is pure Python over plain dataclasses — no ORM, no network, fully unit-tested.
The agents extract, validate, and advise; they read the computed figures and
are instructed not to derive their own.

That is what makes the output auditable. `/api/analytics/context` returns the
exact text the advice agent was given, and every score carries its own
derivation (`alignment.explanation`) — so when a recommendation looks wrong you
can tell immediately whether the inputs or the reasoning was at fault.

Two consequences worth knowing:

- Changing a constant in `alignment.py` (the 70/30 split, the necessity
  weights, the partial-credit fraction) changes every historical score. They
  are named constants in one place for exactly that reason.
- `EnumStr` exists because a `String` column annotated `Mapped[SomeStrEnum]`
  writes fine but reads back as a bare `str`. Everything using `==` keeps
  working while everything using `is` silently fails. Use `EnumStr` for any new
  enum column.
