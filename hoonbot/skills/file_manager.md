# Skill: File Manager

Manage Messenger server storage.

## Use When

list server files, upload to server, download from server, rename file, delete file, create folder

## Inputs

- operation: `list`, `mkdir`, `upload`, `download`, `delete`, or `rename`
- server path rooted at `/`
- local path for upload/download when needed

## API

- `GET /files/list?path=...`
- `POST /files/mkdir` with `{path, name}`
- `POST /files/upload?path=...` multipart field `files`
- `GET /files/download?path=...`
- `POST /files/delete` with `{path}`
- `POST /files/rename` with `{path, newName}`

Use `shell_exec` with `curl`. These `/files` routes do not require the Messenger API key unless the server later adds auth.

## Rules

- Use virtual server paths only, beginning with `/`.
- No recursive listing unless explicitly requested.
- For `delete`, require explicit confirmation in the same user turn.
- Validate local upload source paths before calling the API.

## Reply

List: `<path>: <n> item(s). [DIR] ... [FILE] ...`

Create: `Created directory: <path>.`

Upload: `Uploaded <n> file(s) to <server_path>.`

Download: `Downloaded <server_path> to <local_path>.`

Delete: `Deleted: <path>.`

Rename: `Renamed: <old_path> -> <new_path>.`

Failure: `File operation failed. op=<operation>. status=<code>. error=<message>.`
