# CLAUDE.md — Huni Messenger

This file provides context for AI assistants working on this codebase.

## Project Overview

Huni Messenger is an internal messenger designed as a **bridge between LLM agents and humans**.
It consists of an Electron + React desktop client and an Express + Socket.IO + sql.js server.
Bots and automation scripts interact via REST API endpoints under `/api`.

## Directory Structure

```
Messenger/
├── client/               # Electron + React + Vite desktop app (TypeScript)
│   ├── electron/         # main.ts (BrowserWindow), preload.ts (IPC bridge)
│   ├── src/
│   │   ├── components/   # ChatWindow, Sidebar, MessageBubble, NewRoomModal, MentionSuggestion
│   │   ├── contexts/     # AuthContext, SocketContext
│   │   ├── pages/        # LoginPage, ChatPage, FilesPage
│   │   ├── services/     # api.ts (Axios wrapper)
│   │   └── utils/        # notifications.ts (Electron + browser notifications)
│   ├── vite.config.ts    # Electron build config
│   └── vite.config.web.ts # Web-only build config
├── server/               # Express + Socket.IO backend (TypeScript)
│   ├── src/
│   │   ├── db/           # sql.js init, schema, query helpers (index.ts)
│   │   ├── routes/       # auth, rooms, upload, api (bot endpoints), files (file manager)
│   │   ├── socket/       # handler.ts (realtime events)
│   │   ├── services/     # webhook.ts (dispatch), web-poller.ts (URL watcher)
│   │   ├── middleware/    # apiAuth.ts (API key validation)
│   │   └── cron/         # cleanup.ts (30-day file expiry)
│   ├── data/             # messenger.db (auto-created)
│   ├── uploads/          # chat uploads (YYYY-MM-DD/)
│   └── storage/          # file manager storage root
├── shared/               # Shared TypeScript types (types.ts)
├── docs/                 # API.md, FEATURES.md
├── test.ipynb            # Jupyter notebook for interactive API testing
├── CLAUDE.md             # This file
└── README.md             # Project documentation
```

## Tech Stack

| Layer    | Technology                                   |
| -------- | -------------------------------------------- |
| Client   | React 18, Vite, Tailwind CSS, Electron       |
| Server   | Express 4, Socket.IO 4, sql.js (SQLite WASM) |
| Database | SQLite (persisted to `server/data/messenger.db`) |
| Uploads  | Disk storage under `server/uploads/YYYY-MM-DD/` |
| Storage  | File manager under `server/storage/`          |

## Key Commands

```bash
# Install dependencies (from project root)
npm install

# Run both server and client
npm run dev

# Run server only (hot-reload)
cd server && npm run dev

# Run client only
cd client && npm run dev

# Build client for Windows
cd client && npm run build

# Build client for Linux
cd client && npm run build:linux

# Web-only build
cd client && npm run build:web
```

## API Endpoints (for bots / LLM agents)

All bot-facing endpoints live under `/api`. See [docs/API.md](docs/API.md) for full reference.

### Core Messaging

| Method | Endpoint | Purpose |
| ------ | -------- | ------- |
| POST | `/api/send-message` | Send text message (supports `replyToId`) |
| POST | `/api/send-file` | Upload + send file |
| POST | `/api/send-base64` | Send base64 image |
| POST | `/api/upload-file` | Upload file (returns URL) |
| GET | `/api/messages/:roomId` | Fetch messages (pagination) |
| POST | `/api/edit-message` | Edit own message |
| POST | `/api/delete-message` | Soft-delete own message |
| POST | `/api/mark-read` | Mark messages as read |

### Search, Reactions, Pins

| Method | Endpoint | Purpose |
| ------ | -------- | ------- |
| GET | `/api/search?q=...` | Search messages globally |
| POST | `/api/reactions` | Toggle emoji reaction |
| GET | `/api/pins/:roomId` | Get pinned messages |
| POST | `/api/pins` | Pin a message |
| DELETE | `/api/pins/:messageId` | Unpin a message |

### Rooms & Users

| Method | Endpoint | Purpose |
| ------ | -------- | ------- |
| GET | `/api/rooms` | List rooms |
| POST | `/api/create-room` | Create room by user names |
| POST | `/api/leave-room` | Leave a room |
| GET | `/api/users` | List all users |

### Bots, Webhooks, Watchers

| Method | Endpoint | Purpose |
| ------ | -------- | ------- |
| POST | `/api/bots` | Register bot, get API key |
| GET | `/api/bots/me` | Get current bot identity |
| POST/GET/PATCH/DELETE | `/api/webhooks` | Webhook subscriptions |
| POST/GET/PATCH/DELETE | `/api/watchers` | URL polling watchers |
| POST | `/api/typing` | Typing indicator start |
| POST | `/api/stop-typing` | Typing indicator stop |

## Database Schema

Ten tables in SQLite:

| Table | Purpose |
| ----- | ------- |
| `users` | Human users + bots (IP-based identity, `is_bot` flag) |
| `rooms` | Chat rooms (1:1 and group) |
| `room_members` | Room membership (many-to-many) |
| `messages` | All messages (text, image, file; `reply_to`, `mentions`) |
| `read_receipts` | Per-user read tracking |
| `api_keys` | Bot API keys (`huni_...` format) |
| `webhooks` | Outbound webhook subscriptions |
| `web_watchers` | URL polling configurations |
| `message_reactions` | Emoji reactions per message per user |
| `pinned_messages` | Pinned messages per room |

Foreign keys are enforced. The database auto-saves every 5 seconds.

## Socket.IO Events

### Client → Server

`join_room`, `leave_room`, `send_message` (with `replyToId`), `edit_message`, `delete_message`, `read_receipt`, `typing_start`, `typing_stop`, `toggle_reaction`, `pin_message`, `unpin_message`, `leave_room_permanent`

### Server → Client

`new_message`, `message_edited`, `message_deleted`, `message_read`, `user_typing`, `user_stop_typing`, `user_online_status`, `room_created`, `mention_notification`, `reaction_updated`, `message_pinned`, `message_unpinned`, `member_left`

## Conventions

- **Language**: Korean UI strings in client; English for API error messages.
- **IP-based auth**: Users are identified by IP + display name. No passwords.
- **Message types**: `text`, `image`, `file`.
- **File cleanup**: A cron job at 03:00 daily deletes chat uploads older than 30 days.
- **Socket.IO rooms**: Prefixed with `room:` (e.g., `room:1`).
- **Error handling**: Be strict — no silent fallbacks. Throw or return errors early.
- **Code style**: TypeScript strict mode. Keep code readable.

## Testing

Open `test.ipynb` in Jupyter to run through all API endpoints interactively.

## Feature Comparison

See [docs/FEATURES.md](docs/FEATURES.md) for a comparison with Slack/Teams and remaining gaps.
