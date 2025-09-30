"""YooKassa Webhook Handler - Standalone Flask server"""

import logging
from flask import Flask, request, jsonify
import asyncio
from telegram.ext import Application

from config import Config
from payments import process_payment_notification

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Global bot application
bot_app = None


async def process_webhook_async(data):
    """Process webhook asynchronously"""
    if bot_app:
        await process_payment_notification(data, bot_app.bot_data)


@app.route('/yookassa/webhook', methods=['POST'])
def yookassa_webhook():
    """Handle YooKassa webhook notifications"""
    try:
        data = request.json
        
        if not data:
            return jsonify({"error": "No data"}), 400
        
        event_type = data.get("event")
        payment_data = data.get("object", {})
        
        logger.info(f"Received YooKassa webhook: {event_type}, payment_id: {payment_data.get('id')}")
        
        # Process payment notification
        if event_type == "payment.succeeded":
            # Run async processing
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(process_webhook_async(payment_data))
            loop.close()
        
        return jsonify({"status": "ok"}), 200
        
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "healthy"}), 200


def run_webhook_server(application: Application, port: int = 8000):
    """Run webhook server
    
    Args:
        application: Telegram bot application
        port: Server port
    """
    global bot_app
    bot_app = application
    
    logger.info(f"Starting YooKassa webhook server on port {port}")
    logger.info(f"Webhook URL: http://your-domain.com/yookassa/webhook")
    logger.info("Configure this URL in YooKassa dashboard: Settings -> Notifications -> HTTP notifications")
    
    app.run(host='0.0.0.0', port=port, debug=False)


if __name__ == "__main__":
    # For testing purposes
    config = Config()
    run_webhook_server(None, port=8000)
