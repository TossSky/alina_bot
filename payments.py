# payments.py - Модуль для работы с платежами и подписками
"""
Обработка платежей через PayMaster и управление подписками.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from telegram import Update, LabeledPrice, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


class SubscriptionManager:
    """Управление подписками пользователей."""
    
    # Тарифные планы (цены в копейках)
    SUBSCRIPTION_PLANS = {
        "day": {
            "name": "День",
            "price": 9900,  # 99 рублей
            "days": 1,
            "description": "Подписка на 1 день"
        },
        "week": {
            "name": "Неделя", 
            "price": 49900,  # 499 рублей
            "days": 7,
            "description": "Подписка на 7 дней"
        },
        "month": {
            "name": "Месяц",
            "price": 149900,  # 1499 рублей
            "days": 30,
            "description": "Подписка на 30 дней"
        }
    }
    
    def __init__(self, db):
        """
        Args:
            db: Экземпляр DialogueDB
        """
        self.db = db
        self._init_subscription_table()
    
    def _init_subscription_table(self):
        """Создает таблицу подписок если её нет."""
        import sqlite3
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            
            # Таблица подписок
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
            
            # Индекс для быстрого поиска активных подписок
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_subscriptions_active 
                ON subscriptions (user_id, is_active, end_date)
            """)
            
            conn.commit()
    
    def has_active_subscription(self, user_id: int) -> bool:
        """Проверяет наличие активной подписки."""
        import sqlite3
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT COUNT(*) FROM subscriptions 
                WHERE user_id = ? 
                AND is_active = 1 
                AND end_date > CURRENT_TIMESTAMP
            """, (user_id,))
            
            count = cursor.fetchone()[0]
            return count > 0
    
    def get_active_subscription(self, user_id: int) -> Optional[Dict]:
        """Получает информацию об активной подписке."""
        import sqlite3
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, plan_type, start_date, end_date, amount, currency
                FROM subscriptions 
                WHERE user_id = ? 
                AND is_active = 1 
                AND end_date > CURRENT_TIMESTAMP
                ORDER BY end_date DESC
                LIMIT 1
            """, (user_id,))
            
            row = cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "plan_type": row[1],
                    "start_date": row[2],
                    "end_date": row[3],
                    "amount": row[4],
                    "currency": row[5]
                }
            return None
    
    def add_subscription(self, user_id: int, plan_type: str, payment_id: str = None) -> bool:
        if plan_type not in self.SUBSCRIPTION_PLANS:
            logger.error(f"Unknown subscription plan: {plan_type}")
            return False

        plan = self.SUBSCRIPTION_PLANS[plan_type]
        add_delta = timedelta(minutes=plan["minutes"]) if "minutes" in plan else timedelta(days=plan["days"])

        import sqlite3
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()

            # Есть ли уже активная подписка?
            cursor.execute("""
                SELECT id, plan_type, end_date
                FROM subscriptions
                WHERE user_id = ? AND is_active = 1 AND end_date > CURRENT_TIMESTAMP
                ORDER BY end_date DESC LIMIT 1
            """, (user_id,))
            row = cursor.fetchone()

            now = datetime.now()

            if row:
                # ПРОДЛЕВАЕМ текущую активную подписку
                sub_id, cur_plan, cur_end = row[0], row[1], row[2]
                cur_end_dt = datetime.fromisoformat(cur_end)

                # Продлеваем от большего из (сейчас, текущий конец)
                base = cur_end_dt if cur_end_dt > now else now
                new_end = base + add_delta

                # (опционально) можно обновить plan_type на новый
                cursor.execute("""
                    UPDATE subscriptions
                    SET plan_type = ?, end_date = ?, amount = COALESCE(amount,0) + ?, is_active = 1
                    WHERE id = ?
                """, (plan_type, new_end, plan["price"], sub_id))
                logger.info(f"Extended subscription for user {user_id}: {cur_end_dt} -> {new_end} ({plan_type})")
            else:
                # НЕТ активной: создаём новую
                new_end = now + add_delta
                cursor.execute("""
                    INSERT INTO subscriptions (user_id, plan_type, end_date, payment_id, amount, currency, is_active)
                    VALUES (?, ?, ?, ?, ?, 'RUB', 1)
                """, (user_id, plan_type, new_end, payment_id, plan["price"]))
                logger.info(f"Created new subscription for user {user_id} until {new_end} ({plan_type})")

            conn.commit()
            return True

    
    def get_subscription_keyboard(self) -> InlineKeyboardMarkup:
        """Создает клавиатуру с вариантами подписки."""
        keyboard = []
        
        for plan_id, plan in self.SUBSCRIPTION_PLANS.items():
            price_rub = plan["price"] // 100
            button_text = f"{plan['name']} - {price_rub} ₽"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"subscribe_{plan_id}")])
        
        return InlineKeyboardMarkup(keyboard)
    
    def get_days_remaining(self, user_id: int) -> int:
        """Возвращает количество дней до окончания подписки."""
        subscription = self.get_active_subscription(user_id)
        if not subscription:
            return 0
        
        end_date = datetime.fromisoformat(subscription["end_date"])
        days_left = (end_date - datetime.now()).days
        return max(0, days_left)
    
    def format_subscription_info(self, user_id: int) -> str:
        """Форматирует информацию о подписке для отображения."""
        subscription = self.get_active_subscription(user_id)
        
        if not subscription:
            return "У вас нет активной подписки."
        
        days_left = self.get_days_remaining(user_id)
        plan_name = self.SUBSCRIPTION_PLANS.get(subscription["plan_type"], {}).get("name", subscription["plan_type"])
        end_date = datetime.fromisoformat(subscription["end_date"]).strftime("%d.%m.%Y")
        
        if days_left == 0:
            return f"Ваша подписка ({plan_name}) истекает сегодня!"
        elif days_left == 1:
            return f"Ваша подписка ({plan_name}) активна ещё 1 день (до {end_date})"
        else:
            return f"Ваша подписка ({plan_name}) активна ещё {days_left} дней (до {end_date})"


async def create_invoice(
    update: Update, 
    context: ContextTypes.DEFAULT_TYPE,
    plan_type: str,
    payments_token: str
) -> None:
    """Создает и отправляет invoice для оплаты."""
    
    # берём из bot_data, а если нет — используем глобальный экземпляр
    manager = context.bot_data.get('subscription_manager') or SubscriptionManager(getattr(context.application, "db", None) or None)
    # но у тебя subscription_manager уже создан в bot.py и импортирован — используем его напрямую:
    from payments import SubscriptionManager  # (если уже есть импорт — не дублировать)
    try:
        manager = context.bot_data.get('subscription_manager') or subscription_manager
    except NameError:
        # если глобальная переменная недоступна в этом модуле, подстрахуемся:
        manager = context.bot_data.get('subscription_manager')

    # фиксируем в bot_data на будущее
    context.bot_data['subscription_manager'] = manager

    if not manager:
        await update.callback_query.answer("Ошибка: система подписок не инициализирована")
        return

    
    if plan_type not in SubscriptionManager.SUBSCRIPTION_PLANS:
        await update.callback_query.answer("Неверный тип подписки")
        return
    
    plan = SubscriptionManager.SUBSCRIPTION_PLANS[plan_type]
    
    # Проверяем тестовый режим
    if payments_token.split(':')[1] == 'TEST':
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ Тестовый платеж! Средства не будут списаны."
        )
    
    # Создаем цену
    price = LabeledPrice(label=plan["description"], amount=plan["price"])
    
    # Отправляем invoice
    await context.bot.send_invoice(
        chat_id=update.effective_chat.id,
        title=f"Подписка на бота Алину - {plan['name']}",
        description=plan["description"],
        payload=f"{plan_type}_{update.effective_user.id}",  # Сохраняем тип подписки и user_id
        provider_token=payments_token,
        currency="RUB",
        prices=[price],
        photo_url="https://images.unsplash.com/photo-1573164713714-d95e436ab8d6?w=400",  # Можно заменить на свою картинку
        photo_width=400,
        photo_height=250,
        photo_size=400,
        is_flexible=False,
        start_parameter=f"subscription-{plan_type}",
        protect_content=True
    )


async def handle_subscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатия на кнопку подписки."""
    query = update.callback_query
    await query.answer()
    
    # Извлекаем тип подписки из callback_data
    # Формат: subscribe_day, subscribe_week, subscribe_month
    plan_type = query.data.replace("subscribe_", "")
    
    # Получаем токен платежей из конфига
    from config import Config
    config = Config()
    
    # Создаем и отправляем invoice
    await create_invoice(update, context, plan_type, config.payments_token)