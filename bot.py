# bot.py - Главный файл бота Алины
"""
Базовая версия: только приём сообщений, история и ответ LLM.
С personality.py подключается базовый промпт.
"""

import logging
import os
import sys
from typing import Dict, List

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
)

from config import Config
from database import DialogueDB
from llm import AlinaLLM
from personality import ALINA_PERSONALITY, enrich_prompt
from payments import SubscriptionManager, create_invoice, handle_subscribe_callback

# ---------------------------
# Инициализация
# ---------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
# Оставляем только свои INFO, а сторонние снижаем
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telegram.ext._application").setLevel(logging.WARNING)

logger = logging.getLogger("alina-bot")

config = Config()
db = DialogueDB()
llm = AlinaLLM(
    api_key=config.openai_api_key,
    model=config.openai_model,
    use_proxy=config.use_proxy,
    proxy_url=config.proxy_url,
)

# Менеджер подписок
subscription_manager = SubscriptionManager(db)

# ---------------------------
# Обработчики
# ---------------------------

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /subscribe - показывает варианты подписки."""
    user = update.effective_user
    user_id = user.id
    
    # Сохраняем менеджер подписок в контексте
    context.bot_data['subscription_manager'] = subscription_manager
    
    # Проверяем текущую подписку
    if subscription_manager.has_active_subscription(user_id):
        info = subscription_manager.format_subscription_info(user_id)
        await update.message.reply_text(
            f"✅ {info}\n\n"
            "Хотите продлить подписку заранее? Выберите новый период:",
            reply_markup=subscription_manager.get_subscription_keyboard()
        )
    else:
        await update.message.reply_text(
            "🌟 Оформите подписку на бота Алину!\n\n"
            "Выберите удобный период:",
            reply_markup=subscription_manager.get_subscription_keyboard()
        )


async def subscription_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /subscription - проверка статуса подписки."""
    user = update.effective_user
    user_id = user.id
    
    if subscription_manager.has_active_subscription(user_id):
        info = subscription_manager.format_subscription_info(user_id)
        await update.message.reply_text(f"✅ {info}")
    else:
        await update.message.reply_text(
            "❌ У вас нет активной подписки.\n\n"
            "Используйте /subscribe для оформления."
        )


async def pre_checkout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик pre-checkout запроса."""
    query = update.pre_checkout_query
    # Проверяем что всё корректно, отвечаем в течение 10 секунд
    await query.answer(ok=True)
    logger.info(f"Pre-checkout query from user {query.from_user.id}")


async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик успешной оплаты."""
    user = update.effective_user
    user_id = user.id
    payment = update.message.successful_payment
    
    # Извлекаем тип подписки из payload
    payload_parts = payment.invoice_payload.split('_')
    if len(payload_parts) >= 1:
        plan_type = payload_parts[0]
        
        # Добавляем подписку
        if subscription_manager.add_subscription(user_id, plan_type, payment.provider_payment_charge_id):
            plan = subscription_manager.SUBSCRIPTION_PLANS.get(plan_type, {})
            await update.message.reply_text(
                f"✅ Спасибо за оплату!\n\n"
                f"Ваша подписка '{plan.get('name', plan_type)}' активирована.\n"
                f"Срок действия: {plan.get('days', 0)} дней\n\n"
                f"Теперь вы можете пользоваться ботом без ограничений! 💜"
            )
            logger.info(f"Successful payment: User {user_id}, Plan {plan_type}, Amount {payment.total_amount}")
        else:
            await update.message.reply_text(
                "Произошла ошибка при активации подписки. "
                "Пожалуйста, обратитесь к администратору."
            )
    else:
        await update.message.reply_text(
            "Ошибка обработки платежа. Пожалуйста, обратитесь к администратору."
        )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start."""
    user = update.effective_user
    db.get_or_create_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )
    text = "Меня зовут Алина) рада буду пообщаться с тобой!"
    logger.info(f"Alina: {text}")
    await update.message.reply_text(text)


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /restart - перезапускает бота."""
    user = update.effective_user
    user_id = user.id
    
    # Проверяем, есть ли у пользователя права на перезапуск
    # Можно добавить список админов через config или проверять владельца бота
    admin_ids = config.admin_ids if hasattr(config, 'admin_ids') else []
    
    # Если список админов не задан, разрешаем всем (можно изменить логику)
    # if admin_ids and user_id not in admin_ids:
    #     await update.message.reply_text("У вас нет прав для перезапуска бота.")
    #     logger.warning(f"User {user_id} tried to restart bot without permission")
    #     return
    
    logger.info(f"User {user_id} initiated bot restart")
    await update.message.reply_text("Перезапускаюсь... Подождите несколько секунд.")
    
    # Сохраняем путь к Python и скрипту
    python = sys.executable
    script = os.path.abspath(sys.argv[0])
    
    # Перезапускаем процесс
    os.execv(python, [python, script] + sys.argv[1:])


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приём сообщения, сохранение истории и ответ через LLM с personality."""
    user = update.effective_user
    user_id = user.id
    user_message = (update.message.text or "").strip()

    if not user_message:
        return
    
    # Проверяем подписку, если она требуется
    if config.subscription_required:
        if not subscription_manager.has_active_subscription(user_id):
            # Проверяем лимит бесплатных сообщений
            user_data = db.get_or_create_user(user_id)
            free_messages_used = user_data.get('total_messages', 0)
            
            if free_messages_used >= config.free_messages_limit:
                await update.message.reply_text(
                    f"❌ Вы использовали все {config.free_messages_limit} бесплатных сообщений.\n\n"
                    "Для продолжения общения необходима подписка.\n"
                    "Используйте /subscribe для оформления.",
                    reply_markup=subscription_manager.get_subscription_keyboard()
                )
                return
            else:
                messages_left = config.free_messages_limit - free_messages_used - 1
                if messages_left > 0:
                    warning_text = f"\n\n_⚠️ Осталось бесплатных сообщений: {messages_left}_"
                else:
                    warning_text = f"\n\n_⚠️ Это ваше последнее бесплатное сообщение!_"

    # Лог и сохранение входящего
    logger.info(f"User {user_id}: {user_message}")
    db.add_message(user_id, "user", user_message)

    # История уже содержит только что сохранённое сообщение пользователя
    history: List[Dict[str, str]] = db.get_dialogue_history(user_id, limit=20)

    system_prompt = enrich_prompt(ALINA_PERSONALITY, {})

    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    messages.extend(history)  # НИЧЕГО НЕ ДОБАВЛЯЕМ СЮДА ЕЩЁ РАЗ


    # Генерация ответа
    try:
        response = await llm.generate_response(messages, llm_context=None)
    except TypeError:
        response = await llm.generate_response(messages)

    response = (response or "").strip() or "Хм, не уверена, что поняла."

    # Отправка и сохранение
    # Добавляем предупреждение о лимите, если нужно
    if config.subscription_required and not subscription_manager.has_active_subscription(user_id):
        user_data = db.get_or_create_user(user_id)
        free_messages_used = user_data.get('total_messages', 0)
        messages_left = config.free_messages_limit - free_messages_used
        if messages_left > 0 and messages_left <= 2:
            response += f"\n\n_⚠️ Осталось бесплатных сообщений: {messages_left}_"
        elif messages_left == 0:
            response += f"\n\n_⚠️ Это было ваше последнее бесплатное сообщение! Используйте /subscribe для продолжения._"
    
    await update.message.reply_text(response, parse_mode='Markdown')
    db.add_message(user_id, "assistant", response)
    logger.info(f"Alina: {response}")


# ---------------------------
# Точка входа
# ---------------------------

def main():
    if not config.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN не установлен!")
        return

    if not config.openai_api_key:
        logger.error("OPENAI_API_KEY не установлен!")
        return

    application = Application.builder().token(config.telegram_bot_token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("restart", restart))
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("subscription", subscription_status))
    application.add_handler(CallbackQueryHandler(handle_subscribe_callback, pattern="^subscribe_"))
    application.add_handler(PreCheckoutQueryHandler(pre_checkout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Алина запущена")
    application.run_polling()


if __name__ == "__main__":
    main()
