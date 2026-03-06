import logging
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class Config:
    SECRET_TOKEN: str = os.getenv("SECRET_TOKEN", "changeme")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    CLAUDE_CMD: str = os.getenv("CLAUDE_CMD", "claude")
    CURSOR_CMD: str = os.getenv("CURSOR_CMD", "agent")
    WORKSPACE_DIR: str = os.getenv("WORKSPACE_DIR", str(Path.cwd()))
    MIN_TASK_GAP_SECONDS: int = int(os.getenv("MIN_TASK_GAP_SECONDS", "0"))
    TASK_TIMEOUT_SECONDS: int = int(os.getenv("TASK_TIMEOUT_SECONDS", "1800"))
    TUNNEL_ENABLED: bool = os.getenv("TUNNEL_ENABLED", "false").lower() == "true"
    CLOUDFLARED_CMD: str = os.getenv("CLOUDFLARED_CMD", "cloudflared")
    MAX_PROMPT_LENGTH: int = 10000
    MAX_DELAY_MINUTES: float = 10080  # 7 days

    _active_workspace: str | None = None

    @property
    def active_workspace(self) -> str:
        return self._active_workspace or self.WORKSPACE_DIR

    @active_workspace.setter
    def active_workspace(self, value: str) -> None:
        self._active_workspace = value

    def list_workspaces(self) -> list[str]:
        """Return sorted subdirectory names inside WORKSPACE_DIR."""
        base = Path(self.WORKSPACE_DIR)
        return sorted(p.name for p in base.iterdir() if p.is_dir())

    def set_workspace(self, name: str) -> str:
        """Set active workspace to a subdirectory of WORKSPACE_DIR. Returns the full path."""
        base = Path(self.WORKSPACE_DIR)
        target = base / name
        if not target.is_dir():
            raise ValueError(f"Not a valid directory: {name}")
        self._active_workspace = str(target)
        logger.info(f"Workspace changed to: {self._active_workspace}")
        return self._active_workspace

    def validate(self) -> None:
        """Validate configuration on startup."""
        errors = []

        ws_path = Path(self.WORKSPACE_DIR)
        if not ws_path.exists():
            errors.append(f"WORKSPACE_DIR does not exist: {self.WORKSPACE_DIR}")
        elif not ws_path.is_dir():
            errors.append(f"WORKSPACE_DIR is not a directory: {self.WORKSPACE_DIR}")

        if not shutil.which(self.CLAUDE_CMD):
            logger.warning(f"CLAUDE_CMD not found on PATH: {self.CLAUDE_CMD}")
        if not shutil.which(self.CURSOR_CMD):
            logger.warning(f"CURSOR_CMD not found on PATH: {self.CURSOR_CMD}")

        if self.TUNNEL_ENABLED and not shutil.which(self.CLOUDFLARED_CMD):
            errors.append(
                f"TUNNEL_ENABLED is true but CLOUDFLARED_CMD not found on PATH: "
                f"{self.CLOUDFLARED_CMD}"
            )

        if self.PORT < 1 or self.PORT > 65535:
            errors.append(f"PORT must be 1-65535, got {self.PORT}")
        if self.TASK_TIMEOUT_SECONDS < 10:
            errors.append(f"TASK_TIMEOUT_SECONDS must be >= 10, got {self.TASK_TIMEOUT_SECONDS}")
        if self.MIN_TASK_GAP_SECONDS < 0:
            errors.append(f"MIN_TASK_GAP_SECONDS must be >= 0, got {self.MIN_TASK_GAP_SECONDS}")

        if errors:
            error_msg = "Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
            logger.error(error_msg)
            raise ValueError(error_msg)

        logger.info("Configuration validated successfully")


config = Config()
