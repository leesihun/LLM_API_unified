"""DispatchMixin: in-process tool execution with parallel support."""
import asyncio
import time
from typing import List, Dict, Any, Optional

import config
from backend.core.llm_backend import ToolCall
from pathlib import Path

from tools.file_ops._postcheck import (
    check_python, is_python_path,
    check_typescript, is_typescript_path,
)
from tools.file_ops._agents_md import walk_up_for_agents_md, attach_to_result


class DispatchMixin:
    """Executes tool calls in-process; parallel via asyncio.gather."""

    def _tool_parameters(self, name: str) -> Dict[str, Any]:
        return config.TOOL_PARAMETERS.get(name, {})

    def _tool_timeout(self, name: str, arguments: Dict[str, Any], default: Optional[int] = None) -> Optional[int]:
        timeout = arguments.get("timeout")
        if timeout is not None:
            return timeout
        return self._tool_parameters(name).get("timeout", default)

    async def execute_tool(self, name: str, arguments: Dict[str, Any],
                           tool_call_id: str = None) -> Dict[str, Any]:
        start = time.time()
        print(f"\n{'='*70}")
        print(f"[TOOL] Executing: {name}")
        print(f"{'='*70}")
        for k, v in arguments.items():
            sv = str(v)
            print(f"  {k}: {sv[:150]}{'...' if len(sv) > 150 else ''}")

        try:
            result = await self._dispatch_tool(name, arguments, tool_call_id=tool_call_id)
            duration = time.time() - start
            print(f"[TOOL] {name} completed in {duration:.2f}s — success={result.get('success', '?')}")
            self.tool_calls_log.append({
                "name": name, "input": arguments,
                "tool_call_id": tool_call_id,
                "success": result.get("success", True), "duration": duration,
            })
            if len(self.tool_calls_log) > 200:
                self.tool_calls_log = self.tool_calls_log[-200:]
            self._log_tool_result(name, tool_call_id, result, duration)
            self._track_temp_files(name, result)
            await self._run_postchecks(name, result)
            self._inject_subtree_agents_md(name, arguments, result)
            return result
        except Exception as e:
            duration = time.time() - start
            print(f"[TOOL] {name} FAILED in {duration:.2f}s — {e}")
            err_result = {"success": False, "error": str(e)}
            self.tool_calls_log.append({
                "name": name, "input": arguments,
                "tool_call_id": tool_call_id,
                "success": False, "error": str(e), "duration": duration,
            })
            if len(self.tool_calls_log) > 200:
                self.tool_calls_log = self.tool_calls_log[-200:]
            self._log_tool_result(name, tool_call_id, err_result, duration)
            return err_result

    def _track_temp_files(self, name: str, result: Dict[str, Any]) -> None:
        """Register newly-created files (not flagged persist=True) for cleanup
        at end of run_stream. file_writer and apply_patch are the only tools
        that can create new files; file_edit only modifies existing ones."""
        if not result.get("success"):
            return
        tracker = getattr(self, "_tracked_new_files", None)
        if tracker is None:
            return
        if name == "file_writer":
            if result.get("new_file") and not result.get("persist"):
                path = result.get("path")
                if path:
                    tracker.add(path)
        elif name == "apply_patch":
            if result.get("persist"):
                return
            for change in result.get("files_changed", []) or []:
                if change.get("op") == "added":
                    path = change.get("path")
                    if path:
                        tracker.add(path)

    async def _run_postchecks(self, name: str, result: Dict[str, Any]) -> None:
        """Run lightweight post-write verification (Python syntax + TS typecheck).

        Attaches a `post_edit_check` field to *result* in-place so the model
        sees the verification outcome in the next turn. Never raises - check
        failures become structured data the model can react to.
        """
        if not result.get("success"):
            return
        py_paths: List[str] = []
        ts_paths: List[str] = []
        if name in ("file_writer", "file_edit"):
            path = result.get("path")
            if is_python_path(path):
                py_paths.append(path)
            elif is_typescript_path(path):
                ts_paths.append(path)
        elif name == "apply_patch":
            for change in result.get("files_changed", []) or []:
                if change.get("op") == "deleted":
                    continue
                path = change.get("path")
                if is_python_path(path):
                    py_paths.append(path)
                elif is_typescript_path(path):
                    ts_paths.append(path)
        if not py_paths and not ts_paths:
            return

        failures: List[Dict[str, Any]] = []
        all_paths: List[str] = py_paths + ts_paths

        if py_paths:
            outcomes = await asyncio.gather(*(check_python(p) for p in py_paths))
            failures.extend(
                {"path": p, "error": o.get("error", "")}
                for p, o in zip(py_paths, outcomes)
                if o.get("status") == "failed"
            )
        if ts_paths:
            # Typecheck is project-wide — one call covers all changed TS files.
            ts_outcome = await check_typescript(ts_paths[0])
            if ts_outcome.get("status") == "failed":
                failures.append({
                    "path": ", ".join(ts_paths),
                    "error": ts_outcome.get("error", ""),
                })

        if failures:
            result["post_edit_check"] = {
                "status": "failed",
                "failures": failures,
                "hint": "Fix the error before continuing. Re-read the file with file_reader if needed.",
            }
        else:
            result["post_edit_check"] = {"status": "passed", "files": all_paths}

    def _inject_subtree_agents_md(
        self, name: str, arguments: Dict[str, Any], result: Dict[str, Any]
    ) -> None:
        """When the agent reads into a subtree, surface that subtree's
        AGENTS.md / CLAUDE.md (if any, and not already seen this session).

        Only fires for the discovery tools - reader/navigator/grep. Walks
        parents of the accessed path up to the workspace root, capped by
        the per-session seen set on the agent loop instance.
        """
        if name not in ("file_reader", "file_navigator", "grep"):
            return
        if not result.get("success"):
            return

        accessed_raw = (
            result.get("path")
            or result.get("root")
            or arguments.get("path")
        )
        if not accessed_raw:
            return

        try:
            accessed = Path(accessed_raw)
        except Exception:
            return

        workspace_root = self.workspace_dir or getattr(
            config, "AGENT_DEFAULT_WORKSPACE", None
        )
        if not workspace_root:
            return

        seen = getattr(self, "_agents_md_seen", None)
        if seen is None:
            return

        try:
            discovered = walk_up_for_agents_md(accessed, Path(workspace_root), seen)
        except Exception as exc:
            self._log(f"  [AGENTS.md] walk-up failed for {accessed}: {exc}")
            return

        attach_to_result(result, discovered)

    async def _execute_tools_parallel(self, tool_calls: List[ToolCall]) -> List[Dict[str, Any]]:
        """Execute multiple tool calls concurrently."""
        tasks = [
            self.execute_tool(tc.function.name, tc.function.arguments, tool_call_id=tc.id)
            for tc in tool_calls
        ]
        return await asyncio.gather(*tasks)

    async def _dispatch_tool(self, name: str, arguments: Dict[str, Any], tool_call_id: str = None) -> Dict[str, Any]:
        cache = self._tool_cache

        if name == "websearch":
            if "websearch" not in cache:
                from tools.web_search import WebSearchTool
                cache["websearch"] = WebSearchTool()
            return await asyncio.to_thread(
                cache["websearch"].search,
                query=arguments["query"],
                max_results=arguments.get("max_results"),
            )

        elif name == "code_exec":
            if "code_exec" not in cache:
                from tools.code_exec import CodeExecTool
                cache["code_exec"] = CodeExecTool(session_id=self.session_id)
            return await cache["code_exec"].execute(
                code=arguments["code"],
                timeout=self._tool_timeout("code_exec", arguments),
            )

        elif name == "rag":
            if "rag" not in cache:
                from tools.rag import RAGTool
                cache["rag"] = RAGTool(username=self.username)
            available_collections = self._get_available_rag_collections()
            requested_collection = arguments.get("collection_name")

            if not available_collections:
                return {
                    "success": False,
                    "error": "No RAG collections are available for this user. Create a collection first.",
                    "available_collections": [],
                }

            if requested_collection not in available_collections:
                return {
                    "success": False,
                    "error": (
                        f"Invalid collection_name '{requested_collection}'. "
                        "Use one of the available collections."
                    ),
                    "available_collections": available_collections,
                }

            return await asyncio.to_thread(
                cache["rag"].retrieve,
                collection_name=requested_collection,
                query=arguments["query"],
                max_results=arguments.get("max_results"),
            )

        elif name == "file_reader":
            if "file_reader" not in cache:
                from tools.file_ops import FileReaderTool
                cache["file_reader"] = FileReaderTool(
                    username=self.username, session_id=self.session_id,
                    workspace_dir=self.workspace_dir,
                )
            return await asyncio.to_thread(
                cache["file_reader"].read,
                path=arguments["path"],
                offset=arguments.get("offset"),
                limit=arguments.get("limit"),
            )

        elif name == "file_writer":
            if "file_writer" not in cache:
                from tools.file_ops import FileWriterTool
                cache["file_writer"] = FileWriterTool(
                    session_id=self.session_id,
                    workspace_dir=self.workspace_dir,
                )
            return await asyncio.to_thread(
                cache["file_writer"].write,
                path=arguments["path"],
                content=arguments["content"],
                mode=arguments.get("mode", "write"),
                persist=bool(arguments.get("persist", False)),
            )

        elif name == "apply_patch":
            if "apply_patch" not in cache:
                from tools.file_ops import ApplyPatchTool
                cache["apply_patch"] = ApplyPatchTool(
                    session_id=self.session_id, username=self.username,
                    workspace_dir=self.workspace_dir,
                )
            return await asyncio.to_thread(
                cache["apply_patch"].apply,
                patch=arguments["patch"],
                persist=bool(arguments.get("persist", False)),
            )

        elif name == "shell_lint":
            if "shell_lint" not in cache:
                from tools.shell.lint import ShellLintTool
                cache["shell_lint"] = ShellLintTool()
            return await asyncio.to_thread(
                cache["shell_lint"].lint,
                path=arguments["path"],
            )

        elif name == "tool_result_recall":
            if "tool_result_recall" not in cache:
                from tools.recall.tool import ToolResultRecallTool
                cache["tool_result_recall"] = ToolResultRecallTool(session_id=self.session_id)
            return await asyncio.to_thread(
                cache["tool_result_recall"].recall,
                tool_call_id=arguments["tool_call_id"],
                offset=arguments.get("offset", 0),
                limit=arguments.get("limit", 8000),
            )

        elif name == "file_navigator":
            if "file_navigator" not in cache:
                from tools.file_ops import FileNavigatorTool
                cache["file_navigator"] = FileNavigatorTool(
                    username=self.username, session_id=self.session_id,
                    workspace_dir=self.workspace_dir,
                )
            return await asyncio.to_thread(
                cache["file_navigator"].navigate,
                operation=arguments["operation"],
                path=arguments.get("path"),
                pattern=arguments.get("pattern"),
            )

        elif name == "shell_exec":
            if "shell_exec" not in cache:
                from tools.shell import ShellExecTool
                cache["shell_exec"] = ShellExecTool(
                    session_id=self.session_id,
                    workspace_dir=self.workspace_dir,
                )
            desc = arguments.get("description")
            if desc:
                print(f"  [shell_exec] {desc}")
            return await cache["shell_exec"].execute(
                command=arguments["command"],
                timeout=self._tool_timeout("shell_exec", arguments, 300),
                working_directory=arguments.get("working_directory"),
            )

        elif name == "memo":
            if "memo" not in cache:
                from tools.memo import MemoTool
                cache["memo"] = MemoTool(username=self.username)
            return await asyncio.to_thread(
                cache["memo"].execute,
                operation=arguments["operation"],
                key=arguments.get("key"),
                value=arguments.get("value"),
            )

        elif name == "process_monitor":
            if "process_monitor" not in cache:
                from tools.process_monitor import ProcessMonitorTool
                cache["process_monitor"] = ProcessMonitorTool(session_id=self.session_id)
            return await asyncio.to_thread(
                cache["process_monitor"].execute,
                operation=arguments["operation"],
                command=arguments.get("command"),
                handle=arguments.get("handle"),
                working_directory=arguments.get("working_directory"),
                offset=arguments.get("offset"),
                max_lines=arguments.get("max_lines"),
                stream=arguments.get("stream"),
            )

        elif name == "file_edit":
            if "file_edit" not in cache:
                from tools.file_ops import FileEditorTool
                cache["file_edit"] = FileEditorTool(
                    session_id=self.session_id, username=self.username,
                    workspace_dir=self.workspace_dir,
                )
            return await asyncio.to_thread(
                cache["file_edit"].edit,
                path=arguments["path"],
                old_string=arguments["old_string"],
                new_string=arguments["new_string"],
                replace_all=arguments.get("replace_all", False),
            )

        elif name == "grep":
            if "grep" not in cache:
                from tools.grep import GrepTool
                cache["grep"] = GrepTool()
            return await asyncio.to_thread(
                cache["grep"].search,
                pattern=arguments["pattern"],
                path=arguments.get("path"),
                glob=arguments.get("glob"),
                output_mode=arguments.get("output_mode", "files_with_matches"),
                context=arguments.get("context", arguments.get("-C", 0)),
                before=arguments.get("-B", 0),
                after=arguments.get("-A", 0),
                case_insensitive=arguments.get("-i", False),
                file_type=arguments.get("type"),
                head_limit=arguments.get("head_limit", 250),
                offset=arguments.get("offset", 0),
                multiline=arguments.get("multiline", False),
            )

        elif name == "todo_write":
            if "todo_write" not in cache:
                from tools.todo import TodoTool
                cache["todo_write"] = TodoTool()
            result = await asyncio.to_thread(
                cache["todo_write"].write,
                todos=arguments.get("todos", []),
            )
            if result.get("success"):
                self._session_todos = result["todos"]
            return result

        elif name == "agent":
            if "agent" not in cache:
                from tools.agent import SubAgentTool
                cache["agent"] = SubAgentTool(session_id=self.session_id, username=self.username)
            # Derive a unique session_id per sub-agent invocation so each gets
            # a distinct llama.cpp KV slot — prevents parallel sub-agents from
            # serializing on the parent's slot.
            child_session_id = f"{self.session_id}::{tool_call_id}" if tool_call_id else self.session_id
            # SubAgentTool.execute is async — await directly (not to_thread)
            return await cache["agent"].execute(
                prompt=arguments["prompt"],
                subagent_type=arguments.get("subagent_type", "explore"),
                description=arguments.get("description"),
                child_session_id=child_session_id,
            )

        else:
            return {"success": False, "error": f"Unknown tool: {name}"}
