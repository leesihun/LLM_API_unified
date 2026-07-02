# LLM_API_fast — Implementation Plan

> **Status: IMPLEMENTED (2026-06-28).** All four workstreams below are coded and
> syntax/import-validated. One operator action is required to fully enable
> proactive compaction: set **`MODEL_CONTEXT_WINDOW`** (env or `cluster_config.py`)
> to your served model's max context length (vLLM `--max-model-len`). Left at the
> default `0`, proactive compaction stays off and only the existing reactive
> autocompact runs — nothing regresses. Vision defaults to ON
> (`MODEL_SUPPORTS_VISION=true`); set it false for a text-only model.
> See "Implementation status" at the end for the file-by-file summary.

Scope after review. Four workstreams, in priority order:

1. **Relay delegated cluster results back to Messenger** — fixes a currently-broken feature.
2. **Streamlined agentic flow** — token-aware budgeting, duplicate hard-stop, structured planning. *(The research-depth focus.)*
3. **Hoonbot filesystem awareness** — a persistent, code-level hierarchy snapshot for self-reference.
4. **Vision passthrough** — let VL models actually see attached images.

**Explicitly out of scope** (decided, not to be re-proposed):
`web_fetch` — server is airgapped, no outbound URLs. Semantic long-term memory — already covered by
Hoonbot's `memory.md`. Cron tool — already doable via OS scheduler + shell script, or the heartbeat
loop. Dedicated git tool. Broader cluster scaling (SQLite queue, long-poll, load-aware routing,
remote sub-agents, fast lease recovery, slave streaming) — not required for current deployment.

Effort: **S** <½ day · **M** 1–3 days · **L** >3 days.

---

## 1. Relay delegated cluster results back to Messenger · M · critical

### Problem (grounded)
The `@node` delegation path is half-wired. `try_submit_from_message`
([hoonbot/core/cluster_client.py](hoonbot/core/cluster_client.py)) posts *"Queued cluster task X"*
to the room and returns. The slave runs it and writes `result` into the master's `cluster_store`
([cluster_worker.py:84-90](hoonbot/core/cluster_worker.py#L84-L90) → `/tasks/{id}/complete`), but
**no master-side loop ever reads it back**: the master lifespan starts only `_catch_up` and
`run_heartbeat_loop` ([hoonbot/hoonbot.py:291-292](hoonbot/hoonbot.py#L291-L292)). The answer lands
in the store, already addressed — `room_id` is saved in `task.metadata`
([cluster_client.py:75,87](hoonbot/core/cluster_client.py#L75)) — and is never delivered. Today the
whole delegation feature produces no user-visible output.

### Design
Add a master-only background watcher started from the master branch of the lifespan
([hoonbot.py:291](hoonbot/hoonbot.py#L291), alongside catch-up/heartbeat):

- Poll `GET /api/cluster/tasks?include_completed=true` (or read the per-task event log via
  `cluster_store.load_events`) on a short interval.
- Track a set of already-relayed `task_id`s (persist to `hoonbot/data/relayed_tasks.json` so a master
  restart doesn't double-post or drop in-flight results).
- On a newly `completed`/`failed` task that carries `metadata.room_id` and `source == "messenger"`,
  post to that room via `messenger.send_message`: the `result` on success, or a short `error` line on
  failure. Reference the originating directive (`metadata.directive`) so the user knows which `@node`
  call it answers.
- Handle `@all-slaves` fan-out: the broadcast creates N tasks
  ([cluster_client.py:61-81](hoonbot/core/cluster_client.py#L61-L81)); relay each as it finishes,
  prefixed with the node name.

### Files
- `hoonbot/core/cluster_relay.py` *(new)* — the watcher loop.
- `hoonbot/hoonbot.py` — start it on the master branch of `lifespan`.
- `hoonbot/core/cluster_client.py` — ensure `room_id`/`directive` always land in `metadata` (already
  do; confirm for the tag/role/broadcast branches).

### Verification
Start a master + one slave locally, send `@<slave> say hello` in a room, confirm the slave's reply
posts back to the same room. Kill the slave mid-task and confirm a failure line is relayed after lease
expiry. `cd hoonbot ; python scripts\test_llm.py` for connectivity.

---

## 2. Streamlined agentic flow

The loop is already strong: segmented-parallel tools, mid-stream early start, KV-stable prefix,
anti-spiral reminders. The gains below are about **measuring instead of guessing** and **acting on
reflection instead of only describing it.** None of them may mutate the source `msgs` list — the
KV-cache prefix must stay byte-stable (see `compaction.py:33-56`).

### 2.1 Token-aware context budgeting · M · highest-value
**Problem.** Every budget decision is a character-count guess — `AGENT_OLD_TOOL_RESULT_SUMMARY_MAX_CHARS`,
`per_msg_cap`, the `TOOL_RESULT_BUDGET` table — and autocompact is **reactive**: it waits for vLLM to
400 with "maximum context length…" ([compaction.py:228-244](llm-api/backend/agent/compaction.py#L228-L244)),
then summarizes and **re-sends the entire request** ([compaction.py:346-394](llm-api/backend/agent/compaction.py#L346-L394)).
That's a wasted full round-trip on the hot path, and char≈token is wrong for code and CJK. The cause:
`chat_stream` never sets `stream_options` and never reads the `usage` block, so real token counts are
thrown away ([llm_backend.py:137-183, 232-348](llm-api/backend/core/llm_backend.py#L137-L183)).

**Design.**
- Set `payload["stream_options"] = {"include_usage": True}` in `_build_payload`; capture the final
  `usage` chunk (`prompt_tokens`, `completion_tokens`) and surface it from `chat_stream` (e.g. a final
  `UsageEvent`, or stash on the backend for the loop to read).
- Maintain a running `last_prompt_tokens` on the loop. **Before** sending, if projected prompt tokens
  exceed a fraction of the model's context window (new `MODEL_CONTEXT_WINDOW` /
  `AGENT_COMPACT_AT_TOKEN_FRACTION ≈ 0.75` config), run `_summarize_and_compact_msgs` *proactively*.
  The existing reactive catch stays only as a safety net.
- Log real tokens next to the char counts so the `TOOL_RESULT_BUDGET` table can finally be tuned
  against ground truth.

**Why first among the flow items.** It removes a latency cliff and makes every other budget knob
honest. Everything else here is cheaper once tokens are observable.

### 2.2 Duplicate hard-stop + read memoization · S
**Problem.** `_tool_cache` ([tool_dispatch.py:212](llm-api/backend/agent/tool_dispatch.py#L212)) caches
tool *instances*, not *results*. Nothing stops the model from re-`file_reader`/`grep`-ing identical
args; anti-spiral only *nudges* after the third try and obeys a cooldown
([loop.py:189-218](llm-api/backend/agent/loop.py#L189-L218)).

**Design.** Add a per-run result cache keyed by `_tool_signature(name, args)` (helper already exists,
[loop.py:169-180](llm-api/backend/agent/loop.py#L169-L180)) for read-only/concurrency-safe tools
(`TOOL_METADATA` flags). On a byte-identical repeat, **short-circuit**: return the prior result plus a
firm `<system-reminder>` ("you already ran this — here is the result; do something different"). Turns
reflection into enforcement and reclaims wasted iterations. Invalidate read caches after any mutating
barrier (`shell_exec`/`file_edit`/`apply_patch`/`file_writer`) so stale reads can't survive a write.

### 2.3 Structured plan artifact + plan-aware reminders · M
**Problem.** The iteration-0 nudge asks for a plan but captures nothing
([loop.py:256-270](llm-api/backend/agent/loop.py#L256-L270)); the milestone reminder just re-echoes the
raw user request ([loop.py:234-254](llm-api/backend/agent/loop.py#L234-L254)). `todo_write` exists but
is optional and disconnected.

**Design.** On the first iteration of a multi-step request, capture the model's stated plan into
`_session_todos` (already injected via `_format_todos`,
[prompt_assembly.py:339-348](llm-api/backend/agent/prompt_assembly.py#L339-L348)). Then the milestone /
tail-goal overlays check progress *against the plan* ("steps 2,3 still open") instead of re-pasting the
prompt. Gives the long-horizon reminders something concrete to anchor on and makes drift visible.

### 2.4 Structured autocompact via guided_json · M
**Problem.** Autocompact emits free-text and then **regex-greps** an `Active goal:` line back out of it
([compaction.py:316-322](llm-api/backend/agent/compaction.py#L316-L322)) — fragile and lossy.

**Design.** `guided_json` is already plumbed end-to-end
([llm_backend.py:179-182](llm-api/backend/core/llm_backend.py#L179-L182),
[loop.py:426-429](llm-api/backend/agent/loop.py#L426-L429)). Have the summarizer emit
`{active_goal, files_touched, decisions, open_questions, key_results[]}` and re-inject fields
deterministically. Reliable carry-forward across long runs; pairs with 2.3 (the plan is part of the
structured state).

### 2.5 Startup tool-call self-check · S
**Problem.** `loop.py:571-588` retries "without tools" when a chat template emits an end-of-turn token
right after a tool result — a silent workaround for a vLLM parser/flag mismatch
(`--enable-auto-tool-choice --tool-call-parser <family>`).

**Design.** On startup, ping `/v1/chat/completions` with one trivial tool and assert a structured
`tool_calls` delta arrives. Fail fast with a clear message ("vLLM not launched with a tool-call parser
matching <model>") instead of degrading every session at runtime.

### Flow sequencing
2.1 (token visibility) → 2.2 (dup hard-stop, immediate quality win) → 2.3 + 2.4 (planning/state, which
benefit from token accounting) → 2.5 (operational hardening).

---

## 3. Hoonbot filesystem awareness · M

### Idea (yours)
Give Hoonbot durable "spatial awareness" of its own deployment — what files/skills/configs exist, where
data lives, what changed — for future reference, maintained from the heartbeat rather than rediscovered
every turn.

### Design — persistent, code-level snapshot (no LLM cost)
- New `hoonbot/core/fs_snapshot.py`: a pure-Python walk of key roots (repo root depth-limited,
  `data/`, `skills/`, `prompts/`), excluding the usual noise (`.git`, `__pycache__`, `node_modules`,
  `.venv`, `data` blobs) — mirror the exclude set already used in
  [prompt_assembly.py:73](llm-api/backend/agent/prompt_assembly.py#L73). It writes a compact tree +
  recently-changed files to `hoonbot/data/filesystem_map.md`, and diffs against the previous snapshot
  to record **drift** (added / removed / modified — especially under `skills/`, `prompts/`, and the
  config files).
- Drive it from `run_heartbeat_loop` ([heartbeat.py:373-405](hoonbot/core/heartbeat.py#L373-L405)) every
  *K* ticks (or a slower sibling cadence), so it costs a directory walk, not an LLM call.
- Surface a one-line digest in ambient context — extend `build_per_turn_context`
  ([context.py:123-168](hoonbot/core/context.py#L123-L168)), which already reports data dir / memory
  size / skills — e.g. *"Filesystem: 412 files / 37 dirs; changed since last scan: skills/foo.md (new),
  config.py (modified)."* Add the map's absolute path to `_build_session_variables`
  ([context.py:171-190](hoonbot/core/context.py#L171-L190)) so the agent can `file_reader` the full map
  on demand.
- **Keep it out of `memory.md`.** `memory.md` is injected wholesale into every session
  ([context.py:84-86](hoonbot/core/context.py#L84-L86)); a full tree there would bloat the prefix every
  turn. Separate map file + short digest is the right split. Optionally let the heartbeat note *notable
  drift only* (e.g. a skill was added/removed) into `memory.md` as a one-liner.

### Why it's a good fit
It extends the ambient-awareness pattern Hoonbot already has, and gives the autonomous loop a way to
notice when it (or a deploy) changed its own skills/config — useful precisely because the bot can edit
its own `skills/` and `memory.md`.

### Files
`hoonbot/core/fs_snapshot.py` *(new)*, `hoonbot/core/heartbeat.py` (invoke every K ticks),
`hoonbot/core/context.py` (digest + path). `data/filesystem_map.md` and `relayed_tasks.json` are
runtime artifacts — never committed (`data/` is already gitignored).

---

## 4. Vision passthrough for attached images · M

### Problem
`_format_attached_files` injects image *metadata* only
([prompt_assembly.py:413-438](llm-api/backend/agent/prompt_assembly.py#L413-L438)); image bytes never
reach the model, so a VL model (GLM-4.x-V / Qwen-VL) is blind to attachments.

### Design
When the served model is vision-capable, pass attached images as OpenAI `image_url` content parts on
the user turn in `_build_payload` ([llm_backend.py:137-183](llm-api/backend/core/llm_backend.py#L137-L183))
instead of (or alongside) the text metadata block. Gate on a new `MODEL_SUPPORTS_VISION` flag in
`cluster_config.py` so text-only deployments are unaffected. Respect a size/count cap and downscale
large images before encoding.

### Verification
With a VL `VLLM_MODEL`, attach a screenshot in Messenger and ask the bot to describe it; confirm the
description reflects actual image content. Confirm text-only models are unchanged when the flag is off.

---

## Overall sequencing

1. **Workstream 1** (relay) — unblocks a broken feature; smallest blast radius.
2. **2.1 → 2.2** (token budgeting, then duplicate hard-stop) — biggest quality-per-effort in the loop.
3. **Workstream 3** (filesystem awareness) and **2.3/2.4** (planning/state) in parallel — independent.
4. **Workstream 4** (vision) and **2.5** (self-check) — contained, do when convenient.

## Verification commands (from CLAUDE.md)
```
python -m py_compile <file.py>                 # syntax-check Python edits
cd messenger ; npm.cmd run typecheck           # TS check
cd hoonbot   ; python scripts\test_llm.py      # LLM API connectivity
curl http://127.0.0.1:10000/v1/models          # confirm VLLM_MODEL name
```

---

## Implementation status (2026-06-28)

What actually shipped, and where. Note 2.3/2.4/2.5 were left as documented
follow-ups; the implemented set is 1, 2.1, 2.2, 3, and 4.

**1 — Cluster result relay**
- `hoonbot/core/cluster_relay.py` *(new)* — master watcher: polls terminal tasks, fetches the
  full (un-truncated) result, posts it to `metadata.room_id`, persists relayed IDs in
  `data/relayed_tasks.json`, seeds existing-terminal on first run to avoid backlog spam.
- `hoonbot/hoonbot.py` — starts/stops `run_cluster_relay_loop(messenger.send_message)` on the master.

**2.1 — Token-aware budgeting**
- `llm_backend.py` — new `UsageEvent`; `stream_options.include_usage` in the payload; captures the
  trailing usage chunk and emits `UsageEvent`.
- `llm_interceptor.py` — passes `UsageEvent` through and logs REAL tokens when present.
- `compaction.py` — captures usage into `_last_prompt_tokens`; `_should_proactively_compact()`;
  proactive summarize-before-send in `_stream_with_autocompact` (reactive path retained as safety net).
- `loop.py` — initializes `_last_prompt_tokens`. `config.py` — `MODEL_CONTEXT_WINDOW` (default 0 =
  off), `AGENT_COMPACT_AT_TOKEN_FRACTION` (0.75).

**2.2 — Duplicate-call hard-stop + read memoization**
- `tool_dispatch.py` — per-run cache for read-only + concurrency-safe tools (`_read_cache_key`);
  identical repeats short-circuit with a `cached`/`cache_note` marker; cache cleared by any
  non-read-only (mutating) tool so reads can't go stale.
- `loop.py` — initializes `_read_result_cache`.

**3 — Hoonbot filesystem awareness**
- `hoonbot/core/fs_snapshot.py` *(new)* — pure-Python bounded walk (depth/excludes/file-cap); writes
  `data/filesystem_map.md` + `data/filesystem_snapshot.json`; computes added/removed/modified drift;
  returns a one-line digest. Smoke-tested: produced a real digest.
- `heartbeat.py` — runs `run_snapshot()` every `HEARTBEAT_FS_SNAPSHOT_EVERY_TICKS` (default 1) ticks,
  off the event loop via `asyncio.to_thread`, regardless of active hours.
- `context.py` — digest line in `build_per_turn_context`; map path added to Session Variables.

**4 — Vision gate**
- `config.py` — `MODEL_SUPPORTS_VISION` (default true). `chat.py` — embeds `image_url` parts only when
  enabled; otherwise surfaces images as metadata so a text-only model isn't sent parts it can't decode.
  (Core vision embedding already existed; this only adds the gate.)

**Validation run:** all 12 changed/new files `py_compile` clean; both services import-load; new
`AgentLoop` exposes the new state and `_read_cache_key`/`_should_proactively_compact` behave correctly.

**Not yet wired (operator):** set `MODEL_CONTEXT_WINDOW` to enable proactive compaction. Live
end-to-end checks still worth running: a real `@slave` round-trip (relay), and a vision attachment on a
VL model.
