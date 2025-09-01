from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from datetime import datetime, timedelta

engine: Engine = create_engine("sqlite:///alina.db", future=True)

def init():
    with engine.begin() as conn:
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            style TEXT DEFAULT 'gentle',
            verbosity TEXT DEFAULT 'normal',
            free_left INTEGER DEFAULT 10,
            is_subscribed INTEGER DEFAULT 0,
            sub_until DATETIME
        );"""))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            content TEXT,
            ts DATETIME DEFAULT CURRENT_TIMESTAMP
        );"""))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS payments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            provider TEXT,           -- 'stars' | 'redsys'
            order_id TEXT,           -- наш внутренний id/номер заказа
            amount INTEGER,          -- в минимальных единицах (звёздочки или центы)
            currency TEXT,           -- 'XTR' или 'EUR'
            status TEXT,             -- 'pending' | 'paid' | 'failed'
            raw TEXT,                -- текст/JSON ответ провайдера
            ts DATETIME DEFAULT CURRENT_TIMESTAMP
        );"""))

def get_user(user_id:int):
    with engine.begin() as conn:
        row = conn.execute(text("SELECT * FROM users WHERE user_id=:u"), {"u": user_id}).mappings().first()
        if not row:
            conn.execute(text("INSERT INTO users(user_id) VALUES(:u)"), {"u": user_id})
            row = conn.execute(text("SELECT * FROM users WHERE user_id=:u"), {"u": user_id}).mappings().first()
        return row

def update_user(user_id:int, **fields):
    sets = ", ".join([f"{k}=:{k}" for k in fields])
    fields["u"] = user_id
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE users SET {sets} WHERE user_id=:u"), fields)

def add_msg(user_id:int, role:str, content:str):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO messages(user_id, role, content) VALUES(:u,:r,:c)"),
                     {"u": user_id, "r": role, "c": content})

def last_dialog(user_id:int, limit:int=12):
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT role, content FROM messages WHERE user_id=:u ORDER BY ts DESC LIMIT :l
        """), {"u": user_id, "l": limit}).mappings().all()
        return list(reversed(rows))

def set_name(user_id:int, name:str):
    update_user(user_id, name=name)

def set_style(user_id:int, style:str=None, verbosity:str=None):
    fields = {}
    if style: fields["style"] = style
    if verbosity: fields["verbosity"] = verbosity
    if fields:
        update_user(user_id, **fields)

# ---- подписка и платежи ----
def activate_subscription(user_id:int, days:int=30):
    # продлеваем sub_until на days от текущего момента/текущего sub_until, что больше
    with engine.begin() as conn:
        row = conn.execute(text("SELECT sub_until FROM users WHERE user_id=:u"), {"u": user_id}).mappings().first()
        now = datetime.utcnow()
        base = now
        if row and row["sub_until"]:
            try:
                cur = datetime.fromisoformat(row["sub_until"])
                if cur > now:
                    base = cur
            except Exception:
                pass
        new_until = (base + timedelta(days=days)).isoformat(timespec='seconds')
        conn.execute(text("UPDATE users SET is_subscribed=1, sub_until=:su WHERE user_id=:u"),
                     {"su": new_until, "u": user_id})
        # можно также сбросить лимиты
        conn.execute(text("UPDATE users SET free_left=10 WHERE user_id=:u"), {"u": user_id})

def upsert_payment(user_id:int, provider:str, order_id:str, amount:int, currency:str, status:str, raw:str=""):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO payments(user_id, provider, order_id, amount, currency, status, raw)
            VALUES(:u,:p,:o,:a,:c,:s,:r)
        """), {"u": user_id, "p": provider, "o": order_id, "a": amount, "c": currency, "s": status, "r": raw})

def mark_payment(order_id:str, status:str):
    with engine.begin() as conn:
        conn.execute(text("UPDATE payments SET status=:s WHERE order_id=:o"), {"s": status, "o": order_id})
