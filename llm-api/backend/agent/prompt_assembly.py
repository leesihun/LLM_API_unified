"""PromptMixin: system prompt, dynamic context, RAG/memo/file formatting, and tool schema helpers."""
import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

import config
from backend.agent._cache import (
    _CACHED_SYSTEM_PROMPT,
    _CACHED_TOOL_SCHEMAS,
    _load_memo_cached,
    _rag_collections_cache,
    _RAG_CACHE_TTL,
)


class PromptMixin:
    """Builds the static system prompt and per-request dynamic context."""

    def _build_system_prompt(self) -> str:
        """Return the STATIC system prompt (byte-stable for KV cache reuse)."""
        return _CACHED_SYSTEM_PROMPT

    def _build_dynamic_context(self, attached_files: Optional[List[Dict[str, Any]]] = None) -> Optional[str]:
        """Return per-request dynamic context (RAG, memo, files). Separate from
        system prompt so the static prefix stays byte-identical for cache_prompt."""
        parts = []
        repo_docs = self._format_repo_instructions_context()
        if repo_docs:
            parts.append(repo_docs)
        rag_ctx = self._format_rag_collections_context()
        if rag_ctx:
            parts.append(rag_ctx)
        if self.username and "memo" in self.enabled_tools:
            memo_ctx = _load_memo_cached(self.username)
            if memo_ctx:
                memo_cap = getattr(config, "AGENT_MEMO_MAX_CHARS", 2000)
                if len(memo_ctx) > memo_cap:
                    memo_ctx = memo_ctx[:memo_cap] + "\n...[memo context truncated]"
                parts.append(memo_ctx)
        if self._session_todos:
            parts.append(self._format_todos())
        if attached_files:
            parts.append(self._format_attached_files(attached_files))
        if not parts:
            return None
        dynamic_ctx = "\n".join(parts)
        dynamic_cap = getattr(config, "AGENT_DYNAMIC_CONTEXT_MAX_CHARS", 6000)
        if len(dynamic_ctx) > dynamic_cap:
            dynamic_ctx = dynamic_ctx[:dynamic_cap] + "\n...[dynamic context truncated]"
        return dynamic_ctx

    def _repo_doc_candidates(self) -> List[Path]:
        """Return repository instruction docs in precedence/read order."""
        repo_root = config.APP_DIR.parent.resolve()
        candidates = [
            repo_root / "AGENTS.md",
            repo_root / "CLAUDE.md",
            repo_root / "README.md",
            config.APP_DIR / "README.md",
            repo_root / "hoonbot" / "README.md",
            repo_root / "messenger" / "README.md",
        ]
        seen = set()
        unique = []
        for path in candidates:
            resolved = path.resolve()
            if resolved not in seen:
                unique.append(resolved)
                seen.add(resolved)
        return unique

    def _format_repo_instructions_context(self) -> str:
        """Inject discovered repo docs before the model plans or edits."""
        cap = getattr(config, "AGENT_REPO_DOC_CONTEXT_MAX_CHARS", 12000)
        if cap <= 0:
            return ""

        sections = []
        remaining = cap
        for path in self._repo_doc_candidates():
            if remaining <= 0 or not path.exists() or not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            if not text.strip():
                continue

            rel = path.relative_to(config.APP_DIR.parent.resolve())
            header = f"\n### {rel.as_posix()}\n"
            budget = remaining - len(header)
            if budget <= 0:
                break
            body = text[:budget]
            if len(text) > budget:
                body += "\n...[repo doc truncated]"
            sections.append(header + body)
            remaining -= len(header) + len(body)

        if not sections:
            return ""

        return (
            "\n\n## REPOSITORY INSTRUCTIONS DISCOVERED BEFORE WORK\n"
            "Follow these as repository guidance after higher-priority instructions. "
            "Use them before planning, editing, or verification.\n"
            + "\n".join(sections)
        )

    def _refresh_available_rag_collections(self):
        """Load available RAG collections for the current user (60s module-level TTL cache)."""
        self._available_rag_collections = []

        if "rag" not in self.enabled_tools or not self.username:
            return

        # Check module-level cache first
        cached = _rag_collections_cache.get(self.username)
        if cached and time.time() < cached["expires_at"]:
            self._available_rag_collections = cached["collections"]
            return

        try:
            from tools.rag import RAGTool
            tool = RAGTool(username=self.username)
            result = tool.list_collections()
            if not result.get("success"):
                return

            collections = result.get("collections", [])
            names = sorted({
                c.get("name")
                for c in collections
                if isinstance(c, dict) and isinstance(c.get("name"), str) and c.get("name")
            })
            self._available_rag_collections = names
            _rag_collections_cache[self.username] = {
                "collections": names,
                "expires_at": time.time() + _RAG_CACHE_TTL,
            }
        except Exception as e:
            print(f"[RAG] Failed to load available collections for prompt context: {e}")

    def _get_available_rag_collections(self) -> List[str]:
        if self._available_rag_collections is None:
            self._refresh_available_rag_collections()
        return self._available_rag_collections or []

    def _format_rag_collections_context(self) -> str:
        if "rag" not in self.enabled_tools:
            return ""

        available = self._get_available_rag_collections()
        lines = ["\n\n## RAG COLLECTIONS"]
        lines.append("Use only existing collection_name values from this list when calling the rag tool.")
        if available:
            lines.append(f"Available collection_name values: {json.dumps(available, ensure_ascii=False)}")
        else:
            lines.append("Available collection_name values: []")
            lines.append("No collection exists yet. Ask the user to create a collection before using rag.")
        return "\n".join(lines)

    def _format_todos(self) -> str:
        """Format session todos for injection into dynamic context."""
        status_icon = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
        lines = ["\n\n## CURRENT TASKS"]
        lines.append("Track progress here. Mark tasks completed immediately when done.")
        for t in self._session_todos:
            icon = status_icon.get(t.get("status", "pending"), "[ ]")
            priority = t.get("priority", "medium")
            lines.append(f"  {icon} {t['id']}: {t['content']} (priority: {priority})")
        return "\n".join(lines)

    def _format_attached_files(self, attached_files: List[Dict[str, Any]]) -> str:
        if not attached_files:
            return ""
        lines = ["\n\n## ATTACHED FILES"]
        lines.append(f"The user has attached {len(attached_files)} file(s).\n")
        for idx, f in enumerate(attached_files, 1):
            if "error" in f:
                lines.append(f"{idx}. {f['name']} - ERROR: {f['error']}")
                continue
            size_kb = f.get('size', 0) / 1024
            lines.append(f"{idx}. {f['name']} ({f.get('type', '?')}, {size_kb:.1f} KB)")
            if 'headers' in f:
                lines.append(f"   Columns: {', '.join(f['headers'])}")
                lines.append(f"   Rows: {f.get('rows', '?')}")
            if 'structure' in f:
                lines.append(f"   Structure: {f['structure']}")
                if f.get('keys'):
                    lines.append(f"   Keys: {', '.join(f['keys'][:10])}")
            if 'lines' in f:
                lines.append(f"   Lines: {f['lines']}")
                if f.get('definitions'):
                    lines.append(f"   Definitions: {', '.join(f['definitions'][:5])}")
            if 'preview' in f:
                preview_cap = getattr(config, "AGENT_FILE_PREVIEW_MAX_CHARS", 120)
                lines.append(f"   Preview: {str(f['preview'])[:preview_cap]}...")
        return "\n".join(lines)

    def _get_tool_schemas(self) -> Optional[List[Dict[str, Any]]]:
        if not self.enabled_tools:
            return None
        if self._filtered_tool_schemas is None:
            enabled = set(self.enabled_tools)
            self._filtered_tool_schemas = [
                s for s in _CACHED_TOOL_SCHEMAS
                if s["function"]["name"] in enabled
            ]
        return self._filtered_tool_schemas if self._filtered_tool_schemas else None
