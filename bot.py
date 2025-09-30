"""Alina Bot - Main Application Module"""

import logging
import os
import sys
from typing import Dict, List

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
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
from llm import AlinaLLM, create_image_message
from payments import SubscriptionManager, create_invoice, handle_subscribe_callback
from personality import ALINA_PERSONALITY, enrich_prompt

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

logger = logging.getLogger("alina-bot")


class AlinaBot:
    """Main bot application class"""
    
    def __init__(self):
        self.config = Config()
        self.db = DialogueDB()
        self.llm = AlinaLLM(
            api_key=self.config.openai_api_key,
            model=self.config.openai_model,
            use_proxy=self.config.use_proxy,
            proxy_url=self.config.proxy_url,
        )
        self.subscription_manager = SubscriptionManager(self.db)
        self.docs_service = get_docs_service()
        self.system_prompt = enrich_prompt(ALINA_PERSONALITY, {})
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command"""
        user = update.effective_user
        self.db.get_or_create_user(user_id=user.id)
        
        text = "Меня зовут Алина) рада буду пообщаться с тобой!\n\n📸 Теперь ты можешь отправлять мне картинки, и я их пойму!"
        await update.message.reply_text(text)
        logger.info(f"New user started: {user.id}")
    
    async def restart(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /restart command - restarts bot process"""
        user_id = update.effective_user.id
        
        if self.config.admin_ids and user_id not in self.config.admin_ids:
            logger.warning(f"Non-admin {user_id} tried to restart bot")
            return
        
        logger.info(f"Admin {user_id} initiated bot restart")
        await update.message.reply_text("Перезапускаюсь... Подождите несколько секунд.")
        
        os.execv(sys.executable, [sys.executable] + sys.argv)
    
    async def reset_limits(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /reset_limits - admin only command"""
        user_id = update.effective_user.id
        
        if self.config.admin_ids and user_id not in self.config.admin_ids:
            logger.warning(f"Non-admin {user_id} tried to reset limits")
            return
        
        self.db.reset_user_limits(user_id)
        
        await update.message.reply_text(
            "✅ Лимиты сброшены!\n\n"
            f"💬 Доступно: {self.config.free_messages_limit} сообщений\n"
            f"🎯 Доступно: {self.config.free_tokens_limit} токенов\n"
            f"📸 Доступно: {self.config.free_images_limit} изображений"
        )
        logger.info(f"Admin {user_id} reset their limits")
    
    async def subscribe(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /subscribe command"""
        user_id = update.effective_user.id
        context.bot_data['subscription_manager'] = self.subscription_manager
        
        if self.subscription_manager.has_active_subscription(user_id):
            info = self.subscription_manager.format_subscription_info(user_id)
            text = f"✅ {info}\n\nХотите продлить подписку заранее? Выберите новый период:"
        else:
            text = "🌟 Оформите подписку на бота Алину!\n\nВыберите удобный период:"
        
        await update.message.reply_text(
            text,
            reply_markup=self.subscription_manager.get_subscription_keyboard()
        )
    
    async def subscription_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /subscription command - check subscription status"""
        user_id = update.effective_user.id
        
        if self.subscription_manager.has_active_subscription(user_id):
            info = self.subscription_manager.format_subscription_info(user_id)
            await update.message.reply_text(f"✅ {info}")
        else:
            usage = self.db.get_user_usage(user_id)
            messages_left = max(0, self.config.free_messages_limit - usage["messages"])
            tokens_left = max(0, self.config.free_tokens_limit - usage["tokens"])
            images_left = max(0, self.config.free_images_limit - usage["images"])
            
            await update.message.reply_text(
                "❌ *У вас нет активной подписки*\n\n"
                f"📦 *Бесплатные лимиты:*\n"
                f"💬 Сообщения: {usage['messages']}/{self.config.free_messages_limit} (осталось {messages_left})\n"
                f"🎯 Токены: {usage['tokens']}/{self.config.free_tokens_limit} (осталось {tokens_left})\n"
                f"📸 Изображения: {usage['images']}/{self.config.free_images_limit} (осталось {images_left})\n\n"
                "Используйте /subscribe для оформления подписки.",
                parse_mode=ParseMode.MARKDOWN
            )
    
    async def clean(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /clean command - remove reply keyboard"""
        await update.message.reply_text(
            "✅ Клавиатура очищена",
            reply_markup=ReplyKeyboardRemove()
        )
        logger.info(f"Keyboard cleared for user {update.effective_user.id}")
    
    async def faq(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /faq command - show interactive FAQ with inline keyboard"""
        try:
            await update.message.delete()
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение /faq: {e}")
        
        faq_items = self.docs_service.parse_faq_items()
        
        if not faq_items:
            await update.message.reply_text("❌ FAQ пуст. Попробуйте позже.")
            return
        
        context.user_data['faq_items'] = faq_items
        context.user_data['faq_page'] = 0
        
        await self._show_faq_inline(update.message, context, page=0)
        logger.info(f"FAQ shown to user {update.effective_user.id}")
    
    async def _show_faq_inline(self, message, context: ContextTypes.DEFAULT_TYPE, page: int = 0, edit: bool = False):
        """Показать Inline клавиатуру FAQ"""
        faq_items = context.user_data.get('faq_items', [])
        
        if not faq_items:
            return
        
        items_per_page = 3
        total_pages = (len(faq_items) + items_per_page - 1) // items_per_page
        page = max(0, min(page, total_pages - 1))
        context.user_data['faq_page'] = page
        
        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, len(faq_items))
        page_items = faq_items[start_idx:end_idx]
        
        keyboard = []
        
        for idx, (question, _) in enumerate(page_items):
            button_text = question
            callback_data = f"faq_q_{start_idx + idx}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        
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
        
        if edit:
            await message.edit_text(faq_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await message.reply_text(faq_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    async def handle_faq_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработка нажатий на Inline кнопки FAQ"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        faq_items = context.user_data.get('faq_items', [])
        page = context.user_data.get('faq_page', 0)
        
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
            pass
        elif data.startswith("faq_q_"):
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

    
    async def pre_checkout_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle pre-checkout query from payment provider"""
        await update.pre_checkout_query.answer(ok=True)
        logger.info(f"Pre-checkout query from user {update.pre_checkout_query.from_user.id}")
    
    async def successful_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle successful payment"""
        user_id = update.effective_user.id
        payment = update.message.successful_payment
        
        plan_type = payment.invoice_payload.split('_')[0] if '_' in payment.invoice_payload else None
        
        if plan_type and self.subscription_manager.add_subscription(user_id, plan_type, payment.provider_payment_charge_id):
            plan = self.subscription_manager.SUBSCRIPTION_PLANS.get(plan_type, {})
            await update.message.reply_text(
                f"✅ Спасибо за оплату!\n\n"
                f"Ваша подписка '{plan.get('name', plan_type)}' активирована.\n"
                f"Срок действия: {plan.get('days', 0)} дней\n\n"
                f"Теперь вы можете пользоваться ботом без ограничений! 💜"
            )
            logger.info(f"Payment success: User {user_id}, Plan {plan_type}, Amount {payment.total_amount}")
        else:
            await update.message.reply_text(
                "Произошла ошибка при активации подписки. "
                "Пожалуйста, обратитесь к администратору."
            )
    
    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle photo messages with vision"""
        user = update.effective_user
        user_id = user.id
        
        # Проверяем подписку и лимиты для изображений
        if self.config.subscription_required and not self.subscription_manager.has_active_subscription(user_id):
            usage = self.db.get_user_usage(user_id)
            if usage["images"] >= self.config.free_images_limit:
                await update.message.reply_text(
                    "⚠️ `Вы исчерпали бесплатный лимит изображений`\n\n"
                    "🌟 Для продолжения общения с картинками подключите /subscribe",
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_markup=self.subscription_manager.get_subscription_keyboard()
                )
                return
            
            if not await self._check_limits(user_id, update):
                return
        
        # Получаем фото
        photo = update.message.photo[-1]  # Берём самое большое фото
        
        # Проверяем размер
        file_size_mb = photo.file_size / (1024 * 1024)
        if file_size_mb > self.config.max_image_size_mb:
            await update.message.reply_text(
                f"⚠️ Изображение слишком большое ({file_size_mb:.1f} МБ)\n"
                f"Максимальный размер: {self.config.max_image_size_mb} МБ"
            )
            return
        
        # Скачиваем фото
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        
        # Получаем caption или используем дефолтный текст
        user_text = (update.message.caption or "").strip() or "реагируй коротко и живо, как в переписке. не описывай подробно, а просто скажи что думаешь или чувствуешь"
        
        logger.info(f"User {user_id} sent photo with caption: {user_text[:50]}...")
        
        # Получаем актуальный промпт
        current_personality = self.docs_service.get_personality()
        current_system_prompt = enrich_prompt(current_personality, {})
        
        # Создаём сообщение с изображением
        image_message = create_image_message(
            image_bytes=bytes(image_bytes),
            text=user_text,
            mime_type="image/jpeg",
            detail=self.config.image_detail_level
        )
        
        # Получаем историю диалогов (только текст)
        history = self.db.get_dialogue_history(user_id, limit=10)  # Меньше истории при изображениях
        
        # Формируем messages: system + history + image
        messages = [{"role": "system", "content": current_system_prompt}] + history + [image_message]
        
        # Генерация ответа
        response_text, _ = await self.llm.generate_response(messages)
        response_text = (response_text or "").strip() or "Хм, не уверена, что поняла."
        
        # Считаем токены
        user_tokens_now = self.llm.count_tokens_text(user_text) + self.llm._calculate_image_tokens("")
        output_tokens_now = self.llm.count_tokens_text(response_text)
        tokens_net = user_tokens_now + output_tokens_now
        
        # Отправляем ответ
        await update.message.reply_text(response_text)
        
        # Сохраняем в БД (текст + пометка об изображении)
        self.db.add_message(user_id, "user", f"[📸 Изображение] {user_text}", 
                           has_image=True, image_count=1)
        self.db.add_message(user_id, "assistant", response_text, tokens_net)
        
        # Проверяем лимиты после
        if self.config.subscription_required and not self.subscription_manager.has_active_subscription(user_id):
            usage = self.db.get_user_usage(user_id)
            if (usage["messages"] >= self.config.free_messages_limit) or \
               (usage["tokens"] >= self.config.free_tokens_limit) or \
               (usage["images"] >= self.config.free_images_limit):
                await update.message.reply_text(
                    "⚠️ `Вы исчерпали бесплатный лимит`\n\n"
                    "🌟 Для продолжения общения подключите /subscribe",
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_markup=self.subscription_manager.get_subscription_keyboard()
                )
        
        logger.info(f"Alina (vision): {response_text[:50]}... (tokens: {tokens_net}, images: 1)")
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Main message handler with LLM integration"""
        user = update.effective_user
        user_id = user.id
        user_message = (update.message.text or "").strip()
        
        if not user_message:
            return

        
        # Check subscription limits if required
        if self.config.subscription_required and not self.subscription_manager.has_active_subscription(user_id):
            if not await self._check_limits(user_id, update):
                return
        
        # Log and save user message
        logger.info(f"User {user_id}: {user_message[:50]}...")
        self.db.add_message(user_id, "user", user_message)
        
        # Get conversation history
        history = self.db.get_dialogue_history(user_id, limit=20)
        
        # Получаем актуальный промпт из кеша
        current_personality = self.docs_service.get_personality()
        current_system_prompt = enrich_prompt(current_personality, {})
        
        messages = [{"role": "system", "content": current_system_prompt}] + history
        
        # Token counting for logging
        sys_tokens = self.llm.count_tokens_messages([{"role": "system", "content": current_system_prompt}])
        hist_tokens = self.llm.count_tokens_messages(history)
        total_est = self.llm.count_tokens_messages(messages)
        logger.info(f"Context: sys={sys_tokens}, hist={hist_tokens}, total={total_est}")
        
        # Генерация ответа
        response_text, _ = await self.llm.generate_response(messages)
        response_text = (response_text or "").strip() or "Хм, не уверена, что поняла."

        # Считаем лимит ТОЛЬКО по текущему user и текущему ответу бота
        user_tokens_now = self.llm.count_tokens_text(user_message)
        output_tokens_now = self.llm.count_tokens_text(response_text)
        tokens_net = user_tokens_now + output_tokens_now

        # Отправляем только ответ Алины
        await update.message.reply_text(response_text)

        
        self.db.add_message(user_id, "assistant", response_text, tokens_net)

        # Если подписки нет и по итогу ЭТОГО сообщения лимит пробит — отдельное уведомление
        if self.config.subscription_required and not self.subscription_manager.has_active_subscription(user_id):
            usage = self.db.get_user_usage(user_id)
            if (usage["messages"] >= self.config.free_messages_limit) or (usage["tokens"] >= self.config.free_tokens_limit):

                await update.message.reply_text(
                    "⚠️ `Вы исчерпали бесплатный лимит сообщений`\n\n"
                    "🌟 Для продолжения общения подключите /subscribe",
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_markup=self.subscription_manager.get_subscription_keyboard()
                )


        logger.info(f"Alina: {response_text[:50]}... (net_tokens: {tokens_net})")
    
    async def _check_limits(self, user_id: int, update: Update) -> bool:
        """Check if user has reached free usage limits"""
        usage = self.db.get_user_usage(user_id)
        
        if usage["messages"] >= self.config.free_messages_limit or \
           usage["tokens"] >= self.config.free_tokens_limit or \
           usage["images"] >= self.config.free_images_limit:
            
            await update.message.reply_text(
                    "⚠️ `Вы исчерпали бесплатный лимит`\n\n"
                    "🌟 Для продолжения общения подключите /subscribe",
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_markup=self.subscription_manager.get_subscription_keyboard()
                )
            return False
        return True
    
    
    async def post_init(self, application: Application) -> None:
        """Called after the bot starts - initialize background tasks"""
        logger.info("Initializing background tasks...")
        self.docs_service.start_periodic_updates()
        logger.info("Background tasks started")
    
    async def post_shutdown(self, application: Application) -> None:
        """Called before bot shutdown - cleanup background tasks"""
        logger.info("Stopping background tasks...")
        self.docs_service.stop_periodic_updates()
        logger.info("Background tasks stopped")
    
    def run(self) -> None:
        """Start the bot application"""
        if not self.config.telegram_bot_token or not self.config.openai_api_key:
            logger.error("Missing required configuration!")
            return
        
        app = (Application
            .builder()
            .token(self.config.telegram_bot_token)
            .concurrent_updates(False)
            .post_init(self.post_init)
            .post_shutdown(self.post_shutdown)
            .build())

        app.bot_data['subscription_manager'] = self.subscription_manager
        
        # Register handlers
        app.add_handlers([
            CommandHandler("start", self.start),
            CommandHandler("restart", self.restart),
            CommandHandler("reset_limits", self.reset_limits),
            CommandHandler("subscribe", self.subscribe),
            CommandHandler("subscription", self.subscription_status),
            CommandHandler("clean", self.clean),
            CommandHandler("faq", self.faq),
            CallbackQueryHandler(self.handle_faq_callback, pattern="^faq_"),
            CallbackQueryHandler(handle_subscribe_callback, pattern="^subscribe_"),
            PreCheckoutQueryHandler(self.pre_checkout_callback),
            MessageHandler(filters.SUCCESSFUL_PAYMENT, self.successful_payment),
            MessageHandler(filters.PHOTO, self.handle_photo),
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message),
        ])
        
        logger.info("Алина запущена с поддержкой изображений! 📸")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


def main():
    """Application entry point"""
    bot = AlinaBot()
    bot.run()


if __name__ == "__main__":
    main()
