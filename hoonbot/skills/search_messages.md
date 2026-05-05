# Skill: Search Messages

Search Messenger messages globally or in one room.

## Trigger

search messages, find message, when did we discuss, find conversation

## Required Inputs

- `query` (required)
- optional `room_id` or exact `room_name`
- optional `limit` (default `20`, max `100`)

## Message Header Format

Every message begins with:
```
[Room: <name> (id:<id>, <DM|group>) | From: <sender>]
```
When the user says "search this room" or similar, extract `id` and `name` directly from this line — no API call needed.

## API

- **Tool**: `shell_exec` — run `curl` with the `x-api-key` header
- `GET {messenger_url}/api/search?q=<query>&limit=<limit>`
- `GET {messenger_url}/api/search?q=<query>&roomId=<room_id>&limit=<limit>`

## Hard Rules

- If query is missing, stop and ask.
- If a room name is given and does not resolve to exactly one room, stop.
- Use `/api/search` endpoint only for consistency.

## Procedure

1. Get `messenger_url`, `messenger_api_key`, and `bot_user_id` from session variables.
2. Parse query, room scope, and limit.
3. Resolve the room when a scope is specified:
   - **Current room** ("this room", "here", or no scope): extract `id` from the message header.
   - **Named room**: call `GET {messenger_url}/api/rooms?userId={bot_user_id}` and match case-insensitively; stop if no match.
4. Execute the search request with the API key.
5. Return a compact result list: message ID, room, sender, timestamp, and content preview.

## Response Format

Found:
`Found <count> message(s) for "<query>": 1) [<room>] <sender> <time> "<preview>" (id=<id>) ...`

No results:
`No messages found for "<query>".`

Failure:
`Search failed. status=<code>. error=<message>.`
