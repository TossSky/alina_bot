# bot.py - Главный файл бота Алины
"""
Базовая версия: только приём сообщений, история и ответ LLM.
С personality.py подключается базовый промпт.
"""

import logging
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
    text = "Я Алина. Пиши, о чём хочешь поговорить."
    logger.info(f"Alina: {text}")
    await update.message.reply_text(text)


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

    # История
    history: List[Dict[str, str]] = db.get_dialogue_history(user_id, limit=20)

    # Промпт из personality
    system_prompt = enrich_prompt(ALINA_PERSONALITY, {})

    # Формируем сообщения
    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

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
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Алина запущена")
    application.run_polling()


if __name__ == "__main__":
    main()
