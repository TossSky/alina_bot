"""YooKassa Integration Module - Russian Payment Gateway"""

import logging
import uuid
from typing import Dict, Optional

from yookassa import Configuration, Payment

logger = logging.getLogger(__name__)


class YooKassaClient:
    """Client for YooKassa payment processing API"""
    
    def __init__(self, shop_id: str, secret_key: str):
        """Initialize YooKassa client with credentials
        
        Args:
            shop_id: YooKassa shop/account ID
            secret_key: YooKassa secret API key
        """
        Configuration.account_id = shop_id
        Configuration.secret_key = secret_key
        
        logger.info(f"YooKassa initialized with shop_id: {shop_id[:10]}...")
    
    def create_payment(
        self,
        amount: float,
        description: str,
        return_url: str = None,
        metadata: Dict = None
    ) -> Optional[Dict]:
        """Create new payment in YooKassa system
        
        Args:
            amount: Payment amount in RUB
            description: Human-readable payment description
            return_url: URL to redirect user after payment (optional)
            metadata: Additional metadata to attach to payment (optional)
            
        Returns:
            Payment data dictionary with confirmation URL, or None on error
        """
        try:
            # Generate idempotency key for safe retries
            idempotence_key = str(uuid.uuid4())
            
            # Build payment data
            payment_data = {
                "amount": {
                    "value": f"{amount:.2f}",
                    "currency": "RUB"
                },
                "confirmation": {
                    "type": "redirect",
                    "return_url": return_url or "https://t.me/Alina_buterbot"
                },
                "capture": True,  # Auto-capture payment
                "description": description
            }
            
            # Add metadata if provided
            if metadata:
                payment_data["metadata"] = metadata
            
            # Create payment via YooKassa API
            payment = Payment.create(payment_data, idempotence_key)
            
            # Format response
            result = {
                "id": payment.id,
                "status": payment.status,
                "amount": float(payment.amount.value),
                "currency": payment.amount.currency,
                "description": payment.description,
                "confirmation_url": payment.confirmation.confirmation_url,
                "metadata": payment.metadata or {}
            }
            
            logger.info(f"Created payment {payment.id} for {amount} RUB")
            return result
            
        except Exception as e:
            logger.error(f"Failed to create payment: {e}")
            return None
    
    def get_payment_status(self, payment_id: str) -> Optional[str]:
        """Get current status of payment from YooKassa
        
        Args:
            payment_id: YooKassa payment ID
            
        Returns:
            Payment status string, or None on error
        """
        try:
            payment = Payment.find_one(payment_id)
            return payment.status
        except Exception as e:
            logger.error(f"Failed to get payment status for {payment_id}: {e}")
            return None
    
    def check_payment_succeeded(self, payment_id: str) -> bool:
        """Check if payment was successfully completed
        
        Args:
            payment_id: YooKassa payment ID
            
        Returns:
            True if payment status is 'succeeded', False otherwise
        """
        status = self.get_payment_status(payment_id)
        return status == "succeeded"
