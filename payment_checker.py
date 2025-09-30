"""Background Payment Status Checker"""

import logging
import asyncio
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict

from telegram.ext import ContextTypes

from config import Config
from yookassa_integration import YooKassaClient

logger = logging.getLogger(__name__)


class PaymentStatusChecker:
    """Periodically checks pending payment statuses"""
    
    def __init__(self, db_path: str, yookassa_client: YooKassaClient):
        self.db_path = db_path
        self.yookassa = yookassa_client
        self.running = False
        self.task = None
    
    def get_pending_payments(self, minutes: int = 60) -> List[Dict]:
        """Get pending payments created in last N minutes
        
        Args:
            minutes: Look back period in minutes
            
        Returns:
            List of pending payment records
        """
        cutoff = (datetime.now() - timedelta(minutes=minutes)).isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT user_id, payment_id, plan_type, amount
                FROM pending_payments
                WHERE status = 'pending' AND created_at > ?
                ORDER BY created_at DESC
            """, (cutoff,))
            
            rows = cursor.fetchall()
            return [
                dict(zip(["user_id", "payment_id", "plan_type", "amount"], row))
                for row in rows
            ]
    
    async def check_payment_statuses(self, context: ContextTypes.DEFAULT_TYPE):
        """Check all pending payments and process successful ones"""
        manager = context.bot_data.get('subscription_manager')
        
        if not manager:
            logger.error("Subscription manager not initialized")
            return
        
        pending = self.get_pending_payments(minutes=60)
        
        if not pending:
            return
        
        logger.info(f"Checking {len(pending)} pending payments...")
        
        for payment_info in pending:
            payment_id = payment_info["payment_id"]
            user_id = payment_info["user_id"]
            plan_type = payment_info["plan_type"]
            
            # Check status in YooKassa
            status = self.yookassa.get_payment_status(payment_id)
            
            if status == "succeeded":
                # Activate subscription
                from payments import SubscriptionManager
                
                if manager.add_subscription(user_id, plan_type, payment_id):
                    manager.update_payment_status(payment_id, "succeeded")
                    
                    plan = SubscriptionManager.SUBSCRIPTION_PLANS.get(plan_type, {})
                    
                    # Send success message
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=f"✅ *Оплата успешна!*\n\n"
                                 f"Ваша подписка '{plan.get('name', plan_type)}' активирована.\n"
                                 f"Срок действия: {plan.get('days', 0)} дней\n\n"
                                 f"Теперь вы можете пользоваться ботом без ограничений! 💜",
                            parse_mode="Markdown"
                        )
                        logger.info(f"✅ Payment {payment_id} succeeded for user {user_id}")
                    except Exception as e:
                        logger.error(f"Failed to send message to user {user_id}: {e}")
            
            elif status == "canceled":
                manager.update_payment_status(payment_id, "canceled")
                logger.info(f"❌ Payment {payment_id} canceled")
    
    async def run_periodic_check(self, context: ContextTypes.DEFAULT_TYPE):
        """Run periodic payment status checks"""
        while self.running:
            try:
                await self.check_payment_statuses(context)
            except Exception as e:
                logger.error(f"Error in payment status checker: {e}")
            
            # Check every 30 seconds
            await asyncio.sleep(30)
    
    def start(self, context: ContextTypes.DEFAULT_TYPE):
        """Start periodic checking"""
        if self.running:
            logger.warning("Payment checker already running")
            return
        
        self.running = True
        
        # Create task in the event loop
        loop = asyncio.get_event_loop()
        self.task = loop.create_task(self.run_periodic_check(context))
        
        logger.info("Payment status checker started (checking every 30 seconds)")
    
    def stop(self):
        """Stop periodic checking"""
        self.running = False
        
        if self.task:
            self.task.cancel()
        
        logger.info("Payment status checker stopped")
