# Skill: Download Attachment

Download a Messenger attachment to local disk.

## Use When

download attachment, save that file, download image, get file from chat

## Inputs

- room: current room unless the user names a room
- selector: `message_id`, exact filename, "last file", "last image", or quoted reply text
- destination: requested folder, otherwise current working directory

## API

- `GET {messenger_url}/api/messages/{roomId}?limit=50`
- `GET {messenger_url}{fileUrl}`

Use `shell_exec` with `curl` and `x-api-key: {messenger_api_key}`.

## Rules

- Attachments may be in `attachments[]`; legacy messages may also use `fileUrl`, `fileName`, and `type`.
- If the user replied to a message, match the quoted sender/content against recent messages. If not unique, ask for `message_id`.
- If a selector matches multiple attachments, stop and ask for `message_id`.
- If the destination file exists, append ` (1)`, ` (2)`, etc.

## Steps

1. Resolve room ID from the message header, explicit ID, or `/api/rooms?userId={bot_user_id}`.
2. Fetch recent messages.
3. Select one attachment by the requested selector.
4. Download `{messenger_url}{fileUrl}` with the API key.
5. Save only after a successful response and verify the file exists with nonzero size.

## Reply

Success: `Downloaded <filename> from message <id>. saved_to=<absolute_path>.`

No match: `No matching attachment found in recent messages.`

Ambiguous: `Multiple attachments matched: <message_id:filename list>. Specify one message_id.`

Failure: `Download failed. status=<code>. error=<message>.`
