"""
Tool Configuration and Schemas
Define all available tools with their schemas for LLM native tool calling.
"""
from typing import List, Dict, Any

import config


# ============================================================================
# Tool Schemas
# ============================================================================

TOOL_SCHEMAS = {
    "websearch": {
        "name": "websearch",
        "description": "Search the web for current information and get answers to questions. Use this when you need up-to-date information, facts, news, or information not in your knowledge base.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to find information about"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of search results to return (default: 5)",
                    "default": 5
                }
            },
            "required": ["query"]
        },
    },

    "python_coder": {
        "name": "python_coder",
        "description": (
            "Execute a coding task by providing natural language instructions. "
            "An AI coding agent will generate Python code, execute it, and return the results. "
            "Describe WHAT you want done — not HOW. "
            "Example: 'Read sales.csv, compute monthly totals, and save a bar chart to chart.png'"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": (
                        "Natural language instruction describing the task. "
                        "Be specific about: what to compute, expected outputs, "
                        "files to read/create, and any constraints."
                    )
                },
                "session_id": {
                    "type": "string",
                    "description": "Session ID for workspace isolation (injected by agent)"
                },
                "timeout": {
                    "type": "integer",
                    "description": "Execution timeout in seconds (optional)",
                    "default": 30
                }
            },
            "required": ["instruction", "session_id"]
        },
    },

    "rag": {
        "name": "rag",
        "description": "Retrieve relevant information from document collections using semantic search. Query user-specific document collections. Documents must be uploaded first using the RAG upload API.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The query to search for in the document database"
                },
                "collection_name": {
                    "type": "string",
                    "description": "Name of the document collection to search in (required)"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of documents to retrieve (default: 5)",
                    "default": 5
                }
            },
            "required": ["query", "collection_name"]
        },
    },

    "file_reader": {
        "name": "file_reader",
        "description": "Read the contents of a file from the user's uploads or scratch workspace. Use this for viewing text files, code, CSV data, logs, configs, etc. Prefer this over python_coder for simple file reading. Supports offset and limit for large files.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path — relative to workspace (e.g. 'data.csv') or absolute within allowed directories"
                },
                "offset": {
                    "type": "integer",
                    "description": "Start reading from this line number (1-based). Optional."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to return. Optional."
                },
                "session_id": {
                    "type": "string",
                    "description": "Session ID for workspace resolution (injected by agent)"
                }
            },
            "required": ["path", "session_id"]
        },
    },

    "file_writer": {
        "name": "file_writer",
        "description": "Write or append text content to a file in the scratch workspace. Use this for creating text files, saving results, writing code files, etc. Prefer this over python_coder for simple file creation.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to scratch workspace (e.g. 'output.txt', 'scripts/run.py')"
                },
                "content": {
                    "type": "string",
                    "description": "The text content to write to the file"
                },
                "mode": {
                    "type": "string",
                    "description": "Write mode: 'write' to overwrite (default), 'append' to add to end",
                    "enum": ["write", "append"],
                    "default": "write"
                },
                "session_id": {
                    "type": "string",
                    "description": "Session ID for workspace resolution (injected by agent)"
                }
            },
            "required": ["path", "content", "session_id"]
        },
    },

    "file_navigator": {
        "name": "file_navigator",
        "description": "List directory contents or search for files using glob patterns in the user's uploads and scratch workspace. Use this to explore available files before reading them.",
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "description": "Operation: 'list' to list a directory, 'find' to search with glob pattern",
                    "enum": ["list", "find"]
                },
                "path": {
                    "type": "string",
                    "description": "Directory path for 'list' operation. Omit to see workspace roots."
                },
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern for 'find' operation (e.g. '*.csv', '**/*.py')"
                },
                "session_id": {
                    "type": "string",
                    "description": "Session ID for workspace resolution (injected by agent)"
                }
            },
            "required": ["operation", "session_id"]
        },
    },

    "shell_exec": {
        "name": "shell_exec",
        "description": "Execute a shell command in the scratch workspace. Use this for running scripts, installing packages, git operations, or any command-line task. Prefer this over python_coder with subprocess.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute"
                },
                "timeout": {
                    "type": "integer",
                    "description": "Maximum execution time in seconds (default: 30)",
                    "default": 30
                },
                "working_directory": {
                    "type": "string",
                    "description": "Working directory relative to scratch workspace. Optional."
                },
                "session_id": {
                    "type": "string",
                    "description": "Session ID for workspace isolation (injected by agent)"
                }
            },
            "required": ["command", "session_id"]
        },
    },

    "memory": {
        "name": "memory",
        "description": "Persistent key-value store for remembering information across sessions. Use this to store user preferences, project context, frequently used settings, or any information that should persist between conversations.",
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "description": "Operation: 'set' to store, 'get' to retrieve, 'delete' to remove, 'list' to see all keys",
                    "enum": ["set", "get", "delete", "list"]
                },
                "key": {
                    "type": "string",
                    "description": "The key to operate on (required for set/get/delete)"
                },
                "value": {
                    "type": "string",
                    "description": "The value to store (required for set)"
                }
            },
            "required": ["operation"]
        },
    },
}


# ============================================================================
# Helper Functions
# ============================================================================

def get_tool_schema(tool_name: str) -> Dict[str, Any]:
    return TOOL_SCHEMAS.get(tool_name)


def get_all_tool_schemas() -> Dict[str, Dict[str, Any]]:
    return TOOL_SCHEMAS


def get_available_tools() -> List[str]:
    return list(TOOL_SCHEMAS.keys())


def get_native_tool_schemas(exclude_injected: bool = True) -> List[Dict[str, Any]]:
    """
    Format tool schemas for llama.cpp native tool calling.
    When exclude_injected=True, removes session_id from python_coder
    (agent injects it automatically).
    """
    tools = []

    for tool_name, schema in TOOL_SCHEMAS.items():
        params = dict(schema["parameters"])
        props = dict(params.get("properties", {}))
        required = list(params.get("required", []))

        if exclude_injected:
            props.pop("session_id", None)
            if "session_id" in required:
                required.remove("session_id")

        tools.append({
            "type": "function",
            "function": {
                "name": schema["name"],
                "description": schema["description"],
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        })

    return tools
