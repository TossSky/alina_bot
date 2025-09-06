# fixed_enhanced_bot.py - Человечный бот Алина
"""
Упрощенная версия с фокусом на естественность общения.
Меньше анализа, больше человечности.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict
import random

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

from config import Config
from database import DialogueDB
from enhanced_personality import (
    ALINA_CORE,
    generate_contextual_prompt,
    get_generation_params,
    SimplePatternDetector,
    get_spam_response,
    get_emotional_context,
    get_spontaneous_detail
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================================================

config = Config()
db = DialogueDB()

# Импортируем нужный LLM клиент
# Используем упрощенную версию или базовую
try:
    from llm import AlinaLLM  # Базовая версия
    llm = AlinaLLM(
        api_key=config.openai_api_key,
        model=config.openai_model,
        use_proxy=config.use_proxy,
        proxy_url=config.proxy_url
    )
except ImportError:
    from advanced_llm import AdvancedAlinaLLM
    llm = AdvancedAlinaLLM(
        api_key=config.openai_api_key,
        model=config.openai_model
    )

# Детекторы спама для каждого пользователя
spam_detectors = {}

# ============================================================================
# УТИЛИТЫ
# ============================================================================

async def simulate_typing(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Имитация набора текста для естественности."""
    char_count = len(text)
    
    # Рассчитываем время набора
    if char_count < 30:
        typing_time = random.uniform(1.0, 2.0)
    elif char_count < 100:
        typing_time = random.uniform(2.0, 3.5)
    else:
        typing_time = random.uniform(3.0, 4.5)
    
    # Отправляем "печатает..."
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING
    )
    await asyncio.sleep(typing_time)

def build_user_context(user_id: int) -> Dict:
    """Строит упрощенный контекст пользователя."""
    stats = db.get_conversation_stats(user_id)
    message_count = stats["total_messages"]
    
    # Определяем стадию отношений просто
    if message_count < 10:
        relationship = "stranger"
    elif message_count < 50:
        relationship = "acquaintance"
    elif message_count < 200:
        relationship = "friend"
    else:
        relationship = "close_friend"
    
    # Получаем память о пользователе
    user_memory = {}
    for key in ["name", "work", "pet"]:
        value = db.get_user_data(user_id, key)
        if value:
            user_memory[key] = value
    
    return {
        "relationship": relationship,
        "message_count": message_count,
        "user_memory": user_memory
    }

# ============================================================================
# ОБРАБОТЧИКИ СООБЩЕНИЙ
# ============================================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Основной обработчик сообщений с упрощенной логикой."""
    
    user = update.effective_user
    user_id = user.id
    user_message = update.message.text
    
    logger.info(f"Message from {user_id}: {user_message[:50]}...")
    
    # Инициализируем детектор спама
    if user_id not in spam_detectors:
        spam_detectors[user_id] = SimplePatternDetector()
    
    detector = spam_detectors[user_id]
    
    # Проверяем только критические случаи
    spam_level = detector.check_spam(user_message, user_id)
    is_sensitive = detector.is_sensitive_topic(user_message)
    
    # Обработка спама (человечно)
    if spam_level >= 3:
        response = get_spam_response(spam_level)
        await simulate_typing(update, context, response)
        await update.message.reply_text(response)
        
        if spam_level >= 5:
            return  # Прекращаем общение
    
    # Сохраняем сообщение
    db.add_message(user_id, "user", user_message)
    
    # Получаем историю
    history = db.get_dialogue_history(user_id, limit=15)
    
    # Строим контекст пользователя
    user_context = build_user_context(user_id)
    
    # Генерируем промпт БЕЗ излишних правил
    system_prompt = generate_contextual_prompt(
        ALINA_CORE,
        user_context,
        history
    )
    
    # Добавляем эмоциональный контекст если нужно
    emotional_context = get_emotional_context(user_message)
    if emotional_context:
        system_prompt += f"\n{emotional_context}"
    
    # Формируем сообщения для API
    messages = [
        {"role": "system", "content": system_prompt}
    ]
    
    # Добавляем историю
    for msg in history:
        messages.append(msg)
    
    # Добавляем текущее сообщение
    messages.append({"role": "user", "content": user_message})
    
    try:
        # Получаем параметры для генерации
        params = get_generation_params(user_context)
        
        # Генерируем ответ
        if hasattr(llm, 'generate_response'):
            # Используем базовый метод
            response = await llm.generate_response(messages, user_context)
        else:
            # Для advanced_llm
            result = await llm.generate_with_functions(
                messages, 
                mode="chat",
                use_functions=False  # Отключаем функции для простоты
            )
            response = result["content"]
        
        # Добавляем спонтанную деталь (иногда)
        spontaneous = get_spontaneous_detail()
        if spontaneous and user_context["relationship"] in ["friend", "close_friend"]:
            # Решаем, добавить в начало или конец
            if random.random() < 0.5:
                response = f"{spontaneous}\n\n{response}"
            else:
                response = f"{response}\n\nой, {spontaneous}"
        
        # Иногда разбиваем на несколько сообщений (для естественности)
        if len(response) > 100 and random.random() < 0.3:
            # Находим место для разделения
            split_point = response.find(". ", 50)
            if split_point > 0 and split_point < len(response) - 20:
                first_part = response[:split_point + 1]
                second_part = response[split_point + 2:]
                
                # Отправляем первую часть
                await simulate_typing(update, context, first_part)
                await update.message.reply_text(first_part)
                
                # Небольшая пауза
                await asyncio.sleep(random.uniform(1.0, 2.0))
                
                # Отправляем вторую часть
                await simulate_typing(update, context, second_part)
                await update.message.reply_text(second_part)
            else:
                # Отправляем целиком
                await simulate_typing(update, context, response)
                await update.message.reply_text(response)
        else:
            # Отправляем целиком
            await simulate_typing(update, context, response)
            await update.message.reply_text(response)
        
        # Сохраняем ответ
        db.add_message(user_id, "assistant", response)
        
        logger.info(f"Response sent: {response[:50]}...")
        
    except Exception as e:
        logger.error(f"Error generating response: {e}")
        
        # Человечные fallback ответы
        fallbacks = [
            "ой, что-то я запуталась... можешь ещё раз?",
            "блин, не поняла( давай попробуем ещё раз",
            "секунду, кот на клаву прыгнул... что ты написал?",
            "сорри, отвлеклась... можешь повторить?"
        ]
        
        await update.message.reply_text(random.choice(fallbacks))

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /start с человечным приветствием."""
    
    user = update.effective_user
    user_id = user.id
    
    # Получаем или создаём пользователя
    user_data = db.get_or_create_user(
        user_id=user_id,
        username=user.username,
        first_name=user.first_name
    )
    
    # Проверяем, новый ли пользователь
    stats = db.get_conversation_stats(user_id)
    is_returning = stats["total_messages"] > 0
    
    if is_returning:
        greetings = [
            "о, привет! давно не виделись) как дела?",
            "хей, с возвращением! что нового?",
            "привет-привет! рада тебя видеть снова 😊"
        ]
    else:
        greetings = [
            "привет! я алина) рада познакомиться 😊\n\nможешь писать мне о чём угодно - поболтаем, посмеёмся, или просто послушаю если нужно",
            "оо новое лицо! привет, я алина 👋\n\nтут можно просто общаться как с подругой - никаких формальностей",
            "хей! алина на связи)\n\nрасскажи что-нибудь о себе? или просто поболтаем о чём хочешь"
        ]
    
    greeting = random.choice(greetings)
    
    # Добавляем временной контекст
    hour = datetime.now().hour
    if hour >= 23 or hour < 5:
        greeting += "\n\nкстати, ты чего не спишь? 😅"
    
    await simulate_typing(update, context, greeting)
    await update.message.reply_text(greeting)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик голосовых сообщений."""
    
    user_id = update.effective_user.id
    user_context = build_user_context(user_id)
    
    responses = [
        "сорри, не могу послушать голосовые сейчас( можешь текстом написать?",
        "ой, я на работе, неудобно слушать... напиши лучше",
        "голосовые не очень люблю если честно... давай текстом?",
        "блин, наушники забыла... можешь написать о чём там?"
    ]
    
    response = random.choice(responses)
    await simulate_typing(update, context, response)
    await update.message.reply_text(response)

async def handle_non_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик медиа-сообщений."""
    
    if update.message.photo:
        responses = [
            "оо классное фото!",
            "ничего себе! круто выглядит",
            "вау, красиво 😍",
            "хорошее фото)"
        ]
    elif update.message.sticker:
        responses = [
            "ахаха классный стикер",
            "😄",
            "хех, забавно)",
            "люблю этот стикер!"
        ]
    else:
        responses = [
            "эмм, не поняла что это)",
            "что-то не могу открыть(",
            "хм, у меня не показывает.. что там?"
        ]
    
    response = random.choice(responses)
    await simulate_typing(update, context, response)
    await update.message.reply_text(response)

# ============================================================================
# MAIN
# ============================================================================

def main():
    """Запуск человечного бота."""
    
    # Проверяем конфигурацию
    if not config.telegram_bot_token or not config.openai_api_key:
        logger.error("Missing required configuration!")
        return
    
    # Создаём приложение
    application = Application.builder().token(config.telegram_bot_token).build()
    
    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", handle_start))
    
    # Обработчики сообщений
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    application.add_handler(
        MessageHandler(filters.VOICE, handle_voice)
    )
    application.add_handler(
        MessageHandler(filters.PHOTO | filters.STICKER, handle_non_text)
    )
    application.add_handler(
        MessageHandler(~filters.TEXT & ~filters.COMMAND, handle_non_text)
    )
    
    # Запускаем бота
    logger.info("Человечная Алина запущена! 💛")
    application.run_polling()

if __name__ == "__main__":
    main()