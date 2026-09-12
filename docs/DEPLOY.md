# Deploying

## Read this first

**Set `APP_PASSWORD` before exposing this.** It is empty by default, and an
empty password means the gate is off — fine on localhost, wide open on a public
URL.

```ini
APP_PASSWORD=something-long-and-random
SECRET_KEY=<python -c "import secrets; print(secrets.token_urlsafe(32))">
COOKIE_SECURE=true       # you are serving over HTTPS
```

With those set, every `/api/*` route requires a session, obtained by posting
the password to `/api/auth/login` and held in a signed, http-only cookie.
`/health` and `/api/auth/status` stay open — platforms probe the first, and the
frontend needs the second to know whether to show a login screen.

`SECRET_KEY` matters more than it looks: without it a random key is generated
per process, so every restart logs everyone out and two workers never agree on
a session. The app logs a warning when that is happening.

This is one shared password, not a user system. It exists to stop strangers
reading the résumé and spending the API key — not to model identity. Everything
still runs against a single profile (`CURRENT_PROFILE_ID = 1`), so anyone with
the password sees the same data. Multi-user would mean per-user filtering on
every query and a real login system.

### Rate limits

Three separate budgets, per client IP:

| Limit | Default | Why |
|---|---|---|
| `RATE_LIMIT_AI_PER_HOUR` | 40 | These routes call a model. Each one costs money. |
| `RATE_LIMIT_API_PER_MINUTE` | 120 | General throughput. |
| `RATE_LIMIT_LOGIN_PER_HOUR` | 10 | Guessing one shared password is the attack this design invites. |

The AI budget is separate on purpose: exhausting it must not lock you out of
your own board, so cheap reads are never charged against it.

**Counters live in process memory.** Two workers each allow the full budget and
a restart clears everything — the right trade for a single instance, which is
what this is. More than one instance means moving the store to Redis;
`app/core/ratelimit.py` is written so only the storage class changes.

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

## To Render, step by step

A `render.yaml` blueprint is in the repo, so most of this is click-through.

1. **Push the branch** you want deployed. Render builds from GitHub.
2. Go to [dashboard.render.com](https://dashboard.render.com) → **New** →
   **Blueprint**.
3. Connect the GitHub repo and pick the branch (`vinay_v1` unless you have
   merged to `main`).
4. Render reads `render.yaml` and shows a web service plus a Postgres database.
   It will prompt for **`OPENAI_API_KEY`** — that is the only value you type.
   `SECRET_KEY` and `APP_PASSWORD` are generated, `DATABASE_URL` is wired to
   the database, `COOKIE_SECURE` is already true.
5. **Apply.** The first build takes roughly 5–10 minutes: it installs Node,
   builds the frontend, then installs the Python dependencies.
6. When it goes live, open the service → **Environment** → reveal
   **`APP_PASSWORD`**. That is your login. Change it there if you would rather
   pick your own; the service restarts on save.
7. Open the URL, enter the password, and upload your résumé.

### Two things about Render's free tier

- **The service sleeps after 15 minutes idle.** The next request takes 30–60
  seconds to wake it. Harmless for personal use; it looks broken in a demo, so
  load the page a minute beforehand.
- **The free database is deleted after 30 days.** Render will email first. Back
  up with `pg_dump`, or move to the paid plan, or switch to SQLite on a
  persistent disk (also paid).

### Other hosts

Anything that builds a Dockerfile works — Railway, Fly, Cloud Run. The image
honours `$PORT`, which all of them set. Without a blueprint you set the
variables from the table below by hand; nothing else differs.

What to configure:

| Setting | Value |
|---|---|
| `APP_PASSWORD` | **Required.** Without it the API is open to anyone. |
| `SECRET_KEY` | **Required.** Stable and secret, or sessions break on restart. |
| `COOKIE_SECURE` | `true` — every real host terminates TLS. |
| `DATABASE_URL` | The managed Postgres URL, as the provider gives it |
| `OPENAI_API_KEY` | Your key, as a secret |
| `LLM_PROVIDER` | `openai` (default) or `anthropic` |
| `CORS_ORIGINS` | Only matters if a separately hosted frontend calls this API |

**`DATABASE_URL` is normalized for you.** Managed Postgres hands out
`postgres://user:pass@host/db`, which SQLAlchemy 2 rejects; the app rewrites it
to `postgresql+psycopg://` at startup. Paste the provider's URL as-is.

**Use a managed database, not the container's disk.** Most platforms have
ephemeral filesystems — a SQLite file inside the container is wiped on every
redeploy.

The schema provisions itself on first boot against an empty database and stamps
the Alembic head, so no migration step is needed for a fresh deploy. For an
existing database, run `alembic upgrade head` as a release command.

## What has actually been verified

Tested on this machine:

- **The password gate, against a running server with `APP_PASSWORD` set.** A
  cookie-less client is refused on `/api/profile`, `/api/opportunities`,
  `/api/analytics/funnel` and `/api/extract/text`; `/health` and
  `/api/auth/status` stay open; the wrong password is rejected and leaves the
  API closed; the right one issues an http-only `SameSite=Lax` cookie that
  opens it; sign-out closes it again; and repeated failed logins are throttled
  with a `Retry-After`. Thirty-seven tests cover the gate and the limiter.
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
