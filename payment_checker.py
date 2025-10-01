"""
Background Payment Status Checker

This module handles automatic payment status checking for YooKassa payments.
It runs in the background and periodically checks pending payments, 
activating subscriptions when payments are confirmed.

Key Features:
- Checks payment status every 5 seconds
- Automatically activates subscriptions on successful payment
- Notifies users about payment status changes
- Cleans up old pending payments
"""

import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List

logger = logging.getLogger(__name__)


class PaymentStatusChecker:
    """
    Periodically checks pending payment statuses in YooKassa
    
    This service runs in the background and checks all pending payments
    every 5 seconds. When a payment is confirmed as successful, it:
    1. Activates the user's subscription
    2. Updates payment status in database
    3. Sends notification to user
    """
    
    def __init__(self, db_path: str, yookassa_client, subscription_manager):
        """
        Initialize payment checker
        
        Args:
            db_path: Path to SQLite database
            yookassa_client: YooKassaClient instance for API calls
            subscription_manager: SubscriptionManager instance for subscription activation
        """
        self.db_path = db_path
        self.yookassa = yookassa_client
        self.subscription_manager = subscription_manager
        self.running = False
        self.task = None
        self.bot = None
    
    # ==================== DATABASE QUERIES ====================
    
    def get_pending_payments(self, minutes: int = 60) -> List[Dict]:
        """
        Get pending payments created within last N minutes
        
        Only checks recent payments to avoid unnecessary API calls
        for old/expired payment attempts.
        
        Args:
            minutes: Look back period in minutes (default: 60)
            
        Returns:
            List of dictionaries with payment information
        """
        cutoff = (datetime.now() - timedelta(minutes=minutes)).strftime('%Y-%m-%d %H:%M:%S')
        
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
    
    # ==================== PAYMENT STATUS CHECKING ====================
    
    async def check_payment_statuses(self):
        """
        Check all pending payments and process successful ones
        
        This method:
        1. Retrieves all pending payments from database
        2. Checks their status in YooKassa
        3. Activates subscription if payment succeeded
        4. Updates payment status in database
        5. Sends notification to user
        """
        if not self.bot:
            logger.error("Bot not set for payment checker")
            return
        
        pending = self.get_pending_payments(minutes=60)
        
        if not pending:
            return  # No pending payments to check
        
        logger.info(f"Checking {len(pending)} pending payments...")
        
        for payment_info in pending:
            payment_id = payment_info["payment_id"]
            user_id = payment_info["user_id"]
            plan_type = payment_info["plan_type"]
            
            try:
                # Check payment status in YooKassa
                status = self.yookassa.get_payment_status(payment_id)
                
                if status == "succeeded":
                    await self._handle_successful_payment(user_id, payment_id, plan_type)
                elif status == "canceled":
                    await self._handle_canceled_payment(payment_id)
                
            except Exception as e:
                logger.error(f"Error checking payment {payment_id}: {e}")
    
    async def _handle_successful_payment(self, user_id: int, payment_id: str, plan_type: str):
        """
        Handle successful payment confirmation
        
        Args:
            user_id: Telegram user ID
            payment_id: YooKassa payment ID
            plan_type: Subscription plan type
        """
        # Import here to avoid circular dependency
        from payments import SubscriptionManager
        
        # Activate subscription
        if self.subscription_manager.add_subscription(user_id, plan_type, payment_id):
            self.subscription_manager.update_payment_status(payment_id, "succeeded")
            
            plan = SubscriptionManager.SUBSCRIPTION_PLANS.get(plan_type, {})
            
            # Send success notification to user
            try:
                await self.bot.send_message(
                    chat_id=user_id,
                    text=f"✅ *Оплата успешна!*\n\n"
                         f"Ваша подписка '{plan.get('name', plan_type)}' активирована.\n"
                         f"Срок действия: {plan.get('days', 0)} дней\n\n"
                         f"Теперь вы можете пользоваться ботом без ограничений! 💜",
                    parse_mode="Markdown"
                )
                logger.info(f"✅ Payment {payment_id} succeeded for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to send success message to user {user_id}: {e}")
    
    async def _handle_canceled_payment(self, payment_id: str):
        """
        Handle canceled payment
        
        Args:
            payment_id: YooKassa payment ID
        """
        self.subscription_manager.update_payment_status(payment_id, "canceled")
        logger.info(f"❌ Payment {payment_id} canceled")
    
    # ==================== BACKGROUND TASK MANAGEMENT ====================
    
    async def run_periodic_check(self):
        """
        Run periodic payment status checks every 5 seconds
        
        This is the main background loop that continuously checks
        for payment updates while the bot is running.
        """
        logger.info("🔄 Payment checker loop started")
        
        while self.running:
            try:
                await self.check_payment_statuses()
            except Exception as e:
                logger.error(f"Error in payment status checker: {e}")
            
            # Wait 5 seconds before next check
            await asyncio.sleep(5)
    
    def start(self, bot):
        """
        Start periodic payment checking in background
        
        Args:
            bot: Telegram bot instance for sending notifications
        """
        if self.running:
            logger.warning("Payment checker already running")
            return
        
        self.bot = bot
        self.running = True
        
        # Create async task in current event loop
        loop = asyncio.get_event_loop()
        self.task = loop.create_task(self.run_periodic_check())
        
        logger.info("💳 Payment status checker started (checking every 5 seconds)")
    
    def stop(self):
        """
        Stop periodic payment checking
        
        Gracefully stops the background task and cleans up resources.
        """
        self.running = False
        
        if self.task:
            self.task.cancel()
        
        logger.info("Payment status checker stopped")
