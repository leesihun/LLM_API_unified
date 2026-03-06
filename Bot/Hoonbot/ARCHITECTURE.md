# Hoonbot Architecture

## Overview

Hoonbot is a tool-driven personal AI assistant that bridges Huni Messenger (chat frontend) and LLM_API_fast (LLM backend). It has no custom databases or complex state management — just a memory file, a skills directory, and pure tool usage through the LLM agent.

```
┌─────────────────────┐
│  Huni Messenger     │ (Chat UI on port 3000)
│   (TypeScript)      │
└──────────┬──────────┘
           │ webhooks + REST API
           │
┌──────────▼──────────┐
│     Hoonbot         │ (FastAPI on port 3939)
│    (Python)         │
│                     │
│  • Webhook handler  │
│  • Messenger client │
│  • Heartbeat loop   │
│  • Session manager  │
│  • Prompt builder   │
└──────────┬──────────┘
           │ /v1/chat/completions (streaming SSE)
           │
┌──────────▼──────────┐
│ LLM_API_fast        │ (Agent system on port 10007)
│ (Python)            │
│                     │
│ • websearch         │
│ • file_reader/writer│
│ • file_navigator    │
│ • python_coder      │
│ • shell_exec        │
│ • rag / memo        │
│ • process_monitor   │
└─────────────────────┘
```

## File Organization

```
Hoonbot/
├── hoonbot.py              # Entry point, FastAPI server + lifespan startup
├── config.py               # All config (env > settings.txt > defaults)
├── PROMPT.md               # System prompt (identity, memory, skills, tools)
├── HEARTBEAT.md            # Proactive task checklist run every heartbeat
├── ARCHITECTURE.md         # This file
├── setup.py                # One-time: configure LLM API credentials
├── reset.py                # Utility: clear/view memory
├── test_llm.py             # Dev utility: test LLM connectivity
├── requirements.txt        # fastapi, uvicorn, httpx
│
├── handlers/
│   ├── webhook.py          # Message processing, session management, streaming
│   └── health.py           # GET /health endpoint
│
├── core/
│   ├── messenger.py        # Messenger REST API client (persistent httpx pool)
│   ├── heartbeat.py        # Background heartbeat loop
│   └── retry.py            # Exponential backoff helper
│
├── skills/                 # Skill docs — loaded by agent via file_reader
│   └── diagnose_system.md  # Full system health check procedure
│
└── data/
    ├── memory.md           # Persistent LLM memory (Markdown)
    ├── room_sessions.json  # Room → session ID mapping (auto-created)
    ├── .apikey             # Messenger bot API key (auto-created)
    ├── .llm_key            # LLM API bearer token (created by setup.py)
    └── .llm_model          # LLM model name (created by setup.py)
```

## Core Components

### 1. Entry Point: `hoonbot.py`

FastAPI app with async lifespan startup:

1. LLM health check (non-fatal if unreachable)
2. Bot registration — restores key from `data/.apikey` or registers new
3. Webhook subscription — `new_message`, `message_edited`, `message_deleted`
4. Catch-up — scans rooms for unanswered messages
5. Heartbeat loop — background task

### 2. Webhook Handler: `handlers/webhook.py`

**Session management:** Per-room sessions in `data/room_sessions.json`. Sessions auto-expire after `SESSION_MAX_AGE_DAYS`. On 404 from LLM API, clears and starts fresh.

**Message flow:**
1. Validate (text/image/file, not bot, @mention in non-home rooms)
2. Mark read (fire-and-forget)
3. Debounce (combine rapid messages within configurable window)
4. `process_message()` — builds context and calls LLM

**New session context injection:**
- PROMPT.md content
- Memory file absolute path
- Skills directory absolute path
- Current memory content

**Existing session:** sends only the user message with `session_id` (LLM API retains history).

**Memory flush:** At message #`MEMORY_FLUSH_THRESHOLD` (default 30) in a session, a system hint is injected nudging the agent to save important unsaved info to memory before context compaction.

**Streaming:** Tool status events shown as temporary messages (deleted after reply). Text accumulated and sent as threaded reply.

### 3. Heartbeat: `core/heartbeat.py`

Background loop that reads `HEARTBEAT.md`, builds full context (same as new session), and runs through the agent non-streaming. Posts results to home room. Features:
- Active-hours window (configurable start/end times)
- LLM cooldown on connection errors (avoids hammering dead server)
- First tick after one full interval (never immediate)

### 4. Skills System

Markdown files in `skills/` — the agent loads them via `file_reader`/`file_navigator` at runtime. No loader code needed; the skills directory path is injected into every new session context.

To add a skill: drop a `.md` file in `skills/` and add a reference in `memory.md`. The agent discovers and reads skills autonomously.

### 5. Memory: `data/memory.md`

Single curated Markdown file. Read/written by the LLM agent using `file_reader`/`file_writer`. Injected into new session context. The absolute path is provided so the LLM knows where to find it.

### 6. Messenger Client: `core/messenger.py`

Persistent `httpx.AsyncClient` wrapping the Messenger REST API. Auto-splits long messages at `MAX_MESSAGE_LENGTH` (2000 chars). All methods are best-effort with logging.

## Configuration

All settings: env var > `settings.txt` > hardcoded default. Key settings:

| Setting | Default | Purpose |
|---------|---------|---------|
| `HOONBOT_PORT` | 3939 | Bot server port |
| `HOONBOT_BOT_NAME` | Hoonbot | Display name |
| `HOONBOT_HOME_ROOM_ID` | 1 | Room for heartbeat output |
| `HOONBOT_STREAMING` | true | Stream LLM responses |
| `HOONBOT_DEBOUNCE_SECONDS` | 1.5 | Rapid message combine window |
| `HOONBOT_LLM_TIMEOUT` | 300 | LLM request timeout (s) |
| `HOONBOT_SESSION_MAX_AGE_DAYS` | 7 | Auto-expire sessions |
| `HOONBOT_MEMORY_FLUSH_THRESHOLD` | 30 | Messages before memory flush hint |
| `HOONBOT_HEARTBEAT_INTERVAL` | 3600 | Seconds between heartbeats |
| `HOONBOT_HEARTBEAT_ACTIVE_START/END` | 00:00/23:59 | Active hours window |

## Design Decisions

1. **No custom systems** — use LLM_API_fast's built-in tools
2. **Single memory file** — simple, inspectable, LLM-managed
3. **Skills as docs** — agent reads and executes them, no special loader
4. **Absolute paths** — injected into prompt so LLM knows exact locations
5. **Minimal code** — 3 dependencies, easy to debug and extend
6. **Heartbeat for scheduling** — user puts tasks in memory, heartbeat picks them up

---

**Last Updated:** 2026-03-02
