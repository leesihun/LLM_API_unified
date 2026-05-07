# Skill: Summarize Room

Summarize recent conversation in one room.

## Use When

summarize room, catch me up, recap chat, what did I miss

## Inputs

- room: current room unless the user names another
- optional count, default 50, max 100

## API

- `GET /api/messages/{roomId}?limit=<count>`

Use `shell_exec` with `curl` and `x-api-key: {messenger_api_key}`.

## Rules

- Exclude bot-authored and deleted messages.
- Keep the summary to 3-6 bullets.
- Include decisions, files shared, action items, and open questions when present.
- If fewer than two human messages remain, say there is not enough to summarize.

## Reply

```
Summary of <room_name> (last <count> messages): Participants=<names>.
- <point>
- <point>
```

Not enough: `Not enough human messages to summarize in <room_name>.`

Failure: `Room summary failed. status=<code>. error=<message>.`
