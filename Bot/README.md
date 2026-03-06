# AIhoonbot.com

A complete ecosystem for AI-powered communication consisting of two integrated projects:

| Component | Description |
|-----------|-------------|
| **[Hoonbot](#hoonbot)** | Personal AI assistant with persistent memory, scheduling, and proactive capabilities |
| **[Messenger](#messenger)** | Real-time chat platform designed as a bridge between LLM agents and humans |

---

## Quick Start

```bash
# Start Messenger (port 3000)
cd Messenger && npm install && npm run dev

# Start Hoonbot (port 3939) - requires Python 3.10+
cd Hoonbot && pip install -r requirements.txt && python hoonbot.py
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AIhoonbot Ecosystem                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌─────────────┐      webhook       ┌───────────┐      HTTP       ┌─────┐ │
│   │   Huni       │  ───────────────► │  Hoonbot  │  ─────────────► │ LLM │ │
│   │  Messenger   │  ◄─────────────── │  (FastAPI) │  ◄───────────── │ API │ │
│   │   :3000      │   send-message    │   :3939    │   chat response │:10007│
│   └──────┬──────┘                    └─────┬─────┘                 └─────┘ │
│          │                                 │                                │
│          │  Socket.IO                      │  SQLite                        │
│          ▼                                 ▼                                │
│   ┌──────────────┐                  ┌─────────────┐                        │
│   │   Clients    │                  │  Persistent │                        │
│   │ - Electron   │                  │   Storage   │                        │
│   │ - Android    │                  │ - Memory    │                        │
│   │ - Web        │                  │ - History   │                        │
│   └──────────────┘                  │ - Schedules │                        │
│                                     └─────────────┘                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Hoonbot

A personal AI assistant that lives inside Huni Messenger. Hoonbot runs locally, connects to an LLM backend, and provides conversational AI with persistent memory, scheduled tasks, a proactive heartbeat loop, extensible skills, daily logging, and desktop notifications.

### Key Features

| Feature | Description |
|---------|-------------|
| **Persistent Memory** | Key-value store with full-text search (SQLite FTS5) |
| **Conversation History** | Per-room message history stored in SQLite |
| **Heartbeat Loop** | Periodic background tasks and proactive actions |
| **Scheduled Jobs** | Cron-based recurring tasks or one-time reminders |
| **Extensible Skills** | Self-extending capabilities via markdown files |
| **Daily Log** | Append-only daily notes for context continuity |
| **Desktop Notifications** | Urgent alerts via plyer library |
| **Incoming Webhooks** | External service integration |

### Installation

```bash
cd Hoonbot
pip install -r requirements.txt
```

### Configuration

| Env Variable | Default | Description |
|-------------|---------|-------------|
| `HOONBOT_PORT` | `3939` | Server port |
| `MESSENGER_PORT` | `3000` | Messenger server port |
| `LLM_API_PORT` | `10007` | LLM backend port |
| `HOONBOT_HOME_ROOM_ID` | `1` | Default room for webhooks |
| `HOONBOT_HEARTBEAT_ENABLED` | `true` | Enable proactive loop |
| `HOONBOT_HEARTBEAT_INTERVAL` | `3600` | Seconds between heartbeats |
| `HOONBOT_NOTIFICATIONS` | `true` | Enable desktop notifications |
| `HOONBOT_WEBHOOK_SECRET` | — | Secret for incoming webhook auth |

### LLM Command Syntax

```
[MEMORY_SAVE: key=<key>, value=<value>, tags=<tags>]
[MEMORY_DELETE: key=<key>]
[SCHEDULE: name=<name>, cron=<HH:MM>, prompt=<what to do>]
[SCHEDULE: name=<name>, at=<YYYY-MM-DD HH:MM>, prompt=<reminder>]
[DAILY_LOG: Brief note about what happened]
[SKILL_CREATE: name=skill_name, description=One-line description]
[NOTIFY: title=Title, message=Body]
```

### Directory Structure

```
Hoonbot/
├── hoonbot.py              # Entry point
├── config.py               # Configuration
├── SOUL.md                 # System prompt / personality
├── HEARTBEAT.md            # Heartbeat checklist
├── core/
│   ├── llm.py              # LLM API client
│   ├── memory.py           # Persistent memory
│   ├── history.py          # Conversation history
│   ├── messenger.py        # Messenger API client
│   ├── heartbeat.py        # Proactive loop
│   └── ...
├── handlers/
│   ├── webhook.py          # Webhook handlers
│   └── health.py           # Health check
├── skills/                 # Extensible skill files
└── data/                   # Runtime data (SQLite, logs)
```

---

## Messenger

An internal real-time messenger designed as a **bridge between LLM agents and humans**. Features include text/image/file messages, @mentions, read receipts, typing indicators, reactions, pinned messages, message search, and a complete REST API for bot integration.

### Tech Stack

| Layer | Technology |
|-------|------------|
| Client | React 18, Vite, Tailwind CSS, Electron |
| Server | Express 4, Socket.IO 4, sql.js (SQLite WASM) |
| Database | SQLite (persisted to `server/data/messenger.db`) |

### Installation

```bash
cd Messenger
npm install
```

### Commands

```bash
npm run dev              # Run server + client
npm run dev:server       # Run server only
npm run dev:client       # Run client only
npm run build:client     # Build Electron app
npm run build:web        # Build web version
npm run typecheck        # TypeScript check
```

### Features

| Feature | Status |
|---------|--------|
| Real-time chat | ✅ |
| Text, image, file messages | ✅ |
| @mentions with notifications | ✅ |
| Read receipts | ✅ |
| Typing indicators | ✅ |
| Online status | ✅ |
| Group & 1:1 rooms | ✅ |
| Message edit/delete | ✅ |
| Message search | ✅ |
| Emoji reactions | ✅ |
| Pinned messages | ✅ |
| Message reply/quote | ✅ |
| File manager | ✅ |
| Bot/API integration | ✅ |
| Webhooks | ✅ |
| Web watchers (URL polling) | ✅ |

### Directory Structure

```
Messenger/
├── client/               # Electron + React desktop app
│   ├── electron/         # main.ts, preload.ts
│   └── src/
│       ├── components/   # ChatWindow, Sidebar, MessageBubble
│       ├── contexts/     # AuthContext, SocketContext
│       ├── pages/        # LoginPage, ChatPage, FilesPage
│       └── services/     # api.ts
├── server/               # Express + Socket.IO backend
│   └── src/
│       ├── db/           # sql.js init, schema
│       ├── routes/       # auth, rooms, upload, api, files
│       ├── socket/       # Socket.IO event handlers
│       ├── services/     # webhook, web-poller
│       └── middleware/   # apiAuth
├── shared/               # Shared TypeScript types
├── android-app/          # React Native mobile app
└── docs/                 # API.md, FEATURES.md
```

---

## Database Schemas

### Messenger (SQLite)

| Table | Purpose |
|-------|---------|
| `users` | Human users + bots |
| `rooms` | Chat rooms |
| `room_members` | Room membership |
| `messages` | All messages with reply support |
| `read_receipts` | Per-user read tracking |
| `api_keys` | Bot API keys (`huni_...`) |
| `webhooks` | Webhook subscriptions |
| `web_watchers` | URL polling configs |
| `message_reactions` | Emoji reactions |
| `pinned_messages` | Pinned messages |

### Hoonbot (SQLite)

| Table | Purpose |
|-------|---------|
| `memory` | Persistent memories with FTS5 |
| `room_history` | Per-room conversation history |
| `scheduled_jobs` | Scheduled tasks |

---

## API Quick Reference

### Messenger Endpoints

| Base | Description |
|------|-------------|
| `/auth/*` | User authentication |
| `/rooms/*` | Room management |
| `/upload/*` | File uploads |
| `/api/*` | Bot API (requires API key) |
| `/files/*` | File manager |

### Hoonbot Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/webhook` | POST | Messenger event webhook |
| `/webhook/incoming/{source}` | POST | External service webhook |

---

## Development

### Prerequisites

- Node.js 18+
- Python 3.10+
- LLM API with OpenAI-compatible endpoint

### Running the Full Stack

```bash
# Terminal 1: Messenger
cd Messenger && npm run dev

# Terminal 2: Hoonbot
cd Hoonbot && python hoonbot.py

# Terminal 3: LLM API (your choice of backend)
# Must provide /v1/chat/completions endpoint on port 10007
```

---

## License

Private project for internal use.
