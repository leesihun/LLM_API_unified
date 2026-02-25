"""
File Navigator Tool
List directory contents and search for files using glob patterns.
"""
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional


class FileNavigatorTool:
    """List and search files on local filesystem."""

    def __init__(self, username: str = None, session_id: str = None):
        self.username = username
        self.session_id = session_id

    def _resolve_base_path(self, path: Optional[str]) -> Path:
        """
        Resolve base path for list/find.

        If path is omitted, use current working directory.
        """
        if not path:
            return Path.cwd().resolve()
        target = Path(path).expanduser()
        if target.is_absolute():
            return target.resolve()
        return (Path.cwd() / target).resolve()

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
            return self._find_files(pattern or "*", path)
        else:
            return {"success": False, "error": f"Unknown operation: {operation}. Use 'list' or 'find'."}

    def _list_directory(self, path: Optional[str] = None) -> Dict[str, Any]:
        target = self._resolve_base_path(path)

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

    def _find_files(self, pattern: str, path: Optional[str] = None) -> Dict[str, Any]:
        root = self._resolve_base_path(path)
        if not root.exists():
            return {"success": False, "error": f"Path not found: {root}"}
        if not root.is_dir():
            return {"success": False, "error": f"Not a directory: {root}"}

        results = []
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
            "root": str(root),
            "pattern": pattern,
            "count": len(results),
        }
