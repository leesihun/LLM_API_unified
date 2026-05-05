# Skill: User Directory

List users or find users by name in Messenger.

## Trigger

list users, who is on messenger, find user, show bots, show humans

## Required Inputs

- optional `query` for name match
- optional filter: `all|humans|bots` (default `all`)

## API

- **Tool**: `shell_exec` — run `curl` with the `x-api-key` header
- `GET {messenger_url}/api/users`

## Hard Rules

- Use `/api/users` only.
- Name search is case-insensitive substring match.
- Treat missing `isBot` as `false`.

## Procedure

1. Get `messenger_url` and `messenger_api_key` from session variables.
2. Fetch users with `GET {messenger_url}/api/users`.
3. Apply filter and optional name query.
4. Return sorted by name.

## Response Format

List:
`Users (<count>): <name>(id=<id>, type=<human|bot>), ...`

Search:
`Matches for "<query>" (<count>): <name>(id=<id>, type=<human|bot>), ...`

No results:
`No users found for "<query>".`

Failure:
`User lookup failed. status=<code>. error=<message>.`
