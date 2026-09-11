# Setup

Verified on Windows 11, Python 3.13.5, Node 22.14.

## Prerequisites

| Tool | Needed for |
|---|---|
| Python 3.11+ | Backend |
| Node 18+ | Frontend |
| An Anthropic API key *or* `ant auth login` | The three agents |
| [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) | Screenshot ingestion only |

Everything except the agents and OCR works without any credentials — scoring,
the board, skill ROI, what-if, and analytics are pure computation.

## Backend

```powershell
cd backend
python -m venv venv
.\venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
Copy-Item .env.example .env      # macOS/Linux: cp .env.example .env
```

Put your key in `.env` as `ANTHROPIC_API_KEY=...`, or leave it blank and run
`ant auth login` — the SDK resolves credentials itself either way.

Create the schema and start the server:

```powershell
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --port 8000
```

`http://localhost:8000/docs` is the interactive API reference.

> The app also calls `create_all` on startup, so it runs without a migration.
> That is a dev convenience only: `create_all` cannot alter an existing table,
> so any schema change after the first run needs a real migration.

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
