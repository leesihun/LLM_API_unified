# Search Messages

Search past messages across all rooms or within a specific room in Messenger.

**Trigger phrases:** search messages, find message, look up what was said, search for, find conversation about, when did we talk about

---

## API

- **Port:** `config.MESSENGER_URL` (10006)
- **Auth:** `x-api-key: config.MESSENGER_API_KEY` (from `data/.apikey`)
- `GET {MESSENGER_URL}/api/search?q=<query>&roomId=<optional>&limit=<optional>` — global search
- `GET {MESSENGER_URL}/rooms/{room_id}/search?q=<query>&limit=<optional>` — room-specific search
- `GET {MESSENGER_URL}/api/rooms?userId=<bot_id>` — room name → ID lookup

---

## Workflow

Execute in order. Stop and report on first failure.

### 1. Read config

```python
import config
base_url = config.MESSENGER_URL   # abort if empty
api_key = config.MESSENGER_API_KEY
```

### 2. Parse the search request

Extract from the user's message:
- **query** (required) — the search term or phrase
- **room** (optional) — a room name or ID to limit the search
- **limit** (optional) — max results, default 20, max 100

If no query can be determined, ask the user what to search for — stop.

### 3. Resolve room (if specified)

If the user names a room:
1. Call `messenger.get_bot_info()` → get bot `id`
2. `GET /api/rooms?userId=<bot_id>` → find case-insensitive name match
3. No match → `"Room '<name>' not found"` — stop

### 4. Execute search

**Global search** (no room specified):

```
GET {MESSENGER_URL}/api/search?q={query}&limit={limit}
x-api-key: {api_key}
```

**Room-scoped search:**

```
GET {MESSENGER_URL}/api/search?q={query}&roomId={room_id}&limit={limit}
x-api-key: {api_key}
```

Alternative room-scoped endpoint:

```
GET {MESSENGER_URL}/rooms/{room_id}/search?q={query}&limit={limit}
```

### 5. Parse response

Response is a JSON array of message objects:

```json
[
  {
    "id": 42,
    "content": "the matching message text",
    "senderId": 1,
    "senderName": "Alice",
    "roomId": 3,
    "roomName": "General",
    "createdAt": "2026-03-10T14:30:00.000Z",
    "type": "text"
  }
]
```

Fields may vary — handle missing `senderName` or `roomName` gracefully.

---

## Response format

**Results found:**
```
Found {count} message(s) matching "{query}":

1. [{roomName}] {senderName} ({date}):
   "{content preview — first 120 chars}"
   (message #{id})

2. ...
```

**No results:**
```
No messages found matching "{query}".
```

**Room-scoped:**
```
Found {count} message(s) matching "{query}" in {roomName}:
...
```

---

## Notes

- Truncate long message content to ~120 characters in the summary
- Show the room name for global searches so the user knows where each result is from
- Format dates as human-readable (e.g. "Mar 10, 2:30 PM")
- If more results may exist beyond the limit, note: "Showing first {limit} results. Ask for more if needed."
