# Tool-calling: research, what changed, and what's left

_Last updated: 2026-06-25_

This document captures (1) how the leading coding agents actually run tool calls,
(2) the change just made to this repo's agent loop to match them, and (3) the
suggestions that were **not** implemented yet, with concrete next steps.

---

## Part 1 — How Claude Code / Cursor / Codex actually do it

There are three independent techniques. Conflating them is why "fast tool calling"
feels mysterious. They stack.

### Layer 1 — Stream the tool call as it's decoded (mid-output dispatch)
The serving engine parses tool-call syntax *incrementally* and emits partial
deltas (`index`, then `function.name`, then `function.arguments` fragments — the
OpenAI streaming shape; Anthropic streams `input_json_delta` inside a `tool_use`
block). The client may begin executing a call **the moment its arguments JSON
closes**, while the model is still emitting the *next* call or trailing text.
This hides tool latency behind generation latency.

### Layer 2 — Parallel tool calls within one turn
When the model emits several calls in one assistant message
(OpenAI `parallel_tool_calls=true`; Anthropic returns multiple `tool_use`
blocks), the client runs the independent ones **concurrently** and returns all
results together before the next model call. Claude is explicitly trained — and
Claude Code's system prompt explicitly instructs — to batch independent calls:
> "If you intend to call multiple tools and there are no dependencies between the
> calls, make all of the independent calls in the same block."

### Layer 3 — Overlap execution with generation + fan-out
- **Speculative/eager execution:** start call N (Layer 1) and keep it running
  while the model generates call N+1. Codex/OpenAI clients do this; Cursor does
  speculative file reads and a fast "apply model" for edits.
- **Subagent fan-out:** Claude Code spawns multiple subagents (Task tool) that
  run in parallel/background, each in its own context. Parallel fan-out is a
  first-class pattern, not an edge case.

### The honest caveat for open models on vLLM
Much of the *naturalness* of GPT/Claude tool use is **trained behavior** — they
reliably emit multiple parallel calls and interleave reasoning with calls. Open
models (Qwen3, MiniMax M2, …) often emit one call per turn with chatty preamble
unless prompted. And on vLLM, tool calling only works when the server is launched
with the **correct tool-call parser** (see Part 3.A). Plumbing is necessary but
not sufficient; model + server config + prompt all matter.

### What this means as a concrete execution model
The robust, implementable denominator across all three tools:
> Within a turn, run **independent** calls concurrently and **mutations**
> serially (ordered); return all results together; preserve model order; and
> start each call as early as its arguments are known.

That is exactly the model this repo now implements (Part 2).

---

## Part 2 — What was implemented in this change

**File:** `llm-api/backend/agent/loop.py` — the result-resolution phase of
`_run_stream_body`.

**Before:** a positional gate (`deferred_seen`) parallelized read-only tools only
**up to the first mutating tool**; everything after it ran **fully serially** —
one `await` at a time. Two consequences:
- Reads issued *after* any write ran one-by-one even though they're independent.
- **Parallel `agent` fan-out was serial** (`agent` is `is_concurrency_safe` but
  not `is_read_only`, so it was never parallelized) — 3 subagents = 3x latency.

**After:** capability-based segmented execution, matching Claude Code / Cursor /
Codex:
- A maximal run of consecutive **`is_concurrency_safe`** calls (reads, web/RAG
  search, **subagent fan-out**) is gathered with `asyncio.gather` → parallel.
- Every non-concurrency-safe call (`shell_exec`, `file_edit`, `apply_patch`,
  `file_writer`, `code_exec`, `memo`, `todo_write`, `process_monitor`) is a
  **serial barrier** that runs alone.
- Ordering is preserved: each group is awaited before the loop advances, so all
  earlier tools finish before a barrier runs, and the barrier finishes before any
  later tool starts → read-after-write and write-after-write semantics hold.
- Mid-stream early start (Layer 1) is unchanged: read-only + concurrency-safe
  tools still launch as their args parse; resolution awaits those in place.

Net effect: independent reads and **parallel subagents** now run concurrently
regardless of position in the batch, while writes stay safely ordered.

The parallel predicate is the existing `TOOL_METADATA` `is_concurrency_safe`
flag (`llm-api/tools/schemas.py`).

---

## Part 3 — Not implemented yet (prioritized)

### A. ⚠️ CRITICAL — verify the vLLM tool-call parser (config, not code)
This is almost certainly the largest single cause of "unnatural" tool calling
after the llama.cpp→vLLM switch. vLLM only does proper tool calling when launched
with:

```
--enable-auto-tool-choice --tool-call-parser <parser>
```

`<parser>` **must match the served model family**:
- Qwen3 → `hermes`
- MiniMax M2 → its dedicated parser (`minimax` in recent vLLM)
- Llama 3.x → `llama3_json`; Mistral → `mistral`

Symptoms of a missing/wrong parser: tool calls arrive as raw `<tool_call>…`
text in `content`, or only as one blob at stream end, or with mangled args.

**Streaming dependency:** not all parsers stream tool-call deltas incrementally.
If the chosen parser does not, vLLM emits the whole batch at stream end and the
repo's Layer-1 mid-output dispatch **never fires** — the agent effectively waits
for full generation. Confirm the parser supports streaming, or accept that the
win is parallel execution only (Part 2), not mid-output overlap.

### B. Instrument mid-output dispatch
Add a debug counter in `_run_stream_body`: how many tool calls were started
mid-stream (`is_partial=True` ToolCallDeltaEvents) vs at stream end. If it's
always 0, the vLLM parser isn't streaming tool calls (see A). Cheap; turns a
guess into a fact. Log it in `_log_execution_summary`.

### C. Mid-stream early start for subagents
Today only `is_read_only AND is_concurrency_safe` tools start mid-stream;
`agent` (concurrency-safe, not read-only) waits for resolution. Subagents have no
file-ordering dependency, so they could start mid-stream too (when no barrier
preceded them), overlapping spawn latency with generation. Resolution-phase
parallelism (Part 2) already gives parallel subagents; this is an extra latency
shave. Lower priority, slightly higher risk.

### D. Finer-grained write parallelism (per-file barriers)
Current model serializes *all* mutating tools. Writes to **different** files are
actually independent and could parallelize (Cursor does this). Implementation:
track the path(s) each mutating tool touches and only serialize when paths
overlap (or when shared loop state — `_tracked_new_files`, `_agents_md_seen`,
post-edit-check — would race). Meaningful speedup for multi-file edits; needs
careful handling of the shared-state mutations. Medium effort, medium risk.

### E. Consolidate the overlapping file tools
`file_edit` vs `apply_patch` vs `file_writer` (and `shell_exec` vs
`grep`/`file_navigator`) overlap. Models burn turns choosing wrong, which reads
as clumsy. Polished agents keep a small, sharp tool set. Consider merging the
edit tools behind one tool with a mode, or sharpening descriptions further in
`llm-api/tools/schemas.py`.

### F. Stream partial tool results
For long-running tools (`shell_exec`, `code_exec`, `agent`), stream incremental
output to the UI instead of only start/complete `ToolStatusEvent`s. The hoonbot
typing-indicator and messenger already render tool status; this would surface
progress during long calls.

### G. System-prompt nudge for batching
Add a line to the agent system prompt (`llm-api/prompts/system.txt`) instructing
the model to batch independent tool calls into one turn — mirrors Claude Code.
Open models need the explicit nudge. Cheap, no code.

---

## Cluster + capability roadmap (from earlier research, not yet built)

### B1 — Result-relay loop (quick win)
Delegated cluster tasks store `metadata.room_id`
(`hoonbot/core/cluster_client.py`) but nothing reads it — the user gets "Queued
task X" and never the result. Add a master-side pending registry +
poll-completions coroutine started in `hoonbot/hoonbot.py`'s master lifespan;
GET `/api/cluster/tasks/{id}` (full body — `list_tasks` truncates `result` to
300 chars) and post back to the room on completion. Persist the registry to disk
(mirror `room_sessions.json`) for restart-safety. ~Half a day.

### B2 — Cancel / stop propagation
No master→slave channel today; a runaway task only expires after 900s.
- Phase 1: `POST /api/cluster/tasks/{id}/cancel` + store flips queued/leased →
  cancelled; slave checks status before executing. `@cancel <task_id>`.
- Phase 2: mid-flight abort by tripping the slave's local llm-api STOP signal for
  session `cluster_{task_id}` (reuse `scripts/stop_inference.py` /
  `check_stop()`).

### B3 — Cluster dashboard
`GET /api/cluster/status` already returns per-node health, model, `disk_free_gb`,
tags, task counts — but there's no UI. Add a Messenger proxy route + a
`ClusterPage.tsx` polling it (~3s), rendering node cards + task table + the
per-task event trail (`load_events`). Optionally extend slave `_node_payload`
with GPU/VRAM/queue-depth telemetry.

### C2 — Cross-cluster model registry + routing
Heartbeat already reports `model` per node. Phase 1: `@model:<name> task`
delegation, add `model` to `_matches_node` (`cluster_store.py`). Phase 2: master
proxies `/v1/chat/completions` to a node serving model X (needs session-sticky
routing for vLLM prefix-cache hits).

### C3 — MCP client + tool registry refactor
Let the agent consume external Model Context Protocol servers as tools. Forcing
function to replace the 240-line `if/elif` dispatch in
`backend/agent/tool_dispatch.py` with a registry: native tools register
statically, MCP tools register dynamically from discovered schemas. Do the
registry refactor first, MCP on top.

### Security (required once this is truly "control-all", not LAN)
- Per-node identity (mTLS or per-node keys) instead of one shared
  `x-cluster-token`; bind `complete`/`heartbeat` to `leased_by`.
- TLS on the control plane — which means **inverting** `validate_advertised_url`
  in `cluster_config.py` (it currently *forbids* the DNS/tunnel hostnames a real
  cert needs).
- Replace the JWT-secret default that is a pasted Tavily key
  (`llm-api/config.py`).

### Foundational
- **Tests:** zero automated tests for ~25K LOC. The compaction/overlay/parallel-
  resolution invariants are comment-protected only. Unit-test the pure functions
  first (`_compress_old_iterations`, overflow detection, the new segmented
  resolution).
- **Logging:** llm-api uses 171 `print()` and 0 loggers; hoonbot uses `logging`.
  Unify llm-api onto a module logger.
- **vLLM has no backup-host failover** anymore (`VllmBackend` has only
  `self.host`; `_select_available_host`'s return value is discarded). Re-add if
  failover matters.
