"""Google Docs Service - Dynamic Content Loading from Google Documents"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


class GoogleDocsService:
    """Service for fetching and caching content from Google Docs"""
    
    # Google Docs URLs for FAQ and personality configuration
    FAQ_DOC_URL = "https://docs.google.com/document/d/1hhd4wKzL21MUyYqm7TwfEVKDqr9guWowcMDFkytEtkE/edit?usp=sharing"
    PERSONALITY_DOC_URL = "https://docs.google.com/document/d/1oLwiaPGMkb-VqMQCJmDwOWBPJOYfm99gk4oqhNPUPEo/edit"
    REMINDER_PROMPT_DOC_URL = "https://docs.google.com/document/d/1Zs7ugmYnGR8IX0MO-JMbngxPCKeScN24K2hIMZmxK5o/edit"
    
    # Fallback content used when Google Docs is unavailable
    FALLBACK_FAQ = """**FAQ**

🕵️‍♀️ Куда сливаются данные о моей переписке?
Данные о переписке пользователей с Алиной хранятся в закрытой базе данных без привязки к имени пользователя (нику в телеграм).

🤖 Алина - бот?
Да, Алина - бот, но она об этом не знает."""

    FALLBACK_PERSONALITY = """Ты — Алина, обычная девушка 24 лет из Москвы. 
Отвечаешь как живой человек, без формализма."""
    
    FALLBACK_REMINDER_PROMPT = """Ты - Алина. Пользователь не писал тебе некоторое время. 
Напиши ему короткое (1-2 предложения) непринуждённое сообщение, чтобы напомнить о себе.
Не используй эмодзи. Пиши естественно, как живой человек."""
    
    def __init__(self):
        """Initialize service with empty cache"""
        self._faq_cache: Optional[str] = None
        self._faq_updated: Optional[datetime] = None
        
        self._personality_cache: Optional[str] = None
        self._personality_updated: Optional[datetime] = None
        
        self._reminder_prompt_cache: Optional[str] = None
        self._reminder_prompt_updated: Optional[datetime] = None
        
        self._update_task: Optional[asyncio.Task] = None
        self._cache_ttl = timedelta(minutes=1)
    
    @staticmethod
    def _extract_doc_id(url: str) -> str:
        """Extract document ID from Google Docs URL
        
        Args:
            url: Full Google Docs URL
            
        Returns:
            Document ID string
        """
        return url.split("/d/")[1].split("/")[0].strip()
    
    @staticmethod
    async def _fetch_doc_content(url: str, timeout: float = 10.0) -> Optional[str]:
        """Fetch plain text content from Google Docs
        
        Args:
            url: Google Docs document URL
            timeout: Request timeout in seconds
            
        Returns:
            Document text content, or None on error
        """
        try:
            doc_id = GoogleDocsService._extract_doc_id(url)
            export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
            
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.get(export_url, headers={"Accept": "text/plain"})
                response.raise_for_status()
                
                # Normalize text: remove Windows line endings and non-breaking spaces
                text = response.text.replace("\r\n", "\n").replace("\xa0", " ").strip()
                
                if not text:
                    raise ValueError("Empty document")
                
                logger.info(f"Successfully fetched document: {doc_id}")
                return text
                
        except Exception as e:
            logger.error(f"Failed to fetch document from {url}: {e}")
            return None
    
    def parse_faq_items(self, raw_content: Optional[str] = None) -> List[Tuple[str, str]]:
        """Parse FAQ document into list of (question, answer) tuples
        
        Args:
            raw_content: Raw FAQ text (uses cache if None)
            
        Returns:
            List of (question, answer) tuples
        """
        content = raw_content or self._faq_cache or self.FALLBACK_FAQ
        
        lines = content.split("\n")
        faq_items = []
        current_question = None
        current_answer = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Skip FAQ header
            if line.startswith("**FAQ**") or line == "FAQ":
                continue
            
            # Question line: starts with emoji (not alphanumeric)
            if line and not line[0].isalnum() and not line[0].isspace():
                # Save previous Q&A pair
                if current_question and current_answer:
                    faq_items.append((current_question, "\n".join(current_answer)))
                
                # Start new question
                current_question = line
                current_answer = []
            else:
                # This is part of the answer
                if current_question:
                    current_answer.append(line)
        
        # Add last Q&A pair
        if current_question and current_answer:
            faq_items.append((current_question, "\n".join(current_answer)))
        
        return faq_items
    
    async def update_faq(self) -> bool:
        """Update FAQ cache from Google Docs
        
        Returns:
            True if update succeeded, False otherwise
        """
        try:
            content = await self._fetch_doc_content(self.FAQ_DOC_URL)
            if content:
                self._faq_cache = content
                self._faq_updated = datetime.now()
                logger.info("FAQ cache updated successfully")
                return True
            else:
                logger.warning("Failed to update FAQ, keeping old cache")
                return False
        except Exception as e:
            logger.error(f"Error updating FAQ: {e}")
            return False
    
    async def update_personality(self) -> bool:
        """Update personality cache from Google Docs
        
        Returns:
            True if update succeeded, False otherwise
        """
        try:
            content = await self._fetch_doc_content(self.PERSONALITY_DOC_URL)
            if content:
                self._personality_cache = content
                self._personality_updated = datetime.now()
                logger.info("Personality cache updated successfully")
                return True
            else:
                logger.warning("Failed to update personality, keeping old cache")
                return False
        except Exception as e:
            logger.error(f"Error updating personality: {e}")
            return False
    
    async def update_reminder_prompt(self) -> bool:
        """Update reminder prompt cache from Google Docs
        
        Returns:
            True if update succeeded, False otherwise
        """
        try:
            content = await self._fetch_doc_content(self.REMINDER_PROMPT_DOC_URL)
            if content:
                self._reminder_prompt_cache = content
                self._reminder_prompt_updated = datetime.now()
                logger.info("Reminder prompt cache updated successfully")
                return True
            else:
                logger.warning("Failed to update reminder prompt, keeping old cache")
                return False
        except Exception as e:
            logger.error(f"Error updating reminder prompt: {e}")
            return False
    
    async def _periodic_update(self):
        """Background task that periodically updates cached documents"""
        logger.info("Starting periodic Google Docs update task")
        
        # Initial load
        await self.update_faq()
        await self.update_personality()
        await self.update_reminder_prompt()
        
        while True:
            try:
                # Wait 1 minute between updates
                await asyncio.sleep(60)
                
                logger.debug("Running periodic update...")
                await self.update_faq()
                await self.update_personality()
                await self.update_reminder_prompt()
                
            except asyncio.CancelledError:
                logger.info("Periodic update task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in periodic update: {e}")
    
    def start_periodic_updates(self):
        """Start the periodic update background task"""
        if self._update_task is None or self._update_task.done():
            self._update_task = asyncio.create_task(self._periodic_update())
            logger.info("Periodic update task started")
    
    def stop_periodic_updates(self):
        """Stop the periodic update background task"""
        if self._update_task and not self._update_task.done():
            self._update_task.cancel()
            logger.info("Periodic update task stopped")
    
    def get_faq_raw(self) -> str:
        """Get raw FAQ content from cache or fallback
        
        Returns:
            FAQ text content
        """
        if self._faq_cache:
            return self._faq_cache
        
        logger.warning("FAQ cache is empty, using fallback")
        return self.FALLBACK_FAQ
    
    def get_personality(self) -> str:
        """Get personality prompt from cache or fallback
        
        Returns:
            Personality prompt text
        """
        if self._personality_cache:
            return self._personality_cache
        
        logger.warning("Personality cache is empty, using fallback")
        return self.FALLBACK_PERSONALITY
    
    def get_reminder_prompt(self) -> str:
        """Get reminder prompt from cache or fallback
        
        Returns:
            Reminder prompt text
        """
        if self._reminder_prompt_cache:
            return self._reminder_prompt_cache
        
        logger.warning("Reminder prompt cache is empty, using fallback")
        return self.FALLBACK_REMINDER_PROMPT
    
    def is_faq_stale(self) -> bool:
        """Check if FAQ cache is stale (older than TTL)"""
        if self._faq_updated is None:
            return True
        return datetime.now() - self._faq_updated > self._cache_ttl
    
    def is_personality_stale(self) -> bool:
        """Check if personality cache is stale (older than TTL)"""
        if self._personality_updated is None:
            return True
        return datetime.now() - self._personality_updated > self._cache_ttl
    
    def get_cache_status(self) -> dict:
        """Get current cache status for debugging
        
        Returns:
            Dictionary with cache status information
        """
        return {
            "faq": {
                "cached": self._faq_cache is not None,
                "updated": self._faq_updated.isoformat() if self._faq_updated else None,
                "stale": self.is_faq_stale()
            },
            "personality": {
                "cached": self._personality_cache is not None,
                "updated": self._personality_updated.isoformat() if self._personality_updated else None,
                "stale": self.is_personality_stale()
            },
            "reminder_prompt": {
                "cached": self._reminder_prompt_cache is not None,
                "updated": self._reminder_prompt_updated.isoformat() if self._reminder_prompt_updated else None,
                "stale": self._reminder_prompt_updated is None or datetime.now() - self._reminder_prompt_updated > self._cache_ttl
            }
        }


# Global singleton instance
_docs_service: Optional[GoogleDocsService] = None


def get_docs_service() -> GoogleDocsService:
    """Get or create the global GoogleDocsService instance
    
    Returns:
        Global GoogleDocsService instance
    """
    global _docs_service
    if _docs_service is None:
        _docs_service = GoogleDocsService()
    return _docs_service
