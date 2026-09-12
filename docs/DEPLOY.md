# Deploying

## Read this first

**The app has no authentication and no rate limiting.** On a public URL that
means two concrete things:

- Anyone who finds the URL can read and edit the profile — résumé text, salary
  expectations, the whole job board. `app/api/deps.py` hardcodes
  `CURRENT_PROFILE_ID = 1`; every request gets the same profile.
- Anyone can call the AI endpoints, and each call spends real money on your API
  key. Nothing caps that.

So: deploy behind something, or keep the URL private, or add auth first. A
platform-level password (Render and Fly both offer one) is enough for a demo.

The architecture anticipated this — every query already filters on
`profile_id`, so adding real auth means replacing `get_profile()` rather than
touching any route.

## Shape

One image, one process, one port. The frontend is built in a Node stage and its
output copied into the Python image, which serves it alongside the API:

```
  browser ──> :8000 ──┬─ /            index.html (SPA shell)
                      ├─ /assets/*    hashed bundles
                      ├─ /api/*       FastAPI
                      └─ /health
```

Because it is one origin, there is no CORS to configure and no second service
to keep in sync. `app/main.py` mounts the build only when
`frontend/dist/index.html` exists, so development is unaffected — Vite still
serves the frontend there.

## Locally, production-shaped

```powershell
docker compose up --build      # app + PostgreSQL
```

Then http://localhost:8000. Put your key in `backend/.env` first; it is read at
runtime and never baked into the image.

Without Docker you can run the same single-process setup directly:

```powershell
cd frontend; npm run build
cd ..\backend; python -m uvicorn app.main:app --port 8000
```

The backend picks up `frontend/dist` automatically and serves everything on
:8000.

## To a host

Any platform that builds a Dockerfile works — Render, Railway, Fly, Cloud Run.
The image honours `$PORT`, which all of them set.

What to configure:

| Setting | Value |
|---|---|
| `DATABASE_URL` | The managed Postgres URL, rewritten as `postgresql+psycopg://...` |
| `OPENAI_API_KEY` | Your key, as a secret |
| `LLM_PROVIDER` | `openai` (default) or `anthropic` |
| `CORS_ORIGINS` | Only matters if a separately hosted frontend calls this API |

**`DATABASE_URL` needs rewriting.** Managed Postgres hands out
`postgres://user:pass@host/db`; SQLAlchemy needs
`postgresql+psycopg://user:pass@host/db`. A URL left in the platform's default
form fails at startup with an unhelpful dialect error.

**Use a managed database, not the container's disk.** Most platforms have
ephemeral filesystems — a SQLite file inside the container is wiped on every
redeploy.

The schema provisions itself on first boot against an empty database and stamps
the Alembic head, so no migration step is needed for a fresh deploy. For an
existing database, run `alembic upgrade head` as a release command.

## What has actually been verified

Tested on this machine:

- The single-process setup, end to end: deep links (`/opportunities/9`) serve
  the SPA shell, `/api/*` reaches its handlers, a mistyped `/api` path returns
  JSON rather than the HTML shell, hashed assets serve, `index.html` is sent
  `no-cache`. Eleven tests in `tests/test_spa_serving.py` cover it.
- The container config, statically: the `frontend/dist` path resolves to the
  same place the Dockerfile copies it, `psycopg` is installed by the image and
  absent from `requirements.txt`, the SQLite-only branches stay off for
  Postgres, compose parses and its dialect matches the installed driver,
  `.dockerignore` excludes `.env` and `*.db`, and the CMD honours `$PORT`.

**Not verified:** the image has never been built and compose has never been
run — Docker is not installed on the machine this was written on. The
Dockerfile and compose file are written from the verified single-process
behaviour, but treat the first `docker compose up --build` as the real test.

Nothing has been deployed to a host.
