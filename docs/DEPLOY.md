# Deploying

## Read this first

**Set `SECRET_KEY` before exposing this.**

```ini
SECRET_KEY=<python -c "import secrets; print(secrets.token_urlsafe(32))">
COOKIE_SECURE=true              # you are serving over HTTPS
REQUIRE_ORG_VERIFICATION=true   # default; leave it on
```

`SECRET_KEY` matters more than it looks: without it a random key is generated
per process, so every restart logs everyone out and two workers never agree on
a session. The app logs a warning when that is happening.

Every `/api/*` route requires a session, obtained by registering or signing in
and held in a signed, http-only cookie. `/health` and `/api/meta/config` stay
open — platforms probe the first, and the sign-in screen needs the second.

**This is a real user system, and three roles are not the same thing.** Each
account owns its own profile and data; a route is reachable only by the role it
belongs to, checked at the router so a route added later cannot arrive
unprotected. A recruiter additionally cannot post or see candidates until an
administrator approves their organization. `APP_PASSWORD`, the single shared
password this used to have, is ignored — it is read only so an existing deploy
that still sets it does not fail to start.

### Rate limits

Three separate budgets, per client IP:

| Limit | Default | Why |
|---|---|---|
| `RATE_LIMIT_AI_PER_HOUR` | 40 | These routes call a model. Each one costs money. |
| `RATE_LIMIT_API_PER_MINUTE` | 120 | General throughput. |
| `RATE_LIMIT_LOGIN_PER_HOUR` | 10 | Password guessing. Keyed by IP, not by account — an account key would let anyone register and reset their own budget. |

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
   `SECRET_KEY` is generated, `DATABASE_URL` is wired to the database,
   `COOKIE_SECURE` is already true.
5. **Apply.** The first build takes roughly 5–10 minutes: it installs Node,
   builds the frontend, then installs the Python dependencies.
6. Open the URL and **register**. There is no shared password any more; the
   sign-in screen creates student and recruiter accounts. The first person to
   register gets no special powers — see the next section for how to make
   yourself an administrator.

### Making yourself an administrator

Someone has to approve the companies allowed to recruit, and an account that
can do that is deliberately not something you can sign up for. On a host with
no shell, use the bootstrap variables. In the service's **Environment** tab:

| Variable | Value |
|---|---|
| `BOOTSTRAP_ADMIN_EMAIL` | An address you do **not** already have an account on |
| `BOOTSTRAP_ADMIN_PASSWORD` | A password you pick |
| `BOOTSTRAP_ADMIN_ROLE` | `admin` |

Save (the service restarts), sign in with those, and you land on
**Organizations**. Then **clear all three and save again** — while they are
set, the password is reapplied on every restart, so a password you change in
the app silently reverts at the next deploy.

`BOOTSTRAP_ADMIN_ROLE` applies only to an account the bootstrap *creates*; an
account that already exists keeps the role it has. That is why the email must
be a new one, and it is what stops the variable silently promoting or demoting
somebody. It defaults to `student`.

With a shell, `python scripts/set_password.py --list` and its sibling commands
do the same job.

### Approving a recruiter

A recruiter can register at any time, but until an administrator approves their
organization they cannot post a role, parse a description, or see a candidate —
which is what stops anyone posting a fake role to collect students' contact
details. As an admin, open **Organizations**, check the email domain against
the company being claimed, and approve. Withdrawing approval later stops new
postings but leaves published roles and existing applications untouched.

To run without this gate — a single-tenant instance where you are the only
recruiter — set `REQUIRE_ORG_VERIFICATION=false`. Don't do that anywhere
students can register.

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
| `SECRET_KEY` | **Required.** Stable and secret, or sessions break on restart. |
| `COOKIE_SECURE` | `true` — every real host terminates TLS. |
| `DATABASE_URL` | The managed Postgres URL, as the provider gives it |
| `OPENAI_API_KEY` | Your key, as a secret |
| `LLM_PROVIDER` | `openai` (default) or `anthropic` |
| `REQUIRE_ORG_VERIFICATION` | `true`. Leave it on anywhere public. |
| `BOOTSTRAP_ADMIN_*` | Temporary, to create the first admin. See above. |
| `CORS_ORIGINS` | Only matters if a separately hosted frontend calls this API |
| `APP_PASSWORD` | Legacy and unused. Kept only so an existing deploy still boots. |

**`DATABASE_URL` is normalized for you.** Managed Postgres hands out
`postgres://user:pass@host/db`, which SQLAlchemy 2 rejects; the app rewrites it
to `postgresql+psycopg://` at startup. Paste the provider's URL as-is.

**Use a managed database, not the container's disk.** Most platforms have
ephemeral filesystems — a SQLite file inside the container is wiped on every
redeploy.

**Migrations run at startup.** An empty database is created and stamped; an
existing one is upgraded to head. No release command, and nothing to remember.

This is deliberate rather than tidy. An earlier version created the schema only
when the database was empty and left existing ones to "a release command" —
which was never wired up, so a deploy shipped new code against an old schema.
The app booted, served pages, and 500'd on `no such table: accounts` the moment
anyone signed up. Booting into a broken state is worse than refusing to boot.

One assumption comes with it: **a single instance**. Two processes migrating
concurrently can deadlock or double-apply. If you scale out, move this to a
pre-deploy command that runs once.

## What has actually been verified

Tested on this machine:

- **Authentication and roles.** A cookie-less client is refused on every
  `/api/*` route; `/health` and `/api/meta/config` stay open; a wrong password
  is rejected and leaves the API closed; the right one issues an http-only
  `SameSite=Lax` cookie; sign-out closes it again; repeated failed logins are
  throttled with a `Retry-After`. Across roles: a student cannot reach a
  recruiter's routes or an administrator's, a recruiter cannot approve their
  own organization, and a recruiter cannot read or modify another
  organization's postings.
- **Organization verification, end to end.** An unapproved recruiter is refused
  on posting and on the AI parse route; after an administrator approves them
  both open; withdrawing approval closes them again while leaving published
  roles on the board and students' applications intact.
- The single-process setup, end to end: deep links (`/opportunities/9`) serve
  the SPA shell, `/api/*` reaches its handlers, a mistyped `/api` path returns
  JSON rather than the HTML shell, hashed assets serve, `index.html` is sent
  `no-cache`. Eleven tests in `tests/test_spa_serving.py` cover it.
- The container config, statically: the `frontend/dist` path resolves to the
  same place the Dockerfile copies it, `psycopg` is installed by the image and
  absent from `requirements.txt`, the SQLite-only branches stay off for
  Postgres, compose parses and its dialect matches the installed driver,
  `.dockerignore` excludes `.env` and `*.db`, and the CMD honours `$PORT`.

**Deployed and running** on Render's free tier against managed Postgres, built
from this blueprint. Two deploys failed before it stood up, and both failures
are the reason for advice above: a dependency that was installed by hand and
never added to `requirements.txt` (`tests/test_dependencies.py` now fails the
build for that), and migrations that existed only as a documented release
command nobody had wired up (startup runs them now).

**Not verified:** the image has never been built locally and compose has never
been run — Docker is not installed on the machine this was written on. Render
builds the same Dockerfile, so the image itself is exercised; `docker compose
up --build` is not.
