# Manage Webhooks

List, update, or delete the bot's webhook subscriptions in Messenger.

**Trigger phrases:** list webhooks, show webhooks, delete webhook, remove webhook, update webhook, manage webhooks, webhook subscriptions

---

## API

- **Port:** `config.MESSENGER_URL` (10006)
- **Auth:** `x-api-key: config.MESSENGER_API_KEY` (from `data/.apikey`)
- `GET {MESSENGER_URL}/api/webhooks` — list all webhook subscriptions
- `PATCH {MESSENGER_URL}/api/webhooks/{id}` — update a webhook
- `DELETE {MESSENGER_URL}/api/webhooks/{id}` — delete a webhook
- `POST {MESSENGER_URL}/api/webhooks` — create a new webhook

---

## Workflow

### 1. Read config

```python
import config
base_url = config.MESSENGER_URL
api_key = config.MESSENGER_API_KEY
```

### 2. Determine operation

From the user's request:
- **list** — show all current subscriptions
- **delete** — remove a specific webhook by ID
- **update** — change URL or events for a webhook
- **create** — add a new subscription

Default to **list** if the user just says "webhooks" or "show webhooks".

### 3. Execute operation

**List webhooks:**
```
GET {MESSENGER_URL}/api/webhooks
x-api-key: {api_key}
```

Response:
```json
[
  {
    "id": 1,
    "url": "http://localhost:3939/webhook",
    "events": ["new_message", "message_edited", "message_deleted"],
    "createdAt": "2026-03-01T00:00:00.000Z"
  }
]
```

**Delete webhook:**
```
DELETE {MESSENGER_URL}/api/webhooks/{webhook_id}
x-api-key: {api_key}
```

**Update webhook:**
```
PATCH {MESSENGER_URL}/api/webhooks/{webhook_id}
x-api-key: {api_key}
Content-Type: application/json

{
  "url": "http://new-url:3939/webhook",
  "events": ["new_message"]
}
```

**Create webhook:**
```
POST {MESSENGER_URL}/api/webhooks
x-api-key: {api_key}
Content-Type: application/json

{
  "url": "http://localhost:3939/webhook",
  "events": ["new_message", "message_edited"],
  "secret": "optional-hmac-secret"
}
```

Available events: `new_message`, `message_edited`, `message_deleted`, `message_read`

---

## Response format

**List:**
```
Webhook Subscriptions ({count}):

1. ID: {id}
   URL: {url}
   Events: {events joined by ", "}
   Created: {date}

2. ...
```

**Delete:**
```
Webhook #{id} deleted.
```

**Update:**
```
Webhook #{id} updated.
- URL: {new_url}
- Events: {new_events}
```

**Create:**
```
Webhook created (ID: {id}).
- URL: {url}
- Events: {events}
```

**No webhooks:**
```
No webhook subscriptions found.
```

---

## Notes

- Be careful deleting webhooks — removing the bot's main webhook (`/webhook`) will stop it from receiving messages
- Warn the user before deleting the primary webhook: "This appears to be the bot's main webhook. Deleting it will stop message processing. Proceed?"
- The `secret` field enables HMAC-SHA256 signature verification on incoming payloads
- Webhook registration is idempotent — creating a duplicate URL won't cause issues (Messenger checks for existing URLs)
