# Screenshot & Send

Capture a screenshot of the desktop or a specific window and send it to the current Messenger room.

**Trigger phrases:** take a screenshot, screenshot, capture screen, show me the screen, grab the screen, snap the desktop, what's on screen

---

## API

- **Port:** `config.MESSENGER_URL` (10006)
- **Auth:** `x-api-key: config.MESSENGER_API_KEY` (from `data/.apikey`)
- `POST {MESSENGER_URL}/api/send-file` — upload image to room (multipart)

---

## Workflow

### 1. Determine capture scope

From the user's request, determine what to capture:
- **Full desktop** (default) — "take a screenshot"
- **Specific window** — "screenshot of the browser", "capture the terminal window"
- **Specific monitor** — "screenshot of the left monitor" (multi-monitor setups)

### 2. Capture the screenshot

**Windows (PowerShell):**

Full desktop screenshot:
```powershell
powershell -Command "Add-Type -AssemblyName System.Windows.Forms; $screens = [System.Windows.Forms.Screen]::AllScreens; $minX = ($screens | ForEach-Object { $_.Bounds.X } | Measure-Object -Minimum).Minimum; $minY = ($screens | ForEach-Object { $_.Bounds.Y } | Measure-Object -Minimum).Minimum; $maxX = ($screens | ForEach-Object { $_.Bounds.X + $_.Bounds.Width } | Measure-Object -Maximum).Maximum; $maxY = ($screens | ForEach-Object { $_.Bounds.Y + $_.Bounds.Height } | Measure-Object -Maximum).Maximum; $w = $maxX - $minX; $h = $maxY - $minY; $bmp = New-Object System.Drawing.Bitmap($w, $h); $g = [System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($minX, $minY, 0, 0, (New-Object System.Drawing.Size($w, $h))); $bmp.Save('{save_path}', [System.Drawing.Imaging.ImageFormat]::Png); $g.Dispose(); $bmp.Dispose()"
```

Primary monitor only:
```powershell
powershell -Command "Add-Type -AssemblyName System.Windows.Forms; $s = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; $bmp = New-Object System.Drawing.Bitmap($s.Width, $s.Height); $g = [System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($s.X, $s.Y, 0, 0, $s.Size); $bmp.Save('{save_path}', [System.Drawing.Imaging.ImageFormat]::Png); $g.Dispose(); $bmp.Dispose()"
```

**Linux:**
```bash
import -window root {save_path}
# or
scrot {save_path}
# or
gnome-screenshot -f {save_path}
```

Use a temporary file path like `/tmp/screenshot_YYYYMMDD_HHMMSS.png` or a scratch directory path.

### 3. Verify the screenshot was captured

```python
import os
if not os.path.exists(save_path) or os.path.getsize(save_path) == 0:
    raise FileNotFoundError("Screenshot capture failed")
```

### 4. Send to room

Upload the screenshot to the current room:

```
POST {MESSENGER_URL}/api/send-file
Content-Type: multipart/form-data
x-api-key: {api_key}

Form fields:
  roomId   — current room ID as string
  file     — the screenshot PNG file
  content  — "Screenshot" (optional caption)
```

```python
import httpx, config

with open(save_path, "rb") as f:
    resp = httpx.post(
        f"{config.MESSENGER_URL}/api/send-file",
        headers={"x-api-key": config.MESSENGER_API_KEY},
        data={"roomId": str(room_id)},
        files={"file": ("screenshot.png", f, "image/png")},
    )
resp.raise_for_status()
msg_id = resp.json().get("message", {}).get("id") or resp.json().get("id")
```

### 5. Clean up

Delete the temporary screenshot file after upload.

---

## Response format

**Success:**
```
Screenshot captured and sent to room. (message #{msg_id})
```

**Failure — capture failed:**
```
Screenshot capture failed.
reason: {error details}
fix: Ensure the display is accessible and the screenshot tool is available.
```

**Failure — upload failed:**
```
Screenshot captured but upload failed.
file: {save_path}
error: {http_status} — {error message}
```

---

## Notes

- Default to PNG format for lossless quality
- On Windows, the PowerShell method works without any additional tools installed
- On headless/remote systems, screenshot capture may fail — report clearly
- For "specific window" requests on Windows, you may need to use different PowerShell techniques or third-party tools
- Clean up temporary files even on failure (best-effort)
- If the screenshot is very large (>10 MB), consider reducing quality or cropping
