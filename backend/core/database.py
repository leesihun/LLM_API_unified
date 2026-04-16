"""
Simple SQLite database for users and sessions.
Append-only JSONL storage for conversation history.
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
from filelock import FileLock

import config


class Database:
    """Simple SQLite database wrapper"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.DATABASE_PATH
        self.init_db()

    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Return rows as dictionaries
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self):
        """Initialize database tables"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT DEFAULT 'user',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Sessions table (lightweight metadata only)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    message_count INTEGER DEFAULT 0,
                    FOREIGN KEY (username) REFERENCES users(username)
                )
            """)

            # Add title column if it doesn't exist (migration for existing DBs)
            cols = [row[1] for row in cursor.execute("PRAGMA table_info(sessions)").fetchall()]
            if "title" not in cols:
                cursor.execute("ALTER TABLE sessions ADD COLUMN title TEXT")

            # Create default admin user
            self._create_default_admin()

    def _create_default_admin(self):
        """Create default admin user if not exists"""
        # Import here to avoid circular dependency
        from passlib.context import CryptContext

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Validate password length before hashing (bcrypt limit: 72 bytes)
                password_bytes = config.DEFAULT_ADMIN_PASSWORD.encode('utf-8')
                password_to_hash = config.DEFAULT_ADMIN_PASSWORD
                
                if len(password_bytes) > 72:
                    print(f"Warning: DEFAULT_ADMIN_PASSWORD exceeds 72 bytes ({len(password_bytes)} bytes).")
                    print("Please update config.DEFAULT_ADMIN_PASSWORD to be 72 bytes or less.")
                    # Truncate to 72 bytes as a fallback
                    password_to_hash = config.DEFAULT_ADMIN_PASSWORD.encode('utf-8')[:72].decode('utf-8', errors='ignore')
                
                pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
                password_hash = pwd_context.hash(password_to_hash)
                
                cursor.execute(
                    "INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                    (
                        config.DEFAULT_ADMIN_USERNAME,
                        password_hash,
                        "admin"
                    )
                )
        except Exception as e:
            print(f"Warning: Could not create default admin: {e}")

    # ========================================================================
    # User operations
    # ========================================================================
    def create_user(self, username: str, password_hash: str, role: str = "user") -> bool:
        """Create a new user"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                    (username, password_hash, role)
                )
                return True
        except sqlite3.IntegrityError:
            return False

    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user by username"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            row = cursor.fetchone()
            return dict(row) if row else None

    # ========================================================================
    # Session operations
    # ========================================================================
    def create_session(self, session_id: str, username: str) -> bool:
        """Create a new session"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO sessions (id, username) VALUES (?, ?)",
                    (session_id, username)
                )
                return True
        except sqlite3.IntegrityError:
            return False

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session metadata"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_session_message_count(self, session_id: str, count: int):
        """Update message count for session"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE sessions SET message_count = ? WHERE id = ?",
                (count, session_id)
            )

    def increment_session_message_count(self, session_id: str, delta: int):
        """Increment message count for a session."""
        if delta == 0:
            return
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE sessions SET message_count = COALESCE(message_count, 0) + ? WHERE id = ?",
                (delta, session_id)
            )

    def list_user_sessions(self, username: str) -> List[Dict[str, Any]]:
        """List all sessions for a user"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM sessions WHERE username = ? ORDER BY created_at DESC",
                (username,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def update_session_title(self, session_id: str, title: str):
        """Set or update the title for a session."""
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE sessions SET title = ? WHERE id = ?",
                (title, session_id)
            )

    def search_sessions(self, username: str, query: str) -> List[Dict[str, Any]]:
        """Search sessions by title or session ID for a user."""
        pattern = f"%{query}%"
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM sessions WHERE username = ? AND (title LIKE ? OR id LIKE ?) ORDER BY created_at DESC",
                (username, pattern, pattern)
            )
            return [dict(row) for row in cursor.fetchall()]


class ConversationStore:
    """
    Store conversations as append-only JSONL plus a small recent-message cache.

    Files:
      - data/sessions/{session_id}.jsonl
      - data/sessions/{session_id}.recent.json
      - data/sessions/{session_id}.lock

    Legacy sessions stored as data/sessions/{session_id}.json are migrated on first access.
    """

    def __init__(self, sessions_dir: str = "data/sessions"):
        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _get_session_log_file(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.jsonl"

    def _get_recent_file(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.recent.json"

    def _get_legacy_file(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.json"

    def _get_lock_file(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.lock"

    def _recent_window(self) -> int:
        return max(1, int(getattr(config, "MAX_CONVERSATION_HISTORY", 50)))

    def _session_exists(self, session_id: str) -> bool:
        return (
            self._get_session_log_file(session_id).exists()
            or self._get_recent_file(session_id).exists()
            or self._get_legacy_file(session_id).exists()
        )

    def save_conversation(self, session_id: str, messages: List[Dict[str, Any]]):
        """Rewrite the full conversation history."""
        with FileLock(self._get_lock_file(session_id), timeout=10):
            self._write_full_conversation_unlocked(session_id, messages)

    def append_messages(self, session_id: str, messages: List[Dict[str, Any]]):
        """Append new messages and refresh the bounded hot-history cache."""
        if not messages:
            return

        with FileLock(self._get_lock_file(session_id), timeout=10):
            self._ensure_migrated_unlocked(session_id)

            log_file = self._get_session_log_file(session_id)
            with open(log_file, 'a', encoding='utf-8') as f:
                for message in messages:
                    f.write(json.dumps(message, ensure_ascii=False, default=str))
                    f.write("\n")

            recent_messages = self._load_recent_unlocked(session_id)
            recent_messages.extend(messages)
            self._write_recent_unlocked(
                session_id,
                recent_messages[-self._recent_window():],
            )

    def load_conversation(self, session_id: str) -> Optional[List[Dict[str, Any]]]:
        """Load the full conversation history."""
        if not self._session_exists(session_id):
            return None

        try:
            with FileLock(self._get_lock_file(session_id), timeout=10):
                self._ensure_migrated_unlocked(session_id)
                return self._read_log_unlocked(session_id)
        except Exception:
            return None

    def load_recent_conversation(
        self,
        session_id: str,
        limit: Optional[int] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """Load the recent conversation cache used on the hot request path."""
        if not self._session_exists(session_id):
            return None

        try:
            with FileLock(self._get_lock_file(session_id), timeout=10):
                self._ensure_migrated_unlocked(session_id)
                recent_messages = self._load_recent_unlocked(session_id)
                if not recent_messages:
                    full_messages = self._read_log_unlocked(session_id)
                    recent_messages = full_messages[-self._recent_window():]
                    self._write_recent_unlocked(session_id, recent_messages)
                if limit is not None and limit >= 0:
                    if limit == 0:
                        return []
                    return recent_messages[-limit:]
                return recent_messages
        except Exception:
            return None

    def _ensure_migrated_unlocked(self, session_id: str):
        log_file = self._get_session_log_file(session_id)
        if log_file.exists():
            return

        legacy_file = self._get_legacy_file(session_id)
        if not legacy_file.exists():
            return

        with open(legacy_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        messages = data.get("messages", [])
        self._write_full_conversation_unlocked(session_id, messages)
        if legacy_file.exists():
            legacy_file.unlink()

    def _write_full_conversation_unlocked(self, session_id: str, messages: List[Dict[str, Any]]):
        log_file = self._get_session_log_file(session_id)
        with open(log_file, 'w', encoding='utf-8') as f:
            for message in messages:
                f.write(json.dumps(message, ensure_ascii=False, default=str))
                f.write("\n")

        self._write_recent_unlocked(session_id, messages[-self._recent_window():])

        legacy_file = self._get_legacy_file(session_id)
        if legacy_file.exists():
            legacy_file.unlink()

    def _read_log_unlocked(self, session_id: str) -> List[Dict[str, Any]]:
        log_file = self._get_session_log_file(session_id)
        if not log_file.exists():
            return []

        messages: List[Dict[str, Any]] = []
        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                messages.append(json.loads(line))
        return messages

    def _load_recent_unlocked(self, session_id: str) -> List[Dict[str, Any]]:
        recent_file = self._get_recent_file(session_id)
        if not recent_file.exists():
            return []

        try:
            with open(recent_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get("messages", [])
        except Exception:
            return []

    def _write_recent_unlocked(self, session_id: str, messages: List[Dict[str, Any]]):
        recent_file = self._get_recent_file(session_id)
        payload = {
            "session_id": session_id,
            "updated_at": datetime.now().isoformat(),
            "messages": messages,
        }
        with open(recent_file, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    def delete_conversation(self, session_id: str):
        """Delete all conversation artifacts for a session."""
        for path in (
            self._get_session_log_file(session_id),
            self._get_recent_file(session_id),
            self._get_legacy_file(session_id),
            self._get_lock_file(session_id),
        ):
            if path.exists():
                path.unlink()


# Global instances
db = Database()
conversation_store = ConversationStore()
