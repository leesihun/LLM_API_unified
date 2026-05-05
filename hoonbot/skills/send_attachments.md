# Skill: Send Attachments

Send local files or base64 images to a Messenger room.

## Trigger

attach, upload, send file, send image, share document

## Required Inputs

- target room — use current room from message header unless an explicit room name or ID is given
- one or more file paths, or one base64 image data URL

## Message Header Format

Every message begins with:
```
[Room: <name> (id:<id>, <DM|group>) | From: <sender>]
```
Extract `id` from `id:<number>` in this line to get the current room ID.

## API

- **Tool**: `shell_exec` — run `curl` with the `x-api-key` header
- `POST {messenger_url}/api/send-file` for local files (multipart)
- `POST {messenger_url}/api/send-base64` for base64 image payloads

## Hard Rules

- Validate all paths before the first upload; if any path is invalid, stop with no uploads.
- No glob expansion, no fuzzy path matching, no room fallback.
- On `401` or `403`, stop immediately.
- Upload files sequentially and stop at the first failed upload.

## Procedure

1. Get `messenger_url`, `messenger_api_key`, and `bot_user_id` from session variables.
2. Resolve the target room:
   - **Explicit room ID**: use it directly.
   - **Explicit room name**: call `GET {messenger_url}/api/rooms?userId={bot_user_id}` and match the name case-insensitively; stop if no match or multiple matches.
   - **No explicit target**: extract `id` from the message header.
3. Validate attachment input:
   - File mode: every path exists and is a file.
   - Base64 mode: input starts with `data:image/` and contains `;base64,`.
4. Send attachments:
   - File mode → `POST {messenger_url}/api/send-file` with `roomId`, optional `content`, and `file`.
   - Base64 mode → `POST {messenger_url}/api/send-base64` with `roomId`, `data`, optional `fileName`, optional `content`.
5. Parse the message ID as `response.message.id`. If missing, stop and report an invalid API response.

## Response Format

Success:
`Uploaded <n> attachment(s) to room <room_id>: <file> -> <message_id>, ...`

Failure before upload:
`Upload aborted. reason=<reason>. fix=<required user correction>.`

Failure during upload:
`Partial upload to room <room_id>. uploaded=<list>. failed=<file>. status=<code>. error=<message>.`
