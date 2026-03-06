# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

Two components that run together:

- **Hoonbot** — Python/FastAPI personal AI bot (port 3939), connects to LLM API (port 10007)
- **Messenger** — TypeScript/Node.js real-time chat platform (port 10006 by default) that serves as the human-bot UI

Hoonbot registers as a bot in Messenger, receives webhooks, processes messages through the LLM API agent, and replies via the Messenger REST API.

## Commands

### Full Stack
```bash
./start-all.sh              # Linux: start all services (sources settings.txt)
start-all.bat               # Windows: start Messenger + Cloudflare only
```

### Hoonbot (Python)
```bash
cd Hoonbot
pip install -r requirements.txt
python setup.py             # One-time: configure LLM API credentials
python hoonbot.py           # Start the bot

python reset.py --memory    # Clear memory.md
python reset.py --list-memory
python test_llm.py          # Verify LLM API connectivity
```

### Messenger (TypeScript/Node)
```bash
cd Messenger
npm install
npm run dev:server          # Server only (hot-reload)
npm run dev                 # Server + Vite client
npm run typecheck           # Type-check without emit
npm run build:web           # Web-only build
npm run build               # Electron build (Windows)
```

## Configuration

**Master config:** `settings.txt` at the repo root — all values readable by both `start-all.sh` (sourced as env vars) and `Hoonbot/config.py` (parsed directly, works on Windows too).

`Hoonbot/config.py` reads: env var → `settings.txt` → hardcoded default. To change any Hoonbot behavior, edit `settings.txt`. Key Hoonbot settings:

| Setting | Default | Purpose |
|---------|---------|---------|
| `HOONBOT_PORT` | 3939 | Bot server port |
| `HOONBOT_BOT_NAME` | Bot | Display name in Messenger |
| `HOONBOT_HOME_ROOM_ID` | 1 | Room that receives heartbeat output |
| `HOONBOT_STREAMING` | true | Stream LLM responses with tool status updates |
| `HOONBOT_DEBOUNCE_SECONDS` | 1.5 | Combine rapid messages within this window |
| `HOONBOT_LLM_TIMEOUT` | 300 | LLM request timeout in seconds |
| `HOONBOT_SESSION_MAX_AGE_DAYS` | 7 | Auto-expire and reset room sessions |
| `HOONBOT_HEARTBEAT_INTERVAL` | 3600 | Seconds between heartbeat ticks |
| `HOONBOT_HEARTBEAT_ACTIVE_START/END` | 00:00/23:59 | Active hours window |

LLM credentials are stored in `Hoonbot/data/.llm_key` and `Hoonbot/data/.llm_model` (created by `setup.py`). The Messenger API key is in `Hoonbot/data/.apikey` (created at first startup).

## Architecture

### Message Flow

```
Messenger UI
    │ webhook: POST /webhook
    ▼
Hoonbot handlers/webhook.py
    ├── validate (text/image/file, not bot, @mention if non-home room)
    ├── mark_read (best-effort)
    ├── debounce (combine rapid messages, configurable window)
    └── process_message()
            │ POST /v1/chat/completions (streaming or sync)
            ▼
        LLM API (port 10007)
            └── agent loop: uses tools (websearch, file_reader/writer,
                python_coder, shell_exec, rag, file_navigator)
            │ SSE stream or JSON response
            ▼
        Hoonbot: send reply via Messenger API
            └── reply is threaded as a reply to the original message
```

### Hoonbot Internal Structure

**Entry point:** `hoonbot.py` — lifespan startup: health-check LLM API → register bot → subscribe webhooks (`new_message`, `message_edited`, `message_deleted`) → catch-up on missed messages → start heartbeat loop.

**Key modules:**

| File | Responsibility |
|------|---------------|
| `handlers/webhook.py` | All message processing: debounce, session management, streaming/sync LLM calls, file/image handling, session lifecycle |
| `core/messenger.py` | Messenger REST API client with persistent connection pool. Covers: send/edit/delete messages, typing, read receipts, files, pins, web watchers, room creation, search |
| `core/heartbeat.py` | Background loop: reads `HEARTBEAT.md` checklist, calls LLM agent, posts result to home room |
| `core/retry.py` | `with_retry()` helper — exponential backoff for transient HTTP failures |
| `config.py` | Reads `settings.txt` + env vars. Single source of truth for all runtime config |

**System prompt:** `PROMPT.md` — defines identity, memory usage, and behavior. Tool documentation is intentionally omitted here because the LLM API already sends tool schemas via the `tools` parameter automatically.

**Heartbeat prompt:** `HEARTBEAT.md` — user-editable checklist. The heartbeat runs this checklist through the full LLM agent every `HEARTBEAT_INTERVAL_SECONDS`.

**Memory:** `data/memory.md` — Markdown file read/written by the LLM using `file_reader`/`file_writer` tools. Its absolute path is injected into the system prompt on every new session so the LLM knows where to find it.

### Session Management

Per-room LLM sessions are stored in `data/room_sessions.json` as `{room_id: {session_id, created_at}}`. Sessions auto-expire after `SESSION_MAX_AGE_DAYS`. On expiry or 404 from LLM API, a new session is started (re-injects full context: system prompt + memory).

First message in a session sends the full context (system prompt + memory path + memory content). Subsequent messages in the same session just send the user message — the LLM API maintains history server-side.

### Streaming vs Sync

Controlled by `HOONBOT_STREAMING` in `settings.txt`. When streaming:
- LLM API sends SSE events
- Tool status events (`tool_status.started` / `tool_status.completed`) are sent as temporary messages to Messenger and deleted after the reply is ready
- Full text accumulates and is sent as the final reply, threaded as a reply to the original message

### Messenger API Coverage

`core/messenger.py` wraps these Messenger endpoints (all authenticated with `x-api-key` header):
- Messages: send, send-returning-id, edit, delete, mark-read, search
- Typing: start/stop
- Files: send-file (multipart), send-base64
- Pins: pin, unpin, get
- Web watchers: create, list, delete — polls URLs and posts to room on content change
- Rooms: create, get, get-messages
- Bot: register, get-info, register-webhook

### LLM API Integration

Hoonbot calls `POST /v1/chat/completions` on LLM API (port 10007) with form-encoded data:
- `model`, `messages` (JSON-encoded array), optional `session_id`, optional `stream=true`
- Response includes `x_session_id` to persist for the room
- The LLM API agent loop handles all tool calls internally — Hoonbot never calls tools directly

## Key Files

| File | Purpose |
|------|---------|
| `settings.txt` | Master config for all services |
| `Hoonbot/PROMPT.md` | System prompt (identity + memory instructions; no tool docs) |
| `Hoonbot/HEARTBEAT.md` | Proactive task checklist run every heartbeat interval |
| `Hoonbot/data/memory.md` | Persistent LLM memory (Markdown, read/written by LLM tools) |
| `Hoonbot/data/room_sessions.json` | Room → LLM session ID + creation timestamp |
| `Messenger/docs/API.md` | Full Messenger REST API reference |
| `Messenger/shared/types.ts` | Canonical TypeScript types for messages, rooms, users |

## Gotchas

1. **Memory path must be absolute** — injected as text in system prompt so LLM can call `file_reader`/`file_writer` with the right path
2. **New sessions re-inject full context** — if a session expires or 404s, the next message becomes a "first message" and rebuilds the full system prompt + memory context
3. **Streaming requires LLM API SSE support** — if LLM API doesn't return proper `tool_status` events, tool status messages won't appear (silent degradation, final reply still sent)
4. **Bot API key survives restarts** — stored in `data/.apikey`; if Messenger resets, delete this file to force re-registration
5. **Webhook subscription is idempotent** — `register_webhook()` checks existing subscriptions before adding; safe to call on every restart
6. **sql.js is in-memory** — Messenger DB lives in RAM, auto-saved to disk every 5 seconds; unclean shutdown can lose up to 5 seconds of data
7. **Heartbeat first tick is delayed** — runs after one full interval at startup, never immediately
8. **`data/` directories are gitignored** — all runtime data excluded from version control
