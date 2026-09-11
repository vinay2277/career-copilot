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

## Branches

| Branch | Purpose |
|---|---|
| `main` | Stable baseline. |
| `vinay_v1` | Active development. |

## Getting started

See [`docs/SETUP.md`](docs/SETUP.md) on the `vinay_v1` branch.

## License

MIT
