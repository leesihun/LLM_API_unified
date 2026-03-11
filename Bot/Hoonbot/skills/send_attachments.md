# Send Attachments to Room

Send one or more local pictures or files to a Messenger room using Hoonbot's Messenger API client.

---

## CRITICAL: Use the Right Base URL

**Always resolve the Messenger URL from config. Never hard-code a port number or guess it.**

There are multiple services running on different ports. Using the wrong one silently fails.
The relevant config keys in `settings.txt` are:

| Service   | `settings.txt` key | Purpose                      |
|-----------|--------------------|------------------------------|
| Messenger | `MESSENGER_PORT`   | The chat platform — use this |
| LLM API   | `LLM_API_PORT`     | AI inference — do NOT use    |
| Hoonbot   | `HOONBOT_PORT`     | Bot webhook receiver         |

### How `config.py` builds the Messenger URL

`config.py` reads `settings.txt` and resolves `config.MESSENGER_URL` using this priority:

1. Env var `MESSENGER_URL` — used as-is if set
2. `USE_CLOUDFLARE=true` in `settings.txt` — uses the Cloudflare tunnel URL
3. `MESSENGER_PORT` in `settings.txt` — builds `http://localhost:<MESSENGER_PORT>`

Always use `config.MESSENGER_URL` in code. Never construct the URL manually.

### How to confirm the URL at runtime

Inside the Hoonbot Python process:
```python
import config
print(config.MESSENGER_URL)  # Already resolved from settings.txt
```

From a shell (to inspect settings.txt directly):
```bash
grep -E '^(MESSENGER_PORT|USE_CLOUDFLARE)=' ../settings.txt
```

The `settings.txt` file is located one directory above `Hoonbot/` (at the repo root).

---

## API Overview

- **Base URL**: `config.MESSENGER_URL`
- **Auth header**: `x-api-key: <config.MESSENGER_API_KEY>` (loaded from `data/.apikey` at startup)
- **Upload a file (default)**: `POST {MESSENGER_URL}/api/send-file`
- **Upload a base64 image**: `POST {MESSENGER_URL}/api/send-base64`
- **List rooms (for name lookup)**: `GET {MESSENGER_URL}/api/rooms?userId=<bot_id>`

---

## Required Workflow

Execute these steps in order. Stop and report on first failure — do not continue.

1. Resolve Messenger base URL
2. Detect target room
3. Validate files
4. Upload files
5. Report results

---

## Step 1: Resolve Messenger Base URL

Before any API call, read the URL from config:

```python
import config
base_url = config.MESSENGER_URL
```

Do not proceed if `config.MESSENGER_URL` is empty or unset.

---

## Step 2: Detect Target Room

This skill does not automatically receive the current room context. The target room must come from the user.

**Detection order:**
1. Explicit room ID in user request → use directly as `target_room_id`
2. Explicit room name in user request → resolve to a room ID (see below)
3. Neither given → ask the user for a room ID or name, then stop

### Resolving a room name to an ID

```
GET {MESSENGER_URL}/api/rooms?userId=<bot_user_id>
Header: x-api-key: <config.MESSENGER_API_KEY>
```

Steps:
1. Call `messenger.get_bot_info()` → extract the bot's `id`
2. Call the rooms endpoint above with that ID
3. Find the room whose `name` matches exactly (case-insensitive, full string equality — no partial matching)

Failure rules:
- No match → stop, report: `"Room '<name>' not found"`
- Multiple matches → stop, report: `"Ambiguous room name — matches: <list>"`

---

## Step 3: Validate Files

For each file path in the order requested:

1. Resolve to absolute path
2. Check it exists — `os.path.exists(path)`
3. Check it is a file, not a directory — `os.path.isfile(path)`
4. Detect MIME type — `mimetypes.guess_type(path)` (best effort)

**Rules:**
- No glob expansion or fuzzy path matching
- If any file fails, stop and report the failing path + reason before uploading anything

---

## Step 4: Upload Files

### A) Local file from disk — standard path

**Use this for any file read from the local filesystem.**

```
POST {MESSENGER_URL}/api/send-file
Content-Type: multipart/form-data  ← set automatically by httpx; do not set manually
Header: x-api-key: <config.MESSENGER_API_KEY>
```

Form fields:
- `roomId` — room ID as a string (required)
- `file` — the file binary with its original filename (required)
- `content` — optional caption; defaults to the filename if omitted

The server auto-classifies the message type by file extension:
- `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`, `.bmp`, `.svg` → type `image`
- Everything else → type `file`

**Success response:** HTTP 201
```json
{ "success": true, "message": { "id": 1234, "roomId": 7, "type": "image", ... } }
```

**Reference implementation** (matches `core/messenger.py` patterns):

```python
async def send_file(room_id: int, file_path: str) -> int:
    """Upload a local file to a room. Returns message_id on success."""
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

---

### B) Base64 image — only when input is already base64

**Use this only when the image data arrives as a base64 string, not a file path.**

```
POST {MESSENGER_URL}/api/send-base64
Content-Type: application/json
Header: x-api-key: <config.MESSENGER_API_KEY>
```

Request body:
```json
{
  "roomId": <room_id>,
  "data": "data:image/png;base64,<encoded-bytes>",
  "fileName": "optional-display-name.png",
  "content": "optional caption"
}
```

Important: the `data` field must include the full data URL prefix (`data:image/<ext>;base64,...`).
Sending raw base64 without this prefix will fail silently on the server.

**Success response:** HTTP 201
```json
{ "success": true, "message": { "id": 1234, ... } }
```

---

### C) Forbidden — do not use these patterns

- Do not use the two-step flow: `/api/upload-file` → `/api/send-message`
- Do not switch endpoints mid-upload without an explicit reason
- Do not retry on `401`/`403` — report the error immediately
- Do not fall back to a different room on any failure

---

## Step 5: Parse Message ID from Response

Check the response body in this order:
1. `resp.json()["message"]["id"]` — primary path
2. `resp.json()["id"]` — fallback
3. Neither present → raise `ValueError("message_id missing in upload response")`

---

## Multi-file Upload Behavior

Uploads are **not atomic**. There is no rollback.

- Each file is uploaded independently in request order
- If file N fails after files 1..N-1 succeeded, those earlier uploads remain in the room
- Always report what succeeded and what failed — never hide partial state

---

## Response Format to User

**All succeeded:**
```
Uploaded 2 file(s) to room <room_id>.
- photo.png    → message_id=<id>  [image]
- report.pdf   → message_id=<id>  [file]
```

**Partial failure (some uploaded before failure):**
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

**Aborted before any upload (room or file validation failed):**
```
Upload aborted — no files were sent.
reason: <what failed>
fix: <what the user should provide or correct>
```

---

## Trigger Phrases

Apply this skill when the user's intent includes:
- attach / send / upload a file or image
- share a picture or document in a room
- send this file to room X
