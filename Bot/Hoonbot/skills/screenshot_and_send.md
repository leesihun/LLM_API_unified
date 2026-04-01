# Skill: Screenshot And Send

Capture a screenshot and upload it to the current room.

## Trigger

take screenshot, capture screen, send screen, what is on screen

## Required Inputs

- `room_id` — extract from `id:<number>` in the message header
- optional scope: `desktop` (default) or `primary_monitor`

## Message Header Format

Every message begins with:
```
[Room: <name> (id:<id>, <DM|group>) | From: <sender>]
```
Extract the room `id` from `id:<number>` in this line.

## API

- **Tool**: `shell_exec` — capture screenshot, then upload via `curl`
- `POST {messenger_url}/api/send-file` (multipart upload)

## Hard Rules

- Use PNG only.
- Capture must produce a non-empty file before upload.
- On capture failure, stop; do not attempt upload.
- Always delete the temp file after completion (success or failure).

## Procedure

1. Get `messenger_url` and `messenger_api_key` from session variables.
2. Extract `room_id` from the message header (`id:<number>`).
3. Capture screenshot to a temp path:
   - Windows: PowerShell `System.Drawing` capture
   - Linux: `import -window root` (single method)
4. Verify the file exists and `size > 0`.
5. Upload with `POST {messenger_url}/api/send-file` using `roomId` and the `file` field.
6. Read the uploaded message ID from `response.message.id`.
7. Delete the temp file.

## Response Format

Success:
`Screenshot sent to room <room_id>. message_id=<id>.`

Failure:
`Screenshot failed. step=<capture|upload>. reason=<reason>.`
