# Download Attachment from Chat

Download a file or image from a previous message in Messenger and save it to disk.

**Trigger phrases:** download attachment, save that file, grab the image, download file from chat, save attachment, get that picture

---

## API

- **Port:** `config.MESSENGER_URL` (10006)
- **Auth:** `x-api-key: config.MESSENGER_API_KEY` (from `data/.apikey`)
- `GET {MESSENGER_URL}/api/messages/{roomId}?limit={N}&before={messageId}` — fetch messages (paginated)
- `GET {MESSENGER_URL}{fileUrl}` — download file by its relative URL
- `GET {MESSENGER_URL}/api/rooms?userId=<bot_id>` — room lookup

---

## Workflow

Execute in order. Stop and report on first failure.

### 1. Read config

```python
import config
base_url = config.MESSENGER_URL
api_key = config.MESSENGER_API_KEY
```

### 2. Identify the target

Determine what the user wants to download. Possibilities:
1. **Specific message ID** — user says "download the file from message #42"
2. **Most recent file/image** — user says "download that image" or "save the last file"
3. **By description** — user says "download the PDF from earlier"

If ambiguous, default to searching the current room's recent messages for file/image types.

### 3. Fetch messages from the room

```
GET {MESSENGER_URL}/api/messages/{roomId}?limit=50
x-api-key: {api_key}
```

Response is a JSON array of messages. Filter for file/image messages:

```python
attachments = [
    msg for msg in messages
    if msg.get("type") in ("file", "image") and msg.get("fileUrl")
]
```

Each file/image message has:
```json
{
  "id": 42,
  "type": "file",
  "content": "report.pdf",
  "fileUrl": "/uploads/abc123/report.pdf",
  "fileName": "report.pdf",
  "fileSize": 102400,
  "senderName": "Alice",
  "createdAt": "2026-03-10T14:30:00.000Z"
}
```

### 4. Select the right attachment

- If user specified a message ID → find exact match
- If user described a filename → match by `fileName` or `content`
- If "the last file/image" → take the most recent matching message
- If multiple matches → list them and ask the user to pick — stop

### 5. Download the file

```python
import httpx, os

file_url = f"{base_url}{msg['fileUrl']}"
resp = httpx.get(file_url, headers={"x-api-key": api_key})
resp.raise_for_status()

filename = msg.get("fileName") or msg["fileUrl"].rsplit("/", 1)[-1]
```

### 6. Save to disk

Default save location: current working directory, or a user-specified path.

```python
save_path = os.path.join(save_dir, filename)
with open(save_path, "wb") as f:
    f.write(resp.content)
```

If the file already exists at the save path, append a number: `report (1).pdf`.

---

## Response format

**Success:**
```
Downloaded "{filename}" ({file_size_human}) from message #{id} by {senderName}.
Saved to: {absolute_save_path}
```

**Multiple matches found:**
```
Found {count} attachments in recent messages:
1. {fileName} ({fileSize}) — {senderName}, {date} (message #{id})
2. ...

Which one should I download? Specify by number or message ID.
```

**No attachments found:**
```
No file or image attachments found in the last 50 messages of this room.
```

---

## Notes

- File sizes should be human-readable (KB, MB)
- The `fileUrl` is a relative path — always prepend `MESSENGER_URL`
- For images, the `type` field is `"image"`; for documents, it's `"file"`
- Pagination: use `before=<messageId>` to go further back if needed
