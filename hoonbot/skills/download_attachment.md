# Skill: Download Attachment

Download a file or image from room messages and save it locally.

## Trigger

download attachment, save that file, download image, get file from chat

## Required Inputs

- target room (default: current room from message header)
- one selector:
  - exact `message_id`, or
  - exact `filename`, or
  - keyword `last file` / `last image`, or
  - **reply context** — if the user's message is a reply (a `> Sender: "..."` line appears in the header), the quoted message is the target

## Message Header Format

Every message begins with:
```
[Room: <name> (id:<id>, <DM|group>) | From: <sender>]
```
Optionally followed by a reply line:
```
> <original_sender>: "<original_message_content>"
```
If a reply line is present, the quoted message is the attachment the user is referring to — resolve `message_id` from `replyToId` in that context.

## API

- **Tool**: `shell_exec` — run `curl` with the `x-api-key` header
- `GET {messenger_url}/api/messages/{roomId}?limit=50`
- `GET {messenger_url}{fileUrl}` (download the file binary)

## Hard Rules

- If the selector matches multiple attachments, stop and ask the user to choose.
- Do not guess between multiple candidates.
- Save only after a successful download response.
- If the target path already exists, append a numeric suffix: `(1)`, `(2)`, etc.

## Procedure

1. Get `messenger_url`, `messenger_api_key`, and `bot_user_id` from session variables.
2. Resolve the target room:
   - **Current room**: extract `id` from the message header.
   - **Named room**: call `GET {messenger_url}/api/rooms?userId={bot_user_id}` and match case-insensitively; stop if no match.
3. Fetch recent messages from the target room.
4. Keep only messages with `type` in `{"file", "image"}` and a non-empty `fileUrl`.
5. Resolve a single attachment using the selector:
   - **Reply context**: use the `replyToId` from the triggering message to find the exact attachment.
   - `message_id`: exact ID match.
   - filename: exact case-insensitive filename match.
   - `last file` / `last image`: newest matching type.
6. Download with `GET {messenger_url}{fileUrl}` using the API key.
7. Save to the requested directory, or the current working directory if none was given.

## Response Format

Success:
`Downloaded <filename> from message <id> by <sender>. saved_to=<absolute_path>.`

No match:
`No matching attachment found in recent messages.`

Ambiguous match:
`Multiple attachments matched: <list with message_id and filename>. Specify one message_id.`

Failure:
`Download failed. status=<code>. error=<message>.`
