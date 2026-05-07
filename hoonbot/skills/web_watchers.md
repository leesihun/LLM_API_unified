# Skill: Web Watchers

Manage Messenger web page watchers.

## Use When

watch this page, monitor URL, list watchers, pause watcher, resume watcher, delete watcher

## Inputs

- operation: `list`, `create`, `update`, or `delete`
- create: `url`, room ID/name, optional `intervalSeconds`
- update: watcher ID plus `url`, `intervalSeconds`, or `isActive`
- delete: watcher ID and explicit confirmation

## API

- `GET /api/watchers`
- `POST /api/watchers` with `{url, roomId, intervalSeconds?}`
- `PATCH /api/watchers/{id}` with any of `{url, intervalSeconds, isActive}`
- `DELETE /api/watchers/{id}`

Use `shell_exec` with `curl` and `x-api-key: {messenger_api_key}`.

## Rules

- Resolve room names through `/api/rooms?userId={bot_user_id}`.
- Server clamps interval to 5-3600 seconds; tell the user the returned value.
- Delete requires explicit confirmation in the same user turn.
- Watchers post updates to their target room through Messenger.

## Reply

List: `Watchers (<count>): id=<id> url=<url> room=<roomId> interval=<seconds>s active=<true|false>; ...`

Create: `Watcher created. id=<id> url=<url> room=<roomId> interval=<seconds>s.`

Update: `Watcher updated. id=<id> active=<true|false> interval=<seconds>s.`

Delete: `Watcher deleted. id=<id>.`

Failure: `Watcher operation failed. op=<operation>. status=<code>. error=<message>.`
