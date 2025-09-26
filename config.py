# config.py - Конфигурация бота
"""
Простая конфигурация из переменных окружения.
"""

import os
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()


class Config:
    """Конфигурация приложения."""
    
    def __init__(self):
        # Telegram
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        
        # OpenAI
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        
        # Кастомный API endpoint (для OpenRouter, Together AI, etc)
        self.openai_base_url = os.getenv("OPENAI_BASE_URL", "")
        
        # Прокси (опционально)
        self.use_proxy = os.getenv("USE_PROXY", "false").lower() == "true"
        self.proxy_url = os.getenv("PROXY_URL", "")
        
        # База данных
        self.db_path = os.getenv("DB_PATH", "alina.db")
        
        # Отладка
        self.debug = os.getenv("DEBUG", "false").lower() == "true"
        
        # Админы (список ID пользователей через запятую)
        admin_ids_str = os.getenv("ADMIN_IDS", "")
        self.admin_ids = [int(id.strip()) for id in admin_ids_str.split(",") if id.strip().isdigit()]
        
        # Платежи
        self.payments_token = os.getenv("PAYMENTS_TOKEN", "1744374395:TEST:923f8a2de386e1a60ee5")
        self.subscription_required = os.getenv("SUBSCRIPTION_REQUIRED", "false").lower() == "true"
        self.free_messages_limit = int(os.getenv("FREE_MESSAGES_LIMIT", "15"))
        self.free_tokens_limit = int(os.getenv("FREE_TOKENS_LIMIT", "2000"))
        
        # Валидация
        self._validate()
    
    def _validate(self):
        """Проверяет корректность конфигурации."""
        if not self.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN не установлен в .env файле")
        
        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY не установлен в .env файле")
        
        if self.use_proxy and not self.proxy_url:
            raise ValueError("USE_PROXY включен, но PROXY_URL не установлен")
