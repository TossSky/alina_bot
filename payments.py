"""Payments Module - Subscription Management with YooKassa and Telegram Stars"""

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Update
from telegram.ext import ContextTypes

from config import Config
from yookassa_integration import YooKassaClient

logger = logging.getLogger(__name__)


class SubscriptionManager:
    """Manages user subscriptions and payment processing"""
    
    SUBSCRIPTION_PLANS = {
        "day": {
            "name": "День",
            "price_rub": 10,
            "price_stars": 60,
            "days": 1,
            "description": "Подписка на 1 день"
        },
        "week": {
            "name": "Неделя",
            "price_rub": 499.00,
            "price_stars": 300,
            "days": 7,
            "description": "Подписка на 7 дней"
        },
        "month": {
            "name": "Месяц",
            "price_rub": 1499.00,
            "price_stars": 900,
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
                    payment_method TEXT DEFAULT 'rub',
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
            
            try:
                cursor.execute("ALTER TABLE subscriptions ADD COLUMN payment_method TEXT DEFAULT 'rub'")
            except sqlite3.OperationalError:
                pass
    
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
                    payment_method TEXT DEFAULT 'rub',
                    amount REAL NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            try:
                cursor.execute("ALTER TABLE pending_payments ADD COLUMN payment_method TEXT DEFAULT 'rub'")
            except sqlite3.OperationalError:
                pass
    
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
                SELECT id, plan_type, start_date, end_date, amount, currency, payment_method
                FROM subscriptions 
                WHERE user_id = ? AND is_active = 1 AND end_date > CURRENT_TIMESTAMP
                ORDER BY end_date DESC LIMIT 1
            """, (user_id,))
            
            row = cursor.fetchone()
            if row:
                return dict(zip(["id", "plan_type", "start_date", "end_date", "amount", "currency", "payment_method"], row))
            return None
    
    def add_subscription(self, user_id: int, plan_type: str, payment_id: str = None, payment_method: str = "rub") -> bool:
        """Add or extend user subscription"""
        if plan_type not in self.SUBSCRIPTION_PLANS:
            logger.error(f"Unknown subscription plan: {plan_type}")
            return False
        
        plan = self.SUBSCRIPTION_PLANS[plan_type]
        duration = timedelta(days=plan["days"])
        amount = plan["price_rub"] if payment_method == "rub" else plan["price_stars"]
        currency = "RUB" if payment_method == "rub" else "XTR"
        
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, end_date FROM subscriptions
                WHERE user_id = ? AND is_active = 1 AND end_date > CURRENT_TIMESTAMP
                ORDER BY end_date DESC LIMIT 1
            """, (user_id,))
            
            existing = cursor.fetchone()
            now = datetime.now()
            
            if existing:
                sub_id, current_end = existing
                current_end_dt = datetime.fromisoformat(current_end)
                new_end = max(current_end_dt, now) + duration
                
                cursor.execute("""
                    UPDATE subscriptions
                    SET plan_type = ?, end_date = ?, amount = COALESCE(amount, 0) + ?
                    WHERE id = ?
                """, (plan_type, new_end, amount, sub_id))
                
                logger.info(f"Extended subscription for user {user_id}: {current_end_dt} -> {new_end}")
            else:
                new_end = now + duration
                cursor.execute("""
                    INSERT INTO subscriptions 
                    (user_id, plan_type, end_date, payment_id, payment_method, amount, currency)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (user_id, plan_type, new_end, payment_id, payment_method, amount, currency))
                
                logger.info(f"Created subscription for user {user_id} until {new_end} via {payment_method}")
            
            return True
    
    def save_pending_payment(self, user_id: int, payment_id: str, plan_type: str, amount: float, payment_method: str = "rub"):
        """Save pending payment to track it"""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO pending_payments (user_id, payment_id, plan_type, payment_method, amount)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, payment_id, plan_type, payment_method, amount))
            conn.commit()
    
    def get_pending_payment(self, payment_id: str) -> Optional[Dict]:
        """Get pending payment info"""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT user_id, plan_type, amount, status, payment_method
                FROM pending_payments
                WHERE payment_id = ?
            """, (payment_id,))
            
            row = cursor.fetchone()
            if row:
                return dict(zip(["user_id", "plan_type", "amount", "status", "payment_method"], row))
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
    
    def get_payment_method_keyboard(self) -> InlineKeyboardMarkup:
        """Generate payment method selection keyboard"""
        keyboard = [
            [InlineKeyboardButton("⭐ Оплатить звёздочками", callback_data="payment_method_stars")],
            [InlineKeyboardButton("💳 Оплатить рублями (ЮКасса)", callback_data="payment_method_rub")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def get_subscription_keyboard(self, payment_method: str = "rub") -> InlineKeyboardMarkup:
        """Generate subscription options keyboard with callback data"""
        keyboard = []
        for plan_id, plan in self.SUBSCRIPTION_PLANS.items():
            if payment_method == "stars":
                price = plan["price_stars"]
                symbol = "⭐"
            else:
                price = plan["price_rub"]
                symbol = "₽"
            
            button = InlineKeyboardButton(
                f"{plan['name']} - {price:.0f} {symbol}",
                callback_data=f"subscribe_{payment_method}_{plan_id}"
            )
            keyboard.append([button])
        
        keyboard.append([InlineKeyboardButton("◀️ Назад к выбору способа оплаты", callback_data="back_to_payment_methods")])
        
        return InlineKeyboardMarkup(keyboard)


async def handle_stars_pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle pre-checkout query for Stars payment"""
    query = update.pre_checkout_query
    await query.answer(ok=True)
    logger.info(f"Pre-checkout approved for Stars payment: {query.invoice_payload}")


async def handle_stars_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle successful Stars payment"""
    manager = context.bot_data.get('subscription_manager')
    
    if not manager:
        logger.error("Subscription manager not initialized")
        return
    
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    
    payload_parts = payment.invoice_payload.split('_')
    
    if len(payload_parts) >= 2 and payload_parts[0] == "stars":
        plan_type = payload_parts[1]
        
        if manager.add_subscription(user_id, plan_type, payment.telegram_payment_charge_id, payment_method="stars"):
            plan = SubscriptionManager.SUBSCRIPTION_PLANS.get(plan_type, {})
            
            await update.message.reply_text(
                f"✅ *Оплата успешна!*\n\n"
                f"Ваша подписка '{plan.get('name', plan_type)}' активирована.\n"
                f"Срок действия: {plan.get('days', 0)} дней\n\n"
                f"Теперь вы можете пользоваться ботом без ограничений! 💜",
                parse_mode="Markdown"
            )
            
            logger.info(f"Stars payment succeeded: user {user_id}, plan {plan_type}, amount {payment.total_amount} stars")
        else:
            await update.message.reply_text(
                "Произошла ошибка при активации подписки. "
                "Пожалуйста, обратитесь к администратору."
            )
    else:
        logger.error(f"Invalid Stars payment payload: {payment.invoice_payload}")


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
    
    payment = yookassa.create_payment(
        amount=plan["price_rub"],
        description=f"Подписка - {plan['name']}",
        metadata={
            "user_id": user_id,
            "plan_type": plan_type,
            "telegram_username": update.effective_user.username or ""
        }
    )
    
    if not payment:
        await update.message.reply_text("Ошибка создания платежа. Попробуйте позже.")
        return
    
    manager.save_pending_payment(user_id, payment["id"], plan_type, plan["price_rub"], payment_method="rub")
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Оплатить", url=payment["confirmation_url"])]
    ])
    
    await update.message.reply_text(
        f"💰 *Оплата подписки*\n\n"
        f"План: {plan['name']}\n"
        f"Стоимость: {plan['price_rub']:.0f} ₽\n\n"
        f"Нажмите кнопку для оплаты.\n"
        f"После оплаты вернитесь в бот — подписка активируется автоматически!",
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    
    logger.info(f"Created YooKassa payment {payment['id']} for user {user_id}, plan {plan_type}")


async def handle_subscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle subscription button press"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    manager = context.bot_data.get('subscription_manager')
    
    if data == "payment_method_stars":
        keyboard = []
        for plan_id, plan in SubscriptionManager.SUBSCRIPTION_PLANS.items():
            price = plan["price_stars"]
            keyboard.append([InlineKeyboardButton(f"{plan['name']} - {price} ⭐", callback_data=f"stars_direct_{plan_id}")])

        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_payment_methods")])
        keyboard.append([InlineKeyboardButton("❌", callback_data="close_subscribe")])

        await query.message.edit_text(
            "⭐ *Оплата звёздочками Telegram*\n\n"
            "Выберите период подписки:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    elif data == "payment_method_rub":
        base = manager.get_subscription_keyboard("rub")
        rows = [list(row) for row in base.inline_keyboard]
        rows.append([InlineKeyboardButton("❌", callback_data="close_subscribe")])
        reply_markup = InlineKeyboardMarkup(rows)

        await query.message.edit_text(
            "💳 *Оплата рублями через ЮКассу*\n\n"
            "Выберите период подписки:",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
        return
    
    elif data == "back_to_payment_methods":
        base = manager.get_payment_method_keyboard()
        rows = [list(row) for row in base.inline_keyboard]
        rows.append([InlineKeyboardButton("❌", callback_data="close_subscribe")])
        reply_markup = InlineKeyboardMarkup(rows)

        await query.message.edit_text(
            "🌟 *Оформление подписки*\n\n"
            "Выберите способ оплаты:",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
        return
    
    if data.startswith("stars_direct_"):
        plan_type = data.replace("stars_direct_", "")
        
        if not manager or plan_type not in SubscriptionManager.SUBSCRIPTION_PLANS:
            await query.answer("Ошибка: неверный тип подписки", show_alert=True)
            return
        
        plan = SubscriptionManager.SUBSCRIPTION_PLANS[plan_type]
        user_id = update.effective_user.id
        
        try:
            await query.message.delete()
        except:
            pass
            
        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title=f"Подписка - {plan['name']}",
            description=plan["description"],
            payload=f"stars_{plan_type}_{user_id}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="⭐", amount=plan["price_stars"])],
            is_flexible=False,
            start_parameter=f"subscription-{plan_type}",
        )
        
        logger.info(f"Created Stars invoice for user {user_id}, plan {plan_type}, amount {plan['price_stars']} stars")
        return
    
    if data.startswith("subscribe_stars_"):
        plan_type = data.replace("subscribe_stars_", "")
        
        if not manager or plan_type not in SubscriptionManager.SUBSCRIPTION_PLANS:
            await query.answer("Ошибка: неверный тип подписки", show_alert=True)
            return
        
        plan = SubscriptionManager.SUBSCRIPTION_PLANS[plan_type]
        user_id = update.effective_user.id
        
        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title=f"Подписка - {plan['name']}",
            description=plan["description"],
            payload=f"stars_{plan_type}_{user_id}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="⭐", amount=plan["price_stars"])],
            is_flexible=False,
            start_parameter=f"subscription-{plan_type}",
        )
        
        logger.info(f"Created Stars invoice for user {user_id}, plan {plan_type}, amount {plan['price_stars']} stars")
        return
    
    elif data.startswith("subscribe_rub_"):
        plan_type = data.replace("subscribe_rub_", "")
        yookassa = context.bot_data.get('yookassa_client')
        
        if not manager or not yookassa or plan_type not in SubscriptionManager.SUBSCRIPTION_PLANS:
            await query.message.reply_text("Ошибка: система оплаты не инициализирована")
            return
        
        plan = SubscriptionManager.SUBSCRIPTION_PLANS[plan_type]
        user_id = update.effective_user.id
        
        payment = yookassa.create_payment(
            amount=plan["price_rub"],
            description=f"Подписка - {plan['name']}",
            metadata={
                "user_id": user_id,
                "plan_type": plan_type,
                "telegram_username": update.effective_user.username or ""
            }
        )
        
        if not payment:
            await query.message.reply_text("Ошибка создания платежа. Попробуйте позже.")
            return
        
        manager.save_pending_payment(user_id, payment["id"], plan_type, plan["price_rub"], payment_method="rub")
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Оплатить", url=payment["confirmation_url"])]
        ])
       
        try:
            await query.message.delete()
        except:
            pass

        await query.message.reply_text(
            f"💳 *{plan['name']} - {plan['price_rub']:.0f} ₽*\n\n"
            f"Нажмите кнопку для перехода к оплате.\n"
            f"После оплаты подписка активируется автоматически!",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        
        logger.info(f"Created YooKassa payment {payment['id']} for user {user_id}, plan {plan_type}")


async def process_payment_notification(payment_data: dict, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Process payment notification from YooKassa webhook"""
    manager = context.bot_data.get('subscription_manager')
    
    if not manager:
        logger.error("Subscription manager not initialized")
        return False
    
    payment_id = payment_data.get("id")
    status = payment_data.get("status")
    
    if not payment_id:
        logger.error("No payment_id in notification")
        return False
    
    pending = manager.get_pending_payment(payment_id)
    
    if not pending:
        logger.warning(f"Pending payment not found: {payment_id}")
        return False
    
    user_id = pending["user_id"]
    plan_type = pending["plan_type"]
    payment_method = pending.get("payment_method", "rub")
    
    if status == "succeeded":
        if manager.add_subscription(user_id, plan_type, payment_id, payment_method=payment_method):
            manager.update_payment_status(payment_id, "succeeded")
            
            plan = SubscriptionManager.SUBSCRIPTION_PLANS.get(plan_type, {})
            
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"✅ *Оплата успешна!*\n\n"
                         f"Ваша подписка '{plan.get('name', plan_type)}' активирована.\n"
                         f"Срок действия: {plan.get('days', 0)} дней\n\n"
                         f"Теперь вы можете пользоваться ботом без ограничений! 💜",
                    parse_mode="Markdown"
                )
                logger.info(f"YooKassa payment {payment_id} succeeded for user {user_id}")
                return True
            except Exception as e:
                logger.error(f"Failed to send success message to user {user_id}: {e}")
                return False
        else:
            logger.error(f"Failed to activate subscription for payment {payment_id}")
            return False
    
    elif status == "canceled":
        manager.update_payment_status(payment_id, "canceled")
        logger.info(f"YooKassa payment {payment_id} canceled")
        return True
    
    return False
