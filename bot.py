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
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import Config
from database import DialogueDB
from llm import AlinaLLM
from personality import ALINA_PERSONALITY, enrich_prompt

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

# ---------------------------
# Обработчики
# ---------------------------

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
    await update.message.reply_text(response)
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
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Алина запущена")
    application.run_polling()


if __name__ == "__main__":
    main()
