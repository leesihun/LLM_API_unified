# Skill: Send Attachments

Send files or base64 images to Messenger.

## Use When

attach, upload, send file, send image, share document

## Inputs

- target room: current room unless explicit room ID/name is given
- one or more local file paths, or one image data URL
- optional caption

## API

- `POST /api/send-file` multipart: `roomId`, `file`, optional `content`
- `POST /api/send-base64` JSON: `{roomId, data, fileName?, content?}`
- `POST /api/send-message` JSON supports `attachments[]` only when files were already uploaded

Use `shell_exec` with `curl` and `x-api-key: {messenger_api_key}`.

## Rules

- Validate every local path before the first upload. If any path is invalid, upload nothing.
- No glob expansion or fuzzy path matching.
- Stop immediately on `401` or `403`.
- Upload sequentially and stop at the first failure.

## Reply

Success: `Uploaded <n> attachment(s) to room <room_id>: <file> -> <message_id>, ...`

Aborted: `Upload aborted. reason=<reason>. fix=<required correction>.`

Partial: `Partial upload to room <room_id>. uploaded=<list>. failed=<file>. status=<code>. error=<message>.`
