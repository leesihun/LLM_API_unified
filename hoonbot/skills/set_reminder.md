# Skill: Set Reminder

Schedule a delayed Messenger message.

## Use When

remind me, set reminder, notify me in, timer, cancel reminder

## Inputs

- delay: seconds, minutes, hours, or combos like `1h30m`
- message text
- target room: current room unless explicit room ID/name is given
- cancellation requires a process handle

## Tools

- `process_monitor` for background `sleep`/`curl`
- Messenger endpoint: `POST /api/send-message` with `{roomId, content}`

## Rules

- Valid delay: 1 to 86400 seconds.
- Ask if delay or reminder text is missing.
- Use one background process per reminder.
- Return the handle so the user can cancel.

## Reply

Set: `Reminder set for <delay_human>. fires_at=<time>. handle=<handle>. message="<message>".`

Cancelled: `Reminder cancelled. handle=<handle>.`

Failure: `Reminder failed. reason=<reason>.`
