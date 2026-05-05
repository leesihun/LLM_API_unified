# Huni Messenger

A self-hosted real-time team chat platform with bot integration, file sharing, and embedded terminal access for Claude/OpenCode. Serves as the UI for Hoonbot.

## Quick Start

```bash
# 1. Install dependencies + build web client
./install.sh

# 2. Edit configuration
nano .env        # copy from .env.example if needed

# 3. Start
./start.sh
# → http://localhost:10006
```

## Configuration

**All runtime settings live in `.env`** (copied from `.env.example` at install time).

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `10006` | HTTP/Socket.IO listen port |
| `MESSENGER_DATA_DIR` | auto | SQLite DB directory |
| `MESSENGER_UPLOADS_DIR` | auto | User-uploaded file storage |
| `WORKSPACE_DIR` | `/scratch0` | Working dir for /claude and /opencode terminals |
| `SECRET_TOKEN` | `leesihun` | Auth token for terminal WebSocket sessions — **change in prod** |
| `CLAUDE_CMD` | `claude` | Claude Code CLI binary name |
| `OPENCODE_CMD` | `opencode` | OpenCode CLI binary name |

> All paths without a leading `/` are resolved relative to `server/src/` if unset. Leave variables empty to use built-in defaults.

## Directory Layout

```
messenger/
├── package.json            npm workspaces root (server, client, shared)
├── package-lock.json
├── .env.example            Template — copy to .env and edit
├── .env                    Runtime config (gitignored)
├── install.sh              Installer
├── start.sh                Start script (dev: npm run dev:server, prod: npm start)
├── deps/
│   └── build-portable.mjs  Electron portable-build helper
├── server/                 Express + Socket.IO backend
│   ├── src/
│   │   ├── index.ts        Entry point
│   │   ├── db/             sql.js SQLite (auto-saved to disk every 5s)
│   │   ├── routes/         REST API (auth, rooms, upload, api, files)
│   │   ├── socket/         Real-time Socket.IO handlers
│   │   ├── services/       webhook dispatcher, web-poller
│   │   ├── cron/           cleanup jobs
│   │   ├── middleware/      API key auth
│   │   └── terminal.ts     WebSocket terminal (Claude, OpenCode)
│   └── uploads/            Uploaded files (date-organised)
├── client/                 React/Vite frontend (also Electron shell)
│   └── src/
│       ├── pages/          ChatPage, LoginPage, FilesPage
│       ├── components/     ChatWindow, Sidebar, MessageBubble, ...
│       ├── contexts/       AuthContext, SocketContext
│       └── services/       Axios API client
├── shared/
│   └── types.ts            Canonical TypeScript types for messages, rooms, users
├── docs/
│   └── API.md              Full REST API reference
└── data/                   Runtime state (gitignored)
    ├── messenger.db         SQLite database (auto-saved from memory every 5s)
    └── uploads/            User file uploads
```

## REST API Summary

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/health` | GET | No | Server status |
| `/auth/login` | POST | No | Login by username |
| `/auth/users` | GET | No | List all users |
| `/rooms` | GET | No | List rooms |
| `/rooms/:id/messages` | GET | No | Fetch messages (paginated) |
| `/api/send-message` | POST | API key | Send text/file (bot use) |
| `/api/bots` | GET/POST | API key | Register bot / get API key |
| `/api/webhooks` | POST | API key | Subscribe to events |
| `/api/search` | GET | No | Global message search |
| `/claude` | WS | Token | Claude Code terminal |
| `/opencode` | WS | Token | OpenCode terminal |

Full reference: `docs/API.md`

## Bot Integration

Hoonbot registers via `POST /api/bots` on startup and receives events through webhooks. To wire up a bot:

1. `POST /api/bots` with `{"name": "MyBot"}` → get `apiKey`
2. `POST /api/webhooks` with event types (`new_message`, `message_edited`, etc.) and a callback URL
3. Messenger will POST events to your URL as JSON

## Dev Commands

```bash
# Type-check without building
npm run typecheck

# Build web client only (no Electron)
npm run build:web

# Build Electron app (Windows)
npm run build
```

## Gotchas

- **sql.js is in-memory** — DB lives in RAM, auto-saved to disk every 5 seconds. Unclean shutdown can lose up to 5 seconds of data.
- **No TLS built-in** — expects a reverse proxy (Cloudflare Tunnel, nginx). The terminal `SECRET_TOKEN` provides access control.
- **ClaudeWrapper references removed** — `WRAPPER_ENV_PATH` in `terminal.ts` gracefully no-ops if the file is absent.
- **Electron build** — requires Windows to build Windows `.exe`; use `--linux` flag for AppImage.
