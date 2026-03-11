# Set Reminder

Set a timed reminder that delivers a message back to the user after a specified delay.

**Trigger phrases:** remind me, set a reminder, alert me in, notify me in, remind me in, don't let me forget, remind me to, timer for

---

## Mechanism

Use `process_monitor` to start a background process that sleeps for the specified duration, then sends a message to the current room via the Messenger API.

The reminder runs as a detached shell process — it survives even if the current LLM session ends.

---

## Workflow

### 1. Parse the reminder request

Extract:
- **delay** (required) — how long to wait. Examples: "5 minutes", "1 hour", "30 seconds", "2h30m"
- **message** (required) — what to remind about. Examples: "check the build", "call Mom", "meeting at 3"
- **room_id** — the current room (from context)

Convert delay to seconds:
- `Xm` or `X minutes` → X * 60
- `Xh` or `X hours` → X * 3600
- `Xs` or `X seconds` → X
- Combinations: `1h30m` → 5400

If delay or message is missing, ask the user — stop.

### 2. Read config

```python
import config
messenger_url = config.MESSENGER_URL
api_key = config.MESSENGER_API_KEY  # from data/.apikey
```

The API key must be read from the file `data/.apikey` (relative to the Hoonbot directory). Use `file_reader` to read it.

### 3. Build the reminder command

The command sleeps for the delay, then POSTs a message to Messenger:

**Linux:**
```bash
sleep {delay_seconds} && curl -s -X POST "{messenger_url}/api/send-message" \
  -H "Content-Type: application/json" \
  -H "x-api-key: {api_key}" \
  -d '{{"roomId": {room_id}, "content": "Reminder: {message}"}}'
```

**Windows:**
```powershell
powershell -Command "Start-Sleep -Seconds {delay_seconds}; Invoke-RestMethod -Uri '{messenger_url}/api/send-message' -Method Post -ContentType 'application/json' -Headers @{{'x-api-key'='{api_key}'}} -Body ('{{\\"roomId\\": {room_id}, \\"content\\": \\"Reminder: {message}\\"}}' | ConvertTo-Json)"
```

Alternatively, use a simpler cross-platform Python one-liner:
```bash
python -c "import time,httpx; time.sleep({delay_seconds}); httpx.post('{messenger_url}/api/send-message', headers={{'x-api-key':'{api_key}','Content-Type':'application/json'}}, json={{'roomId':{room_id},'content':'Reminder: {message}'}})"
```

### 4. Start the background process

Use the `process_monitor` tool with operation `start`:

```json
{
  "operation": "start",
  "command": "<the reminder command from step 3>"
}
```

This returns a `handle` (e.g. `proc_1`). Save this handle to report back.

### 5. Confirm to user

Report the reminder details and the process handle so they can cancel if needed.

---

## Response format

**Success:**
```
Reminder set! I'll post to this room in {human_readable_delay}.

Details:
- Message: "{message}"
- Fires at: ~{estimated_time} (in {delay_human})
- Handle: {handle} (use this to cancel if needed)
```

**Cancelled (if user asks to cancel):**
Use `process_monitor` with operation `kill` and the handle:
```json
{"operation": "kill", "handle": "proc_1"}
```
```
Reminder cancelled (handle: {handle}).
```

---

## Notes

- Always confirm the parsed delay back to the user before starting: "Setting reminder for 30 minutes from now..."
- Use the estimated fire time (current time + delay) so the user knows when to expect it
- The reminder message is prefixed with "Reminder:" so it's clearly identifiable
- If the server restarts before the reminder fires, the process is lost — warn the user for very long delays (>24h)
- Maximum recommended delay: 24 hours. For longer, suggest using the heartbeat/memo system instead
- Escape special characters in the message (quotes, backslashes) when building the shell command
