# Summarize Room

Read recent messages from a Messenger room and produce a concise summary.

**Trigger phrases:** summarize room, catch me up, what did I miss, summary of chat, recap the conversation, what happened in

---

## API

- **Port:** `config.MESSENGER_URL` (10006)
- **Auth:** `x-api-key: config.MESSENGER_API_KEY` (from `data/.apikey`)
- `GET {MESSENGER_URL}/api/messages/{roomId}?limit={N}&before={messageId}` — fetch messages
- `GET {MESSENGER_URL}/api/rooms?userId=<bot_id>` — room lookup

---

## Workflow

### 1. Read config

```python
import config
base_url = config.MESSENGER_URL
api_key = config.MESSENGER_API_KEY
```

### 2. Determine scope

Extract from user's request:
- **room** — which room to summarize (default: current room)
- **count** — how many messages to include (default: 50, max: 100)
- **time range** — "last hour", "today", "since yesterday" (optional filter)

If a room name is given, resolve to ID via room lookup.

### 3. Fetch messages

```
GET {MESSENGER_URL}/api/messages/{roomId}?limit={count}
x-api-key: {api_key}
```

Messages are returned newest-first. Reverse them to chronological order.

For time-range requests, fetch up to 100 messages and filter by `createdAt`.

If fewer than 2 non-bot messages are found, report "Not enough messages to summarize."

### 4. Build the message log

Format the fetched messages into a readable transcript:

```
[2026-03-10 14:30] Alice: Hey, did you finish the report?
[2026-03-10 14:31] Bob: Almost done, sending it in 5 min
[2026-03-10 14:35] Bob: [file] report_final.pdf
[2026-03-10 14:36] Alice: Thanks!
```

Skip deleted messages (content = "[deleted]" or similar).
For file/image messages, note: `[file] filename` or `[image] filename`.

### 5. Summarize

Using the formatted transcript, produce a summary that covers:

1. **Key topics** discussed
2. **Decisions made** or action items agreed upon
3. **Files shared** (if any)
4. **Questions left unanswered** (if any)
5. **Participants** and rough contribution

Keep the summary concise — aim for 3–8 bullet points depending on message volume.

---

## Response format

```
Summary of {roomName} — last {count} messages ({time_range}):

Participants: {list of names}

• {key point 1}
• {key point 2}
• {decision or action item}
• {file shared: filename}
• {unanswered question, if any}
```

If the messages are trivial or very short:
```
Summary of {roomName} — last {count} messages:

Brief exchange between {names}. {one-sentence summary}.
```

---

## Notes

- Do NOT include the summary generation process in the response — just present the result
- Exclude bot's own messages from the summary content (the user wants to know what humans said)
- If the room has only bot messages, say so: "This room only contains bot messages in the last {count} messages."
- For very long transcripts (>100 messages), note that only the most recent batch was summarized
