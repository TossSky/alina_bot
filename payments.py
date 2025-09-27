"""Payments Module - Subscription Management"""

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Update
from telegram.ext import ContextTypes

from config import Config

logger = logging.getLogger(__name__)


class SubscriptionManager:
    """Manages user subscriptions and payment processing"""
    
    SUBSCRIPTION_PLANS = {
        "day": {
            "name": "День",
            "price": 9900,  # 99 RUB
            "days": 1,
            "description": "Подписка на 1 день"
        },
        "week": {
            "name": "Неделя",
            "price": 49900,  # 499 RUB
            "days": 7,
            "description": "Подписка на 7 дней"
        },
        "month": {
            "name": "Месяц",
            "price": 149900,  # 1499 RUB
            "days": 30,
            "description": "Подписка на 30 дней"
        }
    }
    
    def __init__(self, db):
        self.db = db
        self._init_subscription_table()
    
    def _init_subscription_table(self):
        """Create subscription table if not exists"""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    plan_type TEXT NOT NULL,
                    start_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    end_date TIMESTAMP NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    payment_id TEXT,
                    amount INTEGER,
                    currency TEXT DEFAULT 'RUB',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_subscriptions_active 
                ON subscriptions (user_id, is_active, end_date)
            """)
    
    def has_active_subscription(self, user_id: int) -> bool:
        """Check if user has active subscription"""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM subscriptions "
                "WHERE user_id = ? AND is_active = 1 AND end_date > CURRENT_TIMESTAMP",
                (user_id,)
            )
            return cursor.fetchone()[0] > 0
    
    def get_active_subscription(self, user_id: int) -> Optional[Dict]:
        """Get active subscription details"""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, plan_type, start_date, end_date, amount, currency
                FROM subscriptions 
                WHERE user_id = ? AND is_active = 1 AND end_date > CURRENT_TIMESTAMP
                ORDER BY end_date DESC LIMIT 1
            """, (user_id,))
            
            row = cursor.fetchone()
            if row:
                return dict(zip(["id", "plan_type", "start_date", "end_date", "amount", "currency"], row))
            return None
    
    def add_subscription(self, user_id: int, plan_type: str, payment_id: str = None) -> bool:
        """Add or extend user subscription"""
        if plan_type not in self.SUBSCRIPTION_PLANS:
            logger.error(f"Unknown subscription plan: {plan_type}")
            return False
        
        plan = self.SUBSCRIPTION_PLANS[plan_type]
        duration = timedelta(days=plan["days"])
        
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            
            # Check for existing active subscription
            cursor.execute("""
                SELECT id, end_date FROM subscriptions
                WHERE user_id = ? AND is_active = 1 AND end_date > CURRENT_TIMESTAMP
                ORDER BY end_date DESC LIMIT 1
            """, (user_id,))
            
            existing = cursor.fetchone()
            now = datetime.now()
            
            if existing:
                # Extend existing subscription
                sub_id, current_end = existing
                current_end_dt = datetime.fromisoformat(current_end)
                new_end = max(current_end_dt, now) + duration
                
                cursor.execute("""
                    UPDATE subscriptions
                    SET plan_type = ?, end_date = ?, amount = COALESCE(amount, 0) + ?
                    WHERE id = ?
                """, (plan_type, new_end, plan["price"], sub_id))
                
                logger.info(f"Extended subscription for user {user_id}: {current_end_dt} -> {new_end}")
            else:
                # Create new subscription
                new_end = now + duration
                cursor.execute("""
                    INSERT INTO subscriptions 
                    (user_id, plan_type, end_date, payment_id, amount, currency)
                    VALUES (?, ?, ?, ?, ?, 'RUB')
                """, (user_id, plan_type, new_end, payment_id, plan["price"]))
                
                logger.info(f"Created subscription for user {user_id} until {new_end}")
            
            return True
    
    def get_subscription_keyboard(self) -> InlineKeyboardMarkup:
        """Generate subscription options keyboard"""
        keyboard = []
        for plan_id, plan in self.SUBSCRIPTION_PLANS.items():
            price_rub = plan["price"] // 100
            button = InlineKeyboardButton(
                f"{plan['name']} - {price_rub} ₽",
                callback_data=f"subscribe_{plan_id}"
            )
            keyboard.append([button])
        return InlineKeyboardMarkup(keyboard)
    
    def format_subscription_info(self, user_id: int) -> str:
        """Format subscription status message"""
        subscription = self.get_active_subscription(user_id)
        
        if not subscription:
            return "У вас нет активной подписки."
        
        end_date = datetime.fromisoformat(subscription["end_date"])
        days_left = (end_date - datetime.now()).days
        plan_name = self.SUBSCRIPTION_PLANS.get(subscription["plan_type"], {}).get("name", subscription["plan_type"])
        
        if days_left == 0:
            return f"Ваша подписка ({plan_name}) истекает сегодня!"
        elif days_left == 1:
            return f"Ваша подписка ({plan_name}) активна ещё 1 день"
        else:
            return f"Ваша подписка ({plan_name}) активна ещё {days_left} дней"


async def create_invoice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    plan_type: str,
    payments_token: str
) -> None:
    """Create and send payment invoice"""
    manager = context.bot_data.get('subscription_manager')
    if not manager:
        await update.callback_query.answer("Ошибка: система подписок не инициализирована")
        return
    
    if plan_type not in SubscriptionManager.SUBSCRIPTION_PLANS:
        await update.callback_query.answer("Неверный тип подписки")
        return
    
    plan = SubscriptionManager.SUBSCRIPTION_PLANS[plan_type]
    
    # Check test mode
    if ':TEST:' in payments_token:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ Тестовый платеж! Средства не будут списаны."
        )
    
    # Send invoice
    await context.bot.send_invoice(
        chat_id=update.effective_chat.id,
        title=f"Подписка на бота Алину - {plan['name']}",
        description=plan["description"],
        payload=f"{plan_type}_{update.effective_user.id}",
        provider_token=payments_token,
        currency="RUB",
        prices=[LabeledPrice(label=plan["description"], amount=plan["price"])],
        photo_url="https://images.unsplash.com/photo-1573164713714-d95e436ab8d6?w=400",
        photo_width=400,
        photo_height=250,
        photo_size=400,
        is_flexible=False,
        start_parameter=f"subscription-{plan_type}",
        protect_content=True
    )


async def handle_subscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle subscription button press"""
    query = update.callback_query
    await query.answer()
    
    plan_type = query.data.replace("subscribe_", "")
    config = Config()
    
    await create_invoice(update, context, plan_type, config.payments_token)
