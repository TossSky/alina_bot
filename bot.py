# bot.py - Главный файл бота Алины
"""
Оптимизированный бот с фокусом на человечности.
Простота + качество = естественность.
"""

import asyncio
import logging
import random
from datetime import datetime
from typing import Optional, Dict
from collections import defaultdict

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
from personality import (
    ALINA_PERSONALITY,
    enrich_prompt,
    get_spam_response,
    analyze_negativity,
    NEGATIVE_RESPONSES
)

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация
config = Config()
db = DialogueDB()
llm = AlinaLLM(
    api_key=config.openai_api_key,
    model=config.openai_model,
    use_proxy=config.use_proxy,
    proxy_url=config.proxy_url
)

# Трекеры для пользователей
user_spam_tracker = defaultdict(list)  # История сообщений для спам-детекции
user_negative_counter = defaultdict(int)  # Счетчик негатива
user_last_message_time = {}  # Антифлуд


def get_context_info(user_id: int) -> Dict:
    """Собирает контекст для генерации."""
    hour = datetime.now().hour
    
    # Определяем настроение по времени и рандому
    mood = None
    if random.random() < 0.2:  # 20% шанс на особое настроение
        moods = ["tired", "happy", "annoyed", "sad"]
        mood = random.choice(moods)
    
    # Негатив от пользователя
    negative_count = user_negative_counter.get(user_id, 0)
    
    return {
        "hour": hour,
        "mood": mood,
        "negative_count": negative_count
    }


def check_spam(user_id: int, message: str) -> int:
    """Проверяет спам от пользователя."""
    history = user_spam_tracker[user_id]
    
    # Нормализуем сообщение
    normalized = message.lower().strip()
    
    # Считаем повторы
    spam_count = history.count(normalized)
    
    # Обновляем историю (храним последние 5)
    history.append(normalized)
    if len(history) > 5:
        history.pop(0)
    
    return spam_count


async def simulate_typing(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str):
    """Имитация набора текста."""
    # Время набора зависит от длины
    char_count = len(text)
    
    if char_count < 30:
        typing_time = random.uniform(0.5, 1.2)
    elif char_count < 100:
        typing_time = random.uniform(1.0, 2.5)
    else:
        typing_time = random.uniform(2.0, 3.5)
    
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    await asyncio.sleep(typing_time)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start."""
    user = update.effective_user
    user_id = user.id
    
    # Создаем/получаем пользователя
    user_data = db.get_or_create_user(
        user_id=user_id,
        username=user.username,
        first_name=user.first_name
    )
    
    # Проверяем, новый ли пользователь
    stats = db.get_conversation_stats(user_id)
    is_returning = stats["total_messages"] > 0
    
    if is_returning:
        # Возвращающийся
        greetings = [
            "о, привет! давно не виделись)",
            "ты вернулся! как дела?",
            "привет-привет, соскучилась честно говоря"
        ]
    else:
        # Новый
        greetings = [
            "привет! я алина) рада познакомиться",
            "оо новенький! я алина, а ты?",
            "хей, алина тут. давай знакомиться?"
        ]
    
    greeting = random.choice(greetings)
    
    # Добавляем контекст времени
    hour = datetime.now().hour
    if hour >= 23 or hour < 5:
        greeting += "\n\nкстати, чего не спишь?"
    
    await simulate_typing(context, update.effective_chat.id, greeting)
    await update.message.reply_text(greeting)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help."""
    help_text = (
        "да просто пиши что хочешь\n\n"
        "я не бот-помощник, я алина. "
        "можем поболтать, посмеяться, или просто помолчать вместе)"
    )
    
    await simulate_typing(context, update.effective_chat.id, help_text)
    await update.message.reply_text(help_text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Основной обработчик сообщений."""
    user = update.effective_user
    user_id = user.id
    user_message = update.message.text
    
    # Антифлуд
    current_time = asyncio.get_event_loop().time()
    if user_id in user_last_message_time:
        if current_time - user_last_message_time[user_id] < 0.5:
            return  # Игнорируем слишком частые сообщения
    user_last_message_time[user_id] = current_time
    
    logger.info(f"User {user_id}: {user_message[:50]}...")
    
    # Проверяем на негатив
    negativity = analyze_negativity(user_message)
    if negativity:
        user_negative_counter[user_id] += 1
        
        # Если слишком много негатива - резкий ответ
        if user_negative_counter[user_id] > 3:
            responses = ["все, достал. пока", "блокирую", "иди в баню"]
            response = random.choice(responses)
            await update.message.reply_text(response)
            return
        
        # Обычная реакция на негатив
        response = random.choice(NEGATIVE_RESPONSES.get(negativity, ["..."])) 
        await update.message.reply_text(response)
        return
    
    # Проверяем спам
    spam_count = check_spam(user_id, user_message)
    if spam_count > 0:
        response = get_spam_response(spam_count)
        await update.message.reply_text(response)
        
        # Если слишком много спама - прекращаем
        if spam_count > 3:
            return
    
    # Сохраняем сообщение
    db.add_message(user_id, "user", user_message)
    
    # Получаем историю
    history = db.get_dialogue_history(user_id, limit=20)
    
    # Анализируем контекст
    stats = db.get_conversation_stats(user_id)
    llm_context = llm.analyze_context(user_message, stats["conversation_length"])
    
    # Контекст для промпта
    prompt_context = get_context_info(user_id)
    
    # Обогащаем промпт
    enriched_prompt = enrich_prompt(ALINA_PERSONALITY, prompt_context)
    
    # Формируем сообщения
    messages = [
        {"role": "system", "content": enriched_prompt}
    ]
    
    # Добавляем историю
    for msg in history:
        messages.append(msg)
    
    # Текущее сообщение
    messages.append({"role": "user", "content": user_message})
    
    try:
        # Начинаем печатать
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=ChatAction.TYPING
        )
        
        # Генерируем ответ
        response = await llm.generate_response(messages, llm_context)
        
        # Добавляем спонтанные детали (редко)
        if random.random() < 0.1:  # 10% шанс
            details = [
                "\n\nой кот прыгнул на колени",
                "\n\nчайник вскипел, секунду",
                "\n\nбублик опять спит на клаве))",
                "\n\nдождь пошел кстати"
            ]
            response += random.choice(details)
        
        # Имитируем набор
        await simulate_typing(context, update.effective_chat.id, response)
        
        # Отправляем
        await update.message.reply_text(response)
        
        # Сохраняем ответ
        db.add_message(user_id, "assistant", response)
        
        logger.info(f"Alina: {response[:50]}...")
        
        # Сбрасываем счетчик негатива если общение нормальное
        if user_negative_counter[user_id] > 0:
            user_negative_counter[user_id] -= 1
        
    except Exception as e:
        logger.error(f"Error: {e}")
        
        # Фоллбеки
        fallbacks = [
            "что-то я запуталась... еще раз можно?",
            "блин, не поняла. давай по-другому",
            "ой, кот отвлек. что ты сказал?"
        ]
        
        await update.message.reply_text(random.choice(fallbacks))


async def handle_non_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик медиа."""
    responses = {
        "photo": [
            "о, классное фото",
            "ничего себе!",
            "круто выглядит)",
            "вау"
        ],
        "sticker": [
            "ахах хороший стикер",
            "😄",
            "забавно)",
            "люблю этот"
        ],
        "voice": [
            "сорри, не могу послушать голосовые сейчас",
            "напиши текстом плиз",
            "голосовые не люблю если честно"
        ],
        "default": [
            "что это?",
            "не открывается у меня(",
            "хм, что там?"
        ]
    }
    
    # Определяем тип
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
    """Запуск бота."""
    # Проверяем конфиг
    if not config.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN не установлен!")
        return
    
    if not config.openai_api_key:
        logger.error("OPENAI_API_KEY не установлен!")
        return
    
    # Создаем приложение
    application = Application.builder().token(config.telegram_bot_token).build()
    
    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    
    # Текстовые сообщения
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Медиа
    application.add_handler(MessageHandler(~filters.TEXT & ~filters.COMMAND, handle_non_text))
    
    # Запуск
    logger.info("Алина запущена! 🚀")
    application.run_polling()


if __name__ == "__main__":
    main()
