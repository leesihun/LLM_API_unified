# Skill: Set Reminder

Schedule a delayed message to the current room.

## Trigger

remind me, set reminder, notify me in, timer

## Required Inputs

- `delay` (required): seconds/minutes/hours, including combos like `1h30m`
- `message` (required): reminder text
- `room_id` — extract from `id:<number>` in the message header

## Message Header Format

Every message begins with:
```
[Room: <name> (id:<id>, <DM|group>) | From: <sender>]
```
Extract the room `id` from `id:<number>` in this line.

## Tools

- `process_monitor` (`start` / `kill`) — manage the background sleep+POST process
- The background command uses `curl` to POST to `{messenger_url}/api/send-message`

## Hard Rules

- If delay or message is missing, stop and ask.
- Parse delay strictly; if invalid, stop.
- Maximum delay: `86400` seconds (24h). If larger, stop and reject.
- Use one background process per reminder.

## Procedure

1. Parse delay to total seconds and validate `1..86400`.
2. Get `messenger_url` and `messenger_api_key` from session variables.
3. Extract `room_id` from the message header (`id:<number>`).
4. Build one shell command:
   ```
   sleep <seconds> && curl -s -X POST "{messenger_url}/api/send-message" -H "x-api-key: {messenger_api_key}" -H "Content-Type: application/json" -d '{"roomId":<room_id>,"content":"Reminder: <message>"}'
   ```
5. Start with `process_monitor` operation `start`.
6. Return confirmation with the process handle and estimated fire time.

## Cancel Procedure

If the user requests cancellation:
- Require the `handle` value.
- Call `process_monitor` operation `kill`.

## Response Format

Set:
`Reminder set for <delay_human>. fires_at=<time>. handle=<handle>. message="<message>".`

Cancelled:
`Reminder cancelled. handle=<handle>.`

Failure:
`Reminder failed. reason=<reason>.`
