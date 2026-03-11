# User Directory

Look up users registered in Messenger — list all users or find a specific person.

**Trigger phrases:** list users, who's on messenger, find user, user list, show users, who is, look up user

---

## API

- **Port:** `config.MESSENGER_URL` (10006)
- **Auth:** `x-api-key: config.MESSENGER_API_KEY` (from `data/.apikey`)
- `GET {MESSENGER_URL}/api/users` — list all users (bots and humans)
- `GET {MESSENGER_URL}/auth/users` — alternative endpoint (same data)

---

## Workflow

### 1. Read config

```python
import config
base_url = config.MESSENGER_URL
api_key = config.MESSENGER_API_KEY
```

### 2. Fetch user list

```
GET {MESSENGER_URL}/api/users
x-api-key: {api_key}
```

Response is a JSON array:
```json
[
  {
    "id": 1,
    "name": "Alice",
    "isBot": false,
    "createdAt": "2026-01-15T10:00:00.000Z",
    "updatedAt": "2026-03-10T14:00:00.000Z"
  },
  {
    "id": 5,
    "name": "Bot",
    "isBot": true,
    "createdAt": "2026-02-01T08:00:00.000Z"
  }
]
```

### 3. Filter/search if needed

- **List all** — show everyone
- **Search by name** — case-insensitive partial match on `name`
- **Filter humans only** — exclude `isBot: true`
- **Filter bots only** — include only `isBot: true`

### 4. Format response

---

## Response format

**Full list:**
```
Messenger Users ({total} total):

Humans:
  1. {name} (ID: {id}) — joined {date}
  2. ...

Bots:
  1. {name} (ID: {id}) — registered {date}
  2. ...
```

**Search result:**
```
Found {count} user(s) matching "{query}":
  1. {name} (ID: {id}, {human/bot}) — joined {date}
```

**No results:**
```
No users found matching "{query}".
```

---

## Notes

- Always separate humans and bots in the full listing for clarity
- Format dates as human-readable (e.g. "Jan 15, 2026")
- The `isBot` field may not exist on all user objects — treat missing as `false` (human)
- User IDs are useful for @mentions and room creation — include them
