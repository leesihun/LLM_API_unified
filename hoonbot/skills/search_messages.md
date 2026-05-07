# Skill: Search Messages

Search Messenger message history.

## Use When

search messages, find message, when did we discuss, find conversation

## Inputs

- `query` required
- optional room scope: current room, room ID, or exact room name
- optional `limit`, default 20, max 100

## API

- `GET /api/search?q=<query>&limit=<limit>`
- `GET /api/search?q=<query>&roomId=<room_id>&limit=<limit>`

Use `shell_exec` with `curl` and `x-api-key: {messenger_api_key}`.

## Rules

- If query is missing, ask one question.
- Resolve named rooms through `/api/rooms?userId={bot_user_id}` and require exactly one match.
- Do not search deleted messages; `/api/search` already excludes them.

## Reply

Found: `Found <count> message(s) for "<query>": 1. [<room>] <sender> <time> "<preview>" (id=<id>) ...`

No results: `No messages found for "<query>".`

Failure: `Search failed. status=<code>. error=<message>.`
