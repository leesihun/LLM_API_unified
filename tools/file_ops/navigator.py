"""
File Navigator Tool
List directory contents and search for files using glob patterns.
"""
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

import config


class FileNavigatorTool:
    """List and search files in uploads and scratch workspaces."""

    def __init__(self, username: str = None, session_id: str = None):
        self.username = username
        self.session_id = session_id

    def _get_allowed_roots(self) -> List[Path]:
        roots = []
        if self.session_id:
            scratch = config.SCRATCH_DIR / self.session_id
            scratch.mkdir(parents=True, exist_ok=True)
            roots.append(scratch)
        if self.username:
            uploads = config.UPLOAD_DIR / self.username
            uploads.mkdir(parents=True, exist_ok=True)
            roots.append(uploads)
        return roots

    def _is_within_allowed(self, path: Path) -> bool:
        resolved = path.resolve()
        for root in self._get_allowed_roots():
            if str(resolved).startswith(str(root.resolve())):
                return True
        return False

    def navigate(
        self,
        operation: str = "list",
        path: Optional[str] = None,
        pattern: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        List directory contents or search for files.

        Args:
            operation: "list" to list directory, "find" to search with glob
            path: Directory path for list operation (relative or absolute)
            pattern: Glob pattern for find operation (e.g. "*.csv", "**/*.py")
        """
        if operation == "list":
            return self._list_directory(path)
        elif operation == "find":
            return self._find_files(pattern or "*")
        else:
            return {"success": False, "error": f"Unknown operation: {operation}. Use 'list' or 'find'."}

    def _list_directory(self, path: Optional[str] = None) -> Dict[str, Any]:
        if path:
            target = Path(path)
            if not target.is_absolute():
                # Try scratch first, then uploads
                candidates = []
                if self.session_id:
                    candidates.append(config.SCRATCH_DIR / self.session_id / path)
                if self.username:
                    candidates.append(config.UPLOAD_DIR / self.username / path)

                target = None
                for c in candidates:
                    if c.exists() and c.is_dir():
                        target = c
                        break

                if target is None:
                    return {"success": False, "error": f"Directory not found: {path}"}
            else:
                target = target.resolve()
                if not self._is_within_allowed(target):
                    raise PermissionError("Access denied: path outside allowed directories")
        else:
            # List all roots
            entries = []
            for root in self._get_allowed_roots():
                entries.append({
                    "name": root.name,
                    "path": str(root),
                    "is_dir": True,
                    "type": "scratch" if "scratch" in str(root) else "uploads",
                })
            return {"success": True, "files": entries, "path": "workspace roots"}

        if not target.is_dir():
            return {"success": False, "error": f"Not a directory: {path}"}

        entries = []
        for item in sorted(target.iterdir()):
            stat = item.stat()
            entries.append({
                "name": item.name,
                "path": str(item),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "is_dir": item.is_dir(),
            })

        return {"success": True, "files": entries, "path": str(target)}

    def _find_files(self, pattern: str) -> Dict[str, Any]:
        results = []
        for root in self._get_allowed_roots():
            for match in root.glob(pattern):
                if match.is_file():
                    stat = match.stat()
                    results.append({
                        "name": match.name,
                        "path": str(match),
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    })

        return {
            "success": True,
            "files": results,
            "pattern": pattern,
            "count": len(results),
        }
