# Skill: Reactions And Pins

React to messages and manage pinned messages.

## Use When

react to message, add reaction, remove reaction, pin this, unpin message, list pins

## Inputs

- operation: `react`, `list_pins`, `pin`, or `unpin`
- room ID for pins
- message ID for react/pin/unpin
- emoji for react

## API

- `POST /api/reactions` with `{messageId, emoji}`; same call toggles the reaction
- `GET /api/pins/{roomId}`
- `POST /api/pins` with `{messageId, roomId}`
- `DELETE /api/pins/{messageId}`

Use `shell_exec` with `curl` and `x-api-key: {messenger_api_key}`.

## Rules

- If the user says "this" from a reply, resolve by unique quoted sender/content in recent messages. If not unique, ask for `message_id`.
- Do not invent emoji names; use the exact emoji/text the user provided.
- Pin conflicts return `409`; report that the message is already pinned.

## Reply

React: `Reaction toggled. message_id=<id> emoji=<emoji>.`

Pins: `Pinned messages in room <room_id> (<count>): <message_id> by <sender> "<preview>"; ...`

Pin: `Message pinned. message_id=<id> room_id=<room_id>.`

Unpin: `Message unpinned. message_id=<id>.`

Failure: `Reaction/pin operation failed. op=<operation>. status=<code>. error=<message>.`
