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
        
        # Прокси (опционально)
        self.use_proxy = os.getenv("USE_PROXY", "false").lower() == "true"
        self.proxy_url = os.getenv("PROXY_URL", "")
        
        # База данных
        self.db_path = os.getenv("DB_PATH", "alina.db")
        
        # Отладка
        self.debug = os.getenv("DEBUG", "false").lower() == "true"
        
        # Валидация
        self._validate()

        self.mcp_enabled = os.getenv("MCP_ENABLED", "true").lower() == "true"
        self.mcp_config_path = os.getenv("MCP_CONFIG_PATH", "./mcp_config.json")
    
    def _validate(self):
        """Проверяет корректность конфигурации."""
        if not self.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN не установлен в .env файле")
        
        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY не установлен в .env файле")
        
        if self.use_proxy and not self.proxy_url:
            raise ValueError("USE_PROXY включен, но PROXY_URL не установлен")