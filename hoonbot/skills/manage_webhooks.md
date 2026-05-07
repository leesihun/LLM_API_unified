# Skill: Manage Webhooks

List, create, update, or delete Messenger webhooks.

## Use When

list webhooks, create webhook, update webhook, delete webhook, enable webhook, disable webhook

## Inputs

- operation: `list`, `create`, `update`, or `delete`
- create: `url`, optional `roomId`, optional `events`, optional `secret`
- update: `webhook_id`, plus any of `url`, `events`, `isActive`, `secret`
- delete: `webhook_id` and explicit confirmation

## API

- `GET /api/webhooks`
- `POST /api/webhooks`
- `PATCH /api/webhooks/{id}`
- `DELETE /api/webhooks/{id}`

Use `shell_exec` with `curl` and `x-api-key: {messenger_api_key}`.

## Rules

- Allowed events: `new_message`, `message_edited`, `message_deleted`, `message_read`.
- Do not echo webhook secrets.
- For delete, require explicit confirmation in the same user turn.

## Reply

List: `Webhooks (<count>): id=<id> url=<url> room=<roomId|all> events=<events> active=<true|false>; ...`

Create: `Webhook created. id=<id> url=<url> room=<roomId|all> events=<events>.`

Update: `Webhook updated. id=<id> active=<true|false> events=<events>.`

Delete: `Webhook deleted. id=<id>.`

Failure: `Webhook operation failed. op=<operation>. status=<code>. error=<message>.`
