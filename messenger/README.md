# Huni Messenger

A self-hosted real-time team chat platform with bot integration, file sharing, and embedded terminal access for Claude/OpenCode. Serves as the UI for Hoonbot.

## Quick Start

```bash
# First time: install deps + build the bundle, then start
./start.sh --build --prod
# -> http://127.0.0.1:10006
```

On Windows:

```powershell
.\start.ps1 -Build      # first time only — installs deps + builds the bundle
.\start.ps1             # later runs: launches the prebuilt server.cjs (no npm)
.\start.ps1 -Dev        # development: TypeScript dev server (tsx watch)
```

`start.ps1` runs the prebuilt `server/dist/server.cjs` by default — no
`npm install`, Vite, or tsx at runtime. Those only run when you pass `-Build`.

## Configuration

**All runtime settings live in `config.py`**. Edit it directly.

| Setting | Default | Purpose |
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
├── config.py               Runtime config
├── start.sh                Linux launch script (runs prebuilt bundle by default)
├── start.ps1               Windows launch script (runs prebuilt bundle by default)
├── build-portable.mjs      Builds the portable thin-client Messenger.exe
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

# Build the server bundle (server/dist/server.cjs)
npm run build --workspace=server

# Build the portable thin-client desktop app -> client/dist-portable/Messenger.exe
npm run build:portable
```

## Gotchas

- **sql.js is in-memory** — DB lives in RAM, auto-saved to disk every 5 seconds. Unclean shutdown can lose up to 5 seconds of data.
- **No TLS built-in** — expects a LAN/VPN reverse proxy if exposed beyond the node. The terminal `SECRET_TOKEN` provides access control.
- **ClaudeWrapper references removed** — `WRAPPER_ENV_PATH` in `terminal.ts` gracefully no-ops if the file is absent.
- **Desktop app is a thin client** — `Messenger.exe` (built by `npm run build:portable`) does **not** embed a server. It opens the master node's Messenger UI at `http://<master-ip>:10006`; the default URL is baked from `cluster_config.MESSENGER_URL` and is editable on first launch or via **Ctrl+,**. The master must be reachable. Building the `.exe` requires Windows + the dev toolchain; running it requires nothing.
