# Skill: Screenshot And Send

Capture a screenshot and send it to a Messenger room.

## Use When

take screenshot, capture screen, send screen, what is on screen

## Inputs

- room: current room unless the user gives a room ID/name
- optional caption

## API

- `POST /api/send-file` multipart: `roomId`, `file`, optional `content`

Use `shell_exec` for capture and `curl` with `x-api-key: {messenger_api_key}` for upload.

## Rules

- PNG only.
- Verify the screenshot file exists and is non-empty before upload.
- Delete the temporary file after success or failure.
- If capture is unavailable in the current OS/session, report that exact blocker.

## Steps

1. Resolve room ID from header, explicit ID, or `/api/rooms?userId={bot_user_id}`.
2. Capture to a temporary `.png`.
3. Upload via `/api/send-file`.
4. Parse `response.message.id`.
5. Remove the temporary file.

## Reply

Success: `Screenshot sent to room <room_id>. message_id=<id>.`

Failure: `Screenshot failed. step=<capture|upload|cleanup>. reason=<reason>.`
