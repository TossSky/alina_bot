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
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-5-chat-latest")
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
        
        # Payments & Subscriptions (YooKassa)
        self.yookassa_shop_id = os.getenv("YOOKASSA_SHOP_ID", "")
        self.yookassa_secret_key = os.getenv("YOOKASSA_SECRET_KEY", "test_G61l2gtd7V3fmf3lHcNsncRQcyuLUdpDFyZlx_Tm-CA")
        self.use_webhook = os.getenv("USE_WEBHOOK", "true").lower() == "true"  # Use webhook instead of polling
        self.subscription_required = os.getenv("SUBSCRIPTION_REQUIRED", "true").lower() == "true"
        self.free_messages_limit = int(os.getenv("FREE_MESSAGES_LIMIT", "15"))
        self.free_tokens_limit = int(os.getenv("FREE_TOKENS_LIMIT", "2000"))
        self.free_images_limit = int(os.getenv("FREE_IMAGES_LIMIT", "5"))
        
        # Image settings
        self.max_image_size_mb = int(os.getenv("MAX_IMAGE_SIZE_MB", "10"))
        self.image_detail_level = os.getenv("IMAGE_DETAIL_LEVEL", "auto")  # "low", "high", "auto"
        
        self._validate()
    
    def _validate(self):
        """Validate required configuration"""
        if not self.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN not set in .env file")
        
        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY not set in .env file")
        
        if self.use_proxy and not self.proxy_url:
            raise ValueError("PROXY_URL required when USE_PROXY=true")
        
        if self.image_detail_level not in ["low", "high", "auto"]:
            raise ValueError("IMAGE_DETAIL_LEVEL must be 'low', 'high', or 'auto'")
