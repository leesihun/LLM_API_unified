# Huni Messenger API Reference

**Base URL:** `http://<server-ip>:3000`

## Authentication

### Human Users (ID-based)

Human clients use user IDs after login. No API key is required for `/auth` and `/rooms` routes.

### Bot Users (API Key)

API routes under `/api` accept either:

- **`x-api-key`** header (recommended for bots)
- **`senderId`** or **`senderName`** in body/query (for ad-hoc requests)

---

## Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Server health check |

**Response:** `{ "status": "ok", "timestamp": "..." }`

---

## Auth Routes (`/auth`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/login` | Login or register by display name |
| GET | `/auth/check?userId=N` | Check if a specific user ID exists |
| GET | `/auth/users` | List all users |

### POST /auth/login

**Body:** `{ "name": "Alice" }`

**Response:** `{ "user": { "id", "ip", "name", "createdAt", "updatedAt" } }`

---

## Room Routes (`/rooms`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/rooms?userId=N` | List rooms for current user |
| POST | `/rooms` | Create a room |
| POST | `/rooms/:id/members` | Add members to room |
| GET | `/rooms/:id/messages` | Get messages (paginated) |
| GET | `/rooms/:id/search?q=...` | Search messages in room |
| POST | `/rooms/:id/leave` | Leave a room |
| GET | `/rooms/:id/pins` | Get pinned messages in room |

### GET /rooms/:id/messages

**Query:** `?before=<messageId>&limit=<1-100>` (default limit: 50)

### GET /rooms/:id/search

**Query:** `?q=<search term>&limit=<1-100>` (default limit: 30)

---

## Upload Routes (`/upload`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/upload/file` | Upload file (multipart) |
| POST | `/upload/image-base64` | Upload base64 image |

**Response:** `{ "fileUrl", "fileName", "fileSize" }`

---

## Bot API Routes (`/api`)

All bot routes accept optional `x-api-key` header.

### Messages

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/send-message` | Send text message |
| POST | `/api/send-file` | Upload file and send in one step |
| POST | `/api/send-base64` | Send base64 image |
| POST | `/api/upload-file` | Upload file only (returns URL) |
| GET | `/api/messages/:roomId` | Fetch messages (paginated) |
| POST | `/api/edit-message` | Edit own message |
| POST | `/api/delete-message` | Soft-delete own message |
| POST | `/api/mark-read` | Mark messages as read |

#### POST /api/send-message

**Body:** `{ "roomId": 1, "content": "Hello", "type": "text", "mentions": [], "replyToId": 42 }`

- `type`: `"text"` | `"image"` | `"file"` (default: `"text"`)
- `fileUrl`, `fileName`, `fileSize`: required for image/file types
- `mentions`: array of user IDs to notify
- `replyToId`: optional — ID of message being replied to

### Search

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/search?q=...` | Search messages globally (optional `&roomId=N&limit=N`) |

### Reactions

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/reactions` | Toggle emoji reaction on message |

**Body:** `{ "messageId": 1, "emoji": "👍" }`

### Pinned Messages

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/pins/:roomId` | List pinned messages in room |
| POST | `/api/pins` | Pin a message |
| DELETE | `/api/pins/:messageId` | Unpin a message |

### Leave Room

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/leave-room` | Leave a room |

**Body:** `{ "roomId": 1 }`

### Rooms

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/rooms` | List rooms (optional `?userId=N`) |
| POST | `/api/create-room` | Create room by user names |

### Users

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/users` | List all users |

### Bot Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/bots` | Register bot, get API key |
| GET | `/api/bots/me` | Get current bot identity (requires key) |
| POST | `/api/bots/keys` | Create additional API key |
| DELETE | `/api/bots/keys/:key` | Revoke API key |

### Typing

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/typing` | Broadcast typing start |
| POST | `/api/stop-typing` | Broadcast typing stop |

### Webhooks

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/webhooks` | Create webhook subscription |
| GET | `/api/webhooks` | List own webhooks |
| PATCH | `/api/webhooks/:id` | Update webhook |
| DELETE | `/api/webhooks/:id` | Delete webhook |

**Events:** `new_message`, `message_edited`, `message_deleted`, `message_read`

### Web Watchers

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/watchers` | Create URL poller |
| GET | `/api/watchers` | List own watchers |
| PATCH | `/api/watchers/:id` | Update watcher |
| DELETE | `/api/watchers/:id` | Delete watcher |

---

## File Manager Routes (`/files`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/files/list?path=/` | List directory contents |
| POST | `/files/mkdir` | Create folder |
| POST | `/files/upload` | Upload files (multipart) |
| GET | `/files/download?path=...` | Download file |
| POST | `/files/delete` | Delete file/folder |
| POST | `/files/rename` | Rename file/folder |

---

## Socket.IO Events

### Client → Server

| Event | Data | Description |
|-------|------|-------------|
| `join_room` | `roomId` | Join a Socket.IO room |
| `leave_room` | `roomId` | Leave a Socket.IO room |
| `send_message` | `{ roomId, content, type, fileUrl?, fileName?, fileSize?, mentions?, replyToId? }` | Send message |
| `edit_message` | `{ messageId, content }` | Edit own message |
| `delete_message` | `{ messageId }` | Delete own message |
| `read_receipt` | `{ messageId, roomId }` | Mark message as read |
| `typing_start` | `roomId` | Start typing indicator |
| `typing_stop` | `roomId` | Stop typing indicator |
| `toggle_reaction` | `{ messageId, roomId, emoji }` | Add/remove emoji reaction |
| `pin_message` | `{ messageId, roomId }` | Pin a message |
| `unpin_message` | `{ messageId, roomId }` | Unpin a message |
| `leave_room_permanent` | `roomId` | Permanently leave a room |

### Server → Client

| Event | Data | Description |
|-------|------|-------------|
| `new_message` | `MessageWithSender` | New message in room |
| `message_edited` | `{ messageId, content, updatedAt }` | Message was edited |
| `message_deleted` | `{ messageId }` | Message was deleted |
| `message_read` | `{ messageId, userId, roomId }` | Message was read |
| `user_typing` | `{ roomId, userId, userName }` | User started typing |
| `user_stop_typing` | `{ roomId, userId }` | User stopped typing |
| `user_online_status` | `{ userId, online }` | User online/offline |
| `room_created` | `RoomWithDetails` | New room was created |
| `mention_notification` | `{ message, roomName }` | User was @mentioned |
| `reaction_updated` | `{ messageId, roomId, reactions[] }` | Reactions changed |
| `message_pinned` | `{ roomId, pin }` | Message was pinned |
| `message_unpinned` | `{ roomId, messageId }` | Message was unpinned |
| `member_left` | `{ roomId, userId, userName }` | Member left room |

---

## Request Examples

### Send message with reply

```bash
curl -X POST http://localhost:3000/api/send-message \
  -H "Content-Type: application/json" \
  -H "x-api-key: huni_abc123..." \
  -d '{"roomId":1,"content":"Great idea!","replyToId":42}'
```

### Toggle reaction

```bash
curl -X POST http://localhost:3000/api/reactions \
  -H "Content-Type: application/json" \
  -H "x-api-key: huni_..." \
  -d '{"messageId":42,"emoji":"👍"}'
```

### Search messages

```bash
curl "http://localhost:3000/api/search?q=hello&roomId=1&limit=20" \
  -H "x-api-key: huni_..."
```

### Pin a message

```bash
curl -X POST http://localhost:3000/api/pins \
  -H "Content-Type: application/json" \
  -H "x-api-key: huni_..." \
  -d '{"messageId":42,"roomId":1}'
```

### Leave a room

```bash
curl -X POST http://localhost:3000/api/leave-room \
  -H "Content-Type: application/json" \
  -H "x-api-key: huni_..." \
  -d '{"roomId":1}'
```

### Register bot

```bash
curl -X POST http://localhost:3000/api/bots \
  -H "Content-Type: application/json" \
  -d '{"name":"MyBot"}'
```

---

## Webhook Payload Format

```json
{
  "event": "new_message",
  "roomId": 1,
  "timestamp": "2026-02-19T12:00:00.000Z",
  "data": { ... }
}
```

If `secret` is set, the request includes `x-webhook-signature` (HMAC-SHA256).
