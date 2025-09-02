# app/config.py
import os
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseModel):
    # Telegram
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    free_messages: int = int(os.getenv("FREE_MESSAGES", "10"))

    # DeepSeek (единственный провайдер)
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    # Оплаты через Telegram Stars
    stars_day_amount: int = int(os.getenv("STARS_DAY_AMOUNT", "200"))
    stars_week_amount: int = int(os.getenv("STARS_WEEK_AMOUNT", "600"))
    stars_month_amount: int = int(os.getenv("STARS_MONTH_AMOUNT", "1200"))

    sub_days_day: int = int(os.getenv("SUB_DAYS_DAY", "1"))
    sub_days_week: int = int(os.getenv("SUB_DAYS_WEEK", "7"))
    sub_days_month: int = int(os.getenv("SUB_DAYS_MONTH", "30"))

settings = Settings()