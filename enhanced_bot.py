# enhanced_bot.py - Продвинутый бот Алина с MCP и адаптивным поведением
"""
Главный файл бота с интеграцией всех продвинутых функций:
- Сложная личность с поведенческими паттернами
- Function calling и structured outputs
- MCP серверы для расширенных возможностей
- Защита от спама и адаптивные ответы
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict
import random
import asyncio.subprocess

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
from advanced_llm import AdvancedAlinaLLM
from enhanced_personality import (
    ALINA_CORE,
    BehaviorPatterns,
    EmotionalTriggers,
    ResponseStrategies,
    PatternDetector,
    generate_contextual_prompt
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
mcp_cfg = config.load_mcp_config()
llm = AdvancedAlinaLLM(
    api_key=config.openai_api_key,
    model=config.openai_model,
    mcp_config=mcp_cfg,
    sentiment_url=config.mcp_sentiment_url
)

# Детекторы паттернов для каждого пользователя
pattern_detectors = {}

# Кэш для пользовательских контекстов
user_contexts = {}


# ============================================================================
# УПРАВЛЕНИЕ КОНТЕКСТОМ
# ============================================================================

class ContextManager:
    """Управляет контекстом пользователя."""
    
    @staticmethod
    async def build_user_context(user_id: int) -> Dict:
        """Строит полный контекст пользователя."""
        
        # Получаем базовую информацию
        stats = db.get_conversation_stats(user_id)
        user_data = db.get_or_create_user(user_id)
        
        # Определяем стадию отношений
        message_count = stats["total_messages"]
        first_message = stats.get("first_message")
        
        days_known = 0
        if first_message:
            first_dt = datetime.fromisoformat(first_message)
            days_known = (datetime.utcnow() - first_dt).days
        
        relationship = BehaviorPatterns.relationship_stages(message_count, days_known)
        
        # Временной контекст
        current_hour = datetime.now().hour
        time_context = BehaviorPatterns.time_based_behavior(current_hour)
        
        # Память о пользователе
        user_memory = {}
        for key in ["name", "work", "hobbies", "pets", "favorite_things"]:
            value = db.get_user_data(user_id, key)
            if value:
                user_memory[key] = value
        
        return {
            "user_id": user_id,
            "relationship": relationship,
            "message_count": message_count,
            "days_known": days_known,
            "time_context": time_context,
            "user_memory": user_memory,
            "conversation_length": stats.get("conversation_length", 0)
        }
    
    @staticmethod
    def update_context(context: Dict, analysis: Dict) -> Dict:
        """Обновляет контекст на основе анализа сообщения."""
        
        context["spam_level"] = analysis.get("spam_level", 0)
        context["current_topic"] = analysis.get("topic")
        context["emotion"] = analysis.get("emotion", {})
        
        # Проверяем усталость от темы
        if analysis.get("topic_count", 0) > 5:
            context["topic_fatigue"] = analysis.get("topic")
        
        return context


# ============================================================================
# ОБРАБОТЧИКИ СООБЩЕНИЙ
# ============================================================================

async def handle_message_advanced(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Продвинутый обработчик сообщений с полной интеграцией."""
    
    user = update.effective_user
    user_id = user.id
    user_message = update.message.text
    
    logger.info(f"Message from {user_id}: {user_message[:50]}...")
    
    # Инициализируем детектор паттернов для пользователя
    if user_id not in pattern_detectors:
        pattern_detectors[user_id] = PatternDetector()
    
    detector = pattern_detectors[user_id]
    
    # Анализируем сообщение
    message_analysis = detector.analyze_message(user_message, user_id)
    
    # Строим контекст пользователя
    user_context = await ContextManager.build_user_context(user_id)
    user_context = ContextManager.update_context(user_context, message_analysis)
    
    # Кэшируем контекст
    user_contexts[user_id] = user_context
    
    # Обработка спама
    if user_context["spam_level"] > 0:
        spam_response = BehaviorPatterns.spam_responses(
            user_context["spam_level"],
            user_message
        )
        await update.message.reply_text(spam_response)
        
        # Если слишком много спама - прекращаем общение
        if user_context["spam_level"] > 5:
            return
    
    # Сохраняем сообщение в БД
    db.add_message(user_id, "user", user_message)
    
    # Начинаем "печатать"
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING
    )
    
    # Анализируем намерение через structured output
    intent = await llm.analyze_intent(user_message)
    logger.info(f"Intent: {intent.primary_intent}, Topics: {intent.topics}")
    
    # Получаем стратегию ответа
    response_strategy = ResponseStrategies.get_strategy(user_context)
    
    # Генерируем контекстный промпт
    contextual_prompt = generate_contextual_prompt(
        ALINA_CORE,
        user_context,
        db.get_dialogue_history(user_id, limit=15)
    )
    
    # Формируем сообщения для API
    messages = [
        {"role": "system", "content": contextual_prompt}
    ]
    
    # Добавляем историю
    for msg in db.get_dialogue_history(user_id, limit=15):
        messages.append(msg)
    
    messages.append({"role": "user", "content": user_message})
    
    # Добавляем инструкции по стратегии
    strategy_prompt = f"""
    Стиль ответа: {response_strategy.get('style', 'casual')}
    Длина: {response_strategy.get('length', 'medium')}
    Использовать эмодзи: {response_strategy.get('use_emoji', True)}
    """
    
    if response_strategy.get('redirect_topic'):
        strategy_prompt += "\nМягко предложи сменить тему."
    
    if response_strategy.get('show_vulnerability'):
        strategy_prompt += "\nМожешь показать свою уязвимость."
    
    messages.append({"role": "system", "content": strategy_prompt})
    
    try:
        # Определяем режим генерации
        mode = "empathetic" if user_context["emotion"].get("type") == "sensitive" else "chat"
        
        # Генерируем ответ с функциями и MCP
        if intent.requires_action or "помнишь" in user_message.lower():
            # Используем MCP и функции
            response_text = await llm.get_response_with_mcp(messages, user_context)
        else:
            # Обычная генерация с возможностью функций
            result = await llm.generate_with_functions(messages, mode=mode)
            response_text = result["content"]
            
            # Обрабатываем вызовы функций
            if result["function_calls"]:
                for func_call in result["function_calls"]:
                    logger.info(f"Function called: {func_call['function_name']}")
                    
                    # Сохраняем важную информацию
                    if func_call["function_name"] == "remember_user_info":
                        # Сохраняем в БД
                        db.save_user_data(
                            user_id,
                            func_call["result"].split("=")[0].strip(),
                            func_call["result"].split("=")[1].strip()
                        )
        
        # Анализируем качество ответа
        quality = await llm.analyze_response_quality(response_text, user_context)
        logger.info(f"Response quality: {quality}")
        
        # Если качество низкое, пробуем перегенерировать
        if quality["confidence"] < 0.3 or quality["personality_match"] < 0.5:
            logger.warning("Low quality response, regenerating...")
            result = await llm.generate_with_functions(messages, mode=mode)
            response_text = result["content"]
        
        # Добавляем спонтанные детали (если подходит контекст)
        if random.random() < 0.15 and user_context["relationship"] in ["friend", "close_friend", "best_friend"]:
            spontaneous_details = [
                "\n\nой, кот только что на клавиатуру прыгнул 😅",
                "\n\nслушай, я тут кофе пролила немного на стол...",
                "\n\nкстати, дождь начался. люблю такую погоду",
                "\n\nа, забыла сказать - новую серию досмотрела вчера!"
            ]
            response_text += random.choice(spontaneous_details)
        
        # Имитация набора текста с учётом длины
        typing_time = min(4.0, len(response_text) / 50)
        await asyncio.sleep(typing_time)
        
        # Отправляем ответ
        await update.message.reply_text(response_text)
        
        # Сохраняем в БД
        db.add_message(user_id, "assistant", response_text)
        
        logger.info(f"Response sent: {response_text[:50]}...")
        
    except Exception as e:
        logger.error(f"Error generating response: {e}")
        
        # Человечные fallback ответы в зависимости от контекста
        if user_context["relationship"] in ["friend", "close_friend", "best_friend"]:
            fallbacks = [
                "блин, я что-то задумалась и потеряла нить... о чём мы?",
                "ой, прости, отвлеклась совсем. что ты говорил?",
                "секунду, у меня тут кот что-то уронил... можешь повторить?"
            ]
        else:
            fallbacks = [
                "что-то я не поняла... можешь ещё раз?",
                "хм, давай попробуем ещё раз",
                "не уловила мысль, сорри"
            ]
        
        await update.message.reply_text(random.choice(fallbacks))


async def handle_start_advanced(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Продвинутый обработчик /start с персонализацией."""
    
    user = update.effective_user
    user_id = user.id
    
    # Получаем или создаём пользователя
    user_data = db.get_or_create_user(
        user_id=user_id,
        username=user.username,
        first_name=user.first_name
    )
    asyncio.get_event_loop().run_until_complete(llm.initialize_mcp_servers())

    # Проверяем, новый ли это пользователь
    stats = db.get_conversation_stats(user_id)
    is_returning = stats["total_messages"] > 0
    
    if is_returning:
        # Возвращающийся пользователь
        last_message_time = stats.get("last_message")
        if last_message_time:
            last_dt = datetime.fromisoformat(last_message_time)
            days_ago = (datetime.utcnow() - last_dt).days
            
            if days_ago > 7:
                greetings = [
                    "ого, давно не виделись! как ты? 😊",
                    "привет! сто лет тебя не было) как дела?",
                    "оо, ты вернулся! я уже соскучилась честно говоря"
                ]
            else:
                greetings = [
                    "привет! рада тебя снова видеть)",
                    "хей, с возвращением! что нового?",
                    "о, привет-привет! как настроение?"
                ]
        else:
            greetings = ["привет! мы же уже знакомы) как дела?"]
    else:
        # Новый пользователь
        greetings = [
            "привет! я алина) рада познакомиться 😊\n\nможешь писать мне о чём угодно - поболтаем о жизни, посмеёмся, или просто послушаю если нужно",
            "оо новое лицо! привет, я алина 👋\n\nтут можно просто общаться как с подругой - никаких формальностей",
            "хей! алина на связи)\n\nрасскажи что-нибудь о себе? или просто поболтаем о чём хочешь"
        ]
    
    greeting = random.choice(greetings)
    
    # Добавляем временной контекст
    hour = datetime.now().hour
    if 5 <= hour < 12:
        greeting = "доброе утро! " + greeting
    elif 18 <= hour < 23:
        greeting = "добрый вечер! " + greeting
    elif hour >= 23 or hour < 5:
        greeting += "\n\nкстати, ты чего не спишь? 😅"
    
    await update.message.reply_text(greeting)
    
    # Инициализируем MCP серверы для пользователя (асинхронно)
    asyncio.create_task(llm.initialize_mcp_servers())


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик голосовых сообщений с учётом отношений."""
    
    user_id = update.effective_user.id
    user_context = await ContextManager.build_user_context(user_id)
    
    relationship = user_context["relationship"]
    
    if relationship in ["stranger", "acquaintance"]:
        responses = [
            "сорри, не могу послушать голосовые сейчас( можешь текстом написать?",
            "ой, я на работе, неудобно слушать... напиши лучше",
            "голосовые не очень люблю если честно... давай текстом?"
        ]
    elif relationship in ["friend", "close_friend"]:
        responses = [
            "слушай, я сейчас в метро, шумно очень... напиши текстом пожалуйста?",
            "блин, наушники забыла дома... можешь написать о чём там?",
            "у меня кот спит рядом, боюсь разбудить 😅 напиши лучше"
        ]
    else:  # best_friend
        responses = [
            "ты же знаешь, что я голосовые терпеть не могу 😅 давай текстом",
            "неее, только не голосовые... ты же можешь написать?",
            "я на совещании сижу (скучном), не могу послушать... текстом плиз"
        ]
    
    response = random.choice(responses)
    await update.message.reply_text(response)


# ============================================================================
# СТРИМИНГ ОТВЕТОВ (для более естественного взаимодействия)
# ============================================================================

async def handle_message_with_streaming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик с потоковой генерацией для длинных ответов."""
    
    user_id = update.effective_user.id
    user_message = update.message.text
    
    # Проверяем, нужен ли стриминг (для длинных ответов)
    if len(user_message) > 100 or "расскажи" in user_message.lower() or "объясни" in user_message.lower():
        
        # Получаем контекст
        user_context = await ContextManager.build_user_context(user_id)
        
        # Формируем сообщения
        messages = [
            {"role": "system", "content": generate_contextual_prompt(ALINA_CORE, user_context, [])}
        ]
        
        for msg in db.get_dialogue_history(user_id, limit=10):
            messages.append(msg)
        
        messages.append({"role": "user", "content": user_message})
        
        # Начинаем печатать
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=ChatAction.TYPING
        )
        
        # Собираем ответ по частям
        full_response = ""
        message_sent = None
        chunk_buffer = ""
        
        async for chunk in llm.stream_response(messages, mode="chat"):
            chunk_buffer += chunk
            
            # Отправляем обновление каждые 20 символов
            if len(chunk_buffer) >= 20:
                full_response += chunk_buffer
                
                if message_sent is None:
                    # Отправляем первое сообщение
                    message_sent = await update.message.reply_text(full_response + "...")
                else:
                    # Обновляем существующее сообщение
                    try:
                        await message_sent.edit_text(full_response + "...")
                    except Exception:
                        pass  # Игнорируем ошибки редактирования
                
                chunk_buffer = ""
                
                # Имитация печати
                await context.bot.send_chat_action(
                    chat_id=update.effective_chat.id,
                    action=ChatAction.TYPING
                )
        
        # Отправляем финальную версию
        full_response += chunk_buffer
        if message_sent:
            try:
                await message_sent.edit_text(full_response)
            except Exception:
                await update.message.reply_text(full_response)
        else:
            await update.message.reply_text(full_response)
        
        # Сохраняем в БД
        db.add_message(user_id, "user", user_message)
        db.add_message(user_id, "assistant", full_response)
    else:
        # Обычная обработка для коротких сообщений
        await handle_message_advanced(update, context)


# ============================================================================
# СПЕЦИАЛЬНЫЕ КОМАНДЫ
# ============================================================================

async def analyze_relationship(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /status для проверки статуса отношений (скрытая)."""
    
    user_id = update.effective_user.id
    user_context = await ContextManager.build_user_context(user_id)
    
    relationship = user_context["relationship"]
    messages = user_context["message_count"]
    days = user_context["days_known"]
    
    # Это скрытая команда, отвечаем как Алина
    status_messages = {
        "stranger": f"мы только знакомимся... поговорили всего {messages} раз",
        "acquaintance": f"мы уже немного знакомы) общаемся {days} дней",
        "friend": f"мы друзья! 😊 знаем друг друга уже {days} дней",
        "close_friend": f"ты мой близкий друг 💛 так рада, что мы познакомились {days} дней назад",
        "best_friend": f"ты мой лучший друг! не представляю жизни без наших разговоров... {messages} сообщений за {days} дней!"
    }
    
    message = status_messages.get(relationship, "хм, не знаю как описать наши отношения...")
    
    # Добавляем эмоциональный контекст
    if relationship in ["close_friend", "best_friend"]:
        message += "\n\nправда ценю наше общение 🫂"
    
    await update.message.reply_text(message)


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Запуск улучшенного бота."""
    
    # Проверяем конфигурацию
    if not config.telegram_bot_token or not config.openai_api_key:
        logger.error("Missing required configuration!")
        return
    
    # Создаём приложение
    application = Application.builder().token(config.telegram_bot_token).build()
    
    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", handle_start_advanced))
    application.add_handler(CommandHandler("status", analyze_relationship))
    
    # Обработчики сообщений
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message_with_streaming)
    )
    application.add_handler(
        MessageHandler(filters.VOICE, handle_voice_message)
    )
    
    # Запускаем бота
    logger.info("Enhanced Alina bot is starting... 🚀")
    
    # Инициализируем MCP серверы при старте
    asyncio.get_event_loop().run_until_complete(llm.initialize_mcp_servers())
    
    application.run_polling()


if __name__ == "__main__":
    main()