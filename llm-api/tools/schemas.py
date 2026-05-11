"""
Tool schemas for the LLM agent (OpenAI function-calling format).

Consumed by backend/agent.py at module load time to build the tool list
sent to llama.cpp. Parameter names must exactly match what _dispatch_tool()
passes to each tool's execute/read/write/navigate/edit/search method.
"""

TOOL_SCHEMAS: dict = {

    # ================================================================
    # SHELL EXECUTION
    # ================================================================

    "shell_exec": {
        "name": "shell_exec",
        "description": (
            "Executes a given shell command and returns its output.\n\n"
            "Each shell_exec call is isolated. Shell state and cd commands do not persist; "
            "always pass working_directory for commands that depend on cwd.\n\n"
            "PLATFORM — check the injected ## ENVIRONMENT block before every call:\n"
            "  Windows / PowerShell 5.1: chain with `;` not `&&`; use `$env:VAR` not `$VAR`; "
            "use Get-Content/Set-Content not cat/echo >; do NOT use chmod, export, source, [[ ]].\n"
            "  Linux/macOS / bash: chain with `&&`; use `$VAR`; bash syntax is fine.\n\n"
            "IMPORTANT: Avoid using this tool to run find, grep, cat, head, tail, sed, or awk "
            "unless explicitly instructed. Instead use the dedicated tools:\n"
            "  - file_reader   for reading files (not cat/head/tail)\n"
            "  - file_edit / apply_patch for in-place edits (not sed/awk)\n"
            "  - grep          for content search (not grep/rg)\n"
            "  - file_navigator for listing directories (not find/ls)\n\n"
            "When issuing multiple independent read/search operations, use dedicated read-only "
            "tools instead. shell_exec calls run in request order to avoid state races.\n\n"
            "When using curl for HTTP APIs, always include -sS --fail-with-body so HTTP 4xx/5xx "
            "responses surface as failures instead of silent exit-code-0 successes.\n\n"
            "For long-running commands set a large timeout (600-3600). "
            "For background servers or watchers, use process_monitor instead.\n\n"
            "SHELL SCRIPTS: After editing any shell script, call shell_lint to verify syntax "
            "before running with shell_exec.\n\n"
            "Always provide the description parameter — it appears in logs and helps trace "
            "what each command was doing."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Maximum seconds to wait (default: 300). Process is killed on timeout.",
                },
                "working_directory": {
                    "type": "string",
                    "description": "Working directory for the command. Relative paths resolve from the repository root. Defaults to repository root.",
                },
                "description": {
                    "type": "string",
                    "description": (
                        "Clear description of what this command does (5-10 words for simple commands, "
                        "more detail for piped/complex operations). Example: 'Install numpy via pip' or "
                        "'Find and delete all .tmp files recursively'."
                    ),
                },
            },
            "required": ["command"],
        },
    },

    # ================================================================
    # FILE OPERATIONS
    # ================================================================

    "file_reader": {
        "name": "file_reader",
        "description": (
            "Reads a file from the local filesystem. You can access any file directly by using "
            "this tool.\n\n"
            "Assume this tool can read all files on the machine. It is okay to read a file that "
            "does not exist — an error will be returned.\n\n"
            "Usage notes:\n"
            "- Absolute paths are read directly. Relative paths resolve against the session "
            "scratch workspace, then user uploads, then the current working directory.\n"
            "- By default reads up to 2000 lines from the beginning of the file.\n"
            "- For large files, use offset and limit to read specific sections.\n"
            "- Use this instead of shell_exec cat/head/tail.\n"
            "- If you already know the file path, call file_reader directly — do not explore first."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Path to the file. Absolute paths (e.g. /home/user/file.py) are read directly. "
                        "Relative paths resolve against session scratch, then uploads, then cwd."
                    ),
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (1-based, default: 1).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read (default: 2000).",
                },
            },
            "required": ["path"],
        },
    },

    "file_edit": {
        "name": "file_edit",
        "description": (
            "Performs exact string replacements in files.\n\n"
            "Usage:\n"
            "- You MUST use file_reader at least once before editing a file. This tool will "
            "error if the old_string is not found — reading first ensures you have the exact text.\n"
            "- When editing, preserve the exact indentation (tabs/spaces) as it appears in the file. "
            "Never guess indentation — copy it exactly from file_reader output.\n"
            "- ALWAYS prefer editing existing files over creating new ones with file_writer.\n"
            "- The edit will FAIL if old_string is not unique in the file. Either provide more "
            "surrounding context to make it unique, or set replace_all=true to change every instance.\n"
            "- Use replace_all=true for renaming a variable or string across the whole file.\n"
            "- IMPORTANT: Use this only for single-line or very small changes where old_string "
            "will match exactly (including whitespace and line endings). For multi-line edits, "
            ".ps1 files, or .sh files, use apply_patch instead — it handles CRLF/LF differences "
            "and whitespace tolerance that make exact matching unreliable."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or session-relative path to the file to modify.",
                },
                "old_string": {
                    "type": "string",
                    "description": (
                        "The exact text to replace (must match character-for-character including "
                        "whitespace and indentation). Must be unique in the file unless replace_all=true."
                    ),
                },
                "new_string": {
                    "type": "string",
                    "description": "The text to replace it with. Must be different from old_string.",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace all occurrences of old_string (default false).",
                },
            },
            "required": ["path", "old_string", "new_string"],
        },
    },

    "apply_patch": {
        "name": "apply_patch",
        "description": (
            "Apply a V4A context-anchored patch to one or more files.\n\n"
            "Use this for ALL multi-line edits, .ps1 files, and .sh files. "
            "It locates edit regions by matching surrounding context lines — no line numbers needed — "
            "and is tolerant of CRLF vs LF and trailing-whitespace differences.\n\n"
            "Format:\n"
            "    *** Begin Patch\n"
            "    *** Update File: path/to/file.ps1\n"
            "    @@ optional locator text (a nearby unique line)\n"
            "     unchanged context line\n"
            "    -removed line\n"
            "    +added line\n"
            "     unchanged context line\n"
            "    *** End Patch\n\n"
            "Supported directives: *** Add File, *** Delete File, *** Update File, *** Move to.\n"
            "Multiple files can be patched in one envelope.\n\n"
            "Example — rename a variable in a .ps1 file:\n"
            "    *** Begin Patch\n"
            "    *** Update File: hoonbot/start.ps1\n"
            "    @@ param(\n"
            "     param(\n"
            "    -    [string]$OldName = 'default',\n"
            "    +    [string]$NewName = 'default',\n"
            "     )\n"
            "    *** End Patch\n\n"
            "On failure, returns an actionable error naming the exact context line that did not "
            "match — use file_reader to look up the actual content, then reissue the patch with "
            "corrected context lines. Do NOT write the file if the patch fails."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "string",
                    "description": "V4A patch text starting with '*** Begin Patch' and ending with '*** End Patch'.",
                },
            },
            "required": ["patch"],
        },
    },

    "file_patch": {
        "name": "file_patch",
        "description": (
            "Applies a contextual unified-diff patch to existing text files.\n\n"
            "Usage:\n"
            "- Prefer this for multi-line code or shell-script edits. It is safer than "
            "rewriting an entire file and less brittle than exact string replacement.\n"
            "- The patch must be a standard unified diff with ---/+++ file headers and @@ hunks.\n"
            "- Use repo-relative paths such as a/llm-api/config.py and b/llm-api/config.py.\n"
            "- The tool rejects stale hunks when context does not match the current file.\n"
            "- The tool rejects generated/runtime directories, binary files, deletes, and "
            "paths outside the repository/write policy.\n"
            "- After changing shell scripts, run bash -n on the changed files before final reply."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "string",
                    "description": "Unified diff patch text to apply.",
                },
            },
            "required": ["patch"],
        },
    },

    "file_writer": {
        "name": "file_writer",
        "description": (
            "Writes a file to the local filesystem.\n\n"
            "Usage:\n"
            "- This tool will OVERWRITE the existing file if there is one at the provided path.\n"
            "- ALWAYS prefer file_edit for modifying existing files — it only sends the diff and "
            "is far less likely to corrupt surrounding code.\n"
            "- Only use file_writer to CREATE new files or for complete rewrites of an existing file.\n"
            "- If this is an existing file, you MUST use file_reader first to read its contents.\n"
            "- Never create documentation (*.md) or README files unless explicitly requested.\n"
            "- Relative paths write inside the session scratch workspace."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Path to the file. Absolute paths write directly to that location "
                        "(subject to ALLOWED_WRITE_DIRS). Relative paths write inside the session "
                        "scratch workspace."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": "Text content to write to the file.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["write", "append"],
                    "description": "'write' overwrites the file (default); 'append' adds to the end.",
                },
            },
            "required": ["path", "content"],
        },
    },

    "file_navigator": {
        "name": "file_navigator",
        "description": (
            "List directory contents or find files by name using glob patterns.\n\n"
            "Use this tool to discover file *names* and directory structure. "
            "For searching file *contents* (e.g., finding where a function is defined), "
            "use grep instead.\n\n"
            "Operations:\n"
            "  list   — list files in a directory\n"
            "  search — find files matching a glob pattern (e.g. '*.py', '**/*.ts')\n"
            "  tree   — show recursive directory tree\n\n"
            "Only use this when file paths are unknown. If you already know the path, "
            "call file_reader directly."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["list", "search", "tree"],
                    "description": (
                        "'list': list files in a directory. "
                        "'search': find files matching a glob pattern. "
                        "'tree': show directory tree structure."
                    ),
                },
                "path": {
                    "type": "string",
                    "description": (
                        "Directory path to list or search in. Absolute paths are used directly. "
                        "Relative paths resolve against the session scratch workspace."
                    ),
                },
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern for search operation (e.g. '*.csv', '**/*.py').",
                },
            },
            "required": ["operation"],
        },
    },

    # ================================================================
    # CONTENT SEARCH
    # ================================================================

    "grep": {
        "name": "grep",
        "description": (
            "A powerful search tool built on ripgrep for searching file contents.\n\n"
            "Usage:\n"
            "- ALWAYS use grep for content search tasks. NEVER invoke shell_exec grep or rg.\n"
            "- Supports full regex syntax (e.g. 'log.*Error', 'function\\s+\\w+').\n"
            "- Filter files with glob parameter (e.g. '*.js', '**/*.tsx') or type parameter "
            "(e.g. 'js', 'py', 'rust').\n"
            "- Output modes: 'content' shows matching lines (supports -A/-B/-C context, -n line "
            "numbers), 'files_with_matches' shows only file paths (default), 'count' shows match "
            "counts per file.\n"
            "- Pattern syntax: uses ripgrep (not grep). Literal braces need escaping.\n"
            "- Multiline matching: by default patterns match within single lines. For cross-line "
            "patterns, use multiline=true.\n"
            "- Use agent with subagent_type='explore' for broad open-ended searches that may "
            "require multiple rounds of grepping."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "The regular expression pattern to search for in file contents.",
                },
                "path": {
                    "type": "string",
                    "description": "File or directory to search in (rg PATH). Defaults to current working directory.",
                },
                "glob": {
                    "type": "string",
                    "description": "Glob pattern to filter files (e.g. '*.js', '*.{ts,tsx}') — maps to rg --glob.",
                },
                "output_mode": {
                    "type": "string",
                    "enum": ["content", "files_with_matches", "count"],
                    "description": (
                        "Output mode: 'content' shows matching lines (supports -A/-B/-C context, "
                        "-n line numbers), 'files_with_matches' shows file paths (default), "
                        "'count' shows match counts."
                    ),
                },
                "-A": {
                    "type": "integer",
                    "description": "Number of lines to show after each match (rg -A). Requires output_mode: 'content'.",
                },
                "-B": {
                    "type": "integer",
                    "description": "Number of lines to show before each match (rg -B). Requires output_mode: 'content'.",
                },
                "-C": {
                    "type": "integer",
                    "description": "Alias for context — lines before AND after each match.",
                },
                "context": {
                    "type": "integer",
                    "description": "Number of lines to show before and after each match (rg -C). Requires output_mode: 'content'.",
                },
                "-n": {
                    "type": "boolean",
                    "description": "Show line numbers in output (rg -n). Requires output_mode: 'content'. Defaults to true.",
                },
                "-i": {
                    "type": "boolean",
                    "description": "Case insensitive search (rg -i).",
                },
                "type": {
                    "type": "string",
                    "description": "File type to search (rg --type). Common types: js, py, rust, go, java, ts.",
                },
                "head_limit": {
                    "type": "integer",
                    "description": (
                        "Limit output to first N lines/entries, equivalent to '| head -N'. "
                        "Works across all output modes. Defaults to 250. Pass 0 for unlimited."
                    ),
                },
                "offset": {
                    "type": "integer",
                    "description": "Skip first N lines/entries before applying head_limit. Defaults to 0.",
                },
                "multiline": {
                    "type": "boolean",
                    "description": "Enable multiline mode where . matches newlines and patterns can span lines. Default: false.",
                },
            },
            "required": ["pattern"],
        },
    },

    # ================================================================
    # CODE EXECUTION
    # ================================================================

    "code_exec": {
        "name": "code_exec",
        "description": (
            "Default tool for Python coding tasks. Execute Python code directly — pass the "
            "complete, ready-to-run script as the 'code' argument. Runs in the session workspace, "
            "returns stdout/stderr/returncode.\n\n"
            "Use this for any task where you can write the code yourself: file processing, "
            "data analysis, calculations, multi-step logic, library calls, plotting, ML training.\n\n"
            "Prefer code_exec over shell_exec for Python-specific work — it sets up the correct "
            "workspace and captures output cleanly.\n\n"
            "Before declaring success: verify the script actually ran and produced the expected "
            "output. Check returncode and stderr.\n\n"
            "Timeout policy: omit timeout for the default limit. Set a positive timeout for "
            "known-long runs. Set timeout=0 only when the user explicitly wants no wall-clock "
            "timeout; this can run indefinitely until the process exits or is externally stopped."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Complete Python source code to execute.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Maximum seconds for execution (default: 300). Set 0 for no wall-clock timeout.",
                },
            },
            "required": ["code"],
        },
    },

    # ================================================================
    # TASK TRACKING
    # ================================================================

    "todo_write": {
        "name": "todo_write",
        "description": (
            "Update the todo list for the current session. Use proactively and often to track "
            "progress and pending tasks.\n\n"
            "WHEN to use:\n"
            "- Multi-step tasks with 3 or more distinct steps\n"
            "- Complex non-trivial work requiring careful sequencing\n"
            "- When starting any task — create todos BEFORE beginning work\n"
            "- After completing a step — update status immediately\n"
            "- When new follow-up tasks are discovered mid-execution\n\n"
            "WHEN NOT to use:\n"
            "- Single straightforward tasks\n"
            "- Tasks completable in under 3 trivial steps\n"
            "- Purely conversational requests\n\n"
            "Rules:\n"
            "- Exactly ONE task may be 'in_progress' at a time\n"
            "- Mark tasks 'completed' ONLY when fully done — not if tests fail or work is partial\n"
            "- Pass the COMPLETE updated list every call (this replaces the previous list)\n"
            "- Use clear imperative content: 'Fix auth bug', 'Run tests', 'Refactor parser'"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "The complete updated todo list (replaces previous list).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "Stable identifier (e.g. 'task_1', 'fix_auth').",
                            },
                            "content": {
                                "type": "string",
                                "description": "Imperative form: what needs to be done (e.g. 'Run tests').",
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                                "description": "Current status. Only ONE item may be in_progress at a time.",
                            },
                            "priority": {
                                "type": "string",
                                "enum": ["high", "medium", "low"],
                                "description": "Task priority.",
                            },
                        },
                        "required": ["id", "content", "status", "priority"],
                    },
                },
            },
            "required": ["todos"],
        },
    },

    # ================================================================
    # SUBAGENT SPAWNING
    # ================================================================

    "agent": {
        "name": "agent",
        "description": (
            "Launch a specialized subagent to handle complex, multi-step tasks in a fresh "
            "context without polluting the main conversation.\n\n"
            "Available subagent types:\n"
            "  explore — Read-only research agent (file_reader, grep, file_navigator, websearch). "
            "Use for broad codebase exploration: 'what files handle auth?', 'find all usages of X'. "
            "Faster and cheaper than inline shell loops.\n"
            "  general — Full toolset agent. Use for delegating a complete self-contained subtask.\n\n"
            "WHEN to use:\n"
            "- Open-ended searches that span the codebase and require multiple queries\n"
            "- Research whose findings inform later steps (run foreground)\n"
            "- Genuinely independent parallel work (run multiple agents in one turn)\n\n"
            "WHEN NOT to use:\n"
            "- You already know the target file — use file_reader directly\n"
            "- A single grep or glob would answer the question\n"
            "- The task is a narrow, named lookup\n\n"
            "IMPORTANT: The result returned by the subagent is NOT visible to the user. "
            "You must relay the findings explicitly in your response.\n\n"
            "Do NOT duplicate work a subagent is doing — if you delegate research, do not also "
            "perform the same searches yourself."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": (
                        "Task or question for the subagent. Be specific — brief the agent like a "
                        "smart colleague who just walked in. Include: what to find, what files/areas "
                        "to look in, what form the answer should take."
                    ),
                },
                "subagent_type": {
                    "type": "string",
                    "enum": ["explore", "general"],
                    "description": "'explore' for read-only codebase research (default). 'general' for full toolset tasks.",
                },
                "description": {
                    "type": "string",
                    "description": "Short description of what this agent will do (3-5 words). Used for logging.",
                },
            },
            "required": ["prompt"],
        },
    },

    # ================================================================
    # WEB SEARCH
    # ================================================================

    "websearch": {
        "name": "websearch",
        "description": (
            "Search the web for current information, news, documentation, or facts not in your "
            "training data. Returns results with titles, URLs, and content snippets.\n\n"
            "Use for: library docs, API references, error messages, recent events, version changelogs.\n"
            "Do not use for: information already in your training data or available in uploaded docs "
            "(use rag instead)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query. Be specific for best results.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 5).",
                },
            },
            "required": ["query"],
        },
    },

    # ================================================================
    # KNOWLEDGE BASE
    # ================================================================

    "rag": {
        "name": "rag",
        "description": (
            "Retrieve relevant information from user-uploaded document collections using semantic "
            "search. Use for searching uploaded PDFs, docs, or datasets.\n\n"
            "You must specify which collection to search. Use only existing collection_name values "
            "listed in context. Results are document chunks ranked by relevance.\n\n"
            "Use rag for uploaded documents; use websearch for live web results."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "collection_name": {
                    "type": "string",
                    "description": "Name of the document collection to search. Must be an existing collection.",
                },
                "query": {
                    "type": "string",
                    "description": "The search query to find relevant document chunks.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of document chunks to return (default: 10).",
                },
            },
            "required": ["collection_name", "query"],
        },
    },

    # ================================================================
    # MEMORY
    # ================================================================

    "memo": {
        "name": "memo",
        "description": (
            "Read or write persistent memory that survives across sessions.\n\n"
            "Use memo for facts that should persist across sessions: important results, decisions, "
            "file paths, project-specific conventions, user preferences.\n\n"
            "For current-session task tracking, use todo_write instead.\n\n"
            "Memory is per-user and automatically shown at the start of every session."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["write", "read", "list", "delete"],
                    "description": (
                        "'write': save a value under a key. "
                        "'read': retrieve a value by key. "
                        "'list': show all saved entries. "
                        "'delete': remove an entry by key."
                    ),
                },
                "key": {
                    "type": "string",
                    "description": "Memory key name (e.g. 'best_lr', 'dataset_path', 'project_status').",
                },
                "value": {
                    "type": "string",
                    "description": "Value to store. Required for 'write' operation.",
                },
            },
            "required": ["operation"],
        },
    },

    # ================================================================
    # PROCESS MANAGEMENT
    # ================================================================

    "process_monitor": {
        "name": "process_monitor",
        "description": (
            "Manage long-running background processes: start, check status, read output, or kill.\n\n"
            "Use this instead of shell_exec when you need to:\n"
            "  - Launch a server or watcher and check on it later\n"
            "  - Observe incremental output from a long-running process\n"
            "  - Run a process and continue with other work while it runs\n\n"
            "Each process gets a handle like 'proc_1' for future reference. "
            "Use 'read_output' with next_offset for incremental reads."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["start", "status", "read_output", "kill", "list"],
                    "description": (
                        "'start': launch a background command, returns a handle. "
                        "'status': check if running/exited (by handle). "
                        "'read_output': get stdout/stderr since last read or from an offset (by handle). "
                        "'kill': terminate a process (by handle). "
                        "'list': show all tracked processes for this session."
                    ),
                },
                "command": {
                    "type": "string",
                    "description": "Shell command to run (required for 'start').",
                },
                "handle": {
                    "type": "string",
                    "description": "Process handle (e.g. 'proc_1'). Required for 'status', 'read_output', 'kill'.",
                },
                "working_directory": {
                    "type": "string",
                    "description": "Working directory (only for 'start'). Defaults to scratch workspace.",
                },
                "offset": {
                    "type": "integer",
                    "description": (
                        "Line offset for 'read_output'. Use next_offset from a previous read to get new lines. "
                        "If omitted, returns the last 200 lines."
                    ),
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Maximum lines to return for 'read_output' (default: 200).",
                },
                "stream": {
                    "type": "string",
                    "enum": ["stdout", "stderr", "both"],
                    "description": "Which output stream to read (default: 'both'). Only for 'read_output'.",
                },
            },
            "required": ["operation"],
        },
    },

    # ================================================================
    # SHELL LINTING
    # ================================================================

    "shell_lint": {
        "name": "shell_lint",
        "description": (
            "Run static analysis on a shell script before executing it.\n\n"
            "Use after EVERY shell script edit, before shell_exec. "
            "Returns file:line:severity:rule:message for each issue found.\n\n"
            "  .ps1 files: uses PSScriptAnalyzer (Invoke-ScriptAnalyzer) if installed, "
            "falling back to the PSParser syntax checker.\n"
            "  .sh / .bash files: uses shellcheck -f json if on PATH, falling back to bash -n.\n\n"
            "Workflow: file_edit/apply_patch → shell_lint → fix all errors → "
            "shell_lint again to confirm clean → shell_exec.\n\n"
            "Never skip the second lint — small fixes can introduce new issues."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or repo-relative path to the .ps1, .sh, or .bash file to lint.",
                },
            },
            "required": ["path"],
        },
    },

    # ================================================================
    # TOOL RESULT RECALL
    # ================================================================

    "tool_result_recall": {
        "name": "tool_result_recall",
        "description": (
            "Retrieve the full content of a tool result that was truncated in context.\n\n"
            "When a tool result exceeds its context budget, the in-context message ends with:\n"
            "    ...[truncated to N/M chars — full result at data/tool_results/{session}/{call_id}.json]\n\n"
            "Pass the call_id from that marker to this tool to read the full content. "
            "Supports offset and limit for paging through large results.\n\n"
            "Use this instead of re-calling the original tool — the full result is already on disk."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tool_call_id": {
                    "type": "string",
                    "description": "The tool call ID from the truncation marker (the part before .json).",
                },
                "offset": {
                    "type": "integer",
                    "description": "Character offset to start reading from (default: 0).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum characters to return (default: 8000).",
                },
            },
            "required": ["tool_call_id"],
        },
    },

    # ================================================================
    # PYTHON CODER (disabled — kept for reference)
    # ================================================================

    "python_coder": {
        "name": "python_coder",
        "description": (
            "DEPRECATED — use code_exec instead. "
            "An internal LLM generates and runs Python code from your spec. "
            "Only use when the task is too open-ended or large to write with code_exec directly. "
            "Set timeout=0 only when the user explicitly wants no script wall-clock timeout."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": "A precise engineering spec for the code to generate.",
                },
                "context": {
                    "type": "string",
                    "description": "Optional file contents or data samples the script needs.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Maximum seconds for generated script execution (default: 300). Set 0 for no script wall-clock timeout.",
                },
            },
            "required": ["instruction"],
        },
    },
}

# Per-tool metadata: safety flags, UI activity descriptions, user-facing names.
# Mirrors openclaude's Tool.ts metadata fields.
TOOL_METADATA: dict = {
    "shell_exec":      {"is_read_only": False, "is_destructive": True,  "is_concurrency_safe": False, "activity": "Running shell command",   "user_name": "Shell"},
    "file_reader":     {"is_read_only": True,  "is_destructive": False, "is_concurrency_safe": True,  "activity": "Reading file",            "user_name": "File Reader"},
    "file_edit":       {"is_read_only": False, "is_destructive": False, "is_concurrency_safe": False, "activity": "Editing file",            "user_name": "File Editor"},
    "apply_patch":     {"is_read_only": False, "is_destructive": False, "is_concurrency_safe": False, "activity": "Applying V4A patch",      "user_name": "Apply Patch"},
    "file_patch":      {"is_read_only": False, "is_destructive": False, "is_concurrency_safe": False, "activity": "Applying patch",          "user_name": "File Patch"},
    "shell_lint":      {"is_read_only": True,  "is_destructive": False, "is_concurrency_safe": True,  "activity": "Linting shell script",    "user_name": "Shell Lint"},
    "tool_result_recall": {"is_read_only": True, "is_destructive": False, "is_concurrency_safe": True, "activity": "Recalling tool result",  "user_name": "Tool Recall"},
    "file_writer":     {"is_read_only": False, "is_destructive": True,  "is_concurrency_safe": False, "activity": "Writing file",            "user_name": "File Writer"},
    "file_navigator":  {"is_read_only": True,  "is_destructive": False, "is_concurrency_safe": True,  "activity": "Navigating files",        "user_name": "File Navigator"},
    "grep":            {"is_read_only": True,  "is_destructive": False, "is_concurrency_safe": True,  "activity": "Searching files",         "user_name": "Grep"},
    "code_exec":       {"is_read_only": False, "is_destructive": False, "is_concurrency_safe": False, "activity": "Executing code",          "user_name": "Code Exec"},
    "websearch":       {"is_read_only": True,  "is_destructive": False, "is_concurrency_safe": True,  "activity": "Searching the web",       "user_name": "Web Search"},
    "rag":             {"is_read_only": True,  "is_destructive": False, "is_concurrency_safe": True,  "activity": "Searching documents",     "user_name": "RAG"},
    "memo":            {"is_read_only": False, "is_destructive": False, "is_concurrency_safe": False, "activity": "Accessing memory",        "user_name": "Memo"},
    "todo_write":      {"is_read_only": False, "is_destructive": False, "is_concurrency_safe": False, "activity": "Updating task list",      "user_name": "Todo"},
    "process_monitor": {"is_read_only": False, "is_destructive": True,  "is_concurrency_safe": False, "activity": "Managing processes",      "user_name": "Process Monitor"},
    "agent":           {"is_read_only": False, "is_destructive": False, "is_concurrency_safe": True,  "activity": "Running subagent",        "user_name": "Agent"},
}
