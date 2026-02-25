"""
File Reader Tool
Read file contents from local filesystem.
Lightweight alternative to python_coder for simple file reading.
"""
from pathlib import Path
from typing import Dict, Any, Optional

import config


TEXT_EXTENSIONS = {
    '.txt', '.md', '.json', '.csv', '.py', '.js', '.ts', '.jsx', '.tsx',
    '.html', '.css', '.xml', '.yaml', '.yml', '.log', '.ini', '.cfg',
    '.toml', '.sh', '.bat', '.ps1', '.sql', '.r', '.java', '.cpp', '.c',
    '.h', '.go', '.rs', '.rb', '.php', '.swift', '.kt', '.scala', '.lua',
    '.pl', '.m', '.tex', '.rst', '.org', '.env', '.gitignore', '.dockerfile',
}

MAX_READ_BYTES = 50 * 1024  # 50KB cap


class FileReaderTool:
    """Read files from local filesystem."""

    def __init__(self, username: str = None, session_id: str = None):
        self.username = username
        self.session_id = session_id

    def _resolve_path(self, path: str) -> Path:
        """Resolve path to an absolute local path."""
        target = Path(path).expanduser()
        if target.is_absolute():
            return target.resolve()

        if self.session_id:
            scratch_path = (config.SCRATCH_DIR / self.session_id / target).resolve()
            if scratch_path.exists():
                return scratch_path

        if self.username:
            upload_path = (config.UPLOAD_DIR / self.username / target).resolve()
            if upload_path.exists():
                return upload_path

        return (Path.cwd() / target).resolve()

    def read(
        self,
        path: str,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Read file contents.

        Args:
            path: Absolute path or path relative to current working directory
            offset: Start reading from this line number (1-based)
            limit: Maximum number of lines to return
        """
        resolved = self._resolve_path(path)

        if not resolved.is_file():
            raise FileNotFoundError(f"Not a file: {path}")

        file_size = resolved.stat().st_size
        suffix = resolved.suffix.lower()

        if suffix not in TEXT_EXTENSIONS and suffix != '':
            return {
                "success": False,
                "error": f"Unsupported file type: {suffix}. Only text files are supported.",
                "path": str(resolved),
                "size": file_size,
            }

        truncated = False
        try:
            raw = resolved.read_bytes()
            try:
                text = raw.decode('utf-8')
            except UnicodeDecodeError:
                text = raw.decode('latin-1')

            lines = text.splitlines(keepends=True)
            total_lines = len(lines)

            if offset is not None or limit is not None:
                start = max(0, (offset or 1) - 1)
                end = start + limit if limit else total_lines
                lines = lines[start:end]

            content = ''.join(lines)
            if len(content) > MAX_READ_BYTES:
                content = content[:MAX_READ_BYTES]
                truncated = True

            return {
                "success": True,
                "content": content,
                "path": str(resolved),
                "size": file_size,
                "total_lines": total_lines,
                "lines_returned": len(lines),
                "truncated": truncated,
            }

        except Exception as e:
            return {"success": False, "error": str(e), "path": str(resolved)}
