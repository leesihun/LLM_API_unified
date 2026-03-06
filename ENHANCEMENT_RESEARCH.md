# System Enhancement Research: LLM API Server

## Context

This document contains extensive research findings on ways to enhance the current LLM API server system, based on 2025-2026 agentic AI patterns, industry best practices, and academic research. The current system is a single-agent ReAct loop (`backend/agent.py`) backed by llama.cpp with native tool calling.

---

## 1. HYBRID PLANNING + REACTIVE EXECUTION

### Current State
The agent is a **pure ReAct loop**: reason -> act -> observe -> repeat. No upfront planning.

### Problems
- For complex multi-step tasks, the agent discovers the path incrementally, wasting iterations and tokens on dead ends
- No way to review/audit the agent's strategy before execution
- Early mistakes cascade through subsequent steps (error propagation)
- The LLM re-decides strategy from scratch each iteration

### Research Findings

**ReAct vs Plan-and-Execute** — Two dominant paradigms:
- **ReAct**: Interleaves reasoning with actions in iterative cycles. Exceptional adaptability but high risk of error propagation. Best for uncertain, exploratory tasks.
- **Plan-and-Execute**: Separates planning (upfront decomposition) from execution. Better control, auditability, lower error propagation. Best for well-defined workflows.

| Dimension | ReAct | Plan-and-Execute |
|-----------|-------|------------------|
| Adaptability | Exceptional; handles dynamic tasks | Limited; rigid when assumptions break |
| Efficiency | Potentially costly; step-by-step | Often cheaper; planning happens once |
| Control | Difficult to trace decisions | Strong; plans can be reviewed/audited |
| Error Propagation | High risk; early mistakes cascade | Mitigated; executors handle retries |
| Latency | Low initial; adapts as info emerges | Higher upfront; optimized thereafter |

**Hybrid approach (recommended)**: "The most powerful and trustworthy autonomous systems combine both paradigms, leveraging hybrid models that plan globally and act locally." Key patterns:
1. **High-Level Planning + Reactive Execution**: Planner outlines major stages, ReAct-style executors handle fine-grained adaptive execution within each stage
2. **Continual Planning**: Plan as living document updated incrementally during execution
3. **Dynamic Replanning**: Monitor execution for deviations, trigger partial/full replans when assumptions break
4. **Tool-Aware RAG**: Retrieve documentation on available tools during planning phase

**Deep Agent (Hierarchical Task DAGs)**: Models complex tasks using recursive DAGs that decompose sub-tasks across multiple layers. Planner creates next-level sub-task DAGs only when necessary, preventing premature over-planning.

**Implementation approach**:
```
User Input
    |
Phase 1: PLANNING (1 LLM call, lightweight)
    - Decompose task into numbered sub-steps
    - Identify which tools each step needs
    - Output structured JSON plan
    |
Phase 2: EXECUTION (existing ReAct loop, but guided)
    - Execute steps sequentially per plan
    - After each step: check if plan still valid
    - If tool fails or unexpected result -> LOCAL REPLAN (revise remaining steps)
    - If fundamentally off-track -> GLOBAL REPLAN (re-enter Phase 1)
    |
Final: Synthesize results and respond
```

For simple queries (greetings, direct questions), skip planning entirely using a lightweight classifier (heuristic, not LLM call).

**Sources**:
- [ReAct vs Plan-and-Execute for Reliability](https://byaiteam.com/blog/2025/12/09/ai-agent-planning-react-vs-plan-and-execute-for-reliability/)
- [Deep Agent: Hierarchical Task DAGs](https://arxiv.org/html/2502.07056v1)
- [LLM Agent Task Decomposition Strategies](https://apxml.com/courses/agentic-llm-memory-architectures/chapter-4-complex-planning-tool-integration/task-decomposition-strategies)
- [Long-Running AI Agents and Task Decomposition 2026](https://zylos.ai/research/2026-01-16-long-running-ai-agents)
- [Google: Choose a design pattern for agentic AI](https://docs.cloud.google.com/architecture/choose-design-pattern-agentic-ai-system)

---

## 2. CONTEXT ENGINEERING

### Current State
- Messages grow unbounded (`MAX_CONVERSATION_HISTORY = 50` defined but **NOT enforced** in code)
- Microcompaction truncates old tool results to ~100 chars summaries
- System prompt rebuilt every iteration (RAG collections + memo reloaded)
- No observation masking or hierarchical summarization
- Token estimation is rough (`word_count * 1.3`)

### Research Findings

**Context Rot**: As token count increases, model accuracy decreases. The "effective context window" where the model performs well is often much smaller than the advertised limit (less than ~256k tokens for most models). This is a fundamental constraint that demands active context management.

**Two Main Approaches to Context Management**:

1. **Observation Masking** — Replaces older environment observations (tool results) with placeholders while preserving full action and reasoning history. Uses a rolling window (e.g., keep latest 10 turns visible).
   - Pro: Keeps agent's reasoning and actions intact
   - Pro: Cheap (no extra LLM calls)
   - Con: Loses detailed observation data

2. **LLM Summarization** — Uses a separate LLM to compress older interactions.
   - Pro: Theoretically supports infinite context via repeated compression
   - Con: Causes "trajectory elongation" (~15% more turns with some models)
   - Con: Summary generation costs 7%+ of total cost for large models
   - Con: May obscure stopping signals

**JetBrains Research Benchmark (SWE-bench Verified, 500 instances)**:
- Both methods achieved **over 50% cost reduction** vs unmanaged baseline
- Observation masking **matched or exceeded** summarization in 4 of 5 test configurations
- Qwen3-Coder 480B: Masking provided **2.6% higher solve rates** while being **52% cheaper**
- **Recommended**: Hybrid — observation masking as primary layer, LLM summarization only when necessary

**Anthropic's Context Engineering Framework** (5 strategies):
1. **System Prompt Calibration** — Target the "right altitude" (not too specific, not too vague). Use structured sections. Start minimal, add clarity based on failure modes.
2. **Tool Design** — Minimal, non-overlapping tool sets. Token-efficient returns. Clear decision points.
3. **Few-Shot Examples** — Curate diverse canonical examples rather than exhaustive edge cases.
4. **Just-in-Time Context Retrieval** — Instead of pre-loading all data:
   - Maintain lightweight identifiers (file paths, queries, links)
   - Dynamically load data at runtime via tools
   - Use metadata as behavioral signals
5. **Hybrid Retrieval** — Combine upfront loading for speed with autonomous exploration.

**Token-Efficient Serialization**: Poor data serialization consumes 40-70% of available tokens through unnecessary formatting overhead. CSV outperforms JSON by 40-50% for tabular data.

**Compaction Best Practices** (from Anthropic):
- Summarize conversation history when approaching limits, preserving: architectural decisions, unresolved bugs, implementation details
- Discard redundant outputs
- Start by maximizing recall, then optimize precision
- Agents should maintain persistent external memory (NOTES.md, to-do lists) that persists beyond context windows

**Sub-Agent Architectures**: Deploy specialized agents with clean context windows. Each returns condensed summaries (1,000-2,000 tokens) rather than detailed exploration logs.

**Agent Context Optimization (Acon)**: A unified framework for systematic adaptive context compression. Lowers memory usage by 26-54% (peak tokens) while largely maintaining task performance.

**Sources**:
- [Anthropic: Effective Context Engineering for AI Agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [JetBrains Research: Smarter Context Management for LLM Agents](https://blog.jetbrains.com/research/2025/12/efficient-context-management/)
- [Maxim: Context Window Management Strategies](https://www.getmaxim.ai/articles/context-window-management-strategies-for-long-context-ai-agents-and-chatbots/)
- [Acon: Optimizing Context Compression for Long-horizon Agents](https://arxiv.org/html/2510.00615v1)
- [5 Approaches to Solve LLM Token Limits](https://www.deepchecks.com/5-approaches-to-solve-llm-token-limits/)
- [Top Techniques to Manage Context Length in LLMs](https://agenta.ai/blog/top-6-techniques-to-manage-context-length-in-llms)
- [Context Engineering Part 2 (Phil Schmid)](https://www.philschmid.de/context-engineering-part-2)
- [LangChain: Context Engineering in Agents](https://docs.langchain.com/oss/python/langchain/context-engineering)

---

## 3. MEMORY ARCHITECTURE

### Current State
- `MemoTool`: flat key-value store per user (`data/memory/{username}.json`)
- No episodic memory (past task outcomes)
- No semantic memory (learned facts/patterns)
- No procedural memory (successful tool sequences)
- No cross-session learning
- Agent starts every session cold

### Research Findings

**Three Types of Long-Term Memory AI Agents Need**:

1. **Episodic Memory** — Records specific events or interactions (like a personal diary). Transforms an agent from reactive to one that learns from history. When encountering new situations, agent can search for similar past experiences and adapt its approach.

2. **Semantic Memory** — Stores factual knowledge and conceptual understanding. Facts, rules, definitions, relationships the agent needs for reasoning.

3. **Procedural Memory** — Stores "how-to" knowledge. Successful strategies, tool-calling patterns, learned shortcuts.

**Current Research State (December 2025 survey)**: Traditional taxonomies (long/short-term) have proven insufficient. The field is fragmented with approaches including:
- Structured vs unstructured memory
- Symbolic vs neural
- Graph-based vs vector-based
- Key open challenges: catastrophic forgetting, retrieval efficiency, memory structure choices

**Implementation Approaches**:

- **FAISS for Episodic Memory**: Use sentence-transformer models (e.g., MiniLM) to encode session summaries as vectors. Store in FAISS index. On new session, query FAISS for similar past episodes. Each memory saved to disk enables persistence across sessions.

- **Vector Store Pattern**: Past interactions stored as embeddings using MiniLM and indexed with FAISS. Agent converts questions into vectors and finds most semantically similar memories. Can scale to hundreds/thousands of episodes as it only fetches relevant ones (not all).

- **Layered Architecture**:
  ```
  Working Memory (Context Window)
    - Current conversation + tool results
    - Managed by observation masking
  Episodic Memory
    - Past task summaries + outcomes
    - Vector-indexed for similarity search
    - "Last time user asked X, approach Y worked/failed because Z"
  Semantic Memory (enhanced Memo)
    - User preferences, facts, patterns
    - Auto-extracted from conversations
  Procedural Memory
    - Successful tool-calling sequences
    - "For file analysis: read -> python_coder -> summarize works well"
    - Learned shortcuts and patterns
  ```

- **Auto-extraction**: After each session, generate a 2-3 sentence summary + outcome tag. Track tool sequences. Extract user preferences. All automated, no manual tagging.

- **MemRL (2026)**: Self-evolving agents via runtime reinforcement learning on episodic memory — agents that actively improve their memory retrieval and usage strategies over time.

**Practical Note**: Since the project already uses FAISS for RAG (via `tools/rag/`), the same infrastructure (embedding model, FAISS index management) can be reused for episodic memory, reducing implementation effort significantly.

**Sources**:
- [Beyond Short-term Memory: 3 Types of Long-term Memory AI Agents Need](https://machinelearningmastery.com/beyond-short-term-memory-the-3-types-of-long-term-memory-ai-agents-need/)
- [Memory in the Age of AI Agents: A Survey (arxiv)](https://arxiv.org/abs/2512.13564)
- [How to Build Memory-Driven AI Agents (MarkTechPost)](https://www.marktechpost.com/2026/02/01/how-to-build-memory-driven-ai-agents-with-short-term-long-term-and-episodic-memory/)
- [Types of AI Agent Memory (Taskade)](https://www.taskade.com/blog/ai-agent-memory)
- [AI Agent Memory: Build Stateful Systems That Remember (Redis)](https://redis.io/blog/ai-agent-memory-stateful-systems/)
- [Mastering AI Agent Memory (DEV Community)](https://dev.to/oblivionlabz/mastering-ai-agent-memory-a-deep-dive-into-architecture-for-power-users-nc3)
- [FAISS Memory Integration (Medium)](https://vardhmanandroid2015.medium.com/gave-real-brain-and-hands-to-my-first-agentic-ai-by-integrating-persistent-vector-memory-faiss-5d5aa712cd90)
- [ICLR 2026 Workshop: Memory for LLM-Based Agentic Systems](https://openreview.net/pdf?id=U51WxL382H)

---

## 4. SELF-REFLECTION & ERROR RECOVERY

### Current State
- If a tool fails, the raw error is passed back to the LLM and the loop continues
- No structured reflection on failure causes
- No retry with modified parameters
- No learning from repeated failures

### Research Findings

**Performance Impact**: Self-reflection can improve performance by **18.5 percentage points** when properly implemented. However, external verification systems consistently outperform intrinsic self-correction.

**The "Self-Correction Blind Spot"**: LLMs have a weak tendency to identify and fix their own errors compared to externally-provided feedback. Self-correction converges towards but does not surpass a model/dataset-specific upper bound.

**Key Patterns**:
- **Reflect-Refine Cycle**: Initial generation -> reflection -> refinement (3-phase)
- **Real-time Error Interception**: Autoraters catching errors at the source before they cascade
- **External Verification**: More reliable than self-correction — use tool outputs, tests, or separate verification agents

**Recommended Pattern: Reflect-Retry-Escalate**:
```
Tool Call -> Result
    |-- Success -> Continue
    |-- Failure ->
        |-- Classify error (transient vs permanent vs user-error)
        |-- If transient -> Retry with backoff (max 2 retries)
        |-- If permanent -> Reflect: "Why did this fail? What alternative?"
        |                   Inject reflection into next LLM call
        |-- If 3+ failures on same tool -> Escalate to user
```

**Enterprise Adoption**: According to McKinsey's November 2025 Global Survey, 62% of organizations are at least experimenting with AI agents, with reflection patterns showing up across enterprise workflows where quality matters more than speed.

**Sources**:
- [Self-Evaluation in AI Agents With Chain of Thought (Galileo)](https://galileo.ai/blog/self-evaluation-ai-agents-performance-reasoning-reflection)
- [Iterative Self-Correction in AI (Emergent Mind)](https://www.emergentmind.com/topics/iterative-self-correction)
- [The Reflection Pattern: Why Self-Reviewing AI Improves Quality](https://qat.com/reflection-pattern-ai/)
- [Self-Correcting Multi-Agent AI Systems (Medium)](https://medium.com/@sohamghosh_23912/self-correcting-multi-agent-ai-systems-building-pipelines-that-fix-themselves-010786bae2db)
- [Evaluating AI Agents: Real-world Lessons from Amazon](https://aws.amazon.com/blogs/machine-learning/evaluating-ai-agents-real-world-lessons-from-building-agentic-systems-at-amazon/)

---

## 5. STREAMING & CONTINUOUS FLOW ARCHITECTURE

### The Question
"Is it beneficial to make the agentic flow one continuous flow and parse plans and tool calls along the way?"

### Answer: Yes, with caveats.

### Current State
Streaming yields `TextEvent`, `ToolStatusEvent`, and `ToolCallDeltaEvent` — but the agent loop is discrete iterations (LLM call -> tool execution -> next call).

### Research Findings

**Event-Driven Architecture** (Google, AutoGen v0.4):
- Agent as a state machine, not a loop
- Events (user input, tool results, timeouts) drive state transitions
- Tool execution, LLM calls, and user interaction as concurrent streams
- System can process new user input while tools run

**Google's Bidirectional Streaming Multi-Agent System**:
- Traditional request-response is limited for high-concurrency scenarios
- Streaming architecture natively processes continuous parallel streams as unified context
- Enables real-time environmental/situational awareness
- Agents react to surroundings without manual synchronization

**Practical Benefits**:
- **Lower perceived latency**: User sees progress immediately
- **Parallel tool+LLM**: While tool X runs, LLM can plan tool Y
- **Interruptibility**: User can cancel or redirect mid-execution
- **Better backpressure**: Don't buffer entire tool results before sending

**Recommended Incremental Path**:
1. Start with existing loop but add **streaming plan output** (stream the plan to user before execution)
2. Add **early tool dispatch** (parse tool calls incrementally during streaming)
3. Full event-driven state machine architecture if needed

**State Machine Design**:
```
IDLE -> PLANNING -> EXECUTING -> REFLECTING -> RESPONDING
                      |              |
                      v              v
                  (parallel)   (replan if needed)
                  tool exec
```

**Sources**:
- [Google: Beyond Request-Response Multi-Agent Systems](https://developers.googleblog.com/en/beyond-request-response-architecting-real-time-bidirectional-streaming-multi-agent-system/)
- [AutoGen v0.4: Event-Driven Architecture](https://www.spaceo.ai/blog/agentic-ai-frameworks/)
- [Parallel Agent Processing (Kore.ai)](https://www.kore.ai/ai-insights/parallel-agent-processing)

---

## 6. TOOL EXECUTION SANDBOXING

### Current State
All tools run in-process with the main server. `python_coder` spawns subprocesses but with no real isolation. No resource limits, no system-level timeout enforcement.

### Research Findings

**Sandboxing Tiers (from 2025-2026 research)**:

| Tier | Technology | Isolation | Startup | Overhead |
|------|-----------|-----------|---------|----------|
| 1 | Process + resource limits | Weak | Instant | Minimal |
| 2 | Docker containers | Medium | ~1s | Low-Med |
| 3 | gVisor (user-space kernel) | Strong | ~200ms | Medium |
| 4 | Firecracker MicroVMs | Strongest | ~125-150ms | Low |

**E2B Platform**: Open-source infrastructure for running AI-generated code in secure sandboxes. Uses Firecracker microVMs (same tech as AWS Lambda). Starts in under 200ms with no cold starts, less than 5 MiB memory overhead.

**Docker + E2B Partnership**: Gives developers access to 200+ real-world tools through secure cloud sandboxes.

**Daytona**: Docker containers by default with optional Kata Containers. Fastest cold starts (sub-90ms).

**For this project (local llama.cpp server)**: Tier 1 (process isolation with resource limits) is the pragmatic choice. Tier 2 (Docker) for production deployments.

**Sources**:
- [How to Sandbox AI Agents in 2026 (Northflank)](https://northflank.com/blog/how-to-sandbox-ai-agents)
- [Top AI Sandbox Platforms in 2026](https://northflank.com/blog/top-ai-sandbox-platforms-for-code-execution)
- [E2B: Enterprise AI Agent Cloud](https://e2b.dev/)
- [Docker + E2B Partnership](https://www.docker.com/blog/docker-e2b-building-the-future-of-trusted-ai/)

---

## 7. OBSERVABILITY & EVALUATION

### Current State
- `prompts.log`: human-readable, append-only, all LLM interactions
- No structured tracing
- No metrics framework
- Token estimation: `word_count * 1.3` (rough heuristic)
- No evaluation or quality tracking

### Research Findings

**Leading Platforms (2025-2026)**:
- **LangSmith**: Best for LangChain-based systems. OpenTelemetry support since March 2025.
- **Arize Phoenix**: Built natively on OpenTelemetry. Open-source.
- **Langfuse**: Strong for both evaluation and observability. Open-source.
- **Weave (W&B)**: Experiment-tracking approach. `@weave.op` decorator auto-tracks everything.
- **Opik**: Strong in both areas.

**Key Capabilities Needed**:
- Detailed tracing for multi-step workflows
- Latency, token usage, success/failure rates per tool
- Agent chain debugging (seeing exactly where decisions happen)
- Cost tracking across iterations

**OpenTelemetry Standard**: Industry-standard for distributed tracing. All major platforms support OTEL export. Recommended: add spans for LLM calls, tool executions, planning phases, context compression.

**Structured Trace Format (recommended)**:
```json
{
  "trace_id": "...",
  "session_id": "...",
  "iterations": [
    {
      "iteration": 1,
      "llm_call": {"tokens_in": 2340, "tokens_out": 156, "latency_ms": 1200},
      "tool_calls": [{"name": "websearch", "latency_ms": 800, "success": true}],
      "context_size": {"system": 1200, "history": 3400, "tool_results": 800}
    }
  ]
}
```

**Sources**:
- [8 Observability Platforms for AI Agents (Softcery)](https://softcery.com/lab/top-8-observability-platforms-for-ai-agents-in-2025)
- [Best LLM Observability Tools 2026 (Firecrawl)](https://www.firecrawl.dev/blog/best-llm-observability-tools)
- [Top 5 AI Agent Observability Platforms 2026](https://o-mega.ai/articles/top-5-ai-agent-observability-platforms-the-ultimate-2026-guide)
- [15 AI Agent Observability Tools 2026](https://research.aimultiple.com/agentic-monitoring/)

---

## 8. MODEL CONTEXT PROTOCOL (MCP) INTEGRATION

### Current State
Tools hardcoded in `tools_config.py` with custom dispatch in `_dispatch_tool()`.

### Research Findings

**MCP is now the industry standard** — Launched December 2025, backed by the Agentic AI Foundation (Anthropic, OpenAI, Block).

**MCP Specification (2025-11-25 / 2025-06-18)**:
- Tools as first-class citizens with schema validation
- Dynamic tool discovery (tools register themselves)
- Structured outputs (2025-06-18 update)
- OAuth resource server model for security
- Resource Indicators (RFC 8707) for token scoping
- Server-initiated user interactions

**MCP Best Practices**:
- Each MCP server should have one clear, well-defined purpose
- Agents scale better by writing code to call tools instead of direct tool calls (reduces context per definition/result)
- Load tools on demand, filter data before it reaches the model
- Security: token validation, resource isolation, threat mitigation

**Ecosystem**: 200+ pre-built tools via Docker MCP Catalog (GitHub, Perplexity, Browserbase, ElevenLabs, etc.)

**For this project**: Wrapping existing tools as MCP servers would enable:
- External tool discovery without code changes
- User-pluggable custom tools
- Ecosystem access to 200+ pre-built tools
- Future-proofing as MCP becomes standard

**Sources**:
- [MCP Specification 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25)
- [Anthropic: Code Execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp)
- [MCP Best Practices Guide](https://modelcontextprotocol.info/docs/best-practices/)
- [MCP Enterprise Adoption Guide 2025](https://guptadeepak.com/the-complete-guide-to-model-context-protocol-mcp-enterprise-adoption-market-trends-and-implementation-strategies/)
- [Agentic AI Foundation: Open Standards](https://intuitionlabs.ai/articles/agentic-ai-foundation-open-standards)

---

## 9. llama.cpp BACKEND OPTIMIZATIONS

### Current State
Fully async `LlamaCppBackend` using `httpx.AsyncClient`. Prompt caching via `_CACHED_SYSTEM_PROMPT` and `_CACHED_TOOL_SCHEMAS`.

### Research Findings

**Speculative Decoding**: Use a small draft model to predict tokens, verify with main model in a single batch. Tool-calling responses (highly predictable JSON) benefit the most. Can achieve 2-2.5x speedup. Eagle-3 is current SOTA but not yet supported in llama.cpp (supported in vLLM, TRT-LLM, SGLang).

**Lazy Grammar**: Already available in recent llama.cpp. Delays JSON schema enforcement until a trigger is encountered, allowing natural language first then switching to constrained output for tool invocation. The `--jinja` flag (already used) enables this.

**KV Cache Optimization**: Current `_CACHED_SYSTEM_PROMPT` approach is good for cache reuse. But the system prompt varies each request due to RAG/memo injection, which defeats KV caching. Fix: move dynamic content to user messages instead, keeping system prompt byte-identical.

**Recent Bug Fixes (Feb 2026)**:
- Dangling-reference bug in chat parser fixed
- XML tool-call parsing improved
- Responses API: contiguous assistant messages merged to keep content/reasoning/tool calls together

**Sources**:
- [llama.cpp Speculative Decoding Docs](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md)
- [llama.cpp GitHub](https://github.com/ggml-org/llama.cpp)
- [Constrained Decoding Guide](https://www.aidancooper.co.uk/constrained-decoding/)
- [llama.cpp Weekly Reports (Feb 2026)](https://buttondown.com/weekly-project-news/archive/weekly-github-report-for-llamacpp-february-08-8356/)

---

## 10. LONG-RUNNING AGENT HARNESSES (Anthropic)

### Research Findings

**Core Challenge**: Long-running agents must work in discrete sessions, each starting with no memory of previous work. Context windows are limited and most complex projects cannot complete within a single window.

**Anthropic's Solution: Two-Agent Pattern**:
1. **Initializer Agent** (first run only): Sets up environment, creates `init.sh`, generates `claude-progress.txt`, establishes git baseline
2. **Coding Agent** (subsequent sessions): Reads progress history, works on single features sequentially, leaves environment production-ready

**Progress Documentation Pattern**:
- Maintains `claude-progress.txt` alongside git history
- Features tracked as JSON-formatted lists (200+ items possible)
- Features marked pass/fail (not removed)
- Prevents premature victory declaration and missed requirements

**Context Engineering Patterns**:
- **Context Isolation**: Keep different subtasks separate to avoid confusion
- **Context Reduction**: Drop/compress irrelevant info to avoid context rot
- **Context Retrieval**: Inject fresh info (docs, search results) at the right time

**Key Lesson**: Context compaction alone is insufficient. Requires structural scaffolding: git commits with descriptive messages, comprehensive feature inventories, mandatory end-to-end verification before marking features complete.

**Sources**:
- [Anthropic: Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Claude Code: Best Practices for Agentic Coding](https://www.anthropic.com/engineering/claude-code-best-practices)
- [Building Agents with Claude Agent SDK](https://www.anthropic.com/engineering/building-agents-with-the-claude-agent-sdk)

---

## 11. ADDITIONAL QUICK WINS (Low Effort, Immediate Impact)

### 11a. Enforce MAX_CONVERSATION_HISTORY
- Currently defined as 50 but **never enforced** in code
- Add check in `run()`/`run_stream()`: if over limit, apply observation masking
- Immediate impact on token costs and context rot

### 11b. Deduplicate system.txt
- `process_monitor` and `memo` tool descriptions appear twice in `prompts/system.txt`
- Remove duplicates to save ~500 tokens per request

### 11c. Tool Result Cleanup
- `data/tool_results/{session_id}/` files are never cleaned up
- Add cleanup to `startup_event` in `app.py` (mirror existing session/job cleanup)

### 11d. Smarter Auto-Titling
- Current: truncate first user message to 60 chars
- Better: lightweight LLM call for descriptive 5-word title
- Or: extract key entities from message using simple NLP

### 11e. Session-Level Progress Tracking
- Maintain `progress.json` per session tracking completed steps, pending goals, known failures
- Load at session start for instant orientation (Anthropic's pattern)

---

## AGENTIC AI INDUSTRY TRENDS (2025-2026)

**Architecture Shift**: Single all-purpose agents being replaced by orchestrated teams of specialized agents. 1,445% surge in multi-agent system inquiries from Q1 2024 to Q2 2025.

**Standardization**: Agentic AI Foundation (AAIF) founded December 2025 by Anthropic, OpenAI, and Block. Consolidates MCP, Goose framework, AGENTS.md into neutral consortium.

**Key Frameworks**:
- **LangGraph**: State machine with nodes, edges, conditional routing. Enables conditional decision-making, parallel execution, persistent state.
- **AutoGen v0.4** (Jan 2025): Complete redesign — event-driven, async messaging, distributed execution.
- **OpenAI Agents SDK** (Mar 2025): Minimalist Python-first. Automatic orchestration cycles, schema-validated tools, agent handoffs.
- **Claude Agent SDK**: Augmented LLM capable of generating search queries, selecting tools, managing memory.

**Core Principle**: "Give the system the smallest amount of freedom that still delivers the outcome, then put effort into tool design, safety, and observability."

**Sources**:
- [Stack AI: 2026 Guide to Agentic Workflow Architectures](https://www.stack-ai.com/blog/the-2026-guide-to-agentic-workflow-architectures)
- [7 Agentic AI Trends to Watch in 2026](https://machinelearningmastery.com/7-agentic-ai-trends-to-watch-in-2026/)
- [Agentic AI Design Patterns 2026 Edition](https://medium.com/@dewasheesh.rana/agentic-ai-design-patterns-2026-ed-e3a5125162c5)
- [4 Agentic AI Design Patterns & Real-World Examples](https://research.aimultiple.com/agentic-ai-design-patterns/)
- [The Complete Guide to Agentic Coding in 2026](https://www.teamday.ai/blog/complete-guide-agentic-coding-2026)
- [OpenAI Agents SDK Guide](https://datasciencedojo.com/blog/openai-agents-sdk/)
- [Building for Agentic AI: Agent SDKs & Design Patterns](https://medium.com/dsaid-govtech/building-for-agentic-ai-agent-sdks-design-patterns-ef6e6bd4a029)

---

## PRIORITY RANKING

| # | Enhancement | Impact | Effort | Recommended Order |
|---|-------------|--------|--------|-------------------|
| 11a | Enforce MAX_CONVERSATION_HISTORY | High | Low | **Do first** |
| 11b | Deduplicate system.txt | Low | Trivial | **Do first** |
| 11c | Tool result cleanup | Low | Low | **Do first** |
| 2 | Context engineering (observation masking) | High | Medium | **Phase 1** |
| 2 | Token-efficient serialization | Medium | Low | **Phase 1** |
| 4 | Self-reflection & error recovery | Medium | Medium | **Phase 1** |
| 1 | Hybrid planning + execution | High | High | **Phase 2** |
| 2 | Context budget + JIT loading | High | Medium | **Phase 2** |
| 3 | Advanced memory (episodic) | Medium-High | High | **Phase 2** |
| 5 | Event-driven streaming | Medium | High | **Phase 3** |
| 7 | Observability | Medium | Medium | **Phase 3** |
| 6 | Tool sandboxing | Medium | Medium-High | **Phase 3** |
| 8 | MCP integration | Medium | High | **Phase 4** |
| 9 | llama.cpp optimizations | Low-Medium | Medium | **Ongoing** |
| 10 | Long-running agent harnesses | Medium | Medium | **Phase 3** |
