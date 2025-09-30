"""Main bot launcher with webhook server"""

import logging
import threading
import time
from bot import AlinaBot
from webhook_server import create_webhook_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


def run_webhook_server(bot_app, subscription_manager):
    """Run webhook server in separate thread"""
    # SSL certificate paths
    ssl_cert = "/etc/letsencrypt/live/tosssky.hopto.org-0001/fullchain.pem"
    ssl_key = "/etc/letsencrypt/live/tosssky.hopto.org-0001/privkey.pem"
    
    # Internal port (будет проброшен на 443 или 8443 через Jump)
    internal_port = 5000
    
    logger.info("Starting webhook server in separate thread...")
    
    try:
        create_webhook_server(
            application=bot_app.application,
            manager=subscription_manager,
            ssl_cert_path=ssl_cert,
            ssl_key_path=ssl_key,
            port=internal_port
        )
    except Exception as e:
        logger.error(f"Webhook server error: {e}", exc_info=True)


def main():
    """Main entry point"""
    logger.info("🤖 Starting Alina Bot with Webhook Server...")
    
    # Create bot instance
    bot = AlinaBot()
    
    # Wait for bot to initialize
    logger.info("Initializing bot...")
    time.sleep(2)
    
    # Start webhook server in separate thread
    webhook_thread = threading.Thread(
        target=run_webhook_server,
        args=(bot, bot.subscription_manager),
        daemon=True
    )
    webhook_thread.start()
    
    logger.info("✅ Webhook server thread started")
    logger.info("🚀 Starting bot polling...")
    
    # Run bot (blocking)
    bot.run()


if __name__ == "__main__":
    main()
