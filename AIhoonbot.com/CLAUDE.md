# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a full-stack AI assistant ecosystem composed of two main components:

- **Hoonbot** — Python/FastAPI personal AI bot (port 3939), connects to a local LLM API (port 10007)
- **Messenger** — TypeScript/React/Electron real-time chat platform (port 3000) that serves as the human–bot communication bridge

They are designed to run together. Hoonbot registers itself as a bot in Messenger, subscribes to webhooks, and responds to messages via the Messenger REST API.

## Commands

### Full Stack

```bash
./start-all.sh          # Start both Hoonbot and Messenger
```

### Hoonbot (Python)

```bash
cd Hoonbot
pip install -r requirements.txt
python hoonbot.py

# Utilities
python reset.py --all           # Reset all state
python reset.py --memory        # Clear memory DB
python reset.py --list-memory   # Print stored memories
```

### Messenger (TypeScript/Node)

```bash
cd Messenger
npm install

npm run dev             # Run server + client together
npm run dev:server      # Server only (hot-reload via ts-node-dev)
npm run dev:client      # Client only (Vite)

npm run build           # Build Electron app for Windows
npm run build:linux     # Build Electron app for Linux
npm run build:web       # Web-only Vite build
npm run typecheck       # TypeScript type check (no emit)
```

## Architecture

### How the Two Components Connect

1. On startup, `Hoonbot/hoonbot.py` calls `POST /api/bots` on Messenger to register and receive an API key (stored in `Hoonbot/data/.apikey`).
2. Hoonbot subscribes to `new_message` webhook events via `POST /api/webhooks`.
3. Messenger fires `POST http://localhost:3939/webhook` for each new message.
4. Hoonbot processes the message through the LLM and calls `POST /api/send-message` to reply.

### Hoonbot Internal Architecture

Entry point: `Hoonbot/hoonbot.py` — FastAPI app with lifespan startup/shutdown.

Core modules in `Hoonbot/core/`:
- `llm.py` — LLM API client; loads `SOUL.md` as system prompt, injects memories + skills
- `memory.py` — Persistent key-value store (SQLite + FTS5); `_system`-tagged entries are hidden from the LLM
- `history.py` — Per-room conversation history (SQLite, max 50 messages)
- `heartbeat.py` — Proactive background loop driven by `HEARTBEAT.md` checklist
- `scheduled.py` + `scheduler.py` — APScheduler-backed cron and one-time job storage
- `skills.py` — Loads Markdown files from `skills/` and injects them into every LLM prompt
- `daily_log.py` — Append-only daily notes to `data/memory/YYYY-MM-DD.md`
- `notify.py` — Desktop notifications via plyer
- `status_file.py` — Regenerates `data/status.md` (human-readable DB snapshot)
- `messenger.py` — HTTP client wrapper for the Messenger bot API

Webhook handlers in `Hoonbot/handlers/`:
- `webhook.py` — Handles Messenger-originated events (`POST /webhook`) and external incoming webhooks (`POST /webhook/incoming/<source>`, authenticated via `X-Webhook-Secret`)

LLM command patterns the bot embeds in its replies (parsed by `hoonbot.py`):
- `[MEMORY_SAVE: key=..., value=..., tags=...]`
- `[MEMORY_DELETE: key=...]`
- `[SCHEDULE: name=..., cron=HH:MM, prompt=...]`
- `[SCHEDULE: name=..., at=YYYY-MM-DD HH:MM, prompt=...]`
- `[DAILY_LOG: one sentence entry]`
- `[SKILL_CREATE: name=..., description=...]...instructions...[/SKILL_CREATE]`
- `[NOTIFY: title=..., message=...]`

Configurable via environment variables — see `Hoonbot/config.py` for all 40+ options (ports, active hours, compaction threshold, webhook secret, etc.).

### Messenger Internal Architecture

See `Messenger/CLAUDE.md` for the full Messenger-specific reference including API endpoints, Socket.IO events, and database schema.

Key points:
- **Database**: SQLite via sql.js (WASM), auto-saved every 5 seconds to `server/data/messenger.db`
- **Auth**: IP-based — users identified by IP + display name; no passwords
- **Bot API**: All bot-facing endpoints under `/api`, authenticated via `Authorization: Bearer huni_...` API key
- **Socket.IO rooms** are prefixed `room:<id>`
- **File cleanup**: cron at 03:00 daily purges chat uploads older than 30 days

### Shared Types

`Messenger/shared/types.ts` defines the canonical TypeScript types used by both client and server (messages, rooms, users, etc.).

## Key Files to Know

| File | Purpose |
|------|---------|
| `Hoonbot/SOUL.md` | System prompt / personality for the LLM |
| `Hoonbot/HEARTBEAT.md` | User-editable checklist driving the proactive heartbeat loop |
| `Hoonbot/config.py` | All configuration with env var overrides |
| `Hoonbot/skills/` | Markdown skill files injected into every LLM call |
| `Hoonbot/data/status.md` | Auto-generated human-readable memory/schedule snapshot |
| `Messenger/docs/API.md` | Full Messenger REST API reference |
| `Messenger/test.ipynb` | Jupyter notebook for interactive API testing |
