# Huni Messenger — Feature Comparison & Roadmap

Comparison with traditional work messengers (Slack, Microsoft Teams, Discord) and suggested additions.

---

## Current Features

| Feature | Huni | Slack | Notes |
|---------|------|-------|-------|
| Real-time chat | ✅ | ✅ | Socket.IO |
| Text, image, file messages | ✅ | ✅ | |
| @mentions | ✅ | ✅ | With desktop notifications |
| Read receipts | ✅ | ✅ | |
| Typing indicators | ✅ | ✅ | |
| Online status | ✅ | ✅ | |
| Group & 1:1 rooms | ✅ | ✅ | |
| Message edit/delete | ✅ | ✅ | Own messages only |
| File upload (chat) | ✅ | ✅ | 100MB limit |
| File manager | ✅ | — | Built-in storage browser |
| Bot/API integration | ✅ | ✅ | REST + webhooks |
| Webhooks | ✅ | ✅ | Push events to external URLs |
| Web watchers | ✅ | — | Poll URLs, post changes to rooms |
| Silent mode | ✅ | ✅ | |
| Clipboard image paste | ✅ | ✅ | |
| **Message search** | ✅ | ✅ | Per-room and global search |
| **Emoji reactions** | ✅ | ✅ | Toggle reactions, quick emoji picker |
| **Pinned messages** | ✅ | ✅ | Pin/unpin, pinned message list |
| **Leave room** | ✅ | ✅ | Permanently leave a chat room |
| **Message reply/quote** | ✅ | ✅ | Reply to specific messages with preview |

---

## Remaining Gaps vs Traditional Work Messengers

### Medium Priority

| Feature | Slack/Teams | Huni | Suggested Implementation |
|---------|--------------|------|--------------------------|
| **Threads** | Full reply threads | Partial (reply-to) | Expand into threaded view with `parent_id` filter |
| **Room rename** | Edit channel name | ❌ | `PATCH /rooms/:id` |
| **Public vs private rooms** | Channel visibility | ❌ | Add `is_private` to rooms table |
| **User status** | Custom status | ❌ | Add `status` column to users; optional emoji |
| **Room description** | Channel topic | ❌ | Add `description` column to rooms |

### Lower Priority

| Feature | Slack/Teams | Huni | Suggested Implementation |
|---------|--------------|------|--------------------------|
| **Starred/saved messages** | Save for later | ❌ | New table `saved_messages` |
| **Message links** | Deep links | ❌ | `room/:id/message/:id` route |
| **Rich formatting** | Markdown, code blocks | Partial | Add markdown renderer |
| **Voice/video** | Calls | ❌ | WebRTC integration (large scope) |
| **Scheduled messages** | Send later | ❌ | Cron + `scheduled_messages` table |
| **Message forwarding** | Forward to another channel | ❌ | Copy message to target room |

---

## Huni-Specific Strengths

- **LLM/Bot bridge**: REST API, webhooks, web watchers for automation
- **Zero-config DB**: SQLite via sql.js, no external database
- **File manager**: Shared storage with list/mkdir/upload/download/delete/rename
- **Cross-platform**: Windows portable, Linux AppImage, web build
- **IP-based auth**: Simple internal deployment, no password management

---

## Recently Implemented

1. **Message search** — Per-room and global full-text search (`LIKE` based).
2. **Emoji reactions** — Toggle reactions on any message. Quick emoji picker (👍 ❤️ 😂 😮 😢 🎉). Visual display with counts and user tooltips.
3. **Pinned messages** — Pin/unpin messages. Pinned message panel in chat header with badge count.
4. **Leave room** — Permanently leave a chat room with confirmation dialog.
5. **Message reply/quote** — Reply to specific messages. Reply preview shown in both the input area and the message bubble.
