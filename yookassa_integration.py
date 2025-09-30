"""YooKassa Integration Module"""

import logging
import uuid
from typing import Dict, Optional

from yookassa import Configuration, Payment

logger = logging.getLogger(__name__)


class YooKassaClient:
    """Client for YooKassa payment processing"""
    
    def __init__(self, shop_id: str, secret_key: str):
        """Initialize YooKassa client
        
        Args:
            shop_id: YooKassa shop ID
            secret_key: YooKassa secret key
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
        """Create payment in YooKassa
        
        Args:
            amount: Payment amount in RUB
            description: Payment description
            return_url: URL to redirect after payment
            metadata: Additional metadata
            
        Returns:
            Payment data with confirmation URL or None if error
        """
        try:
            idempotence_key = str(uuid.uuid4())
            
            payment_data = {
                "amount": {
                    "value": f"{amount:.2f}",
                    "currency": "RUB"
                },
                "confirmation": {
                    "type": "redirect",
                    "return_url": return_url or "https://t.me/AlinaGPTsupp_bot"
                },
                "capture": True,
                "description": description
            }
            
            if metadata:
                payment_data["metadata"] = metadata
            
            payment = Payment.create(payment_data, idempotence_key)
            
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
        """Get payment status from YooKassa
        
        Args:
            payment_id: Payment ID
            
        Returns:
            Payment status or None if error
        """
        try:
            payment = Payment.find_one(payment_id)
            return payment.status
        except Exception as e:
            logger.error(f"Failed to get payment status: {e}")
            return None
    
    def check_payment_succeeded(self, payment_id: str) -> bool:
        """Check if payment was successful
        
        Args:
            payment_id: Payment ID
            
        Returns:
            True if payment succeeded, False otherwise
        """
        status = self.get_payment_status(payment_id)
        return status == "succeeded"
