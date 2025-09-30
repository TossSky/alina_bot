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
        """Generate subscription options keyboard with callback data"""
        keyboard = []
        for plan_id, plan in self.SUBSCRIPTION_PLANS.items():
            price_rub = plan["price"]
            button = InlineKeyboardButton(
                f"{plan['name']} - {price_rub:.0f} ₽",
                callback_data=f"subscribe_{plan_id}"
            )
            keyboard.append([button])
        return InlineKeyboardMarkup(keyboard)
    
    def get_subscription_keyboard_for_mode(self, mode: str) -> InlineKeyboardMarkup:
        """
        mode: 'rub' or 'stars'
        Возвращает InlineKeyboardMarkup с кнопками тарифов.
        Для рублёвой оплаты callback == subscribe_<plan>
        Для звёздочной оплаты callback == stars_<plan>
        """
        keyboard = []
        for plan_id, plan in self.SUBSCRIPTION_PLANS.items():
            if mode == "stars":
                # Тут можно перевести цену в звёздочки: примерно 1 звёздочка = 10 руб (пример)
                # Настрой коэффициент по необходимости
                COEF = 10.0
                stars_price = int(round(plan["price"] / COEF))
                text = f"{plan['name']} — {stars_price} ⭐"
                callback = f"stars_{plan_id}"
            else:
                text = f"{plan['name']} — {plan['price']:.0f} ₽"
                callback = f"subscribe_{plan_id}"
            button = InlineKeyboardButton(text, callback_data=callback)
            keyboard.append([button])
        # Добавим кнопку назад/отмена
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="paymode_back")])
        return InlineKeyboardMarkup(keyboard)

    def try_pay_with_stars(self, user_id: int, plan_type: str) -> bool:
        """
        Попытаться списать звёздочки и активировать подписку.
        Возвращает True при успешной оплате и активации.
        Ожидается, что self.db предоставляет методы:
          - get_user_stars(user_id) -> int
          - adjust_user_stars(user_id, delta) -> True/False (delta отрицательное для списания)
        Если таких методов нет — вернёт False.
        """
        # коэффициент конверсии: сколько рублей = 1 звёздочка (настрой)
        COEF = 10.0
        if plan_type not in self.SUBSCRIPTION_PLANS:
            logger.error("Unknown plan for stars payment: %s", plan_type)
            return False

        plan = self.SUBSCRIPTION_PLANS[plan_type]
        stars_cost = int(round(plan["price"] / COEF))

        # проверяем наличие методов у db
        if not hasattr(self.db, "get_user_stars") or not hasattr(self.db, "adjust_user_stars"):
            logger.warning("DB doesn't implement star-balance methods (get_user_stars/adjust_user_stars)")
            return False

        try:
            balance = self.db.get_user_stars(user_id)
            if balance is None:
                balance = 0
        except Exception as e:
            logger.error("Error fetching stars balance for %s: %s", user_id, e)
            return False

        if balance < stars_cost:
            logger.info("User %s doesn't have enough stars: %s < %s", user_id, balance, stars_cost)
            return False

        # Списание
        ok = self.db.adjust_user_stars(user_id, -stars_cost)
        if not ok:
            logger.error("Failed to adjust stars for user %s", user_id)
            return False

        # Активация подписки (как при обычной оплате)
        activated = self.add_subscription(user_id, plan_type, payment_id=None)
        if activated:
            # Сохраним запись в subscriptions таблице: payment_id остаётся NULL, можно записать 'stars:<txid>'
            # Если хочешь — можно занести лог в отдельную таблицу операций
            logger.info("Activated subscription for %s via stars (%s ⭐)", user_id, stars_cost)
            return True

        # Если активация не удалась — вернуть звёздочки обратно
        self.db.adjust_user_stars(user_id, stars_cost)
        return False


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


async def handle_start_payment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    plan_type: str
) -> None:
    """Handle /start pay_<plan> command - create and send payment link"""
    manager = context.bot_data.get('subscription_manager')
    yookassa = context.bot_data.get('yookassa_client')
    
    if not manager or not yookassa:
        await update.message.reply_text("Ошибка: система оплаты не инициализирована")
        return
    
    if plan_type not in SubscriptionManager.SUBSCRIPTION_PLANS:
        await update.message.reply_text("Неверный тип подписки")
        return
    
    plan = SubscriptionManager.SUBSCRIPTION_PLANS[plan_type]
    user_id = update.effective_user.id
    
    # Create payment in YooKassa
    payment = yookassa.create_payment(
        amount=plan["price"],
        description=f"Подписка на бота Алину - {plan['name']}",
        metadata={
            "user_id": user_id,
            "plan_type": plan_type,
            "telegram_username": update.effective_user.username or ""
        }
    )
    
    if not payment:
        await update.message.reply_text("Ошибка создания платежа. Попробуйте позже.")
        return
    
    # Save pending payment
    manager.save_pending_payment(user_id, payment["id"], plan_type, plan["price"])
    
    # Send payment link with inline button
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Оплатить", url=payment["confirmation_url"])]
    ])
    
    await update.message.reply_text(
        f"💰 *Оплата подписки*\n\n"
        f"План: {plan['name']}\n"
        f"Стоимость: {plan['price']:.0f} ₽\n\n"
        f"Нажмите кнопку для оплаты.\n"
        f"После оплаты вернитесь в бот — подписка активируется автоматически!",
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    
    logger.info(f"Created payment {payment['id']} for user {user_id}, plan {plan_type}")


async def handle_subscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle subscription button press - create payment immediately"""
    query = update.callback_query
    await query.answer()
    
    plan_type = query.data.replace("subscribe_", "")
    
    manager = context.bot_data.get('subscription_manager')
    yookassa = context.bot_data.get('yookassa_client')
    
    if not manager or not yookassa:
        await query.message.reply_text("Ошибка: система оплаты не инициализирована")
        return
    
    if plan_type not in SubscriptionManager.SUBSCRIPTION_PLANS:
        await query.message.reply_text("Неверный тип подписки")
        return
    
    plan = SubscriptionManager.SUBSCRIPTION_PLANS[plan_type]
    user_id = update.effective_user.id
    
    # Create payment in YooKassa
    payment = yookassa.create_payment(
        amount=plan["price"],
        description=f"Подписка на бота Алину - {plan['name']}",
        metadata={
            "user_id": user_id,
            "plan_type": plan_type,
            "telegram_username": update.effective_user.username or ""
        }
    )
    
    if not payment:
        await query.message.reply_text("Ошибка создания платежа. Попробуйте позже.")
        return
    
    # Save pending payment
    manager.save_pending_payment(user_id, payment["id"], plan_type, plan["price"])
    
    # Send payment link - just a button, no extra text
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Оплатить", url=payment["confirmation_url"])]
    ])
    
    await query.message.reply_text(
        f"💳 *{plan['name']} - {plan['price']:.0f} ₽*\n\n"
        f"Нажмите кнопку для перехода к оплате.\n"
        f"После оплаты подписка активируется автоматически!",
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    
    logger.info(f"Created payment {payment['id']} for user {user_id}, plan {plan_type}")


async def process_payment_notification(payment_data: dict, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Process payment notification from YooKassa webhook
    
    Args:
        payment_data: Payment data from YooKassa
        context: Bot context
        
    Returns:
        True if processed successfully
    """
    manager = context.bot_data.get('subscription_manager')
    
    if not manager:
        logger.error("Subscription manager not initialized")
        return False
    
    payment_id = payment_data.get("id")
    status = payment_data.get("status")
    metadata = payment_data.get("metadata", {})
    
    if not payment_id:
        logger.error("No payment_id in notification")
        return False
    
    # Get pending payment info
    pending = manager.get_pending_payment(payment_id)
    
    if not pending:
        logger.warning(f"Pending payment not found: {payment_id}")
        return False
    
    user_id = pending["user_id"]
    plan_type = pending["plan_type"]
    
    # Handle payment success
    if status == "succeeded":
        # Activate subscription
        if manager.add_subscription(user_id, plan_type, payment_id):
            manager.update_payment_status(payment_id, "succeeded")
            
            plan = SubscriptionManager.SUBSCRIPTION_PLANS.get(plan_type, {})
            
            # Send success message to user
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"✅ *Оплата успешна!*\n\n"
                         f"Ваша подписка '{plan.get('name', plan_type)}' активирована.\n"
                         f"Срок действия: {plan.get('days', 0)} дней\n\n"
                         f"Теперь вы можете пользоваться ботом без ограничений! 💜",
                    parse_mode="Markdown"
                )
                logger.info(f"Payment {payment_id} succeeded for user {user_id}")
                return True
            except Exception as e:
                logger.error(f"Failed to send success message to user {user_id}: {e}")
                return False
        else:
            logger.error(f"Failed to activate subscription for payment {payment_id}")
            return False
    
    # Handle payment cancellation
    elif status == "canceled":
        manager.update_payment_status(payment_id, "canceled")
        logger.info(f"Payment {payment_id} canceled")
        return True
    
    return False
