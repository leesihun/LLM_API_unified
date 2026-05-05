# Skill: Manage Webhooks

List, create, update, or delete Messenger webhook subscriptions.

## Trigger

list webhooks, create webhook, update webhook, delete webhook

## Required Inputs

- operation: `list|create|update|delete`
- for create: `url`, `events`
- for update: `webhook_id` plus `url` and/or `events`
- for delete: `webhook_id`

## API

- **Tool**: `shell_exec` — run `curl` with the `x-api-key` header
- `GET {messenger_url}/api/webhooks`
- `POST {messenger_url}/api/webhooks`
- `PATCH {messenger_url}/api/webhooks/{id}`
- `DELETE {messenger_url}/api/webhooks/{id}`

## Hard Rules

- If required fields are missing, stop and ask.
- For delete, require explicit confirmation in the same turn.
- Events allowed: `new_message`, `message_edited`, `message_deleted`, `message_read`.

## Procedure

1. Get `messenger_url` and `messenger_api_key` from session variables.
2. Validate operation and required fields.
3. Call the corresponding webhook endpoint.
4. Return compact result with webhook ID.

## Response Format

List:
`Webhooks (<count>): id=<id> url=<url> events=<events>; ...`

Create:
`Webhook created. id=<id> url=<url> events=<events>.`

Update:
`Webhook updated. id=<id> url=<url> events=<events>.`

Delete:
`Webhook deleted. id=<id>.`

Failure:
`Webhook operation failed. op=<operation>. status=<code>. error=<message>.`
