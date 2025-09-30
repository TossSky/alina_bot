"""Payments Module - Subscription Management with YooKassa"""

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import Config
from yookassa_integration import YooKassaClient

logger = logging.getLogger(__name__)


class SubscriptionManager:
    """Manages user subscriptions and payment processing"""
    
    SUBSCRIPTION_PLANS = {
        "day": {
            "name": "День",
            "price": 99.00,  # RUB
            "days": 1,
            "description": "Подписка на 1 день"
        },
        "week": {
            "name": "Неделя",
            "price": 499.00,  # RUB
            "days": 7,
            "description": "Подписка на 7 дней"
        },
        "month": {
            "name": "Месяц",
            "price": 1499.00,  # RUB
            "days": 30,
            "description": "Подписка на 30 дней"
        }
    }
    
    def __init__(self, db, yookassa_client: YooKassaClient):
        self.db = db
        self.yookassa = yookassa_client
        self._init_subscription_table()
        self._init_payment_table()
    
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
                    amount REAL,
                    currency TEXT DEFAULT 'RUB',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_subscriptions_active 
                ON subscriptions (user_id, is_active, end_date)
            """)
    
    def _init_payment_table(self):
        """Create payment tracking table"""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pending_payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    payment_id TEXT UNIQUE NOT NULL,
                    plan_type TEXT NOT NULL,
                    amount REAL NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
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
    
    def save_pending_payment(self, user_id: int, payment_id: str, plan_type: str, amount: float):
        """Save pending payment to track it"""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO pending_payments (user_id, payment_id, plan_type, amount)
                VALUES (?, ?, ?, ?)
            """, (user_id, payment_id, plan_type, amount))
            conn.commit()
    
    def get_pending_payment(self, payment_id: str) -> Optional[Dict]:
        """Get pending payment info"""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT user_id, plan_type, amount, status
                FROM pending_payments
                WHERE payment_id = ?
            """, (payment_id,))
            
            row = cursor.fetchone()
            if row:
                return dict(zip(["user_id", "plan_type", "amount", "status"], row))
            return None
    
    def update_payment_status(self, payment_id: str, status: str):
        """Update payment status"""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE pending_payments
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE payment_id = ?
            """, (status, payment_id))
            conn.commit()
    
    def get_subscription_keyboard(self) -> InlineKeyboardMarkup:
        """Generate subscription options keyboard"""
        keyboard = []
        for plan_id, plan in self.SUBSCRIPTION_PLANS.items():
            price_rub = plan["price"]
            button = InlineKeyboardButton(
                f"{plan['name']} - {price_rub:.0f} ₽",
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


async def create_yookassa_payment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    plan_type: str,
    yookassa_client: YooKassaClient
) -> None:
    """Create YooKassa payment and send payment link"""
    manager = context.bot_data.get('subscription_manager')
    if not manager:
        await update.callback_query.answer("Ошибка: система подписок не инициализирована")
        return
    
    if plan_type not in SubscriptionManager.SUBSCRIPTION_PLANS:
        await update.callback_query.answer("Неверный тип подписки")
        return
    
    plan = SubscriptionManager.SUBSCRIPTION_PLANS[plan_type]
    user_id = update.effective_user.id
    
    # Create payment in YooKassa
    payment = yookassa_client.create_payment(
        amount=plan["price"],
        description=f"Подписка на бота Алину - {plan['name']}",
        metadata={
            "user_id": user_id,
            "plan_type": plan_type
        }
    )
    
    if not payment:
        await update.callback_query.answer("Ошибка создания платежа. Попробуйте позже.")
        return
    
    # Save pending payment
    manager.save_pending_payment(user_id, payment["id"], plan_type, plan["price"])
    
    # Send payment link
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Оплатить", url=payment["confirmation_url"])],
        [InlineKeyboardButton("🔄 Проверить оплату", callback_data=f"check_payment_{payment['id']}")]
    ])
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"💰 *Оплата подписки*\n\n"
             f"План: {plan['name']}\n"
             f"Стоимость: {plan['price']:.0f} ₽\n\n"
             f"Нажмите кнопку ниже для оплаты.\n"
             f"После оплаты нажмите \"Проверить оплату\".",
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    
    logger.info(f"Created payment {payment['id']} for user {user_id}, plan {plan_type}")


async def handle_subscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle subscription button press"""
    query = update.callback_query
    await query.answer()
    
    plan_type = query.data.replace("subscribe_", "")
    yookassa = context.bot_data.get('yookassa_client')
    
    if not yookassa:
        await query.message.reply_text("Ошибка: платежная система не инициализирована")
        return
    
    await create_yookassa_payment(update, context, plan_type, yookassa)


async def handle_check_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle payment check button press"""
    query = update.callback_query
    
    payment_id = query.data.replace("check_payment_", "")
    
    manager = context.bot_data.get('subscription_manager')
    yookassa = context.bot_data.get('yookassa_client')
    
    if not manager or not yookassa:
        await query.answer("Ошибка системы", show_alert=True)
        return
    
    # Get payment info
    pending = manager.get_pending_payment(payment_id)
    
    if not pending:
        await query.answer("Платеж не найден", show_alert=True)
        return
    
    # Check payment status in YooKassa
    status = yookassa.get_payment_status(payment_id)
    
    if status == "succeeded":
        # Activate subscription
        if manager.add_subscription(pending["user_id"], pending["plan_type"], payment_id):
            manager.update_payment_status(payment_id, "succeeded")
            
            plan = SubscriptionManager.SUBSCRIPTION_PLANS.get(pending["plan_type"], {})
            
            await query.message.reply_text(
                f"✅ Спасибо за оплату!\n\n"
                f"Ваша подписка '{plan.get('name', pending['plan_type'])}' активирована.\n"
                f"Срок действия: {plan.get('days', 0)} дней\n\n"
                f"Теперь вы можете пользоваться ботом без ограничений! 💜"
            )
            
            # Remove payment buttons
            await query.message.edit_reply_markup(reply_markup=None)
            
            logger.info(f"Payment {payment_id} succeeded for user {pending['user_id']}")
        else:
            await query.answer("Ошибка активации подписки", show_alert=True)
    
    elif status == "canceled":
        manager.update_payment_status(payment_id, "canceled")
        await query.answer("Платеж отменен", show_alert=True)
    
    elif status == "pending":
        await query.answer("Платеж еще не завершен. Подождите немного.", show_alert=True)
    
    else:
        await query.answer(f"Статус платежа: {status}", show_alert=True)
