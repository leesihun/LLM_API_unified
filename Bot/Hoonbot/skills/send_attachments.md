# Send Attachments to Room

Send one or more local files or images to a Messenger room.

**Trigger phrases:** attach / send / upload a file or image, share a picture or document in a room

---

## API

- **Port:** `config.MESSENGER_URL` (10006)
- **Auth:** `x-api-key: config.MESSENGER_API_KEY` (from `data/.apikey`)
- `POST {MESSENGER_URL}/api/send-file` — local file (multipart)
- `POST {MESSENGER_URL}/api/send-base64` — base64 image data
- `GET {MESSENGER_URL}/api/rooms?userId=<bot_id>` — room name lookup

---

## Workflow

Execute in order. Stop and report on first failure.

### 1. Resolve base URL

```python
import config
base_url = config.MESSENGER_URL  # abort if empty
```

### 2. Detect target room

1. Explicit room ID in request → use directly
2. Explicit room name → resolve to ID:
   - Call `messenger.get_bot_info()` → get bot `id`
   - `GET /api/rooms?userId=<bot_id>` → find exact case-insensitive name match
   - No match → `"Room '<name>' not found"` — stop
   - Multiple matches → `"Ambiguous room name — matches: <list>"` — stop
3. Neither given → ask the user for a room ID or name — stop

### 3. Validate files

For each file path:
1. Resolve to absolute path
2. `os.path.exists(path)` — must exist
3. `os.path.isfile(path)` — must be a file, not a directory
4. `mimetypes.guess_type(path)` — detect MIME (best effort)

No glob expansion or fuzzy matching. If any file fails, stop before uploading anything.

### 4. Upload files

**Local file from disk:**

```
POST {MESSENGER_URL}/api/send-file
Content-Type: multipart/form-data  ← set by httpx automatically; do not set manually
x-api-key: config.MESSENGER_API_KEY

Form fields:
  roomId   — room ID as string (required)
  file     — file binary with original filename (required)
  content  — caption (optional; defaults to filename)
```

Server classifies by extension: `.jpg .jpeg .png .gif .webp .bmp .svg` → `image`, everything else → `file`.

```python
async def send_file(room_id: int, file_path: str) -> int:
    client = _get_client()
    with open(file_path, "rb") as f:
        resp = await client.post(
            f"{config.MESSENGER_URL}/api/send-file",
            headers={"x-api-key": config.MESSENGER_API_KEY},
            data={"roomId": str(room_id)},
            files={"file": (os.path.basename(file_path), f)},
        )
    resp.raise_for_status()
    data = resp.json()
    msg_id = data.get("message", {}).get("id") or data.get("id")
    if not msg_id:
        raise ValueError("message_id missing in upload response")
    return msg_id
```

**Base64 image** (only when input is already base64, not a file path):

```
POST {MESSENGER_URL}/api/send-base64
Content-Type: application/json
x-api-key: config.MESSENGER_API_KEY

{
  "roomId": <room_id>,
  "data": "data:image/png;base64,<encoded-bytes>",  ← full data URL prefix required
  "fileName": "optional-name.png",
  "content": "optional caption"
}
```

**Do not:**
- Use the two-step flow `/api/upload-file` → `/api/send-message`
- Retry on `401`/`403` — report immediately
- Fall back to a different room on failure

### 5. Parse message ID from response (HTTP 201)

```
resp.json()["message"]["id"]  ← primary
resp.json()["id"]             ← fallback
neither → raise ValueError("message_id missing in upload response")
```

---

## Multi-file uploads

Uploads are **not atomic** — no rollback. Each file is uploaded independently in order. If file N fails, files 1..N-1 remain in the room. Always report what succeeded and what failed.

---

## Response format

**All succeeded:**
```
Uploaded 2 file(s) to room <room_id>.
- photo.png   → message_id=<id>  [image]
- report.pdf  → message_id=<id>  [file]
```

**Partial failure:**
```
Partial upload to room <room_id> — stopped at first failure.
Uploaded:
  - photo.png → message_id=<id>
Failed:
  - report.pdf
    endpoint: POST /api/send-file
    status: <http_status>
    error: <server error message>
Note: files already uploaded are not rolled back.
```

**Aborted before any upload:**
```
Upload aborted — no files were sent.
reason: <what failed>
fix: <what the user should provide or correct>
```
