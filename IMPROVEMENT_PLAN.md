# LLM_API_fast — Improvement Plan

A grounded, prioritized roadmap across three axes the user asked for:

1. **More functionality**
2. **Better algorithm / streamlined agentic flow**
3. **Master–Slave node connectivity**

Every proposal cites the real code it touches. Items are tagged with effort
(**S**mall ≈ <½ day, **M**edium ≈ 1–3 days, **L**arge ≈ >3 days) and impact
(★–★★★). Read the "Top wins" section first if you only have five minutes.

---

## 0. What the codebase does well today (so we don't regress it)

- **Segmented-parallel tool execution** in `llm-api/backend/agent/loop.py:631-677` — consecutive
  concurrency-safe calls run via `asyncio.gather`, mutators are serial barriers. This is the
  right model; keep it.
- **Mid-stream early start** of read-only tools (`loop.py:550-569`, `llm_backend.py:262-329`) —
  tool dispatch begins before the model finishes streaming. Genuinely good latency work.
- **KV-cache discipline** — the static system prompt is byte-stable (`_cache.py`,
  `prompt_assembly.py:161-163`) and microcompaction never mutates `msgs`, only a copy
  (`compaction.py:33-56`). Don't break this; several proposals below are explicitly designed
  to preserve it.
- **Anti-spiral reflection** (`loop.py:189-270`) — repeat-call / consecutive-failure / goal-reminder
  overlays. Solid foundation to build hard-stops on (see §2.3).

---

## Top wins (do these first)

| # | Change | Axis | Effort | Impact |
|---|--------|------|--------|--------|
| 1 | **Relay delegated cluster task results back to Messenger** (master completion watcher) | 3 | M | ★★★ |
| 2 | **Token-aware context budgeting** (read vLLM `usage`, compact *proactively*) | 2 | M | ★★★ |
| 3 | **Long-poll the lease endpoint** + drop the file-glob queue for an indexed/SQLite store | 3 | M | ★★★ |
| 4 | **Remote sub-agents**: let the `agent` tool fan out to idle slave GPUs via the task queue | 1+3 | L | ★★★ |
| 5 | **Hard-stop exact-duplicate tool calls** (return cached result instead of re-running) | 2 | S | ★★ |
| 6 | **`web_fetch` tool** (read a specific URL — today the agent can only Tavily-*search*) | 1 | S | ★★ |

---

## 1. More functionality

### 1.1 `web_fetch` tool — read a named URL  ·  S · ★★
**Gap.** The only web tool is `web_search` (Tavily search) — `tool_dispatch.py:214-222`. The agent
can find a URL but cannot read one it already has. The Messenger side already polls URLs
(`server/src/services/web-poller.ts`), so the capability exists in the repo but not for the agent.

**Proposal.** Add `tools/web_fetch/` returning cleaned main-text + metadata (title, status, final
URL after redirects), with an HTML→markdown extractor. Mark it `is_read_only / is_concurrency_safe`
in `schemas.py:TOOL_METADATA` so it joins the parallel read group for free. Cap body size and spill
oversize results to `data/tool_results/` like every other tool.

### 1.2 Semantic long-term memory  ·  M · ★★★
**Gap.** `memo` is flat key-value (`tools/memo/`); `recall` only retrieves *this session's* spilled
tool results. There is no cross-session semantic memory even though the full RAG embedding stack
(bge-m3 + reranker, `cluster_config.py:83-85`) is already loaded.

**Proposal.** A `remember` / `recall_semantic` pair backed by a per-user RAG collection. On write,
embed and store; on recall, vector-search. Auto-capture durable facts at end of a session (a
distilled "what did we learn" pass). This is the single biggest agent-quality lever you have that
reuses infrastructure you already pay for.

### 1.3 User-schedulable jobs (cron tool)  ·  M · ★★
**Gap.** `hoonbot` has a fixed heartbeat (`core/heartbeat.py`) but a user cannot say "every weekday
at 9am, summarize room X" or "remind me in 2h." There is no per-user scheduler.

**Proposal.** A `schedule` tool + a small persistent job table (reuse `backend/core/job_store.py`
patterns). The heartbeat loop already wakes on an interval — add a due-job sweep to it. Output posts
to the requesting room.

### 1.4 First-class git tool  ·  S · ★★
**Gap.** Git happens through `shell_exec`, so the model parses porcelain by hand and there's no
guard rail. `prompt_assembly.py:27-64` already shells out for a git context block.

**Proposal.** `git` tool with structured ops (`status`, `diff`, `log`, `branch`, `commit`,
`create_pr` via `gh`). Returns parsed JSON. Reduces token spend and tool-spam on the most common
workflow, and lets you enforce "branch before commit on default branch" centrally.

### 1.5 Vision passthrough for attached images  ·  M · ★★
**Gap.** `prompt_assembly.py:413-438` injects image *metadata* only; image bytes never reach the
model. GLM-4.x-V / Qwen-VL can consume images directly.

**Proposal.** When `VLLM_MODEL` is a VL model, pass attached images as OpenAI `image_url` content
parts in the user turn (`llm_backend._build_payload`). Gate behind a `MODEL_SUPPORTS_VISION` config
flag so text-only deployments are unaffected.

### 1.6 Cluster task board in Messenger  ·  M · ★★
**Gap.** `/api/cluster/status` and `/tasks` exist (`routes/cluster.py`) but nothing visualizes them.
Operators can't see node health, queue depth, or in-flight tasks.

**Proposal.** A read-only React panel in `messenger/client` polling `/api/cluster/status` — node
health, GPU/queue metrics (once §3.4 lands), live task list with per-task event stream
(`cluster_store.load_events`). Pairs naturally with win #1.

---

## 2. Better algorithm / streamlined agentic flow

### 2.1 Token-aware budgeting (replace char heuristics)  ·  M · ★★★
**Problem.** Every compaction decision is a character-count guess
(`AGENT_OLD_TOOL_RESULT_SUMMARY_MAX_CHARS`, `per_msg_cap`, etc. in `compaction.py`) and autocompact
is **reactive**: it waits for vLLM to 400 with "maximum context length…"
(`compaction.py:228-244, 346-394`), then summarizes and *re-sends the whole request*. That's a
wasted round-trip on the critical path, and char≈token is wrong for code/CJK.

**Proposal.**
- Read the `usage` block from the vLLM stream — **`chat_stream` currently discards it entirely**
  (`llm_backend.py:232-348` never looks at `chunk["usage"]`; vLLM emits it with
  `stream_options={"include_usage": true}`). Plumb real `prompt_tokens` back to the loop.
- Drive compaction off a **token budget** (e.g. compact when projected prompt tokens cross 75% of
  the model's context window) *before* sending, eliminating the 400-retry path for the common case.
- Keep the reactive path as a safety net only.

This is the highest-leverage algorithm change: it removes a latency cliff and makes every other
budget knob honest.

### 2.2 Memoize idempotent reads within a run  ·  S · ★★
**Problem.** `_tool_cache` (`tool_dispatch.py:212`) caches tool *instances*, not *results*. Nothing
stops the model re-`file_reader`-ing or re-`grep`-ing the same args three times — the anti-spiral
logic only *nudges* after the fact (`loop.py:189-218`).

**Proposal.** A per-run result cache keyed by `_tool_signature(name, args)` (the helper already
exists, `loop.py:169-180`) for read-only/concurrency-safe tools. On a hit, return the cached result
instantly with a `(cached)` marker. Cheap, and it directly attacks the spiral instead of describing it.

### 2.3 Hard-stop exact-duplicate calls  ·  S · ★★
**Problem.** `_detect_repeat_call` only emits a reminder *after* the third identical call and obeys a
cooldown (`loop.py:189-218`) — the model can keep burning iterations.

**Proposal.** When a call is byte-identical to one already made this run, short-circuit: return the
prior result plus a firm `<system-reminder>` ("you already ran this; here is the result; do something
different"). Combine with 2.2 — same key space.

### 2.4 Structured autocompact state (guided_json)  ·  M · ★★
**Problem.** Autocompact produces a free-text summary and then *regex-greps* an `Active goal:` line
back out of it (`compaction.py:316-322`). Fragile and lossy.

**Proposal.** The backend already supports `guided_json` end-to-end
(`llm_backend.py:179-182`, `loop.py:426-429`). Use it to make the summarizer emit
`{active_goal, files_touched, decisions, open_questions, key_results[]}`. Re-inject fields
deterministically instead of regexing prose. More reliable carry-forward across long runs.

### 2.5 Promote a real plan artifact  ·  M · ★★
**Problem.** The plan-first nudge (`loop.py:256-270`) only *asks* for a plan; nothing captures it.
`todo_write` exists but is optional and unrelated.

**Proposal.** On iteration 0 of a multi-step request, capture the model's plan into `_session_todos`
automatically and pin it (already injected via `_format_todos`, `prompt_assembly.py:339-348`). Gives
the milestone/goal reminders something concrete to check against instead of re-echoing the raw
request.

### 2.6 Fix the empty-response band-aid  ·  S · ★
**Problem.** `loop.py:571-588` retries "without tools" when a chat template emits an end-of-turn
token right after a tool result. It's a workaround for a parser/template mismatch.

**Proposal.** Document the required vLLM launch flags per model family (already noted in CLAUDE.md:
`--enable-auto-tool-choice --tool-call-parser`) and add a startup self-check that pings
`/v1/chat/completions` with a trivial tool and asserts a structured `tool_calls` delta arrives —
fail fast with a clear message instead of silently degrading every session.

---

## 3. Master–Slave connectivity

This is the weakest area and has the highest ceiling.

### 3.1 Relay delegated results back to Messenger  ·  M · ★★★  **(critical)**
**Bug-level gap.** `try_submit_from_message` (`hoonbot/core/cluster_client.py`) posts *"Queued
cluster task X"* to the room and stops. The slave executes it (`cluster_worker._execute_task`) and
writes the result into the master's `cluster_store`, but **no master-side loop ever reads it back**:
the master lifespan starts only `_catch_up` and `run_heartbeat_loop` (`hoonbot.py:291-292`) — there
is no completion watcher. The `room_id` is already stored in `task.metadata`
(`cluster_client.py:75, 87`), so the answer is sitting in the store, addressed, and never delivered.

**Proposal.** Add a master background task that watches for `completed`/`failed` tasks (via the event
log `cluster_store.load_events` or a status poll) and posts `task.result` to `metadata.room_id`.
Until this lands, the entire `@node` delegation feature produces no user-visible output.

### 3.2 Replace the file-glob task queue  ·  M · ★★★
**Problem.** `cluster_store.lease_task` (`cluster_store.py:136-170`) **globs every `*.json`, sorts by
mtime, and takes a `FileLock` per file on every poll, from every slave, every 3s**
(`CLUSTER_SLAVE_POLL_INTERVAL_SECONDS=3`). `nodes.json` is fully rewritten on every heartbeat
(`_write_nodes_unlocked`, `cluster_store.py:245-246`). This is O(tasks × slaves / interval) disk +
lock contention — fine for 2 nodes, a problem at 10.

**Proposal.** Move the registry/queue to **SQLite** (the repo already uses sql.js in Messenger and
`filelock`; a single `cluster.db` with `WAL` is a natural fit) or at minimum a single append-only
queue index file. Atomic `UPDATE … WHERE status='queued' … LIMIT 1` replaces the glob+lock scan.

### 3.3 Long-poll the lease (push, not 3s poll)  ·  M · ★★
**Problem.** Slaves busy-poll `/tasks/lease` every 3s (`cluster_worker.py:155-167`), adding up to 3s
latency per task and constant load even when idle.

**Proposal.** Make `/tasks/lease` a **long-poll**: hold the request open until a task matches or a
~25s timeout elapses, then return. One-line change on the slave (loop already retries), and the
master can wake waiters when `create_task` runs. Cuts dispatch latency to ~0 and idle load to near
zero.

### 3.4 Load-aware routing of *normal* traffic  ·  L · ★★★
**Problem.** Slave GPUs sit idle unless a user explicitly `@mentions` them. Heartbeats only carry
`disk_free_gb` (`cluster_worker.py:29-43`). The master handles all normal chat itself; the cluster
is a manual-dispatch curiosity, not an inference pool.

**Proposal.**
- Extend the heartbeat payload with **GPU mem free, vLLM running/waiting queue depth, in-flight
  request count** (vLLM exposes `/metrics`).
- Add a master-side router that can forward a normal `/v1/chat/completions` to the least-loaded
  healthy node (respecting KV-cache affinity — prefer the node that served the session before).
- This turns three boxes into one load-balanced endpoint and is the payoff that justifies 3.2/3.3.

### 3.5 Remote sub-agents (unifies §1 + §3)  ·  L · ★★★
**Opportunity.** `SubAgentTool.execute` (`tools/agent/tool.py`) spawns an **in-process** `AgentLoop`
on the master only. Meanwhile idle slaves can run full agent loops. The task queue already moves a
prompt to a slave and returns a text result — exactly a sub-agent's contract.

**Proposal.** Add `subagent_type="remote"` (or an auto policy) that submits the sub-agent prompt to
the cluster queue, leases it to a slave, streams its events into the task event log, and returns the
result. The master agent can then fan out N independent research/build tasks across the cluster in
parallel — real distributed agentic work, not just chat offload. Depends on 3.1 (result plumbing)
and benefits from 3.3 (low-latency lease).

### 3.6 Faster failure recovery  ·  S · ★★
**Problem.** A crashed slave's leased task is only re-queued after the 900s lease expires
(`CLUSTER_TASK_LEASE_SECONDS`, recovered lazily in `_recover_expired_lease`,
`cluster_store.py:299-309`). A 15-minute stall on a node reboot.

**Proposal.** Tie lease liveness to the heartbeat: if a node goes stale
(`CLUSTER_NODE_STALE_SECONDS=90`), immediately re-queue its in-flight leases. Add an explicit
`nack`/release endpoint the slave calls on its own task failure so it doesn't wait for expiry.

### 3.7 Stream slave progress  ·  M · ★
**Problem.** A slave runs the task as a single **non-streaming** chat (`stream:"false"`,
`cluster_worker.py:115-131`) — the master sees nothing until it's done, and the slave runs with no
tools/workspace context beyond `build_llm_context()`.

**Proposal.** Run the slave task through the streaming agent loop and forward `tool_status` / text
deltas into `cluster_store.append_event`. The task board (§1.6) and the relay (§3.1) then show live
progress. Optionally pass a `workspace_dir` so remote sub-agents can do real file work.

---

## Cross-cutting: security & ops (note, not the focus)

- **Default secrets ship in `cluster_config.py`**: `CLUSTER_SECRET="change-me-cluster-token"`,
  admin `administrator`, terminal token `leesihun`. Add a master-start assertion that refuses to bind
  a non-loopback IP while any secret is still default.
- **Cluster auth is a single static shared token** in a plaintext header (`routes/cluster.py:23-29`).
  For LAN this is acceptable (documented), but HMAC-signing request bodies with the shared secret
  would close replay/spoofing on the segment cheaply.
- **Master is a SPOF** for the task store. Out of scope now; worth a line in the architecture doc.

---

## Suggested sequencing

**Phase 1 — make the cluster actually deliver (1–2 weeks)**
3.1 result relay → 2.1 token budgeting → 3.3 long-poll → 2.3/2.2 dup hard-stop+memoize → 1.1 web_fetch.
*Outcome:* delegation produces visible answers, context never silently cliffs, agent stops spinning.

**Phase 2 — scale & capability (2–4 weeks)**
3.2 SQLite queue → 3.4 load-aware routing → 1.2 semantic memory → 1.6 task board → 3.6 fast recovery.
*Outcome:* the three boxes become one load-balanced, observable inference+agent pool.

**Phase 3 — distributed agency (3+ weeks)**
3.5 remote sub-agents → 3.7 slave streaming → 1.3 scheduler → 2.4/2.5 structured plan/summary → 1.5 vision.
*Outcome:* the master orchestrates parallel agent work across the cluster, with live progress.

---

## Quick verification commands referenced in CLAUDE.md
```
python -m py_compile <file.py>                 # syntax-check Python edits
cd messenger ; npm.cmd run typecheck           # TS check
cd hoonbot   ; python scripts\test_llm.py      # LLM API connectivity
curl http://127.0.0.1:10000/v1/models          # confirm VLLM_MODEL name
```
