"""
Alina Bot - Main Application Module

This module contains the main bot application class that handles all user interactions,
message processing, subscriptions, and integrations with external services.
"""

import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

from config import Config
from database import DialogueDB
from google_docs_service import get_docs_service
from llm import AlinaLLM, create_image_message, get_image_hash
from payment_checker import PaymentStatusChecker
from time_mcp_server import get_enrichment_context, get_time_string
from payments import (
    SubscriptionManager,
    handle_stars_pre_checkout,
    handle_stars_successful_payment,
    handle_subscribe_callback,
    handle_start_payment,
)
from personality import ALINA_PERSONALITY, enrich_prompt
from yookassa_integration import YooKassaClient

# Configure logging with appropriate format and level
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

logger = logging.getLogger("alina-bot")


class AlinaBot:
    """
    Main bot application class that handles:
    - User commands and message processing
    - Subscription management
    - Image processing with vision capabilities
    - Payment integration with YooKassa and Telegram Stars
    - Background tasks and periodic updates
    """
    
    def __init__(self):
        """Initialize bot with all necessary components and services"""
        self.config = Config()
        self.db = DialogueDB()
        self.llm = AlinaLLM(
            api_key=self.config.openai_api_key,
            model=self.config.openai_model,
            use_proxy=self.config.use_proxy,
            proxy_url=self.config.proxy_url,
        )
        self.yookassa_client = YooKassaClient(
            shop_id=self.config.yookassa_shop_id,
            secret_key=self.config.yookassa_secret_key
        )
        self.subscription_manager = SubscriptionManager(self.db, self.yookassa_client)
        self.payment_checker = PaymentStatusChecker(
            self.config.db_path,
            self.yookassa_client,
            self.subscription_manager
        )
        self.docs_service = get_docs_service()
        # Initial system prompt without time context (will be enriched per message)
        self.base_personality = ALINA_PERSONALITY
    
    # ==================== COMMAND HANDLERS ====================
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle /start command with deep link support
        Creates new user in database and handles payment deep links
        """
        user_id = update.effective_user.id
        self.db.get_or_create_user(user_id=user_id)
        
        # Handle deep link for payments (e.g., /start pay_month)
        if context.args:
            arg = context.args[0]
            if arg.startswith('pay_'):
                plan_type = arg.replace('pay_', '')
                await handle_start_payment(update, context, plan_type)
                return
        
        # Send welcome message
        text = "Меня зовут Алина) рада буду пообщаться с тобой!\n\n📸 Теперь ты можешь отправлять мне картинки, и я их пойму!"
        await update.message.reply_text(text)
        logger.info(f"New user started: {user_id}")
    
    async def restart(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle /restart command - restarts bot process (admin only)
        """
        user_id = update.effective_user.id
        
        # Check admin permissions
        if self.config.admin_ids and user_id not in self.config.admin_ids:
            logger.warning(f"Non-admin {user_id} tried to restart bot")
            return
        
        logger.info(f"Admin {user_id} initiated bot restart")
        await update.message.reply_text("Перезапускаюсь... Подождите несколько секунд.")
        
        # Execute restart
        os.execv(sys.executable, [sys.executable] + sys.argv)
    
    async def reset_limits(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle /reset_limits command - resets user limits (admin only)
        """
        user_id = update.effective_user.id
        
        # Check admin permissions
        if self.config.admin_ids and user_id not in self.config.admin_ids:
            logger.warning(f"Non-admin {user_id} tried to reset limits")
            return
        
        # Reset usage counters
        self.db.reset_user_limits(user_id)
        
        await update.message.reply_text(
            "✅ Лимиты сброшены!\n\n"
            f"💬 Доступно: {self.config.free_messages_limit} сообщений\n"
            f"🎯 Доступно: {self.config.free_tokens_limit} токенов\n"
            f"📸 Доступно: {self.config.free_images_limit} изображений"
        )
        logger.info(f"Admin {user_id} reset their limits")
    
    async def subscribe(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle /subscribe command - show subscription options
        """
        # Clean up command message
        try:
            await update.message.delete()
        except Exception as e:
            logger.warning(f"Failed to delete /subscribe command: {e}")
        
        user_id = update.effective_user.id
        context.bot_data['subscription_manager'] = self.subscription_manager
        
        # Check if user already has active subscription
        if self.subscription_manager.has_active_subscription(user_id):
            text = self._get_active_subscription_text(user_id)
        else:
            text = "🌟 <b>Оформление подписки</b>\n\nВыберите способ оплаты:"
        
        # Build keyboard with payment methods and close button
        reply_markup = self._build_subscribe_keyboard()
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    
    async def subscription_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle /subscription command - check subscription status
        """
        user_id = update.effective_user.id
        
        # Get active subscription if exists
        sub = self.subscription_manager.get_active_subscription(user_id)
        if sub:
            # Show only status without renewal offer
            end_date = datetime.fromisoformat(sub["end_date"])
            days_left = max(0, (end_date - datetime.now()).days)
            
            # Proper Russian pluralization for days
            n = abs(days_left)
            n10, n100 = n % 10, n % 100
            if n10 == 1 and n100 != 11:
                days_word = "день"
            elif 2 <= n10 <= 4 and not (12 <= n100 <= 14):
                days_word = "дня"
            else:
                days_word = "дней"
            
            text = (
                "✅ <u>У вас есть активная подписка</u>\n\n"
                f"До конца подписки осталось <b><i>{days_left} {days_word}</i></b>"
            )
        else:
            text = (
                "✖️ <u>Сейчас у вас нет активной подписки</u>\n\n"
                "Используйте /subscribe для оформления подписки"
            )
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            parse_mode=ParseMode.HTML
        )
        
        # Clean up command message
        try:
            await update.message.delete()
        except Exception as e:
            logger.warning(f"Failed to delete /subscription command: {e}")
    
    async def clean(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle /clean command - remove reply keyboard
        """
        await update.message.reply_text(
            "✅ Клавиатура очищена",
            reply_markup=ReplyKeyboardRemove()
        )
        logger.info(f"Keyboard cleared for user {update.effective_user.id}")
    
    async def faq(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle /faq command - show interactive FAQ with inline keyboard
        """
        faq_items = self.docs_service.parse_faq_items()
        
        if not faq_items:
            await update.message.reply_text("❌ FAQ пуст. Попробуйте позже.")
            return
        
        # Store FAQ items in user context for navigation
        context.user_data['faq_items'] = faq_items
        context.user_data['faq_page'] = 0
        
        await self._show_faq_inline(update.message, context, page=0)
        
        # Clean up command message
        try:
            await update.message.delete()
        except Exception as e:
            logger.warning(f"Failed to delete /faq message: {e}")
        
        logger.info(f"FAQ shown to user {update.effective_user.id}")
    
    async def handle_close_subscribe(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle close button in subscription menu
        """
        query = update.callback_query
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            pass
    
    # ==================== MESSAGE HANDLERS ====================
    
    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle photo messages with vision capabilities
        Processes images, checks limits, and generates AI responses
        """
        user_id = update.effective_user.id
        
        # Anti-spam protection (for all users)
        if not await self._check_spam_protection(user_id, update):
            return
        
        # Rate limiting (for all users)
        if not await self._check_rate_limit(user_id, update):
            return
        
        # Check subscription status
        has_subscription = self.subscription_manager.has_active_subscription(user_id)
        
        # Check limits based on subscription status
        if self.config.subscription_required and not has_subscription:
            usage = self.db.get_user_usage(user_id)
            
            # Check image limit
            if usage["images"] >= self.config.free_images_limit:
                await update.message.reply_text(
                    "⚠️ `Вы исчерпали бесплатный лимит изображений`\n\n"
                    "🌟 Для продолжения общения с картинками подключите /subscribe",
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_markup=self.subscription_manager.get_payment_method_keyboard()
                )
                return
            
            # Check other limits
            if not await self._check_limits(user_id, update):
                return
        else:
            # Check daily limits for subscribers with "tiredness" system
            if not await self._check_subscriber_limits(user_id, update, for_image=True):
                return
        
        # Validate image size
        photo = update.message.photo[-1]
        file_size_mb = photo.file_size / (1024 * 1024)
        if file_size_mb > self.config.max_image_size_mb:
            await update.message.reply_text(
                f"⚠️ Изображение слишком большое ({file_size_mb:.1f} МБ)\n"
                f"Максимальный размер: {self.config.max_image_size_mb} МБ"
            )
            return
        
        # Download and process image
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        image_hash = get_image_hash(bytes(image_bytes))
        
        # Check for duplicate images (within 30 minutes)
        is_duplicate = self.db.is_duplicate_image(user_id, image_hash, minutes=30)
        user_text = (update.message.caption or "").strip()
        
        logger.info(f"User {user_id} sent photo with caption: {user_text[:50]}...{' (DUPLICATE)' if is_duplicate else ''}")
        
        # Prepare message with image for LLM
        current_personality = self.docs_service.get_personality()
        time_context = get_enrichment_context()
        current_system_prompt = self._build_time_aware_prompt(current_personality, time_context)
        image_message = create_image_message(
            image_bytes=bytes(image_bytes),
            text=user_text,
            is_duplicate=is_duplicate,
            mime_type="image/jpeg",
            detail=self.config.image_detail_level
        )
        
        # Build conversation context
        history = self.db.get_dialogue_history(user_id, limit=10)
        messages = [{"role": "system", "content": current_system_prompt}] + history + [image_message]
        
        # Generate AI response
        response_text, _ = await self.llm.generate_response(messages)
        response_text = (response_text or "").strip() or "Хм, не уверена, что поняла."
        
        # Generate short description of image for history context
        description_prompt = [
            {"role": "system", "content": "Кратко опиши что изображено на фото одним-двумя короткими предложениями. Пиши от лица Алины, которая видит фото: 'вижу...', 'на фото...'. Будь конкретной."},
            image_message
        ]
        
        try:
            image_description, _ = await self.llm.generate_response(description_prompt)
            image_description = (image_description or "").strip()
            
            # Check if description is a refusal (contains apology or refusal phrases)
            refusal_indicators = [
                "извини", "не могу", "нельзя", "sorry", "cannot", "can't",
                "отказ", "запрещ", "неприемлем", "inappropriate"
            ]
            
            if any(indicator in image_description.lower() for indicator in refusal_indicators):
                # Model refused - use neutral fallback
                if "откровен" in response_text.lower() or "откровен" in image_description.lower():
                    image_description = "вижу откровенное изображение"
                else:
                    image_description = "вижу изображение, которое не могу подробно описать"
                logger.info(f"Model refused description, using fallback: {image_description}")
            else:
               
                image_description = image_description
                logger.info(f"Generated image description: {image_description}")
        except Exception as e:
            logger.error(f"Failed to generate image description: {e}")
            image_description = "изображение"
        
        # Calculate token usage
        user_tokens_now = self.llm.count_tokens_text(user_text) + self.llm._calculate_image_tokens("")
        output_tokens_now = self.llm.count_tokens_text(response_text)
        tokens_net = user_tokens_now + output_tokens_now
        
        # Send response
        await update.message.reply_text(response_text)
        
        # Save to database with image description
        if user_text:
            display_text = f"{user_text} [📸 {image_description}]"
        else:
            display_text = f"[📸 {image_description}]"
        
        logger.info(f"Saving to history: {display_text[:100]}...")
        self.db.add_message(user_id, "user", display_text, 
                           has_image=True, image_count=1, image_hash=image_hash)
        self.db.add_message(user_id, "assistant", response_text, tokens_net)
        
        logger.info(f"Alina (vision): {response_text[:50]}... (tokens: {tokens_net}, images: 1)")
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Main text message handler with LLM integration
        Processes user messages and generates AI responses
        """
        user_id = update.effective_user.id
        user_message = (update.message.text or "").strip()
        
        if not user_message:
            return
        
        # Anti-spam protection (for all users)
        if not await self._check_spam_protection(user_id, update):
            return
        
        # Rate limiting (for all users)
        if not await self._check_rate_limit(user_id, update):
            return
        
        # Check subscription status
        has_subscription = self.subscription_manager.has_active_subscription(user_id)
        
        # Check limits based on subscription status
        if self.config.subscription_required and not has_subscription:
            if not await self._check_limits(user_id, update):
                return
        else:
            # Check daily limits for subscribers with "tiredness" system
            if not await self._check_subscriber_limits(user_id, update, for_image=False):
                return
        
        logger.info(f"User {user_id}: {user_message[:50]}...")
        
        # Save user message
        self.db.add_message(user_id, "user", user_message)
        
        # Build conversation context
        history = self.db.get_dialogue_history(user_id, limit=20)
        current_personality = self.docs_service.get_personality()
        time_context = get_enrichment_context()
        current_system_prompt = self._build_time_aware_prompt(current_personality, time_context)
        messages = [{"role": "system", "content": current_system_prompt}] + history
        
        # Log token usage for debugging
        sys_tokens = self.llm.count_tokens_messages([{"role": "system", "content": current_system_prompt}])
        hist_tokens = self.llm.count_tokens_messages(history)
        total_est = self.llm.count_tokens_messages(messages)
        logger.info(f"Context: sys={sys_tokens}, hist={hist_tokens}, total={total_est}")
        
        # Generate AI response
        response_text, _ = await self.llm.generate_response(messages)
        response_text = (response_text or "").strip() or "Хм, не уверена, что поняла."
        
        # Calculate token usage
        user_tokens_now = self.llm.count_tokens_text(user_message)
        output_tokens_now = self.llm.count_tokens_text(response_text)
        tokens_net = user_tokens_now + output_tokens_now
        
        # Send response
        await update.message.reply_text(response_text)
        
        # Save response to database
        self.db.add_message(user_id, "assistant", response_text, tokens_net)
        
        logger.info(f"Alina: {response_text[:50]}... (net_tokens: {tokens_net})")
    
    # ==================== FAQ HANDLERS ====================
    
    async def handle_faq_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle FAQ inline keyboard button presses
        Manages FAQ navigation and question display
        """
        query = update.callback_query
        await query.answer()
        
        data = query.data
        faq_items = context.user_data.get('faq_items', [])
        page = context.user_data.get('faq_page', 0)
        
        # Handle navigation buttons
        if data == "faq_prev":
            await self._show_faq_inline(query.message, context, page - 1, edit=True)
        elif data == "faq_next":
            await self._show_faq_inline(query.message, context, page + 1, edit=True)
        elif data == "faq_close":
            await query.message.delete()
            context.user_data.pop('faq_items', None)
            context.user_data.pop('faq_page', None)
        elif data == "faq_back":
            await self._show_faq_inline(query.message, context, page, edit=True)
        elif data == "faq_noop":
            pass  # Empty placeholder button
        elif data.startswith("faq_q_"):
            # Show specific FAQ question and answer
            idx = int(data.split("_")[2])
            if 0 <= idx < len(faq_items):
                question, answer = faq_items[idx]
                response_text = f"❓ *{question}*\n\n{answer}"
                
                keyboard = [
                    [InlineKeyboardButton("◀️ Назад к FAQ", callback_data="faq_back")],
                    [InlineKeyboardButton("❌ Закрыть", callback_data="faq_close")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.message.edit_text(response_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    # ==================== HELPER METHODS ====================
    
    def _build_time_aware_prompt(self, base_personality: str, time_context: Dict[str, Any]) -> str:
        """Build system prompt with current time and date context
        
        Args:
            base_personality: Base personality from Google Docs
            time_context: Time context from MCP server
            
        Returns:
            Enhanced system prompt with time awareness
        """
        # Создаем контекст времени для внутреннего использования (Алина знает, но не озвучивает)
        time_awareness = (
            f"Текущий контекст времени (используй эту информацию только если спросят или это релевантно):\n"
            f"СЕГОДНЯ: {time_context.get('date')} ({time_context.get('weekday_name')})\n"
            f"ВРЕМЯ: {time_context.get('formatted_time')} ({time_context.get('time_of_day')})"
        )
        
        if time_context.get('is_weekend'):
            time_awareness += ", выходной"
        
        time_awareness += ".\n\nВажно: В истории диалога есть метки с точными датами (например 'вчера (9 октября)'), используй их чтобы точно отвечать на вопросы о датах.\nНе упоминай дату/день недели/год без необходимости - отвечай естественно как живой человек."
        
        # Обогащаем промпт с контекстом настроения
        enriched = enrich_prompt(base_personality, time_context)
        
        # Объединяем всё вместе
        return f"{time_awareness}\n\n{enriched}"
    
    
    async def _check_limits(self, user_id: int, update: Update) -> bool:
        """
        Check if user has reached free usage limits
        Returns True if user can continue, False if limits exceeded
        """
        usage = self.db.get_user_usage(user_id)
        
        if (usage["messages"] >= self.config.free_messages_limit or 
            usage["tokens"] >= self.config.free_tokens_limit or 
            usage["images"] >= self.config.free_images_limit):
            await update.message.reply_text(
                "⚠️ `Вы исчерпали бесплатный лимит`\n\n"
                "🌟 Для продолжения общения подключите /subscribe",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=self.subscription_manager.get_payment_method_keyboard()
            )
            return False
        return True
    
    async def _check_subscriber_limits(self, user_id: int, update: Update, for_image: bool = False) -> bool:
        """Check daily limits for subscribers with 'tiredness' system
        
        Args:
            user_id: Telegram user ID
            update: Update object
            for_image: Whether this is for an image message
            
        Returns:
            True if user can continue, False if limits exceeded
        """
        usage = self.db.get_daily_usage(user_id)
        
        # Reset warning flags if it's a new day
        last_warning_date = self.db.get_user_data(user_id, 'last_warning_date')
        today = datetime.now().date().isoformat()
        if last_warning_date != today:
            self.db.save_user_data(user_id, 'last_warning_pct', 0.0)
            self.db.save_user_data(user_id, 'last_warning_date', today)
            self.db.save_user_data(user_id, 'last_tired_message_time', None)
        
        # Check if completely exhausted (100%)
        messages_limit = self.config.subscriber_daily_messages
        tokens_limit = self.config.subscriber_daily_tokens
        images_limit = self.config.subscriber_daily_images
        
        # Check if user exceeded limits
        limit_exceeded = False
        if for_image and usage["images"] >= images_limit:
            limit_exceeded = True
            logger.warning(f"User {user_id} reached daily image limit: {usage['images']}/{images_limit}")
        elif usage["messages"] >= messages_limit or usage["tokens"] >= tokens_limit:
            limit_exceeded = True
            logger.warning(f"User {user_id} reached daily limits: {usage['messages']}/{messages_limit} msgs, {usage['tokens']}/{tokens_limit} tokens")
        
        if limit_exceeded:
            # Check when we last sent the "tired" message to avoid spam
            last_tired_message = self.db.get_user_data(user_id, 'last_tired_message_time')
            now = datetime.now()
            
            should_send_message = True
            if last_tired_message:
                last_time = datetime.fromisoformat(last_tired_message)
                # Only send message if 10+ minutes passed since last one
                if (now - last_time).total_seconds() < 600:  # 10 minutes
                    should_send_message = False
            
            if should_send_message:
                await update.message.reply_text(
                    "Прости, но я совсем устала сегодня 😴\n"
                    "Мне нужно отдохнуть до завтра. Спокойной ночи! 💜"
                )
                # Save timestamp of tired message
                self.db.save_user_data(user_id, 'last_tired_message_time', now.isoformat())
            
            return False
        
        # Check tiredness levels with warnings
        messages_pct = usage["messages"] / messages_limit
        tokens_pct = usage["tokens"] / tokens_limit
        images_pct = usage["images"] / images_limit if for_image else 0
        max_pct = max(messages_pct, tokens_pct, images_pct)
        
        # Check when we last sent a tiredness warning
        last_warning_pct = self.db.get_user_data(user_id, 'last_warning_pct', 0.0)
        
        # 90% - strong warning (only if we haven't warned at this level)
        if max_pct >= 0.90 and last_warning_pct < 0.90:
            await update.message.reply_text("Уф, я уже изрядно вымоталась... Давай помедленнее? 😅")
            self.db.save_user_data(user_id, 'last_warning_pct', 0.90)
        # 80% - gentle warning (only if we haven't warned at this level)
        elif max_pct >= 0.80 and last_warning_pct < 0.80:
            await update.message.reply_text("Я немного устала, но ещё могу поболтать 😊")
            self.db.save_user_data(user_id, 'last_warning_pct', 0.80)
        
        return True
    
    async def _check_rate_limit(self, user_id: int, update: Update) -> bool:
        """Check if user is sending messages too quickly
        
        Args:
            user_id: Telegram user ID
            update: Update object
            
        Returns:
            True if rate limit passed, False if too fast
        """
        last_message_time = self.db.get_last_message_time(user_id)
        
        if last_message_time:
            time_since_last = (datetime.now() - last_message_time).total_seconds()
            
            if time_since_last < self.config.rate_limit_seconds:
                wait_time = self.config.rate_limit_seconds - time_since_last
                logger.info(f"User {user_id} rate limited: {time_since_last:.1f}s since last message")
                # Silently ignore - don't send error message to avoid spam
                return False
        
        return True
    
    async def _check_spam_protection(self, user_id: int, update: Update) -> bool:
        """Check for spam behavior and block if necessary
        
        Args:
            user_id: Telegram user ID
            update: Update object
            
        Returns:
            True if check passed, False if user is blocked/suspicious
        """
        # Check if user is already blocked
        if self.db.is_user_blocked(user_id):
            block_until = self.db.get_user_data(user_id, 'block_until')
            if block_until:
                block_time = datetime.fromisoformat(block_until)
                minutes_left = max(0, int((block_time - datetime.now()).total_seconds() / 60))
                await update.message.reply_text(
                    f"⛔️ Слишком много сообщений!\n\n"
                    f"Попробуй снова через {minutes_left} мин."
                )
            return False
        
        # Check for spam (20+ messages in 1 minute)
        recent_count = self.db.get_recent_message_count(user_id, minutes=1)
        
        if recent_count >= 20:
            self.db.block_user_temporarily(user_id, minutes=5)
            await update.message.reply_text(
                "⛔️ Обнаружена подозрительная активность!\n\n"
                "Ты отправляешь слишком много сообщений. "
                "Возможность отправлять сообщения заблокирована на 5 минут."
            )
            logger.warning(f"User {user_id} BLOCKED for spam: {recent_count} messages in 1 minute")
            return False
        
        return True
    
    def _get_active_subscription_text(self, user_id: int) -> str:
        """
        Generate formatted text for active subscription status
        """
        sub = self.subscription_manager.get_active_subscription(user_id)
        end_date = datetime.fromisoformat(sub["end_date"])
        days_left = max(0, (end_date - datetime.now()).days)
        
        # Proper Russian pluralization for days
        n = abs(days_left)
        n10, n100 = n % 10, n % 100
        if n10 == 1 and n100 != 11:
            days_word = "день"
        elif 2 <= n10 <= 4 and not (12 <= n100 <= 14):
            days_word = "дня"
        else:
            days_word = "дней"
        
        return (
            "✅ <u>У вас есть активная подписка</u>\n\n"
            f"До конца подписки осталось <b><i>{days_left} {days_word}</i></b>\n\n"
            "Хотите продлить подписку заранее?\n\n"
            "Выберите способ оплаты:"
        )
    
    def _build_subscribe_keyboard(self) -> InlineKeyboardMarkup:
        """
        Build subscription keyboard with payment methods and close button
        """
        base_markup = self.subscription_manager.get_payment_method_keyboard()
        rows = [list(row) for row in base_markup.inline_keyboard]
        rows.append([InlineKeyboardButton("❌", callback_data="close_subscribe")])
        return InlineKeyboardMarkup(rows)
    
    async def _show_faq_inline(self, message, context: ContextTypes.DEFAULT_TYPE, page: int = 0, edit: bool = False):
        """
        Display FAQ inline keyboard with pagination
        """
        faq_items = context.user_data.get('faq_items', [])
        
        if not faq_items:
            return
        
        # Calculate pagination
        items_per_page = 3
        total_pages = (len(faq_items) + items_per_page - 1) // items_per_page
        page = max(0, min(page, total_pages - 1))
        context.user_data['faq_page'] = page
        
        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, len(faq_items))
        page_items = faq_items[start_idx:end_idx]
        
        # Build keyboard with FAQ questions
        keyboard = []
        for idx, (question, _) in enumerate(page_items):
            button_text = question
            callback_data = f"faq_q_{start_idx + idx}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        
        # Add navigation row
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("◀️ Назад", callback_data="faq_prev"))
        else:
            nav_row.append(InlineKeyboardButton("⠀", callback_data="faq_noop"))
        
        nav_row.append(InlineKeyboardButton("❌", callback_data="faq_close"))
        
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("Вперёд ▶️", callback_data="faq_next"))
        else:
            nav_row.append(InlineKeyboardButton("⠀", callback_data="faq_noop"))
        
        keyboard.append(nav_row)
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        faq_text = f"📖 *FAQ - Частые вопросы*\n\nВыберите интересующий вас вопрос\nСтраница {page + 1} из {total_pages}"
        
        # Send or edit message
        if edit:
            await message.edit_text(faq_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await message.reply_text(faq_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    # ==================== LIFECYCLE METHODS ====================
    
    async def post_init(self, application: Application) -> None:
        """
        Called after the bot starts
        Initializes background tasks and services
        """
        logger.info("Initializing background tasks...")
        self.docs_service.start_periodic_updates()
        
        # Store services in bot data for access in handlers
        context = application.bot_data
        context['subscription_manager'] = self.subscription_manager
        context['yookassa_client'] = self.yookassa_client
        
        # Start payment status checker (checks every 5 seconds)
        logger.info("🔄 Starting payment status checker")
        self.payment_checker.start(application.bot)
        
        # Start periodic database cleanup (runs every 6 hours)
        logger.info("🧹 Starting periodic database cleanup")
        import asyncio
        asyncio.create_task(self._periodic_cleanup_task())
        
        # Start daily reminder task (runs at 10:00 MSK)
        logger.info("🔔 Starting daily reminder task")
        asyncio.create_task(self._daily_reminder_task())
        
        logger.info("Background tasks started")
    
    async def _generate_reminder_message(self, user_id: int) -> str:
        """Генерировать персонализированное напоминающее сообщение для неактивного юзера
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            Генерированное сообщение-напоминание
        """
        try:
            # Получаем последние 5 сообщений для контекста
            history = self.db.get_dialogue_history(user_id, limit=5)
            
            # Создаём промпт для генерации напоминания
            current_personality = self.docs_service.get_personality()
            time_context = get_enrichment_context()
            
            reminder_prompt = (
                f"Ты - Алина. Сейчас {time_context.get('time_of_day')}, "
                f"{time_context.get('weekday_name')}, {time_context.get('formatted_time')}.\n\n"
                f"Пользователь не писал тебе больше суток. Напиши ему короткое (1-2 предложения) "
                f"непринуждённое сообщение, чтобы напомнить о себе.\n\n"
                f"Требования:\n"
                f"- Не используй эмодзи\n"
                f"- Пиши естественно, как живой человек\n"
                f"- Можешь сослаться на предыдущий разговор если он был\n"
                f"- Не будь назойливой, просто напомни о себе\n"
                f"- НЕ задавай вопросы типа 'как дела?', 'чем занимаешься?' - это скучно\n"
                f"- Вариируй стиль: можешь пошутить, поделиться мыслью, или просто написать что-то милое\n\n"
                f"Примеры хороших сообщений:\n"
                f"- 'прив, давно не общались)'\n"
                f"- 'что-то тихо стало у тебя'\n"
                f"- 'вспомнила про тебя, как там дела с [topic from history]?'\n"
                f"- 'эй, ты живой?'\n"
                f"- 'скучно мне без твоих сообщений'\n\n"
                f"Напиши ТОЛЬКО само сообщение, без лишних комментариев."
            )
            
            messages = [
                {"role": "system", "content": reminder_prompt}
            ]
            
            # Добавляем контекст из истории если есть
            if history:
                messages.append({
                    "role": "system",
                    "content": f"Последние сообщения с этим пользователем:\n" + 
                              "\n".join([f"{msg['role']}: {msg['content'][:100]}" for msg in history[-3:]])
                })
            
            # Генерируем ответ
            reminder_text, _ = await self.llm.generate_response(messages)
            reminder_text = (reminder_text or "").strip()
            
            # Убираем кавычки если они есть
            if reminder_text.startswith('"') and reminder_text.endswith('"'):
                reminder_text = reminder_text[1:-1]
            if reminder_text.startswith("'") and reminder_text.endswith("'"):
                reminder_text = reminder_text[1:-1]
            
            return reminder_text or "прив, давно не общались)"
            
        except Exception as e:
            logger.error(f"Failed to generate reminder for user {user_id}: {e}")
            return "эй, ты как там?"
    
    async def _send_reminder_to_inactive_users(self):
        """Проверить неактивных юзеров и отправить им напоминания"""
        try:
            # Получаем список неактивных пользователей (> 24 часов)
            inactive_users = self.db.get_inactive_users(hours_threshold=24)
            
            if not inactive_users:
                logger.info("Нет неактивных пользователей для напоминания")
                return
            
            logger.info(f"🔔 Найдено {len(inactive_users)} неактивных пользователей")
            
            sent_count = 0
            failed_count = 0
            
            for user_id in inactive_users:
                try:
                    # Генерируем персонализированное сообщение
                    reminder_message = await self._generate_reminder_message(user_id)
                    
                    # Отправляем сообщение
                    await self.application.bot.send_message(
                        chat_id=user_id,
                        text=reminder_message
                    )
                    
                    # Сохраняем в историю
                    self.db.add_message(user_id, "assistant", reminder_message, tokens_used=0)
                    
                    sent_count += 1
                    logger.info(f"✅ Напоминание отправлено юзеру {user_id}")
                    
                    # Небольшая задержка чтобы не спамить
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    failed_count += 1
                    logger.error(f"❌ Не удалось отправить напоминание юзеру {user_id}: {e}")
            
            logger.info(f"📤 Напоминания отправлены: {sent_count} успешно, {failed_count} ошибок")
            
        except Exception as e:
            logger.error(f"Reminder task failed: {e}")
    
    async def _daily_reminder_task(self):
        """Ежедневная задача отправки напоминаний в 10:00 МСК"""
        import asyncio
        from datetime import datetime, timedelta
        from time_mcp_server import MOSCOW_TZ
        
        while True:
            try:
                # Текущее время в МСК
                now = datetime.now(MOSCOW_TZ)
                
                # Целевое время: 10:00 МСК
                target_time = now.replace(hour=4, minute=28, second=0, microsecond=0)
                
                # Если 10:00 уже прошло сегодня, запланируем на завтра
                if now >= target_time:
                    target_time = target_time + timedelta(days=1)
                
                # Вычисляем сколько секунд до следующего запуска
                wait_seconds = (target_time - now).total_seconds()
                
                hours = int(wait_seconds // 3600)
                minutes = int((wait_seconds % 3600) // 60)
                logger.info(f"🕒 Следующая отправка напоминаний через {hours}ч {minutes}м ({target_time.strftime('%d.%m.%Y %H:%M')})")
                
                # Ждём до целевого времени
                await asyncio.sleep(wait_seconds)
                
                # Отправляем напоминания
                logger.info("🔔 Запуск ежедневной отправки напоминаний...")
                await self._send_reminder_to_inactive_users()
                
            except Exception as e:
                logger.error(f"Daily reminder task error: {e}")
                # При ошибке ждём час и пробуем снова
                await asyncio.sleep(3600)
    
    async def _periodic_cleanup_task(self):
        """Фоновая задача для периодической очистки БД
        
        Запускается каждые 6 часов и удаляет:
        - Сообщения старше 30 дней
        - Все кроме последних 100 сообщений для каждого юзера
        """
        import asyncio
        
        while True:
            try:
                await asyncio.sleep(6 * 60 * 60)  # 6 часов
                logger.info("🧹 Running periodic database cleanup...")
                self.db.periodic_cleanup_all(keep_last=100, days_to_keep=30)
            except Exception as e:
                logger.error(f"Periodic cleanup error: {e}")
    
    async def post_shutdown(self, application: Application) -> None:
        """
        Called before bot shutdown
        Performs cleanup of background tasks
        """
        logger.info("Stopping background tasks...")
        self.docs_service.stop_periodic_updates()
        self.payment_checker.stop()
        logger.info("Background tasks stopped")
    
    # ==================== APPLICATION SETUP ====================
    
    def run(self) -> None:
        """
        Start the bot application
        Configures handlers and starts polling
        """
        # Validate configuration
        if not self.config.telegram_bot_token or not self.config.openai_api_key:
            logger.error("Missing required configuration!")
            return
        
        # Build application
        self.application = (
            Application.builder()
            .token(self.config.telegram_bot_token)
            .concurrent_updates(False)
            .post_init(self.post_init)
            .post_shutdown(self.post_shutdown)
            .build()
        )
        
        # Store services in bot data
        self.application.bot_data['subscription_manager'] = self.subscription_manager
        self.application.bot_data['yookassa_client'] = self.yookassa_client
        
        # Register all handlers
        self.application.add_handlers([
            # Command handlers
            CommandHandler("start", self.start),
            CommandHandler("restart", self.restart),
            CommandHandler("reset_limits", self.reset_limits),
            CommandHandler("subscribe", self.subscribe),
            CommandHandler("subscription", self.subscription_status),
            CommandHandler("clean", self.clean),
            CommandHandler("faq", self.faq),
            
            # Callback query handlers
            CallbackQueryHandler(self.handle_faq_callback, pattern="^faq_"),
            CallbackQueryHandler(handle_subscribe_callback, pattern="^(subscribe_|payment_method_|back_to_payment_methods|stars_direct_)"),
            CallbackQueryHandler(self.handle_close_subscribe, pattern="^close_subscribe$"),
            
            # Payment handlers
            PreCheckoutQueryHandler(handle_stars_pre_checkout),
            MessageHandler(filters.SUCCESSFUL_PAYMENT, handle_stars_successful_payment),
            
            # Message handlers
            MessageHandler(filters.PHOTO, self.handle_photo),
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message),
        ])
        
        logger.info("Алина запущена с поддержкой изображений! 📸")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)


def main():
    """Application entry point"""
    bot = AlinaBot()
    bot.run()


if __name__ == "__main__":
    main()
