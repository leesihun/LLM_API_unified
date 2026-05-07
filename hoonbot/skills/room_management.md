# Skill: Room Management

List, create, resolve, or leave Messenger rooms.

## Use When

list rooms, create room, make group chat, find room id, leave room

## Inputs

- operation: `list`, `resolve`, `create`, or `leave`
- create: room name, `isGroup`, and member names
- leave: room ID/name plus explicit confirmation

## API

- `GET /api/rooms?userId={bot_user_id}`
- `POST /api/create-room` with `{name, isGroup, creatorName, memberNames}`
- `POST /api/leave-room` with `{roomId}`

Use `shell_exec` with `curl` and `x-api-key: {messenger_api_key}`.

## Rules

- Use `creatorName: {bot_name}` when creating rooms as the bot.
- Include the bot in `memberNames`; add requested members by exact name.
- Resolve room names case-insensitively and require one match.
- Leaving a room requires explicit confirmation in the same user turn.

## Reply

List: `Rooms (<count>): <name>(id=<id>, type=<DM|group>, members=<names>), ...`

Resolve: `Room "<name>" resolved to id=<id>.`

Create: `Room created. id=<id> name="<name>" members=<names>.`

Leave: `Left room <room_id>.`

Failure: `Room operation failed. op=<operation>. status=<code>. error=<message>.`
