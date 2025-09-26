# bot.py - Главный файл бота Алины
"""
Telegram бот с поддержкой платных подписок и интеграцией с LLM.
"""

import logging
import os
import sys
from typing import Dict, List

from telegram import Update
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

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telegram.ext._application").setLevel(logging.WARNING)

logger = logging.getLogger("alina-bot")

# Инициализация компонентов
config = Config()
db = DialogueDB()
llm = AlinaLLM(
    api_key=config.openai_api_key,
    model=config.openai_model,
    use_proxy=config.use_proxy,
    proxy_url=config.proxy_url,
)
subscription_manager = SubscriptionManager(db)
SYSTEM_PROMPT = enrich_prompt(ALINA_PERSONALITY, {})


# === Команды бота ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start - приветствие."""
    user = update.effective_user
    db.get_or_create_user(user_id=user.id)
    
    text = "Меня зовут Алина) рада буду пообщаться с тобой!"
    logger.info(f"New user: {user.id}")
    await update.message.reply_text(text)


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /subscribe - показывает варианты подписки."""
    user_id = update.effective_user.id
    
    context.bot_data['subscription_manager'] = subscription_manager
    
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
    user_id = update.effective_user.id
    
    if subscription_manager.has_active_subscription(user_id):
        info = subscription_manager.format_subscription_info(user_id)
        await update.message.reply_text(f"✅ {info}")
    else:
        usage = db.get_user_usage(user_id)
        messages_left = max(0, config.free_messages_limit - usage["messages"])
        tokens_left = max(0, config.free_tokens_limit - usage["tokens"])
        
        await update.message.reply_text(
            "❌ *У вас нет активной подписки*\n\n"
            f"📦 *Бесплатные лимиты:*\n"
            f"💬 Сообщения: {usage['messages']}/{config.free_messages_limit} (осталось {messages_left})\n"
            f"🎯 Токены: {usage['tokens']}/{config.free_tokens_limit} (осталось {tokens_left})\n\n"
            "Используйте /subscribe для оформления подписки.",
            parse_mode='Markdown'
        )


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /restart - перезапускает бота (для всех)."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} initiated bot restart")
    
    await update.message.reply_text("Перезапускаюсь... Подождите несколько секунд.")
    
    python = sys.executable
    script = os.path.abspath(sys.argv[0])
    os.execv(python, [python, script] + sys.argv[1:])


async def reset_limits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /reset_limits - сброс лимитов (только для админов)."""
    user_id = update.effective_user.id
    
    if config.admin_ids and user_id not in config.admin_ids:
        logger.warning(f"Non-admin {user_id} tried to use /reset_limits")
        return
    
    db.reset_user_limits(user_id)
    
    await update.message.reply_text(
        "✅ Лимиты сброшены!\n\n"
        f"💬 Доступно: {config.free_messages_limit} сообщений\n"
        f"🎯 Доступно: {config.free_tokens_limit} токенов"
    )
    logger.info(f"Admin {user_id} reset their limits")


# === Обработчики платежей ===

async def pre_checkout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик pre-checkout запроса."""
    query = update.pre_checkout_query
    await query.answer(ok=True)
    logger.info(f"Pre-checkout query from user {query.from_user.id}")


async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик успешной оплаты."""
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    
    payload_parts = payment.invoice_payload.split('_')
    if not payload_parts:
        await update.message.reply_text(
            "Ошибка обработки платежа. Обратитесь к администратору."
        )
        return
    
    plan_type = payload_parts[0]
    
    if subscription_manager.add_subscription(user_id, plan_type, payment.provider_payment_charge_id):
        plan = subscription_manager.SUBSCRIPTION_PLANS.get(plan_type, {})
        await update.message.reply_text(
            f"✅ Спасибо за оплату!\n\n"
            f"Ваша подписка '{plan.get('name', plan_type)}' активирована.\n"
            f"Срок действия: {plan.get('days', 0)} дней\n\n"
            f"Теперь вы можете пользоваться ботом без ограничений! 💜"
        )
        logger.info(f"Payment successful: User {user_id}, Plan {plan_type}, Amount {payment.total_amount}")
    else:
        await update.message.reply_text(
            "Произошла ошибка при активации подписки. "
            "Пожалуйста, обратитесь к администратору."
        )


# === Основной обработчик сообщений ===

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений от пользователя."""
    user_id = update.effective_user.id
    user_message = (update.message.text or "").strip()
    
    if not user_message:
        return
    
    # Проверка лимитов при отсутствии подписки
    if config.subscription_required and not subscription_manager.has_active_subscription(user_id):
        usage = db.get_user_usage(user_id)
        
        if usage["messages"] >= config.free_messages_limit or usage["tokens"] >= config.free_tokens_limit:
            limit_msg = []
            if usage["messages"] >= config.free_messages_limit:
                limit_msg.append(f"💬 Сообщения: {usage['messages']}/{config.free_messages_limit}")
            if usage["tokens"] >= config.free_tokens_limit:
                limit_msg.append(f"🎯 Токены: {usage['tokens']}/{config.free_tokens_limit}")
            
            await update.message.reply_text(
                f"❌ Вы достигли лимита бесплатного использования:\n\n"
                f"{chr(10).join(limit_msg)}\n\n"
                "Для продолжения общения необходима подписка.\n"
                "Используйте /subscribe для оформления.",
                reply_markup=subscription_manager.get_subscription_keyboard()
            )
            return
    
    # Сохранение сообщения пользователя
    logger.info(f"User {user_id}: {user_message[:50]}...")
    db.add_message(user_id, "user", user_message)
    
    # Формирование контекста для LLM
    history = db.get_dialogue_history(user_id, limit=20)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    
    # Подсчет токенов для логирования
    sys_tokens = llm.count_tokens_messages([{"role": "system", "content": SYSTEM_PROMPT}])
    hist_tokens = llm.count_tokens_messages(history)
    total_input = llm.count_tokens_messages(messages)
    logger.info(f"Context: system={sys_tokens}, history={hist_tokens}, total={total_input}")
    
    # Генерация ответа
    response_text, tokens_total = await llm.generate_response(messages)
    response_text = response_text.strip() or "Хм, не уверена, что поняла."
    
    # Вычитаем системный промпт из учета токенов пользователя
    tokens_net = max(0, tokens_total - sys_tokens)
    
    # Добавление предупреждения о лимитах
    warning = ""
    if config.subscription_required and not subscription_manager.has_active_subscription(user_id):
        usage = db.get_user_usage(user_id)
        messages_left = config.free_messages_limit - (usage["messages"] + 1)
        tokens_left = config.free_tokens_limit - (usage["tokens"] + tokens_net)
        
        if messages_left <= 3 or tokens_left <= 500:
            warning = "\n\n_⚠️ Лимиты бесплатного использования:_\n"
            if messages_left <= 3:
                warning += f"_💬 Осталось сообщений: {max(0, messages_left)}_\n"
            if tokens_left <= 500:
                warning += f"_🎯 Осталось токенов: {max(0, tokens_left)}_\n"
            if messages_left <= 0 or tokens_left <= 0:
                warning += "_\n🔴 Это было ваше последнее бесплатное сообщение! /subscribe_"
    
    # Отправка ответа
    final_response = response_text + warning
    await update.message.reply_text(final_response, parse_mode='Markdown')
    
    # Сохранение ответа и токенов
    db.add_message(user_id, "assistant", response_text, tokens_net)
    logger.info(f"Assistant: {response_text[:50]}... (tokens: {tokens_net})")


# === Точка входа ===

def main():
    """Запуск бота."""
    if not config.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN не установлен!")
        return
    
    if not config.openai_api_key:
        logger.error("OPENAI_API_KEY не установлен!")
        return
    
    # Создание и настройка приложения
    application = Application.builder().token(config.telegram_bot_token).build()
    application.bot_data['subscription_manager'] = subscription_manager
    
    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("restart", restart))
    application.add_handler(CommandHandler("reset_limits", reset_limits))
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
