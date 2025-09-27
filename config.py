"""Configuration Module"""

import os
from typing import List

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration from environment variables"""
    
    # Admin user IDs
    ADMIN_IDS = [367288553, 7372093786, 916411940]
    
    def __init__(self):
        # Telegram Bot
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        
        # OpenAI API
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.openai_base_url = os.getenv("OPENAI_BASE_URL", "")
        
        # Proxy
        self.use_proxy = os.getenv("USE_PROXY", "false").lower() == "true"
        self.proxy_url = os.getenv("PROXY_URL", "")
        
        # Database
        self.db_path = os.getenv("DB_PATH", "alina.db")
        
        # Debug
        self.debug = os.getenv("DEBUG", "false").lower() == "true"
        
        # Admin IDs
        self.admin_ids = self.ADMIN_IDS
        
        # Payments & Subscriptions
        self.payments_token = os.getenv("PAYMENTS_TOKEN", "")
        self.subscription_required = os.getenv("SUBSCRIPTION_REQUIRED", "true").lower() == "true"
        self.free_messages_limit = int(os.getenv("FREE_MESSAGES_LIMIT", "15"))
        self.free_tokens_limit = int(os.getenv("FREE_TOKENS_LIMIT", "2000"))
        
        self._validate()
    
    def _validate(self):
        """Validate required configuration"""
        if not self.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN not set in .env file")
        
        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY not set in .env file")
        
        if self.use_proxy and not self.proxy_url:
            raise ValueError("PROXY_URL required when USE_PROXY=true")
