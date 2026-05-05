# Skill: File Manager

Manage Messenger server files: list, mkdir, upload, download, delete, rename.

## Trigger

list server files, upload to server, download from server, rename file, delete file

## Required Inputs

- operation: `list|mkdir|upload|download|delete|rename`
- operation-specific paths

## API

- **Tool**: `shell_exec` — run `curl` with the `x-api-key` header
- `GET {messenger_url}/files/list?path=...`
- `POST {messenger_url}/files/mkdir`
- `POST {messenger_url}/files/upload`
- `GET {messenger_url}/files/download?path=...`
- `POST {messenger_url}/files/delete`
- `POST {messenger_url}/files/rename`

## Hard Rules

- Use server paths with `/` root only.
- No recursive listing unless explicitly requested.
- For `delete`, require explicit user confirmation in the same turn.
- For `upload`, the local source file must exist before making the request.

## Procedure

1. Get `messenger_url` and `messenger_api_key` from session variables.
2. Parse the requested operation and validate required arguments.
3. Execute exactly one endpoint for the operation.
4. Return a compact result with the target path and status.

## Response Format

List:
`<path>: <n> item(s). [DIR] ... [FILE] ...`

Create:
`Created directory: <path>.`

Upload:
`Uploaded <filename> to <server_path>.`

Download:
`Downloaded <server_path> to <local_path>.`

Delete:
`Deleted: <path>.`

Rename:
`Renamed: <old_path> -> <new_path>.`

Failure:
`File operation failed. op=<operation>. status=<code>. error=<message>.`
