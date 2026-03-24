# Send Attachments to Room

Send one or more local files or images to a Messenger room.

**Trigger phrases:** attach / send / upload a file or image, share a picture or document in a room

---

## API

- **Base URL:** `http://localhost:10006`
- **Auth:** `x-api-key: <api_key>` — read from `<data_dir>/.apikey` using `file_reader`
- `POST {base_url}/api/send-file` — local file (multipart)
- `POST {base_url}/api/send-base64` — base64 image data (images only)
- `GET {base_url}/api/rooms?userId=<bot_id>` — room name lookup

The data directory path can be derived from the memory file path injected in the system prompt (same directory as `memory.md`).

---

## Workflow

Execute in order. Stop and report on first failure.

### 1. Get credentials

Use `file_reader` to read the API key:
```
file_reader: <data_dir>/.apikey
```
Store it as `api_key`. The base URL is `http://localhost:10006`.

### 2. Detect target room

Every message arrives prefixed with `[Room: <id> | From: <sender>]`. Use that room ID as the default.

Override order:
1. Explicit room ID in request → use that
2. Explicit room name → resolve to ID:
   ```
   GET {base_url}/api/bots/me
   x-api-key: <api_key>
   → extract bot id from response

   GET {base_url}/api/rooms?userId=<bot_id>
   x-api-key: <api_key>
   → find room whose name matches exactly (case-insensitive)
   ```
   - No match → `"Room '<name>' not found"` — stop
   - Multiple matches → `"Ambiguous room name — matches: <list>"` — stop
3. Neither given → use the room ID from the message prefix

### 3. Validate files

For each file path:
1. Resolve to absolute path
2. `os.path.exists(path)` — must exist
3. `os.path.isfile(path)` — must be a file, not a directory
4. `mimetypes.guess_type(path)` — detect MIME (best effort)

No glob expansion or fuzzy matching. If any file fails, stop before uploading anything.

### 4. Upload files

**Local file from disk:**

```python
import os, httpx

async def send_file(base_url, api_key, room_id, file_path, caption=None):
    form = {"roomId": str(room_id)}
    if caption:
        form["content"] = caption
    async with httpx.AsyncClient() as client:
        with open(file_path, "rb") as f:
            resp = await client.post(
                f"{base_url}/api/send-file",
                headers={"x-api-key": api_key},  # no Content-Type — httpx sets multipart boundary
                data=form,
                files={"file": (os.path.basename(file_path), f)},
            )
        resp.raise_for_status()
    result = resp.json()
    return result.get("message", {}).get("id") or result.get("id")
```

Server classifies by extension: `.jpg .jpeg .png .gif .webp .bmp .svg` → `image`, everything else → `file`.

**Base64 image** (only when input is already base64, not a file path):

```python
import httpx

async def send_base64(base_url, api_key, room_id, data_url, file_name=None, caption=None):
    body = {"roomId": room_id, "data": data_url}  # data_url MUST include full prefix: data:image/png;base64,...
    if file_name:
        body["fileName"] = file_name
    if caption:
        body["content"] = caption
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/api/send-base64",
            headers={"x-api-key": api_key},
            json=body,  # httpx sets Content-Type: application/json automatically
        )
    resp.raise_for_status()
    result = resp.json()
    return result.get("message", {}).get("id") or result.get("id")
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
