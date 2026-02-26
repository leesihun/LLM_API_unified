# Hoonbot Architecture

## Overview

Hoonbot is a simplified, tool-driven personal AI assistant that bridges Huni Messenger (chat frontend) and LLM_API_fast (LLM backend). It has no custom databases, schedulers, or complex state management—just a single memory file and pure tool usage.

```
┌─────────────────────┐
│  Huni Messenger     │ (Chat UI on port 3000)
│   (TypeScript)      │
└──────────┬──────────┘
           │ (HTTP API calls)
           │
┌──────────▼──────────┐
│     Hoonbot         │ (FastAPI on port 3939)
│    (Python)         │
│                     │
│  • Webhook handler  │
│  • Messenger API    │
│  • Prompt builder   │
└──────────┬──────────┘
           │ (HTTP API calls)
           │
┌──────────▼──────────┐
│ LLM_API_fast        │ (Agent system on port 10007)
│ (Python)            │
│                     │
│ • websearch         │
│ • file_reader       │
│ • file_writer       │
│ • file_navigator    │
│ • python_coder      │
│ • rag               │
│ • shell_exec        │
└─────────────────────┘
```

## Core Components

### 1. Entry Point: `hoonbot.py`

**Purpose:** Initialize and run the Hoonbot server

**Responsibilities:**
- Create FastAPI application
- Register bot with Messenger (get API key)
- Subscribe to webhook events from Messenger
- Catch up on missed messages during downtime
- Serve HTTP endpoints on port 3939

**Key Functions:**
- `_load_saved_key()` — Load API key from disk
- `_save_key()` — Persist API key
- `_catch_up()` — Find and process unanswered messages on startup
- `lifespan()` — Async context manager for startup/shutdown

**Startup Sequence:**
1. Ensure `data/` directory exists
2. Load or register bot API key with Messenger
3. Register webhook subscription
4. Start catching up on missed messages
5. Serve on configured port

### 2. Webhook Handler: `handlers/webhook.py`

**Purpose:** Process incoming messages and call the LLM

**Two Main Endpoints:**

#### POST `/webhook`
Receives `new_message` events from Messenger.

**Processing Pipeline:**
1. Validate message (text only, not from bot, @mention if in group)
2. Debounce rapid messages from same room (combine into one call)
3. When debounce window closes: `process_message()`

```python
process_message(room_id, content, sender_name):
    # 1. Load soul and memory
    soul = _load_soul()
    memory = _read_memory()

    # 2. Build system prompt with absolute path
    abs_path = os.path.abspath(MEMORY_FILE)
    system_prompt = soul + f"\n\n## Memory File Location\n\nAbsolute path: {abs_path}\n\n..."
    system_prompt += f"\n\n## Current Memory\n\n{memory}"

    # 3. Build message list
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content}
    ]

    # 4. Call LLM_API_fast with agent_type=auto
    response = httpx.post(
        f"{LLM_API_URL}/v1/chat/completions",
        data={
            "model": LLM_MODEL,
            "messages": json.dumps(messages),
            "agent_type": "auto"
        },
        headers={"Authorization": f"Bearer {LLM_API_KEY}"}
    )

    # 5. Get LLM response
    reply = response.json()["choices"][0]["message"]["content"]

    # 6. Send reply back to Messenger
    await messenger.send_message(room_id, reply)
```

**Key Points:**
- Debouncing prevents processing every keystroke—waits 1.5s for typing to finish
- Absolute path is injected so LLM knows where to read/write memory
- `agent_type: auto` lets LLM_API_fast choose the best agent automatically
- All tool usage happens within LLM_API_fast (no custom parsing)

#### POST `/webhook/incoming/{source}`
Receives webhooks from external services (GitHub, calendars, etc.)

**Features:**
- Optional secret-based authentication (`X-Webhook-Secret` header)
- Converts JSON payload to readable message
- Sends to home room as `[Webhook from {source}] ...`

### 3. Configuration: `config.py`

**Environment Variables:**
```python
# Server
HOONBOT_PORT=3939                    # Port to listen on
HOONBOT_HOST=0.0.0.0                # Bind address

# Messenger connection
MESSENGER_PORT=3000                  # Messenger port
HOONBOT_BOT_NAME=Hoonbot            # Bot display name
HOONBOT_HOME_ROOM_ID=1              # Default room ID

# LLM_API_fast connection
LLM_API_PORT=10007                   # Main LLM API port
LLM_API_URL=...                      # Override full URL
LLM_API_KEY=...                      # Bearer token (MUST SET)
LLM_MODEL=...                        # Model name (MUST SET)

# Webhooks
HOONBOT_WEBHOOK_SECRET=...           # Secret for incoming webhooks
```

### 4. Prompts: `PROMPT.md`

**Purpose:** Single unified system prompt for the LLM

**Contains:**
- Identity and behavior guidelines
- Memory system instructions
- Complete tool documentation
- Webhook handling guidelines
- When to update memory
- Best practices

**Usage:** Loaded by webhook.py and injected into every LLM call

### 5. Personality: `SOUL.md`

**Purpose:** Legacy personality file (can be deprecated in favor of PROMPT.md)

**Currently:** Still loaded and included in system prompt, but PROMPT.md is more comprehensive

### 6. Memory Storage: `data/memory.md`

**Purpose:** Single persistent memory file

**Format:** Plain Markdown
- Can be edited manually or via file_writer tool
- Auto-injected into every LLM call
- Absolute path provided in system prompt

**Example Content:**
```markdown
# Hoonbot Memory

## User
- Name: Huni
- Language preference: Korean
- Updated: 2026-02-26

## Notes
- User prefers direct, concise responses
- Active projects: [list]
```

### 7. Messenger Connection: `core/messenger.py`

**Purpose:** HTTP wrapper for Messenger REST API

**Key Methods:**
- `register_bot()` — Register bot and get API key
- `register_webhook()` — Subscribe to message events
- `get_bot_info()` — Get bot details
- `get_rooms()` — List rooms bot is in
- `get_room_messages()` — Get message history
- `send_message()` — Send message to room
- `send_typing()` / `stop_typing()` — Typing indicators

**Auth:** Uses Bearer token (API key stored in `data/.apikey`)

### 8. Utilities: `handlers/health.py`

**Purpose:** Simple health check endpoint

**Endpoint:** `GET /health`

**Response:** `{"status": "ok", "timestamp": "..."}`

## Data Flow

### Incoming Message Flow

```
1. Messenger sends: POST /webhook
   {
     "event": "new_message",
     "roomId": 1,
     "data": {
       "content": "Hello!",
       "senderName": "Huni",
       "type": "text"
     }
   }

2. webhook.py receives and validates
   ✓ Is text message
   ✓ Not from bot
   ✓ @mentioned if group chat

3. Debounce (wait 1.5s for more messages)

4. process_message() called
   - Load SOUL.md
   - Load data/memory.md
   - Build system prompt with absolute path
   - Build message list

5. Call LLM_API_fast
   POST http://localhost:10007/v1/chat/completions
   {
     "model": "...",
     "messages": [...],
     "agent_type": "auto"
   }

6. LLM_API_fast agent processes
   - Analyzes the request
   - Uses tools as needed (file_writer, file_reader, websearch, etc.)
   - Generates response
   - Returns to Hoonbot

7. Hoonbot sends reply
   POST http://localhost:3000/api/send-message
   {
     "roomId": 1,
     "content": "..."
   }

8. Messenger displays reply to user
```

### Memory Update Flow (Example)

```
User: "Remember: I'm working on Project X"

1. LLM receives message with:
   - Current memory content
   - Absolute path: c:/Users/.../data/memory.md

2. LLM decides to update memory
   - Uses file_reader to read current memory.md
   - Adds/updates entry for Project X
   - Uses file_writer to save updated memory.md

3. Next message includes updated memory
   - User sends another message
   - webhook.py reads data/memory.md
   - Updated memory is in the context
   - LLM can reference the saved info
```

## File Organization

```
Hoonbot/
├── hoonbot.py              # Entry point, FastAPI server
├── config.py               # Configuration from env vars
├── PROMPT.md               # Unified system prompt for LLM
├── SOUL.md                 # Legacy personality (can remove)
├── ARCHITECTURE.md         # This file
├── reset.py                # Utility to reset memory
├── test_llm.py             # Test script for LLM_API_fast
│
├── handlers/
│   ├── __init__.py
│   ├── webhook.py          # Message processing (MAIN LOGIC)
│   └── health.py           # Health check endpoint
│
├── core/
│   ├── __init__.py
│   ├── messenger.py        # Messenger API client
│   └── retry.py            # Retry decorator
│
└── data/
    ├── memory.md           # Persistent memory file
    └── .apikey             # Stored Messenger API key
```

## Configuration & Startup

### Prerequisites

1. **LLM_API_fast running:**
   ```bash
   cd ../LLM_API_fast
   python tools_server.py &
   python run_backend.py &
   ```

2. **Environment variables:**
   ```bash
   export LLM_API_KEY="your_api_token"
   export LLM_MODEL="your_model_name"
   ```

3. **Huni Messenger running:**
   - Messenger should be on `http://localhost:3000`

### Start Hoonbot

```bash
cd Hoonbot
python hoonbot.py
```

**Expected Output:**
```
[Messenger] Restored API key from disk
[Messenger] Webhook target: http://localhost:3939/webhook
[Hoonbot] Ready on port 3939
```

## Key Design Decisions

### Why This Architecture?

1. **No custom systems** — Use LLM_API_fast's built-in tools instead
2. **Single memory file** — Simple, inspectable, easy to understand
3. **Tool-driven** — Let the LLM decide what to do, not custom commands
4. **Absolute paths** — Passed in prompt so LLM knows exact file locations
5. **Minimal code** — Easier to debug, maintain, and extend
6. **Pure FastAPI** — Standard Python web framework, no custom complexity

### Trade-offs

| Aspect | Benefit | Cost |
|--------|---------|------|
| Single memory file | Simple, inspectable | Limited structure |
| Tool-driven | Flexible, extensible | Depends on LLM quality |
| No database | Fast startup, no migrations | Memory limited to file I/O |
| Agent system | Automatic tool calling | More LLM API calls |

## Extending Hoonbot

### Add a New Capability

Since everything goes through LLM_API_fast tools, new capabilities are added by:

1. **Using existing tools** — file_writer, websearch, shell_exec, etc.
2. **Updating PROMPT.md** — Tell LLM about new use cases
3. **No code changes needed** — The agent handles it automatically

Example: To add "analyze CSV files"
- Don't create new code
- Just tell PROMPT.md to use python_coder or rag
- LLM will use appropriate tools

### Modify Memory Format

Edit `data/memory.md` directly or update PROMPT.md with new guidance on structure. No code changes.

## Troubleshooting

### "LLM 서버에 연결할 수 없어요"

**Cause:** Can't connect to LLM_API_fast

**Fix:**
1. Check LLM_API_fast is running: `ps aux | grep run_backend.py`
2. Check LLM_API_KEY is set: `echo $LLM_API_KEY`
3. Check LLM_API_URL in config matches server port

### LLM doesn't update memory

**Cause:** LLM not using file_writer tool

**Fix:**
1. Ensure PROMPT.md has clear instructions
2. Test with `python test_llm.py`
3. Check LLM_API_fast logs for tool errors

### Memory.md keeps getting reset

**Cause:** file_writer is overwriting instead of preserving content

**Fix:**
1. Read full memory with file_reader before writing
2. Include all existing content in write
3. Don't use `mode: "append"` unless intentional

## Future Improvements

- [ ] Add logging/audit trail to memory changes
- [ ] Create memory.md backup system
- [ ] Add memory search/retrieval optimization (currently all in prompt)
- [ ] Dashboard to view memory and recent interactions
- [ ] Multi-room memory isolation (if needed)

---

**Last Updated:** 2026-02-26
**Version:** 1.0 (Simplified Architecture)
