"""YooKassa Webhook Server with SSL - Production Ready"""

import logging
import asyncio
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Global bot application - will be set when server starts
bot_app = None
subscription_manager = None


@app.route('/yookassa/webhook', methods=['POST'])
def yookassa_webhook():
    """Handle YooKassa webhook notifications"""
    try:
        data = request.json
        
        if not data:
            logger.warning("Received empty webhook data")
            return jsonify({"error": "No data"}), 400
        
        event_type = data.get("event")
        payment_object = data.get("object", {})
        payment_id = payment_object.get("id")
        status = payment_object.get("status")
        
        logger.info(f"📨 Webhook received: event={event_type}, payment_id={payment_id}, status={status}")
        
        # Process only successful payments
        if event_type == "payment.succeeded" and status == "succeeded":
            # Get pending payment info
            if not subscription_manager:
                logger.error("Subscription manager not initialized")
                return jsonify({"error": "Manager not ready"}), 500
            
            pending = subscription_manager.get_pending_payment(payment_id)
            
            if not pending:
                logger.warning(f"Pending payment not found: {payment_id}")
                return jsonify({"status": "ok", "message": "Payment not found"}), 200
            
            user_id = pending["user_id"]
            plan_type = pending["plan_type"]
            
            # Activate subscription
            from payments import SubscriptionManager
            
            if subscription_manager.add_subscription(user_id, plan_type, payment_id):
                subscription_manager.update_payment_status(payment_id, "succeeded")
                
                plan = SubscriptionManager.SUBSCRIPTION_PLANS.get(plan_type, {})
                
                # Send success message to user
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                    async def send_message():
                        await bot_app.bot.send_message(
                            chat_id=user_id,
                            text=f"✅ *Оплата успешна!*\n\n"
                                 f"Ваша подписка '{plan.get('name', plan_type)}' активирована.\n"
                                 f"Срок действия: {plan.get('days', 0)} дней\n\n"
                                 f"Теперь вы можете пользоваться ботом без ограничений! 💜",
                            parse_mode="Markdown"
                        )
                    
                    loop.run_until_complete(send_message())
                    loop.close()
                    
                    logger.info(f"✅ Payment {payment_id} succeeded for user {user_id}, subscription activated")
                except Exception as e:
                    logger.error(f"Failed to send message to user {user_id}: {e}")
            else:
                logger.error(f"Failed to activate subscription for payment {payment_id}")
        
        return jsonify({"status": "ok"}), 200
        
    except Exception as e:
        logger.error(f"Webhook processing error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "webhook_url": "/yookassa/webhook",
        "bot_ready": bot_app is not None
    }), 200


@app.route('/', methods=['GET'])
def root():
    """Root endpoint"""
    return jsonify({
        "service": "Alina Bot Webhook Server",
        "status": "running",
        "endpoints": {
            "webhook": "/yookassa/webhook",
            "health": "/health"
        }
    }), 200


def create_webhook_server(application, manager, ssl_cert_path: str, ssl_key_path: str, port: int = 5000):
    """Create and configure webhook server
    
    Args:
        application: Telegram bot application
        manager: SubscriptionManager instance
        ssl_cert_path: Path to SSL certificate
        ssl_key_path: Path to SSL private key
        port: Server port (internal)
    """
    global bot_app, subscription_manager
    bot_app = application
    subscription_manager = manager
    
    logger.info("=" * 60)
    logger.info("🚀 Starting YooKassa Webhook Server")
    logger.info(f"📡 Internal port: {port}")
    logger.info(f"🔒 SSL Certificate: {ssl_cert_path}")
    logger.info(f"🔑 SSL Key: {ssl_key_path}")
    logger.info("=" * 60)
    logger.info("")
    logger.info("📝 Configure in YooKassa dashboard:")
    logger.info("   Settings -> Notifications -> HTTP notifications")
    logger.info("   URL: https://tosssky.hopto.org/yookassa/webhook")
    logger.info("   (or https://tosssky.hopto.org:8443/yookassa/webhook)")
    logger.info("")
    logger.info("=" * 60)
    
    # Create SSL context
    import ssl
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(ssl_cert_path, ssl_key_path)
    
    # Run Flask with SSL
    app.run(
        host='0.0.0.0',
        port=port,
        ssl_context=context,
        debug=False,
        threaded=True
    )
