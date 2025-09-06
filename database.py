# database.py - Простое управление данными для бота
"""
Минималистичная БД для хранения истории диалогов.
Используем SQLite для простоты.
"""

import sqlite3
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class DialogueDB:
    """
    Простая база данных для хранения диалогов.
    """
    
    def __init__(self, db_path: str = "alina.db"):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        """Инициализирует таблицы БД."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Таблица пользователей
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    total_messages INTEGER DEFAULT 0,
                    user_data TEXT DEFAULT '{}'
                )
            """)
            
            # Таблица сообщений
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
            
            # Индекс для быстрого поиска
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_user_timestamp 
                ON messages (user_id, timestamp DESC)
            """)
            
            conn.commit()
    
    def get_or_create_user(self, user_id: int, username: str = None, first_name: str = None) -> Dict:
        """Получает или создаёт пользователя."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Явно перечисляем столбцы, чтобы потом легко собрать dict
            cursor.execute("""
                SELECT user_id, username, first_name, created_at, last_active, total_messages, user_data
                FROM users WHERE user_id = ?
            """, (user_id,))
            row = cursor.fetchone()

            if row is None:
                # Создаем нового
                cursor.execute(
                    "INSERT INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
                    (user_id, username, first_name)
                )
                conn.commit()
                return {
                    "user_id": user_id,
                    "username": username,
                    "first_name": first_name,
                    "created_at": datetime.now().isoformat(),
                    "last_active": datetime.now().isoformat(),
                    "total_messages": 0,
                    "user_data": {}
                }

            # Сохраняем dict ДО UPDATE (иначе description обнулится)
            columns = ["user_id", "username", "first_name", "created_at", "last_active", "total_messages", "user_data"]
            user_dict = dict(zip(columns, row))
            try:
                user_dict["user_data"] = json.loads(user_dict.get("user_data") or "{}")
            except Exception:
                user_dict["user_data"] = {}

            # Обновляем last_active уже после того, как собрали словарь
            cursor.execute("UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
            conn.commit()

            return user_dict

    
    def add_message(self, user_id: int, role: str, content: str):
        """Добавляет сообщение в историю."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Добавляем сообщение
            cursor.execute("""
                INSERT INTO messages (user_id, role, content) 
                VALUES (?, ?, ?)
            """, (user_id, role, content))
            
            # Увеличиваем счётчик сообщений
            if role == "user":
                cursor.execute("""
                    UPDATE users 
                    SET total_messages = total_messages + 1 
                    WHERE user_id = ?
                """, (user_id,))
            
            conn.commit()
            
            # Периодическая очистка старых сообщений
            if role == "user":
                self._cleanup_old_messages(user_id)
    
    def get_dialogue_history(self, user_id: int, limit: int = 20) -> List[Dict[str, str]]:
        """
        Получает историю диалога.
        
        Args:
            user_id: ID пользователя
            limit: Максимальное количество сообщений
        
        Returns:
            Список сообщений в формате [{"role": "user/assistant", "content": "..."}]
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT role, content 
                FROM messages 
                WHERE user_id = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (user_id, limit))
            
            messages = cursor.fetchall()
            
            # Переворачиваем для хронологического порядка
            return [{"role": role, "content": content} for role, content in reversed(messages)]
    
    def _cleanup_old_messages(self, user_id: int, keep_last: int = 100):
        """
        Очищает старые сообщения, оставляя только последние.
        Вызывается периодически для экономии места.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Проверяем количество сообщений
            cursor.execute("""
                SELECT COUNT(*) FROM messages WHERE user_id = ?
            """, (user_id,))
            
            count = cursor.fetchone()[0]
            
            # Если сообщений больше лимита, удаляем старые
            if count > keep_last * 1.5:  # Удаляем когда в 1.5 раза больше лимита
                cursor.execute("""
                    DELETE FROM messages 
                    WHERE user_id = ? 
                    AND id NOT IN (
                        SELECT id FROM messages 
                        WHERE user_id = ? 
                        ORDER BY timestamp DESC 
                        LIMIT ?
                    )
                """, (user_id, user_id, keep_last))
                
                conn.commit()
                logger.info(f"Cleaned up old messages for user {user_id}")
    
    def save_user_data(self, user_id: int, key: str, value: any):
        """Сохраняет произвольные данные пользователя."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Получаем текущие данные
            cursor.execute("SELECT user_data FROM users WHERE user_id = ?", (user_id,))
            result = cursor.fetchone()
            
            if result:
                user_data = json.loads(result[0] or "{}")
                user_data[key] = value
                
                # Сохраняем обратно
                cursor.execute("""
                    UPDATE users 
                    SET user_data = ? 
                    WHERE user_id = ?
                """, (json.dumps(user_data), user_id))
                
                conn.commit()
    
    def get_user_data(self, user_id: int, key: str, default=None):
        """Получает данные пользователя по ключу."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT user_data FROM users WHERE user_id = ?", (user_id,))
            result = cursor.fetchone()
            
            if result:
                user_data = json.loads(result[0] or "{}")
                return user_data.get(key, default)
            
            return default
    
    def get_conversation_stats(self, user_id: int) -> Dict:
        """Получает статистику диалога."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Общее количество сообщений
            cursor.execute("""
                SELECT COUNT(*) FROM messages 
                WHERE user_id = ? AND role = 'user'
            """, (user_id,))
            total_messages = cursor.fetchone()[0]
            
            # Первое сообщение
            cursor.execute("""
                SELECT timestamp FROM messages 
                WHERE user_id = ? 
                ORDER BY timestamp ASC 
                LIMIT 1
            """, (user_id,))
            first_message = cursor.fetchone()
            
            # Последнее сообщение
            cursor.execute("""
                SELECT timestamp FROM messages 
                WHERE user_id = ? 
                ORDER BY timestamp DESC 
                LIMIT 1
            """, (user_id,))
            last_message = cursor.fetchone()
            
            return {
                "total_messages": total_messages,
                "first_message": first_message[0] if first_message else None,
                "last_message": last_message[0] if last_message else None,
                "conversation_length": self._get_conversation_length(user_id)
            }
    
    def _get_conversation_length(self, user_id: int) -> int:
        """Получает текущую длину разговора (для контекста)."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM messages WHERE user_id = ?
            """, (user_id,))
            return cursor.fetchone()[0]