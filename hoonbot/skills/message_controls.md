# Skill: Message Controls

Edit, delete, mark read, or show typing for Messenger messages.

## Use When

edit my message, delete my message, mark messages read, show typing, stop typing

## Inputs

- operation: `edit`, `delete`, `mark_read`, `typing`, or `stop_typing`
- message ID(s) for edit/delete/mark_read
- new content for edit
- room ID for mark_read/typing

## API

- `POST /api/edit-message` with `{messageId, content}`
- `POST /api/delete-message` with `{messageId}`
- `POST /api/mark-read` with `{roomId, messageIds}`
- `POST /api/typing` with `{roomId, statusText?}`
- `POST /api/stop-typing` with `{roomId}`

Use `shell_exec` with `curl` and `x-api-key: {messenger_api_key}`.

## Rules

- Edit/delete only works for messages authored by the current API key. Report `403` plainly.
- Delete requires explicit confirmation in the same user turn.
- For "last message", fetch recent room messages and choose the newest bot-authored message; if uncertain, ask for `message_id`.
- For mark_read, `messageIds` must be a non-empty array.

## Reply

Edit: `Message edited. message_id=<id>.`

Delete: `Message deleted. message_id=<id>.`

Mark read: `Marked <count> message(s) read in room <room_id>.`

Typing: `Typing status updated in room <room_id>.`

Failure: `Message control failed. op=<operation>. status=<code>. error=<message>.`
