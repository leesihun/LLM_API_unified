# Send Attachments to Room

Attach one or more local pictures/files to a Messenger room using explicit API calls.

## API Contract (Use Exactly)

- Base URL: `config.MESSENGER_URL` (example: `http://localhost:10006`)
- Auth header: `x-api-key: <bot_api_key>`
- Primary endpoint (single-step): `POST /api/send-file`
- Image-base64 endpoint: `POST /api/send-base64`
- Room lookup endpoint: `GET /api/rooms?userId=<bot_user_id>`
- Do not use fallback endpoint flows in strict mode

Strict mode policy:
- Use `/api/send-file` for filesystem files.
- Use `/api/send-base64` only if input is base64 image data.
- Do not switch endpoint strategy unless input format requires it.

## Required Workflow

1. Detect target room
2. Resolve and validate files
3. Upload each file to target room
4. Return per-file result with message IDs

Stop immediately on first failure.

## 1) Detect Target Room

Detection order:
1. Explicit room ID from user request
2. Explicit room name from user request (must resolve to exactly one room)

### Room-name resolution

If user gives room name:
1. Call `messenger.get_bot_info()` -> get bot `id`
2. Call `messenger.get_rooms(bot_user_id)` or `GET /api/rooms?userId=<id>`
3. Match exact name (case-insensitive exact equality only)

Reject when:
- multiple rooms match
- no room matches

Required output:
- `target_room_id: int`
- `room_source: "explicit_id" | "explicit_name"`

Important runtime note:
- This skill does not directly receive raw webhook payload fields.
- Do not assume `payload["roomId"]` is available inside the skill context unless Hoonbot explicitly injects it into prompt/session data.
- If user did not specify room ID/name, ask for it and stop.

## 2) Resolve and Validate Files

For each requested file path, in original order:
1. Resolve absolute path
2. Validate `exists`
3. Validate `isfile`
4. Detect MIME type (best effort)

Rules:
- No glob guessing.
- No nearest-match behavior.
- If any file is invalid, stop and return that exact path + reason.

Required output:
- `resolved_files: list[str]` (absolute paths)
- `content_types: list[str]` (same order)

## 3) Upload Files (Concrete API Calls)

### A) Standard files from disk (default)

Use `POST /api/send-file` as `multipart/form-data`.

Required fields:
- `roomId` (text field)
- `file` (multipart file part)

Required header:
- `x-api-key`

Expected success:
- HTTP 200/201
- response contains message object or message ID (`message.id` or `id`)

### B) Base64 image input only

Use `POST /api/send-base64` with JSON body:

```json
{
  "roomId": 7,
  "data": "data:image/png;base64,<base64-image>",
  "fileName": "image.png",
  "content": "optional caption"
}
```

Expected success:
- HTTP 200/201
- response contains message ID

### C) Forbidden in strict mode

Do not use two-step upload (`/api/upload-file` then `/api/send-message`).
Do not switch rooms, endpoints, or payload mode automatically.
Do not attempt implicit recovery on room resolution failures.

## 4) Hoonbot Implementation Reference

Use current client patterns in `core/messenger.py`:
- Shared async client from `_get_client()`
- Auth headers from `_headers()`
- POST URL format: `f"{config.MESSENGER_URL}/api/..."`
- Fail fast with `resp.raise_for_status()`

When adding helper methods, keep this signature style:

```python
async def send_file(room_id: int, file_path: str, reply_to_id: int | None = None) -> int:
    # returns message_id; raises on failure
```

```python
async def send_base64_image(room_id: int, base64_data: str, file_name: str, reply_to_id: int | None = None) -> int:
    # returns message_id; raises on failure
```

Parsing rule for message ID:
1. `resp.json()["message"]["id"]`
2. else `resp.json()["id"]`
3. else raise `ValueError("message_id missing in upload response")`

Transaction rule:
- Upload is not transactional across multiple files.
- If file N fails after files 1..N-1 succeeded, keep prior successful uploads and report partial side effects explicitly.

## 5) Response Format to User

Success:

```text
Uploaded 2 file(s) to room 7.
- C:\data\photo.png -> message_id=1842
- C:\data\report.pdf -> message_id=1843
```

Failure:

```text
Upload failed.
target_room_id=7
failed_file=C:\data\missing.png
api_endpoint=/api/send-file
error=File not found
```

## Trigger Phrases

Apply this skill when user intent includes:
- attach image/file
- upload picture/document
- send file to room
- share this in another room
