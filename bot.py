# bot.py - Главный файл телеграм бота Алины
"""
Минималистичный, но мощный бот с продуманной личностью.
Фокус на качестве диалога, а не на функциях.
"""

import asyncio
import logging
import random
from datetime import datetime
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from telegram.constants import ChatAction

from config import Config
from database import DialogueDB
from llm import AlinaLLM
from personality import ALINA_PERSONALITY, enrich_prompt

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация компонентов
config = Config()
db = DialogueDB()
llm = AlinaLLM(
    api_key=config.openai_api_key,
    model=config.openai_model,
    use_proxy=config.use_proxy,
    proxy_url=config.proxy_url
)

# Простой rate limiter
last_message_time = {}


def get_time_of_day() -> str:
    """Определяет время суток для контекста."""
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 18:
        return "afternoon"
    elif 18 <= hour < 23:
        return "evening"
    else:
        return "night"


def get_random_mood() -> Optional[str]:
    """Иногда возвращает случайное настроение."""
    if random.random() < 0.3:  # 30% шанс на особое настроение
        moods = ["tired", "happy", "melancholic", "playful", "focused", "distracted"]
        return random.choice(moods)
    return None


async def simulate_typing(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str):
    """Имитация набора текста для естественности."""
    # Рассчитываем время "набора" на основе длины текста
    char_count = len(text)
    
    if char_count < 30:
        typing_time = random.uniform(0.5, 1.5)
    elif char_count < 100:
        typing_time = random.uniform(1.5, 3.0)
    else:
        typing_time = random.uniform(2.5, 4.0)
    
    # Отправляем "печатает..."
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    await asyncio.sleep(typing_time)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start."""
    user = update.effective_user
    user_id = user.id
    
    # Создаём/получаем пользователя в БД
    db.get_or_create_user(
        user_id=user_id,
        username=user.username,
        first_name=user.first_name
    )
    
    # Приветственные сообщения (рандомные для разнообразия)
    greetings = [
        "привет! я алина) рада познакомиться 😊\n\nможешь писать мне о чём угодно - поболтаем, посмеёмся, или просто послушаю, если нужно",
        "оо привет! я алина 👋\n\nтут можно просто поболтать обо всём - как день прошёл, что волнует, или просто так)",
        "хей! алина тут)\n\nпиши что хочешь - поговорим о жизни, сериалах, или о чём душа пожелает 🌿",
    ]
    
    greeting = random.choice(greetings)
    await simulate_typing(context, update.effective_chat.id, greeting)
    await update.message.reply_text(greeting)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help."""
    help_text = (
        "просто пиши мне как подруге 💛\n\n"
        "я не бот-помощник, я просто алина. можем поболтать о чём угодно - "
        "о твоём дне, о сериалах, о жизни... или просто подурачиться)\n\n"
        "а команды тут и не нужны, честно говоря"
    )
    
    await simulate_typing(context, update.effective_chat.id, help_text)
    await update.message.reply_text(help_text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Основной обработчик текстовых сообщений."""
    user = update.effective_user
    user_id = user.id
    user_message = update.message.text
    
    # Rate limiting
    current_time = asyncio.get_event_loop().time()
    if user_id in last_message_time:
        if current_time - last_message_time[user_id] < 1.0:  # Минимум 1 секунда между сообщениями
            return
    last_message_time[user_id] = current_time
    
    # Логируем входящее сообщение
    logger.info(f"User {user_id} ({user.first_name}): {user_message[:50]}...")
    
    # Сохраняем сообщение пользователя
    db.add_message(user_id, "user", user_message)
    
    # Получаем историю диалога
    history = db.get_dialogue_history(user_id, limit=20)
    
    # Анализируем контекст
    stats = db.get_conversation_stats(user_id)
    context_info = llm.analyze_context(user_message, stats["conversation_length"])
    
    # Формируем промпт с учётом времени и настроения
    time_of_day = get_time_of_day()
    mood = get_random_mood()
    
    enriched_prompt = enrich_prompt(
        ALINA_PERSONALITY,
        time_of_day=time_of_day,
        mood=mood
    )
    
    # Формируем сообщения для API
    messages = [
        {"role": "system", "content": enriched_prompt}
    ]
    
    # Добавляем историю
    for msg in history:
        messages.append(msg)
    
    # Добавляем текущее сообщение
    messages.append({"role": "user", "content": user_message})
    
    try:
        # Имитируем набор текста
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, 
            action=ChatAction.TYPING
        )
        
        # Генерируем ответ
        response = await llm.generate_response(messages, context_info)
        
        # Дополнительная имитация набора на основе длины ответа
        await simulate_typing(context, update.effective_chat.id, response)
        
        # Отправляем ответ
        await update.message.reply_text(response)
        
        # Сохраняем ответ в БД
        db.add_message(user_id, "assistant", response)
        
        logger.info(f"Alina to {user_id}: {response[:50]}...")
        
    except Exception as e:
        logger.error(f"Error handling message: {e}")
        
        # Человечные сообщения об ошибке
        error_messages = [
            "ой, что-то я запуталась... можешь ещё раз?",
            "блин, не поняла( давай попробуем ещё раз",
            "секунду, кот на клавиатуру прыгнул... что ты написал?",
            "сорри, отвлеклась... можешь повторить?"
        ]
        
        error_response = random.choice(error_messages)
        await update.message.reply_text(error_response)


async def handle_non_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик не-текстовых сообщений (фото, стикеры и т.д.)."""
    responses = {
        "photo": [
            "оо классное фото!",
            "ничего себе! круто выглядит",
            "вау, красиво 😍",
            "хорошее фото)"
        ],
        "sticker": [
            "ахаха классный стикер",
            "😄",
            "хех, забавно)",
            "люблю этот стикер!"
        ],
        "voice": [
            "сорри, сейчас не могу послушать голосовые( давай текстом?",
            "ой, я на работе, не могу включить звук... можешь написать?",
            "голосовые не могу сейчас.. напиши лучше)"
        ],
        "default": [
            "эмм, не поняла что это)",
            "что-то не могу открыть(",
            "хм, у меня не показывает.. что там?"
        ]
    }
    
    # Определяем тип сообщения
    if update.message.photo:
        response_list = responses["photo"]
    elif update.message.sticker:
        response_list = responses["sticker"]
    elif update.message.voice or update.message.audio:
        response_list = responses["voice"]
    else:
        response_list = responses["default"]
    
    response = random.choice(response_list)
    await simulate_typing(context, update.effective_chat.id, response)
    await update.message.reply_text(response)


def main():
    """Точка входа в приложение."""
    # Проверяем конфигурацию
    if not config.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN не установлен!")
        return
    
    if not config.openai_api_key:
        logger.error("OPENAI_API_KEY не установлен!")
        return
    
    # Создаём приложение
    application = Application.builder().token(config.telegram_bot_token).build()
    
    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    
    # Обработчик текстовых сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Обработчик не-текстовых сообщений
    application.add_handler(MessageHandler(~filters.TEXT & ~filters.COMMAND, handle_non_text))
    
    # Запускаем бота
    logger.info("Алина запущена и готова к общению! 💛")
    application.run_polling()


if __name__ == "__main__":
    main()