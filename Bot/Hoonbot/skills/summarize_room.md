# Skill: Summarize Room

Summarize recent human conversation in a room.

## Trigger

summarize room, catch me up, recap chat, what did I miss

## Required Inputs

- target room (default: current room from message header)
- optional message count (default `50`, max `100`)

## Message Header Format

Every message begins with:
```
[Room: <name> (id:<id>, <DM|group>) | From: <sender>]
```
Extract `name` and `id` from this line for the current room.

## API

- **Tool**: `shell_exec` — run `curl` with the `x-api-key` header
- `GET {messenger_url}/api/messages/{roomId}?limit=<count>`

## Hard Rules

- Exclude bot-authored messages from summary points.
- Exclude deleted messages (`isDeleted: true`).
- If fewer than 2 human messages remain, return "not enough messages".
- Keep summary to 3–8 bullet points.

## Procedure

1. Get `messenger_url`, `messenger_api_key`, and `bot_user_id` from session variables.
2. Resolve the target room:
   - **Current room** (no explicit target given): extract `id` and `name` directly from the message header.
   - **Named room**: call `GET {messenger_url}/api/rooms?userId={bot_user_id}` and match the room name case-insensitively; stop if no match.
3. Fetch messages for the resolved room ID; reverse to chronological order.
4. Filter out bot messages and deleted messages.
5. Summarize: topics discussed, decisions made, files shared, open questions.

## Response Format

```
Summary of <room_name> (last <count> messages): Participants=<names>.
- <point1>
- <point2>
...
```

Not enough:
`Not enough human messages to summarize in <room_name>.`

Failure:
`Room summary failed. status=<code>. error=<message>.`
