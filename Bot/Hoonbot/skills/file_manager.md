# File Manager

Browse, upload, download, rename, and delete files on the Messenger server's file system.

**Trigger phrases:** list server files, browse files on messenger, upload to server, download from server, delete server file, rename server file, server file manager, messenger files

---

## API

- **Port:** `config.MESSENGER_URL` (10006)
- **Auth:** `x-api-key: config.MESSENGER_API_KEY` (from `data/.apikey`)
- `GET {MESSENGER_URL}/files/list?path={dir}` — list directory contents
- `POST {MESSENGER_URL}/files/mkdir` — create folder
- `POST {MESSENGER_URL}/files/upload` — upload files (multipart)
- `GET {MESSENGER_URL}/files/download?path={file}` — download file
- `POST {MESSENGER_URL}/files/delete` — delete file or folder
- `POST {MESSENGER_URL}/files/rename` — rename file or folder

---

## Workflow

### 1. Read config

```python
import config
base_url = config.MESSENGER_URL
api_key = config.MESSENGER_API_KEY
```

### 2. Determine operation

From the user's request:
- **list / browse** — show directory contents
- **mkdir** — create a new folder
- **upload** — upload a local file to the server
- **download** — download a file from the server to local disk
- **delete** — remove a file or folder
- **rename** — rename a file or folder

Default to **list** at root (`/`) if no specific path is given.

### 3. Execute operation

**List directory:**
```
GET {MESSENGER_URL}/files/list?path={directory_path}
x-api-key: {api_key}
```

Response:
```json
[
  {
    "name": "documents",
    "path": "/documents",
    "isDirectory": true,
    "size": 0,
    "modifiedAt": "2026-03-10T14:00:00.000Z"
  },
  {
    "name": "report.pdf",
    "path": "/report.pdf",
    "isDirectory": false,
    "size": 204800,
    "modifiedAt": "2026-03-09T10:00:00.000Z"
  }
]
```

**Create folder:**
```
POST {MESSENGER_URL}/files/mkdir
x-api-key: {api_key}
Content-Type: application/json

{"path": "/new-folder"}
```

**Upload file:**
```
POST {MESSENGER_URL}/files/upload
x-api-key: {api_key}
Content-Type: multipart/form-data

Form fields:
  path   — destination directory (e.g. "/documents")
  file   — file binary with original filename
```

```python
import httpx

with open(local_path, "rb") as f:
    resp = httpx.post(
        f"{base_url}/files/upload",
        headers={"x-api-key": api_key},
        data={"path": destination_dir},
        files={"file": (filename, f)},
    )
resp.raise_for_status()
```

**Download file:**
```
GET {MESSENGER_URL}/files/download?path={file_path}
x-api-key: {api_key}
```

Save the response body to a local file:
```python
resp = httpx.get(
    f"{base_url}/files/download",
    headers={"x-api-key": api_key},
    params={"path": server_file_path},
)
resp.raise_for_status()
with open(local_save_path, "wb") as f:
    f.write(resp.content)
```

**Delete file/folder:**
```
POST {MESSENGER_URL}/files/delete
x-api-key: {api_key}
Content-Type: application/json

{"path": "/old-file.txt"}
```

**Rename file/folder:**
```
POST {MESSENGER_URL}/files/rename
x-api-key: {api_key}
Content-Type: application/json

{"oldPath": "/old-name.txt", "newPath": "/new-name.txt"}
```

---

## Response format

**List:**
```
Files in {path}:

  [DIR]  documents/          — modified Mar 10
  [DIR]  images/             — modified Mar 9
  [FILE] report.pdf (200 KB) — modified Mar 9
  [FILE] notes.txt (1.2 KB)  — modified Mar 8

{count} items ({dirs} folders, {files} files)
```

**Upload:**
```
Uploaded "{filename}" ({size_human}) to {server_path}.
```

**Download:**
```
Downloaded "{filename}" ({size_human}) from server.
Saved to: {local_path}
```

**Delete:**
```
Deleted {file_or_folder}: {path}
```

**Rename:**
```
Renamed: {oldPath} → {newPath}
```

**Empty directory:**
```
{path} is empty.
```

---

## Notes

- Paths use forward slashes and are relative to the Messenger server's file root
- The root path is `/` — do not use OS-specific absolute paths
- File sizes should be shown in human-readable format (KB, MB, GB)
- **Deleting is permanent** — always confirm with the user before deleting: "Are you sure you want to delete {path}?"
- For recursive directory listings, call `list` on each subdirectory — there is no recursive flag
- Upload does not overwrite by default — behavior on name collision depends on server config
