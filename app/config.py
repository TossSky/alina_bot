import os
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseModel):
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    free_messages: int = int(os.getenv("FREE_MESSAGES", "10"))
    llm_provider: str = os.getenv("LLM_PROVIDER", "deepseek")
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat")

    # оплаты
    stars_month_amount: int = int(os.getenv("STARS_MONTH_AMOUNT", "1200"))  # цена в звёздах (XTR)
    sub_days: int = int(os.getenv("SUB_DAYS", "30"))

    # Redsys (заглушки - впиши реальные)
    redsys_merchant_code: str = os.getenv("REDSYS_MERCHANT_CODE", "")  # FUC
    redsys_terminal: str = os.getenv("REDSYS_TERMINAL", "1")
    redsys_currency: str = os.getenv("REDSYS_CURRENCY", "978")  # EUR
    redsys_key: str = os.getenv("REDSYS_KEY", "")               # секрет
    redsys_env: str = os.getenv("REDSYS_ENV", "test")           # test|prod
    redsys_notify_url: str = os.getenv("REDSYS_NOTIFY_URL", "https://your-domain.tld/webhooks/redsys")
    redsys_ok_url: str = os.getenv("REDSYS_OK_URL", "https://t.me/your_bot?start=paid_ok")
    redsys_ko_url: str = os.getenv("REDSYS_KO_URL", "https://t.me/your_bot?start=paid_failed")

settings = Settings()
