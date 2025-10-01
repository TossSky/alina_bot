"""Configuration Module - Application Settings and Environment Variables"""

import os
from typing import List

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Config:
    """Application configuration loaded from environment variables"""
    
    def __init__(self):
        # Telegram Bot Configuration
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        
        # OpenAI API Configuration
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-5-chat-latest")
        self.openai_base_url = os.getenv("OPENAI_BASE_URL", "")
        
        # Proxy Settings (optional)
        self.use_proxy = True
        self.proxy_url = os.getenv("PROXY_URL", "")
        
        # Database Configuration
        self.db_path = os.getenv("DB_PATH", "alina.db")
        
        # Debug Mode
        self.debug = os.getenv("DEBUG", "false").lower() == "true"
        
        # Admin User IDs (comma-separated in .env)
        admin_ids_str = os.getenv("ADMIN_IDS", "367288553,7372093786,916411940")
        self.admin_ids = [int(id.strip()) for id in admin_ids_str.split(",") if id.strip()]
        
        # YooKassa Payment Configuration
        self.yookassa_shop_id = os.getenv("YOOKASSA_SHOP_ID", "")
        self.yookassa_secret_key = os.getenv("YOOKASSA_SECRET_KEY", "")
        
        # Subscription Settings
        self.subscription_required = os.getenv("SUBSCRIPTION_REQUIRED", "true").lower() == "true"
        self.free_messages_limit = int(os.getenv("FREE_MESSAGES_LIMIT", "15"))
        self.free_tokens_limit = int(os.getenv("FREE_TOKENS_LIMIT", "2000"))
        self.free_images_limit = int(os.getenv("FREE_IMAGES_LIMIT", "5"))
        
        # Subscriber daily limits (anti-spam)
        self.subscriber_daily_messages = int(os.getenv("SUBSCRIBER_DAILY_MESSAGES", "150"))
        self.subscriber_daily_tokens = int(os.getenv("SUBSCRIBER_DAILY_TOKENS", "100000"))
        self.subscriber_daily_images = int(os.getenv("SUBSCRIBER_DAILY_IMAGES", "30"))
        
        # Rate limiting
        self.rate_limit_seconds = int(os.getenv("RATE_LIMIT_SECONDS", "2"))
        
        # Image Processing Settings
        self.max_image_size_mb = int(os.getenv("MAX_IMAGE_SIZE_MB", "10"))
        self.image_detail_level = os.getenv("IMAGE_DETAIL_LEVEL", "auto")
        
        # Validate configuration
        self._validate()
    
    def _validate(self):
        """Validate required configuration values"""
        if not self.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN not set in .env file")
        
        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY not set in .env file")
        
        if self.use_proxy and not self.proxy_url:
            raise ValueError("PROXY_URL required when USE_PROXY=true")
        
        if self.image_detail_level not in ["low", "high", "auto"]:
            raise ValueError("IMAGE_DETAIL_LEVEL must be 'low', 'high', or 'auto'")
