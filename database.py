"""Database Module - SQLite Storage for User Conversations and Data"""

import json
import logging
import random
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class DialogueDB:
    """SQLite database handler for storing user conversations and subscriptions"""
    
    def __init__(self, db_path: str = "alina.db"):
        """Initialize database connection and create tables if needed
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.init_db()
    
    @contextmanager
    def _get_connection(self):
        """Context manager for database connections with proper error handling"""
        conn = sqlite3.connect(
            self.db_path,
            timeout=10.0,
            check_same_thread=False
        )
        
        # Enable Write-Ahead Logging for better concurrency
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")

        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def init_db(self):
        """Initialize database schema - create tables and indexes"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Users table - stores user metadata and usage statistics
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    total_messages INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    total_images INTEGER DEFAULT 0,
                    user_data TEXT DEFAULT '{}'
                )
            """)
            
            # Messages table - stores conversation history with image support
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    role TEXT,
                    content TEXT,
                    has_image BOOLEAN DEFAULT 0,
                    image_count INTEGER DEFAULT 0,
                    image_hash TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            """)
            
            # Index for fast message queries by user and timestamp
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_user_timestamp
                ON messages (user_id, timestamp DESC)
            """)
            
            # Migration: Add image columns if they don't exist
            self._migrate_image_columns(cursor)
    
    def _migrate_image_columns(self, cursor):
        """Add image-related columns to existing tables (migration helper)"""
        columns_to_add = [
            ("users", "total_images", "INTEGER DEFAULT 0"),
            ("messages", "has_image", "BOOLEAN DEFAULT 0"),
            ("messages", "image_count", "INTEGER DEFAULT 0"),
            ("messages", "image_hash", "TEXT"),
        ]
        
        for table, column, column_type in columns_to_add:
            try:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
            except sqlite3.OperationalError:
                # Column already exists - skip
                pass
    
    def get_or_create_user(self, user_id: int) -> Dict:
        """Get existing user or create new user record
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            User record as dictionary
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT user_id, created_at, last_active, total_messages, total_tokens, total_images, user_data "
                "FROM users WHERE user_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                # Create new user
                cursor.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
                return {
                    "user_id": user_id,
                    "created_at": datetime.now().isoformat(),
                    "last_active": datetime.now().isoformat(),
                    "total_messages": 0,
                    "total_tokens": 0,
                    "total_images": 0,
                    "user_data": {}
                }
            
            # Update last active timestamp
            cursor.execute(
                "UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?", 
                (user_id,)
            )
            
            # Convert to dictionary
            user_dict = dict(zip(
                ["user_id", "created_at", "last_active", "total_messages", "total_tokens", "total_images", "user_data"],
                row
            ))
            
            # Parse JSON user_data field
            try:
                user_dict["user_data"] = json.loads(user_dict.get("user_data") or "{}")
            except Exception:
                user_dict["user_data"] = {}
            
            return user_dict
    
    def add_message(
        self, 
        user_id: int, 
        role: str, 
        content: str, 
        tokens_used: int = 0,
        has_image: bool = False, 
        image_count: int = 0, 
        image_hash: str = None
    ):
        """Add message to conversation history and update usage counters
        
        Args:
            user_id: Telegram user ID
            role: Message role ('user' or 'assistant')
            content: Message text content
            tokens_used: Number of tokens used in this interaction
            has_image: Whether message contains image
            image_count: Number of images in message
            image_hash: Hash of image for duplicate detection
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Insert message into history
            cursor.execute(
                "INSERT INTO messages (user_id, role, content, has_image, image_count, image_hash) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, role, content, has_image, image_count, image_hash)
            )
            
            # Update user message counter for user messages only
            if role == "user":
                cursor.execute(
                    "UPDATE users SET total_messages = total_messages + 1 WHERE user_id = ?",
                    (user_id,)
                )
                
                # Update image counter if message has images
                if has_image:
                    cursor.execute(
                        "UPDATE users SET total_images = total_images + ? WHERE user_id = ?",
                        (image_count, user_id)
                    )
            
            # Update token counter
            if tokens_used > 0:
                cursor.execute(
                    "UPDATE users SET total_tokens = total_tokens + ? WHERE user_id = ?",
                    (tokens_used, user_id)
                )
            
            # Periodic cleanup (10% chance to run)
            if role == "user" and random.random() < 0.1:
                try:
                    self._cleanup_old_messages(user_id)
                except Exception as e:
                    logger.warning(f"Cleanup skipped: {e}")
    
    def get_dialogue_history(self, user_id: int, limit: int = 20) -> List[Dict[str, str]]:
        """Get conversation history for user with day markers
        
        Args:
            user_id: Telegram user ID
            limit: Maximum number of recent messages to retrieve
            
        Returns:
            List of messages with 'role' and 'content' keys, including day separators
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT role, content, DATE(timestamp) as msg_date FROM messages "
                "WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
                (user_id, limit)
            )
            
            messages = cursor.fetchall()
            
            # Build history with day markers in chronological order
            result = []
            last_date = None
            
            for role, content, msg_date in reversed(messages):
                # Add day marker when date changes
                if last_date is not None and msg_date != last_date:
                    result.append({
                        "role": "system",
                        "content": f"[Новый день: {msg_date}]"
                    })
                
                result.append({"role": role, "content": content})
                last_date = msg_date
            
            return result
    
    def get_user_usage(self, user_id: int) -> Dict:
        """Get user's current usage statistics
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            Dictionary with 'messages', 'tokens', and 'images' counts
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT total_messages, total_tokens, total_images FROM users WHERE user_id = ?",
                (user_id,)
            )
            result = cursor.fetchone()
            
            if result:
                return {
                    "messages": result[0] or 0,
                    "tokens": result[1] or 0,
                    "images": result[2] or 0
                }
            return {"messages": 0, "tokens": 0, "images": 0}
    
    def reset_user_limits(self, user_id: int):
        """Reset all usage counters for user (used by admins)
        
        Args:
            user_id: Telegram user ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET total_messages = 0, total_tokens = 0, total_images = 0 "
                "WHERE user_id = ?",
                (user_id,)
            )
    
    def save_user_data(self, user_id: int, key: str, value: any):
        """Save custom user data (key-value storage)
        
        Args:
            user_id: Telegram user ID
            key: Data key
            value: Data value (will be JSON-serialized)
        """
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
        """Get custom user data by key
        
        Args:
            user_id: Telegram user ID
            key: Data key
            default: Default value if key not found
            
        Returns:
            Stored value or default
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT user_data FROM users WHERE user_id = ?", (user_id,))
            result = cursor.fetchone()
            
            if result:
                user_data = json.loads(result[0] or "{}")
                return user_data.get(key, default)
            return default
    
    def is_duplicate_image(self, user_id: int, image_hash: str, minutes: int = 30) -> bool:
        """Check if user recently sent this exact image
        
        Args:
            user_id: Telegram user ID
            image_hash: SHA256 hash of image
            minutes: Time window to check for duplicates
            
        Returns:
            True if duplicate found within time window
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT COUNT(*) FROM messages 
                WHERE user_id = ? 
                AND image_hash = ? 
                AND has_image = 1
                AND timestamp > datetime('now', '-' || ? || ' minutes')
            """, (user_id, image_hash, minutes))
            
            count = cursor.fetchone()[0]
            return count > 0
    
    def get_daily_usage(self, user_id: int) -> Dict:
        """Get user's usage statistics for current day (00:00 - 23:59)
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            Dictionary with 'messages', 'tokens', and 'images' counts for today
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Count user messages today
            cursor.execute("""
                SELECT COUNT(*) FROM messages 
                WHERE user_id = ? 
                AND role = 'user'
                AND DATE(timestamp) = DATE('now')
            """, (user_id,))
            messages_today = cursor.fetchone()[0]
            
            # Count images today
            cursor.execute("""
                SELECT COALESCE(SUM(image_count), 0) FROM messages 
                WHERE user_id = ? 
                AND has_image = 1
                AND DATE(timestamp) = DATE('now')
            """, (user_id,))
            images_today = cursor.fetchone()[0]
            
            # Calculate tokens used today (sum from all messages today)
            cursor.execute("""
                SELECT user_id, timestamp FROM messages 
                WHERE user_id = ?
                AND DATE(timestamp) = DATE('now')
                ORDER BY timestamp ASC
            """, (user_id,))
            messages_list = cursor.fetchall()
            
            # Estimate tokens (simplified - we'd need to recalculate properly)
            # For now, use total tokens from users table and scale by message ratio
            cursor.execute(
                "SELECT total_messages, total_tokens FROM users WHERE user_id = ?",
                (user_id,)
            )
            result = cursor.fetchone()
            
            if result and result[0] > 0:
                total_msgs, total_tokens = result
                # Estimate today's tokens proportionally
                tokens_today = int((messages_today / max(total_msgs, 1)) * total_tokens)
            else:
                tokens_today = 0
            
            return {
                "messages": messages_today,
                "tokens": tokens_today,
                "images": images_today
            }
    
    def get_last_message_time(self, user_id: int) -> Optional[datetime]:
        """Get timestamp of user's last message
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            Datetime of last message or None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT timestamp FROM messages 
                WHERE user_id = ? AND role = 'user'
                ORDER BY timestamp DESC 
                LIMIT 1
            """, (user_id,))
            
            result = cursor.fetchone()
            if result:
                return datetime.fromisoformat(result[0])
            return None
    
    def get_recent_message_count(self, user_id: int, minutes: int = 1) -> int:
        """Count messages sent by user in recent time window
        
        Args:
            user_id: Telegram user ID
            minutes: Time window in minutes
            
        Returns:
            Number of messages in time window
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT COUNT(*) FROM messages 
                WHERE user_id = ? 
                AND role = 'user'
                AND timestamp > datetime('now', '-' || ? || ' minutes')
            """, (user_id, minutes))
            
            return cursor.fetchone()[0]
    
    def is_user_blocked(self, user_id: int) -> bool:
        """Check if user is temporarily blocked for spam
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            True if user is currently blocked
        """
        block_until = self.get_user_data(user_id, 'block_until')
        if not block_until:
            return False
        
        block_time = datetime.fromisoformat(block_until)
        return datetime.now() < block_time
    
    def block_user_temporarily(self, user_id: int, minutes: int = 5):
        """Temporarily block user for spam
        
        Args:
            user_id: Telegram user ID
            minutes: Duration of block in minutes
        """
        from datetime import timedelta
        block_until = (datetime.now() + timedelta(minutes=minutes)).isoformat()
        self.save_user_data(user_id, 'block_until', block_until)
        logger.warning(f"User {user_id} temporarily blocked for {minutes} minutes")
    
    def _cleanup_old_messages(self, user_id: int, keep_last: int = 100):
        """Remove old messages keeping only recent ones
        
        Args:
            user_id: Telegram user ID
            keep_last: Number of recent messages to keep
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Count total messages for user
            cursor.execute("SELECT COUNT(*) FROM messages WHERE user_id = ?", (user_id,))
            count = cursor.fetchone()[0]

            # Calculate how many to delete
            to_delete = max(0, count - keep_last)
            
            if to_delete > 0:
                # Delete oldest messages
                cursor.execute("""
                    DELETE FROM messages
                    WHERE id IN (
                        SELECT id FROM messages
                        WHERE user_id = ?
                        ORDER BY timestamp ASC
                        LIMIT ?
                    )
                """, (user_id, to_delete))
                
                logger.info(f"Cleaned {to_delete} old messages for user {user_id}")
