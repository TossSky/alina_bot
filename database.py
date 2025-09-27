"""Database Module - SQLite Storage for Conversations"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class DialogueDB:
    """SQLite database for storing user conversations and subscriptions"""
    
    def __init__(self, db_path: str = "alina.db"):
        self.db_path = db_path
        self.init_db()
    
    @contextmanager
    def _get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def init_db(self):
        """Initialize database tables"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    total_messages INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    user_data TEXT DEFAULT '{}'
                )
            """)
            
            # Messages table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    role TEXT,
                    content TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            """)
            
            # Index for fast queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_user_timestamp
                ON messages (user_id, timestamp DESC)
            """)
    
    def get_or_create_user(self, user_id: int) -> Dict:
        """Get or create user record"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT user_id, created_at, last_active, total_messages, total_tokens, user_data "
                "FROM users WHERE user_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                cursor.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
                return {
                    "user_id": user_id,
                    "created_at": datetime.now().isoformat(),
                    "last_active": datetime.now().isoformat(),
                    "total_messages": 0,
                    "total_tokens": 0,
                    "user_data": {}
                }
            
            cursor.execute("UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
            
            user_dict = dict(zip(
                ["user_id", "created_at", "last_active", "total_messages", "total_tokens", "user_data"],
                row
            ))
            
            try:
                user_dict["user_data"] = json.loads(user_dict.get("user_data") or "{}")
            except Exception:
                user_dict["user_data"] = {}
            
            return user_dict
    
    def add_message(self, user_id: int, role: str, content: str, tokens_used: int = 0):
        """Add message to conversation history"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Insert message
            cursor.execute(
                "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
                (user_id, role, content)
            )
            
            # Update counters
            if role == "user":
                cursor.execute(
                    "UPDATE users SET total_messages = total_messages + 1 WHERE user_id = ?",
                    (user_id,)
                )
            
            if tokens_used > 0:
                cursor.execute(
                    "UPDATE users SET total_tokens = total_tokens + ? WHERE user_id = ?",
                    (tokens_used, user_id)
                )
            
            # Periodic cleanup
            if role == "user":
                self._cleanup_old_messages(user_id)
    
    def get_dialogue_history(self, user_id: int, limit: int = 20) -> List[Dict[str, str]]:
        """Get conversation history for user"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT role, content FROM messages "
                "WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
                (user_id, limit)
            )
            
            messages = cursor.fetchall()
            return [{"role": role, "content": content} for role, content in reversed(messages)]
    
    def get_user_usage(self, user_id: int) -> Dict:
        """Get user's usage statistics"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT total_messages, total_tokens FROM users WHERE user_id = ?",
                (user_id,)
            )
            result = cursor.fetchone()
            
            if result:
                return {"messages": result[0] or 0, "tokens": result[1] or 0}
            return {"messages": 0, "tokens": 0}
    
    def reset_user_limits(self, user_id: int):
        """Reset user's usage counters"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET total_messages = 0, total_tokens = 0 WHERE user_id = ?",
                (user_id,)
            )
    
    def save_user_data(self, user_id: int, key: str, value: any):
        """Save arbitrary user data"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT user_data FROM users WHERE user_id = ?", (user_id,))
            result = cursor.fetchone()
            
            if result:
                user_data = json.loads(result[0] or "{}")
                user_data[key] = value
                
                cursor.execute(
                    "UPDATE users SET user_data = ? WHERE user_id = ?",
                    (json.dumps(user_data), user_id)
                )
    
    def get_user_data(self, user_id: int, key: str, default=None):
        """Get user data by key"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT user_data FROM users WHERE user_id = ?", (user_id,))
            result = cursor.fetchone()
            
            if result:
                user_data = json.loads(result[0] or "{}")
                return user_data.get(key, default)
            return default
    
    def _cleanup_old_messages(self, user_id: int, keep_last: int = 100):
        """Remove old messages keeping only recent ones"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM messages WHERE user_id = ?", (user_id,))
            count = cursor.fetchone()[0]
            
            if count > keep_last * 1.5:
                cursor.execute("""
                    DELETE FROM messages 
                    WHERE user_id = ? AND id NOT IN (
                        SELECT id FROM messages 
                        WHERE user_id = ? 
                        ORDER BY timestamp DESC LIMIT ?
                    )
                """, (user_id, user_id, keep_last))
                
                logger.info(f"Cleaned up old messages for user {user_id}")
