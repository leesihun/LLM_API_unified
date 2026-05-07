# Skill: User Directory

List or find Messenger users.

## Use When

list users, who is on messenger, find user, show bots, show humans

## Inputs

- optional name query
- optional filter: `all`, `humans`, or `bots`

## API

- `GET /api/users`
- `GET /api/bots/me` when the user asks "who am I as the bot?"

Use `shell_exec` with `curl` and `x-api-key: {messenger_api_key}`.

## Rules

- Name search is case-insensitive substring match.
- Treat missing `isBot` as `false`.
- Never print API keys.

## Reply

List: `Users (<count>): <name>(id=<id>, type=<human|bot>), ...`

Search: `Matches for "<query>" (<count>): <name>(id=<id>, type=<human|bot>), ...`

No results: `No users found for "<query>".`

Failure: `User lookup failed. status=<code>. error=<message>.`
