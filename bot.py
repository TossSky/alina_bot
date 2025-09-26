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
SYSTEM_PROMPT = enrich_prompt(ALINA_PERSONALITY, {})  # создаётся один раз при старте
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
        # Показываем информацию об использовании лимитов
        usage = db.get_user_usage(user_id)
        messages_used = usage["messages"]
        tokens_used = usage["tokens"]
        messages_left = max(0, config.free_messages_limit - messages_used)
        tokens_left = max(0, config.free_tokens_limit - tokens_used)
        
        await update.message.reply_text(
            "❌ *У вас нет активной подписки*\n\n"
            f"📦 *Бесплатные лимиты:*\n"
            f"💬 Сообщения: {messages_used}/{config.free_messages_limit} (осталось {messages_left})\n"
            f"🎯 Токены: {tokens_used}/{config.free_tokens_limit} (осталось {tokens_left})\n\n"
            "Используйте /subscribe для оформления подписки.",
            parse_mode='Markdown'
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
    user = update.effective_user
    db.get_or_create_user(user_id=user.id)
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


async def reset_limits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /reset_limits — сброс лимитов (только для админов)."""
    user_id = update.effective_user.id
    admin_ids = getattr(config, "admin_ids", [])

    # Если список админов задан и текущий пользователь не админ — молча выходим
    if admin_ids and user_id not in admin_ids:
        # можно оставить лог, чтобы видеть попытки (в чат ничего не отправляем)
        logger.warning(f"Non-admin {user_id} tried to use /reset_limits")
        return

    # Сбрасываем лимиты текущему пользователю
    db.reset_user_limits(user_id)

    await update.message.reply_text(
        "✅ Лимиты сброшены!\n\n"
        f"💬 Доступно: {config.free_messages_limit} сообщений\n"
        f"🎯 Доступно: {config.free_tokens_limit} токенов"
    )

    logger.info(f"Admin {user_id} reset their limits")



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
            # Получаем информацию об использовании
            usage = db.get_user_usage(user_id)
            messages_used = usage["messages"]
            tokens_used = usage["tokens"]
            
            # Проверяем оба лимита
            messages_exceeded = messages_used >= config.free_messages_limit
            tokens_exceeded = tokens_used >= config.free_tokens_limit
            
            if messages_exceeded or tokens_exceeded:
                limit_msg = ""
                if messages_exceeded:
                    limit_msg = f"💬 Использовано сообщений: {messages_used}/{config.free_messages_limit}\n"
                if tokens_exceeded:
                    limit_msg += f"🎯 Использовано токенов: {tokens_used}/{config.free_tokens_limit}\n"
                
                await update.message.reply_text(
                    f"❌ Вы достигли лимита бесплатного использования:\n\n"
                    f"{limit_msg}\n"
                    "Для продолжения общения необходима подписка.\n"
                    "Используйте /subscribe для оформления.",
                    reply_markup=subscription_manager.get_subscription_keyboard()
                )
                return

    # Лог и сохранение входящего
    logger.info(f"User {user_id}: {user_message}")
    db.add_message(user_id, "user", user_message)

    # История уже содержит только что сохранённое сообщение пользователя
    history: List[Dict[str, str]] = db.get_dialogue_history(user_id, limit=20)

    messages: List[Dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)

    sys_tokens_only = llm.count_tokens_messages([{"role": "system", "content": SYSTEM_PROMPT}])

    hist_tok  = llm.count_tokens_messages(history)
    total_est = llm.count_tokens_messages(messages)
    logger.info(f"CTX tokens: system={sys_tokens_only}, history={hist_tok}, total_est={total_est}")


    # Генерация ответа
    response_text, tokens_used_total = await llm.generate_response(messages)
    response_text = (response_text or "").strip() or "Хм, не уверена, что поняла."

    # ВЫЧИТАЕМ system-промпт из общих токенов для пользовательских лимитов
    tokens_used_net = max(0, tokens_used_total - sys_tokens_only)

    # Добавляем предупреждение о лимите, если нужно
    warning = ""
    if config.subscription_required and not subscription_manager.has_active_subscription(user_id):
        usage = db.get_user_usage(user_id)
        messages_used = usage["messages"] + 1  # +1 за текущее сообщение пользователя
        tokens_total = usage["tokens"] + tokens_used_net  # ← считаем по NETTO

        messages_left = config.free_messages_limit - messages_used
        tokens_left = config.free_tokens_limit - tokens_total

        if messages_left <= 3 or tokens_left <= 500:
            warning = "\n\n_⚠️ Лимиты бесплатного использования:_\n"
            if messages_left <= 3:
                warning += f"_💬 Осталось сообщений: {messages_left}_\n"
            if tokens_left <= 500:
                warning += f"_🎯 Осталось токенов: {max(0, tokens_left)}_\n"
            if messages_left == 0 or tokens_left <= 0:
                warning += "_\n🔴 Это было ваше последнее бесплатное сообщение! /subscribe_"

    # Отправка и сохранение
    final_response = response_text + warning
    await update.message.reply_text(final_response, parse_mode='Markdown')

    # Сохраняем в БД NETTO-токены (без system)
    db.add_message(user_id, "assistant", response_text, tokens_used_net)
    logger.info(
        f"Alina: {response_text[:100]}... (tokens_net: {tokens_used_net}, total_raw: {tokens_used_total}, sys: {sys_tokens_only})"
    )



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
    application.bot_data['subscription_manager'] = subscription_manager


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
