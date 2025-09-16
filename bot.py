# bot.py - Главный файл бота Алины
"""
Базовая версия: только приём сообщений, история и ответ LLM.
"""

import asyncio
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

# ---------------------------
# Инициализация
# ---------------------------

# Логирование (только тексты сообщений)
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
    """Команда /start — без рандома и доп. логики."""
    user = update.effective_user
    db.get_or_create_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )
    text = "Привет! Я Алина. Пиши, о чём хочешь поговорить."
    logger.info(f"Alina: {text}")
    await update.message.reply_text(text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приём сообщения, сохранение истории и ответ через LLM."""
    user = update.effective_user
    user_id = user.id
    user_message = (update.message.text or "").strip()

    if not user_message:
        return

    # Лог и сохранение входящего
    logger.info(f"User {user_id}: {user_message}")
    db.add_message(user_id, "user", user_message)

    # История (минимальная форма)
    history: List[Dict[str, str]] = db.get_dialogue_history(user_id, limit=20)

    # Формируем сообщения для LLM (без доп. промптов и контекста)
    messages: List[Dict[str, str]] = []
    messages.extend(history)  # ожидается формат [{"role": "...","content": "..."}]
    messages.append({"role": "user", "content": user_message})

    # Генерация ответа (сигнатура с llm_context оставлена совместимой)
    try:
        response = await llm.generate_response(messages, llm_context=None)
    except TypeError:
        # На случай, если ваша реализация принимает только один аргумент
        response = await llm.generate_response(messages)

    response = (response or "").strip() or "Хм, не уверена, что поняла. Сформулируешь иначе?"

    # Отправка и сохранение исходящего
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
