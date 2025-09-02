# app/db.py
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from datetime import datetime, timedelta
from typing import List, Optional, Dict
import random

engine: Engine = create_engine("sqlite:///alina.db", future=True)


def _has_column(conn, table: str, column: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).mappings().all()
    return any(r["name"] == column for r in rows)


def init():
    with engine.begin() as conn:
        # users
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            style TEXT DEFAULT 'gentle',
            verbosity TEXT DEFAULT 'normal',
            free_left INTEGER DEFAULT 10,
            is_subscribed INTEGER DEFAULT 0,
            sub_until DATETIME,
            tz TEXT,
            last_cleanup DATETIME DEFAULT CURRENT_TIMESTAMP
        );"""))

        # messages - с индексом для быстрого поиска
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            content TEXT,
            ts DATETIME DEFAULT CURRENT_TIMESTAMP
        );"""))
        
        # Индекс для оптимизации выборки истории
        conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_messages_user_ts 
        ON messages(user_id, ts DESC);
        """))

        # payments
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS payments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            provider TEXT,
            order_id TEXT,
            amount INTEGER,
            currency TEXT,
            status TEXT,
            raw TEXT,
            ts DATETIME DEFAULT CURRENT_TIMESTAMP
        );"""))

        # reminders
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS reminders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            rtype TEXT,          -- 'checkin' | 'morning' | 'evening'
            time_local TEXT,     -- 'HH:MM'
            active INTEGER DEFAULT 1
        );"""))
        
        # Миграция: добавляем last_cleanup если его нет
        if not _has_column(conn, "users", "last_cleanup"):
            # Добавляем колонку без DEFAULT
            conn.execute(text("ALTER TABLE users ADD COLUMN last_cleanup DATETIME;"))
            # Обновляем существующие записи текущим временем
            conn.execute(text("UPDATE users SET last_cleanup = CURRENT_TIMESTAMP WHERE last_cleanup IS NULL;"))


def get_user(user_id: int):
    from .config import settings
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT * FROM users WHERE user_id=:u"), {"u": user_id}
        ).mappings().first()
        if not row:
            conn.execute(text("INSERT INTO users(user_id, free_left) VALUES(:u, :f)"), 
                        {"u": user_id, "f": settings.free_messages})
            row = conn.execute(
                text("SELECT * FROM users WHERE user_id=:u"), {"u": user_id}
            ).mappings().first()
        return row


def update_user(user_id: int, **fields):
    if not fields:
        return
    sets = ", ".join([f"{k}=:{k}" for k in fields])
    fields["u"] = user_id
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE users SET {sets} WHERE user_id=:u"), fields)


def add_msg(user_id: int, role: str, content: str):
    """Добавляет сообщение в историю"""
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO messages(user_id, role, content) VALUES(:u,:r,:c)"),
            {"u": user_id, "r": role, "c": content},
        )
        
        # Периодическая очистка старых сообщений (раз в 50 сообщений + рандом)
        if random.random() < 0.02:  # 2% шанс на очистку
            _cleanup_old_messages(conn, user_id)


def _cleanup_old_messages(conn, user_id: int):
    """Очищает старые сообщения, оставляя последние 100"""
    try:
        # Проверяем, когда была последняя очистка
        row = conn.execute(
            text("SELECT last_cleanup FROM users WHERE user_id=:u"),
            {"u": user_id}
        ).mappings().first()
        
        if row and row["last_cleanup"]:
            last = datetime.fromisoformat(row["last_cleanup"])
            if (datetime.utcnow() - last).total_seconds() < 3600:  # Не чаще раза в час
                return
        
        # Удаляем старые сообщения
        conn.execute(
            text("""
            DELETE FROM messages 
            WHERE user_id=:u 
            AND id NOT IN (
                SELECT id FROM messages 
                WHERE user_id=:u 
                ORDER BY ts DESC 
                LIMIT 100
            )
            """),
            {"u": user_id}
        )
        
        # Обновляем время последней очистки
        conn.execute(
            text("UPDATE users SET last_cleanup=CURRENT_TIMESTAMP WHERE user_id=:u"),
            {"u": user_id}
        )
    except Exception:
        pass  # Не критично, если очистка не удалась


def last_dialog(user_id: int, limit: int = 20):
    """
    Возвращает последние сообщения диалога.
    По умолчанию 20 сообщений для хорошего контекста.
    """
    with engine.begin() as conn:
        rows = conn.execute(
            text("""
            SELECT role, content FROM messages
            WHERE user_id=:u
            ORDER BY ts DESC
            LIMIT :l
            """),
            {"u": user_id, "l": limit},
        ).mappings().all()
        return list(reversed(rows))


def set_name(user_id: int, name: str):
    # Ограничиваем длину имени
    name = name[:50] if name else name
    update_user(user_id, name=name)


def set_style(user_id: int, style: str = None, verbosity: str = None):
    fields = {}
    if style and style in ["gentle", "direct"]:
        fields["style"] = style
    if verbosity and verbosity in ["short", "normal", "long"]:
        fields["verbosity"] = verbosity
    if fields:
        update_user(user_id, **fields)


# ---- подписка и платежи ----
def activate_subscription(user_id: int, days: int = 30):
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT sub_until FROM users WHERE user_id=:u"), {"u": user_id}
        ).mappings().first()
        now = datetime.utcnow()
        base = now
        if row and row["sub_until"]:
            try:
                cur = datetime.fromisoformat(row["sub_until"])
                if cur > now:
                    base = cur
            except Exception:
                pass
        new_until = (base + timedelta(days=days)).isoformat(timespec="seconds")
        conn.execute(
            text("UPDATE users SET is_subscribed=1, sub_until=:su WHERE user_id=:u"),
            {"su": new_until, "u": user_id},
        )
        # Восстанавливаем бесплатные сообщения при активации подписки
        from .config import settings
        conn.execute(
            text("UPDATE users SET free_left=:f WHERE user_id=:u"), 
            {"f": settings.free_messages, "u": user_id}
        )


def upsert_payment(
    user_id: int, provider: str, order_id: str,
    amount: int, currency: str, status: str, raw: str = ""
):
    with engine.begin() as conn:
        conn.execute(
            text("""
            INSERT INTO payments(user_id, provider, order_id, amount, currency, status, raw)
            VALUES(:u,:p,:o,:a,:c,:s,:r)
            """),
            {"u": user_id, "p": provider, "o": order_id,
             "a": amount, "c": currency, "s": status, "r": raw},
        )


def mark_payment(order_id: str, status: str):
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE payments SET status=:s WHERE order_id=:o"),
            {"s": status, "o": order_id},
        )


# Вспомогательные функции для TZ
def set_tz(user_id: int, tz: str):
    # Валидация TZ
    if len(tz) > 50:
        tz = tz[:50]
    update_user(user_id, tz=tz)


def get_tz(user_id: int) -> Optional[str]:
    with engine.begin() as conn:
        row = conn.execute(text("SELECT tz FROM users WHERE user_id=:u"), {"u": user_id}).mappings().first()
        return row["tz"] if row and row["tz"] else None


# CRUD для напоминаний
def list_reminders(user_id: int) -> List[Dict]:
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT * FROM reminders WHERE user_id=:u ORDER BY time_local"), 
            {"u": user_id}
        ).mappings().all()
        return [dict(r) for r in rows]


def add_reminder(user_id: int, rtype: str, time_local: str) -> int:
    # Валидация типа
    if rtype not in ["checkin", "morning", "evening"]:
        rtype = "checkin"
    
    with engine.begin() as conn:
        # Проверяем, нет ли уже такого напоминания
        existing = conn.execute(
            text("SELECT id FROM reminders WHERE user_id=:u AND time_local=:tl"),
            {"u": user_id, "tl": time_local}
        ).mappings().first()
        
        if existing:
            return existing["id"]
        
        conn.execute(
            text("INSERT INTO reminders(user_id,rtype,time_local,active) VALUES(:u,:t,:tl,1)"),
            {"u": user_id, "t": rtype, "tl": time_local}
        )
        rid = conn.execute(text("SELECT last_insert_rowid() AS rid")).mappings().first()["rid"]
        return int(rid)


def toggle_reminder(user_id: int, rid: int, active: int):
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE reminders SET active=:a WHERE id=:rid AND user_id=:u"),
            {"a": active, "rid": rid, "u": user_id}
        )


def delete_reminder(user_id: int, rid: int):
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM reminders WHERE id=:rid AND user_id=:u"),
            {"rid": rid, "u": user_id}
        )