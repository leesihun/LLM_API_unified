"""
Tool schemas for the LLM agent (OpenAI function-calling format).

Consumed by backend/agent.py at module load time to build the tool list
sent to llama.cpp. Parameter names must exactly match what _dispatch_tool()
passes to each tool's execute/read/write/navigate method.
"""

TOOL_SCHEMAS: dict = {
    "code_exec": {
        "name": "code_exec",
        "description": (
            "Default tool for coding tasks. Execute Python code directly — pass the complete, "
            "ready-to-run script as the 'code' argument. Runs in the session workspace, returns "
            "stdout/stderr/returncode. Use this for any task where you can write the code yourself: "
            "file processing, data analysis, calculations, multi-step logic, library calls. "
            "Only fall back to python_coder when the task genuinely requires the LLM to author "
            "a substantial program from a high-level description."
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
                    "description": "Maximum seconds for execution (default: 300).",
                },
            },
            "required": ["code"],
        },
    },

    "websearch": {
        "name": "websearch",
        "description": (
            "Search the web for current information, news, or facts not in your training data. "
            "Returns a list of results with titles, URLs, and content snippets."
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

    "python_coder": {
        "name": "python_coder",
        "description": (
            "An internal LLM generates and runs Python code from your spec. "
            "Only use when the task is too open-ended or large to write with code_exec directly. "
            "BEFORE calling: read all input files with file_reader so you know exact schemas, "
            "column names, and formats. Then write a precise spec — vague instructions fail."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": (
                        "A precise engineering spec. Include all that apply:\n"
                        "GOAL: one sentence — what the script must produce\n"
                        "INPUTS: exact filenames, column names, data types (paste schema inline)\n"
                        "OUTPUTS: exactly what to print to stdout AND what files to create with format\n"
                        "CONSTRAINTS: required packages, error behavior, things to avoid\n\n"
                        "BAD:  'Analyze the CSV and make a chart'\n"
                        "GOOD: 'Read sales.csv (cols: date str, product str, units int, revenue float). "
                        "Compute monthly revenue per product. Print markdown table sorted by revenue desc. "
                        "Save monthly_revenue.csv with cols: month,product,revenue.'"
                    ),
                },
                "context": {
                    "type": "string",
                    "description": (
                        "Optional. Paste file contents, data samples, code snippets, or API responses "
                        "the script needs. Include full content here — do not reference files by path "
                        "without also providing their content. Read files first with file_reader, "
                        "then paste the relevant portions here."
                    ),
                },
                "timeout": {
                    "type": "integer",
                    "description": "Maximum seconds for code generation + execution (default: 300).",
                },
            },
            "required": ["instruction"],
        },
    },

    "rag": {
        "name": "rag",
        "description": (
            "Retrieve relevant information from user-uploaded document collections using semantic search. "
            "You must specify which collection to search. "
            "Use only existing collection_name values listed in context. "
            "Results are document chunks ranked by relevance."
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

    "file_reader": {
        "name": "file_reader",
        "description": (
            "Read the contents of a text file. Supports absolute paths (anywhere on the system) "
            "as well as relative paths resolved in this order: session scratch workspace, user uploads, then current working directory. "
            "If the path is known, call file_reader directly instead of exploring first. "
            "Use this instead of python_coder when you just need to see file contents. "
            "Large files can be read in chunks using offset and limit."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Path to the file. Absolute paths (e.g. C:/Users/.../file.txt) are read directly. "
                        "Relative paths are resolved against the session scratch workspace first, then user uploads, then the current working directory."
                    ),
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (1-based, default: 1).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read (default: all).",
                },
            },
            "required": ["path"],
        },
    },

    "file_writer": {
        "name": "file_writer",
        "description": (
            "Write or append text content to a file. Supports absolute paths (anywhere on the system). "
            "Creates parent directories automatically. "
            "Use this instead of python_coder when you just need to save text to a file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Path to the file. Absolute paths write directly to that location. "
                        "Relative paths write inside the session scratch workspace."
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
            "List directory contents or search for files using glob patterns. "
            "Supports absolute paths (anywhere on the system) as well as the session scratch workspace. "
            "Use this only when paths are unknown; avoid repeated retries with equivalent path variants."
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

    "shell_exec": {
        "name": "shell_exec",
        "description": (
            "Execute shell commands. Use for running scripts, package management, git operations, "
            "or any command-line task. "
            "Multiple shell_exec calls in a single turn run concurrently — use this for parallel work. "
            "For long-running scripts, set a large timeout (e.g. 600–3600). "
            "If the process exceeds the timeout, the result reports that it is still running and includes the PID. "
            "Use process_monitor instead when you need incremental output or background process management."
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
                    "description": (
                        "Maximum seconds to wait before returning partial output (default: 300). "
                        "Process is NOT killed on timeout — use 'kill <pid>' to stop it."
                    ),
                },
                "working_directory": {
                    "type": "string",
                    "description": "Working directory for the command. Defaults to the session scratch workspace; relative paths resolve there too.",
                },
            },
            "required": ["command"],
        },
    },

    "memo": {
        "name": "memo",
        "description": (
            "Read or write persistent memory that survives across sessions. "
            "Use to save important results, decisions, file paths, or any fact you want to "
            "remember in future conversations. Memory is per-user and automatically shown "
            "at the start of every session."
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

    "process_monitor": {
        "name": "process_monitor",
        "description": (
            "Manage background processes: start long-running commands, check their status, "
            "read their accumulated output, or kill them. Use this instead of shell_exec when "
            "you need to launch a process and check on it later (e.g., servers, builds, watchers). "
            "Each process gets a handle like 'proc_1' for future reference."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["start", "status", "read_output", "kill", "list"],
                    "description": (
                        "'start': launch a background command, returns a handle. "
                        "'status': check if a process is running/exited (by handle). "
                        "'read_output': get stdout/stderr since last read or from an offset (by handle). "
                        "'kill': terminate a process (by handle). "
                        "'list': show all tracked processes for this session."
                    ),
                },
                "command": {
                    "type": "string",
                    "description": "Shell command to run (required for 'start' operation).",
                },
                "handle": {
                    "type": "string",
                    "description": "Process handle (e.g. 'proc_1'). Required for 'status', 'read_output', 'kill'.",
                },
                "working_directory": {
                    "type": "string",
                    "description": "Working directory for the command (only for 'start'). Defaults to scratch workspace.",
                },
                "offset": {
                    "type": "integer",
                    "description": (
                        "Line offset for 'read_output'. Returns lines starting from this offset. "
                        "Use the 'next_offset' value from a previous read to get new lines. "
                        "If omitted, returns the last 200 lines (tail mode)."
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
}
