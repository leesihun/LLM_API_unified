"""
Simple SQLite database for users and sessions
Human-readable JSON storage for conversations
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
    Store conversations as human-readable JSON files
    Format: data/sessions/{session_id}.json
    """

    def __init__(self, sessions_dir: str = "data/sessions"):
        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _get_session_file(self, session_id: str) -> Path:
        """Get the file path for a session"""
        return self.sessions_dir / f"{session_id}.json"

    def save_conversation(self, session_id: str, messages: List[Dict[str, str]]):
        """Save conversation to JSON file with file locking for concurrency safety"""
        session_file = self._get_session_file(session_id)
        lock_file = session_file.with_suffix('.lock')

        data = {
            "session_id": session_id,
            "updated_at": datetime.now().isoformat(),
            "messages": messages
        }

        # Use file lock to prevent concurrent write corruption
        with FileLock(lock_file, timeout=10):
            with open(session_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

    def load_conversation(self, session_id: str) -> Optional[List[Dict[str, str]]]:
        """Load conversation from JSON file with file locking for concurrency safety"""
        session_file = self._get_session_file(session_id)
        if not session_file.exists():
            return None

        lock_file = session_file.with_suffix('.lock')

        try:
            # Use file lock to ensure we don't read while another process is writing
            with FileLock(lock_file, timeout=10):
                with open(session_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get("messages", [])
        except Exception:
            return None

    def delete_conversation(self, session_id: str):
        """Delete a conversation file"""
        session_file = self._get_session_file(session_id)
        if session_file.exists():
            session_file.unlink()


# Global instances
db = Database()
conversation_store = ConversationStore()
