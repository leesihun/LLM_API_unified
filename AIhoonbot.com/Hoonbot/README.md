# Hoonbot

A simplified, tool-driven personal AI assistant that connects Huni Messenger (chat UI) with LLM_API_fast (LLM backend).

## Quick Start

### Prerequisites

1. **LLM_API_fast running:**
   ```bash
   cd ../LLM_API_fast
   python tools_server.py &      # Terminal 1
   python run_backend.py &       # Terminal 2
   ```

2. **Huni Messenger running on port 3000**

### Setup (One-Time)

Run the setup script to automatically obtain LLM credentials:

```bash
cd Hoonbot
python setup.py
```

This will:
- Connect to LLM_API_fast at http://localhost:10007
- Login with default credentials (admin/administrator)
- Fetch available models
- Save token to `data/.llm_key`
- Save model to `data/.llm_model`

Example output:
```
============================================================
  Hoonbot Setup
============================================================

[Setup] Connecting to LLM_API_fast at http://localhost:10007
[OK] Successfully obtained access token

Fetching available models...

Available models:
  1. claude-opus-4-6
  2. claude-sonnet-4-6
  3. claude-haiku-4-5

Selected: claude-opus-4-6

Saving credentials...
[OK] Saved LLM_API_KEY to data/.llm_key
[OK] Saved LLM_MODEL to data/.llm_model

============================================================
  Setup Complete!
============================================================

Credentials saved to:
  data/.llm_key    (API token)
  data/.llm_model  (Model name)

You can now start Hoonbot:
  python hoonbot.py

No environment variables needed!
```

### Start Hoonbot

```bash
cd Hoonbot
python hoonbot.py
```

**No environment variables needed!** Credentials are loaded from:
- `data/.llm_key` — LLM API token
- `data/.llm_model` — Model name

Expected output:
```
[Messenger] Bot registered and key saved
[Messenger] Webhook target: http://localhost:3939/webhook
[Hoonbot] Ready on port 3939
```

## Key Documentation

### 📋 [PROMPT.md](PROMPT.md) — System Prompt
The unified prompt that tells the LLM how to behave, what tools to use, and how to manage memory.

**Key sections:**
- Identity and behavior guidelines
- Memory system instructions (read/write)
- Complete tool documentation
- When to update memory
- Webhook handling guidelines

**Automatically loaded and injected into every LLM call.**

### 🏗️ [ARCHITECTURE.md](ARCHITECTURE.md) — System Design
Complete technical documentation explaining how Hoonbot works.

**Key sections:**
- System diagrams and data flow
- Component descriptions
- File organization
- Configuration reference
- Startup sequence
- Troubleshooting guide

**Read this to understand how everything connects.**

### 🧠 [data/memory.md](data/memory.md) — Persistent Memory
Single memory file where information persists across conversations.

**Features:**
- Plain Markdown format
- Automatically injected into every LLM prompt
- Absolute path provided to LLM
- Can be edited manually or via file_writer tool

**The LLM uses file_reader to read and file_writer to update.**

## How It Works

### 1. User sends message in Messenger
```
User → Messenger (port 3000) → Hoonbot (port 3939)
```

### 2. Hoonbot processes the message
```
1. Load PROMPT.md (system prompt)
2. Load data/memory.md (persistent memory)
3. Get absolute path to memory file
4. Call LLM_API_fast with agent_type: auto
```

### 3. LLM uses tools to accomplish the task
```
Available tools:
- file_reader      : Read memory and other files
- file_writer      : Update memory and save files
- file_navigator   : Explore directories
- websearch        : Search the web
- python_coder     : Run Python code
- rag              : Query documents
- shell_exec       : Run shell commands
```

### 4. LLM returns response to Hoonbot
```
LLM response → Hoonbot → Messenger (port 3000) → User
```

## File Structure

```
Hoonbot/
├── README.md                ← Start here
├── ARCHITECTURE.md          ← Technical design
├── PROMPT.md               ← System prompt (unified)
├── SOUL.md                 ← Personality reference (included in PROMPT.md)
│
├── hoonbot.py              # Main entry point
├── config.py               # Configuration
├── setup.py                # Setup script (automatic credential management)
├── test_llm.py             # Test script
├── reset.py                # Memory reset utility
│
├── handlers/
│   ├── webhook.py          # Message processing
│   └── health.py           # Health check endpoint
│
├── core/
│   ├── messenger.py        # Messenger API client
│   └── retry.py            # Retry decorator
│
└── data/
    ├── memory.md           # Persistent memory (auto-injected)
    ├── .llm_key            # LLM API token (created by setup.py)
    ├── .llm_model          # LLM model name (created by setup.py)
    └── .apikey             # Messenger API key (auto-created)
```

## Configuration

All settings via environment variables in `config.py`:

```bash
# Server
HOONBOT_PORT=3939
HOONBOT_HOST=0.0.0.0

# Messenger
MESSENGER_PORT=3000
HOONBOT_BOT_NAME=Hoonbot
HOONBOT_HOME_ROOM_ID=1

# LLM_API_fast (loaded from files, not env vars)
# Credentials: setup.py saves to data/.llm_key and data/.llm_model
LLM_API_PORT=10007
LLM_API_URL=http://localhost:10007  # Can override with env var

# Webhooks (optional)
HOONBOT_WEBHOOK_SECRET=optional_secret_for_incoming_webhooks
```

## Memory System

### How It Works

1. `data/memory.md` is a plain Markdown file
2. On every LLM call, memory content is injected into the system prompt
3. LLM's absolute path to the file is also provided
4. LLM can read the file with `file_reader` tool
5. LLM can update the file with `file_writer` tool

### What to Save

- User preferences and personal information
- Important facts and decisions
- Project status
- Anything the user says to remember

### Example Update Flow

```
User: "Remember: I'm working on Project X"
     ↓
LLM sees this in conversation
     ↓
LLM uses file_reader to read current memory.md
     ↓
LLM adds "Project X" entry to memory
     ↓
LLM uses file_writer to save updated memory.md
     ↓
Next message includes updated memory
```

### Manual Editing

Edit `data/memory.md` directly in any text editor:
```markdown
# Hoonbot Memory

## User
- Name: Huni
- Language: Korean
- Preferences: [list preferences]

## Projects
- [Project info]

## Notes
- [Important facts]
```

## Tool System

Everything works through LLM_API_fast tools. The LLM automatically decides which tool to use:

- **Need to save information?** → Use file_writer
- **Need to check saved info?** → Use file_reader
- **Need to search the web?** → Use websearch
- **Need to analyze data?** → Use python_coder
- **Need to run a command?** → Use shell_exec

**No custom commands or parsing—just pure tool usage.**

## Webhook Events

External services can trigger Hoonbot by posting to:
```
POST http://localhost:3939/webhook/incoming/<source>
X-Webhook-Secret: optional_secret (if configured)
Content-Type: application/json

{
  "message": "Something happened"
}
```

Example: GitHub webhook
```
POST http://localhost:3939/webhook/incoming/github
Content-Type: application/json

{
  "action": "opened",
  "pull_request": {
    "title": "Fix bug in auth",
    "url": "..."
  }
}
```

Hoonbot receives: `[Webhook from github] PR opened: Fix bug in auth...`

## Testing

### Test LLM Connection

```bash
python test_llm.py
```

Tests if:
- LLM_API_fast is reachable
- Credentials are properly configured
- LLM responds to messages
- Memory file is accessible

### Reset Memory

```bash
# View current memory
python reset.py --view-memory

# Clear memory (keeps file, makes empty)
python reset.py --memory

# Reset everything (memory, APIkey, etc)
python reset.py --all
```

## Architecture Overview

```
┌─────────────────────────────────────────┐
│  Huni Messenger (TypeScript/Electron)   │
│  Chat UI on port 3000                   │
└──────────────┬──────────────────────────┘
               │ HTTP: POST /webhook
               │
┌──────────────▼──────────────────────────┐
│  Hoonbot (Python/FastAPI)               │
│  Main entry: hoonbot.py                 │
│  Processing: handlers/webhook.py        │
│  Port: 3939                             │
│                                         │
│  1. Receive message from Messenger      │
│  2. Load PROMPT.md + memory.md          │
│  3. Get absolute memory path            │
│  4. Call LLM_API_fast                   │
│  5. LLM uses tools automatically        │
│  6. Send reply back to Messenger        │
└──────────────┬──────────────────────────┘
               │ HTTP: POST /v1/chat/completions
               │
┌──────────────▼──────────────────────────┐
│  LLM_API_fast (Python/FastAPI)          │
│  Agent System on port 10007             │
│                                         │
│  Tools Available:                       │
│  • file_reader / file_writer            │
│  • file_navigator                       │
│  • websearch                            │
│  • python_coder                         │
│  • rag                                  │
│  • shell_exec                           │
└─────────────────────────────────────────┘
```

## Troubleshooting

### Setup fails: "Cannot connect to LLM_API_fast"

Make sure LLM_API_fast is running:
```bash
ps aux | grep run_backend
```

Check the port matches in setup.py (default: http://localhost:10007)

### "LLM_API_KEY is not configured"

Run setup.py to create credentials:
```bash
python setup.py
```

Check that files were created:
```bash
ls -la data/.llm_key data/.llm_model
```

### Memory not updating

The LLM might not be using the file_writer tool:

1. Check PROMPT.md has clear memory update instructions
2. Run `python test_llm.py` to test LLM functionality
3. Check LLM_API_fast logs for tool execution errors
4. Try manually editing `data/memory.md` to verify file is writable

### Bot not responding

General troubleshooting:

1. Check all services are running:
   ```bash
   ps aux | grep -E "(run_backend|npm|hoonbot)"
   ```

2. Check logs:
   ```bash
   tail -f logs/hoonbot.log
   ```

3. Test with simple message in Messenger

4. Verify configuration in `config.py`

## Development

### Add New Capability

Since everything uses LLM_API_fast tools, new capabilities are added by:

1. Update PROMPT.md with new instructions/guidelines
2. LLM automatically uses appropriate tools
3. No code changes needed

Example: To add CSV analysis
- Just mention in PROMPT.md that LLM can use python_coder for CSV files
- LLM will automatically use that tool when needed

### Modify Memory Format

Edit `data/memory.md` directly or update PROMPT.md with new guidance. No code changes needed.

### Add New Webhook Source

No code changes—just POST to `/webhook/incoming/<source>` and Hoonbot handles it.

## Performance Tips

1. **Keep memory.md reasonably sized** — It's included in every prompt
2. **Use file_navigator** — Don't guess file paths, use the tool to explore
3. **Set reasonable timeouts** — Especially for long-running tasks
4. **Monitor token usage** — Memory size affects API costs

## Security

- **LLM API Key:** Stored in `data/.llm_key`, never commit to git
- **Messenger API Key:** Stored in `data/.apikey`, keep secret
- **Webhook Secret:** Use for external integrations to verify authenticity
- **File Access:** LLM has access to files via tools—be careful with sensitive paths
- **Code Execution:** python_coder runs arbitrary code—validate user requests first

## Support

Check these files in order:

1. **ARCHITECTURE.md** — How does the system work?
2. **PROMPT.md** — What are the LLM guidelines?
3. **config.py** — Is it configured correctly?
4. **test_llm.py** — Can we reach the LLM?
5. **Logs** — What errors are in logs/?

## License & Credits

Hoonbot — Simplified AI Assistant for Huni

---

**Last Updated:** 2026-02-26
**Version:** 1.0 (Simplified Tool-Driven Architecture)
