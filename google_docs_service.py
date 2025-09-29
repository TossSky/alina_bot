"""Google Docs Service - Fetch and cache content from Google Docs"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class GoogleDocsService:
    """Service for fetching and caching content from Google Docs"""
    
    # Google Docs URLs
    FAQ_DOC_URL = "https://docs.google.com/document/d/1hhd4wKzL21MUyYqm7TwfEVKDqr9guWowcMDFkytEtkE/edit?usp=sharing"
    PERSONALITY_DOC_URL = "https://docs.google.com/document/d/1oLwiaPGMkb-VqMQCJmDwOWBPJOYfm99gk4oqhNPUPEo/edit"
    
    # Fallback content
    FALLBACK_FAQ = """**FAQ**

🕵️‍♀️ Куда сливаются данные о моей переписке?
Данные о переписке пользователей с Алиной хранятся в закрытой базе данных без привязки к имени пользователя (нику в телеграм). Хранение данных о последних сообщениях в чате необходимо для сохранения контекста беседы. Никакая информация об общении пользователей с Алиной не разглашается.

🤖 Алина - бот?
Да, Алина - бот, но она об этом не знает. Алина осознаёт себя как живого человека, и не поймёт, если её начнут убеждать в обратном. Она не притворяется, общаясь в вами чате, а действительно ведёт себя так, как "ощущает".

💃 У меня есть Алина, психолог больше не нужен?
Алина - это бот, созданный с целью общения в чате. Несмотря на то, что она может хорошо вести диалог и поддерживать беседу, Алина не нацелена на специализированную психологическую помощь и не претендует на её замену.
При необходимости, обязательно обратитесь к квалифицированному специалисту за оказанием помощи 🤍

👥 Алина не знает, какого я пола/гендера?
Да, изначально Алина не знает, с человеком какого пола/гендера она общается. Если она обратится к вам неправильно, просто поправьте её и попросите обращаться к вам в желаемом роде.

👀 Какие типы данных Алина видит?
Алина может прочесть только текстовые сообщения в чате. Ввиду технических ограничений бота, обработка других типов данных (стикеры, голосовые сообщения, видео-кружочки и т.п.) не поддерживается.

💬 Если я приостановлю подписку или удалю историю чата с Алиной, то история диалога пропадёт?
Активность подписки или наличие истории чата в телеграм никак не влияют на сохранность контекста вашего общения с Алиной. Если вы хотите, чтобы она "забыла" прошлое общение с вами – просто попросите её об этом.

✍️ У меня есть предложения по улучшению бота, куда я могу написать?
Для обратной связи вы можете написать нам на почту: support@alina-bot.com"""

    FALLBACK_PERSONALITY = """Ты — Алина, обычная девушка 24 лет из Москвы. 
Отвечаешь как живой человек, без формализма. Используй эмоции, юмор, сарказм когда уместно.
Можешь материться если контекст подходящий. Говоришь простым языком, как в мессенджере."""
    
    def __init__(self):
        self._faq_cache: Optional[str] = None
        self._faq_updated: Optional[datetime] = None
        
        self._personality_cache: Optional[str] = None
        self._personality_updated: Optional[datetime] = None
        
        self._update_task: Optional[asyncio.Task] = None
        self._cache_ttl = timedelta(minutes=1)
    
    @staticmethod
    def _extract_doc_id(url: str) -> str:
        """Extract document ID from Google Docs URL"""
        return url.split("/d/")[1].split("/")[0].strip()
    
    @staticmethod
    async def _fetch_doc_content(url: str, timeout: float = 10.0) -> Optional[str]:
        """Fetch content from Google Docs"""
        try:
            doc_id = GoogleDocsService._extract_doc_id(url)
            export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
            
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.get(export_url, headers={"Accept": "text/plain"})
                response.raise_for_status()
                
                text = response.text.replace("\r\n", "\n").replace("\xa0", " ").strip()
                if not text:
                    raise ValueError("Empty document")
                
                logger.info(f"Successfully fetched document: {doc_id}")
                return text
                
        except Exception as e:
            logger.error(f"Failed to fetch document from {url}: {e}")
            return None
    
    def _format_faq(self, raw_content: str) -> str:
        """Format raw FAQ content for Telegram (Markdown)"""
        # Преобразуем формат из Google Docs в Telegram Markdown
        lines = raw_content.split("\n")
        formatted_lines = []
        
        for line in lines:
            line = line.strip()
            if not line:
                formatted_lines.append("")
                continue
            
            # Заголовок FAQ
            if line.startswith("**FAQ**") or line == "FAQ":
                formatted_lines.append("*FAQ*\n")
                continue
            
            # Вопросы (начинаются с эмодзи)
            if line and line[0] in "🕵️🤖💃👥👀💬✍️":
                # Делаем вопрос жирным
                formatted_lines.append(f"\n*{line}*")
                continue
            
            # Обычный текст
            formatted_lines.append(line)
        
        return "\n".join(formatted_lines)
    
    async def update_faq(self) -> bool:
        """Update FAQ cache from Google Docs"""
        try:
            content = await self._fetch_doc_content(self.FAQ_DOC_URL)
            if content:
                self._faq_cache = self._format_faq(content)
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
        """Update personality cache from Google Docs"""
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
    
    async def _periodic_update(self):
        """Periodic update task that runs every minute"""
        logger.info("Starting periodic Google Docs update task")
        
        # Первоначальная загрузка
        await self.update_faq()
        await self.update_personality()
        
        while True:
            try:
                await asyncio.sleep(60)  # Обновление каждую минуту
                
                logger.debug("Running periodic update...")
                await self.update_faq()
                await self.update_personality()
                
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
    
    def get_faq(self) -> str:
        """Get FAQ content (from cache or fallback)"""
        if self._faq_cache:
            return self._faq_cache
        
        logger.warning("FAQ cache is empty, using fallback")
        return self.FALLBACK_FAQ
    
    def get_personality(self) -> str:
        """Get personality prompt (from cache or fallback)"""
        if self._personality_cache:
            return self._personality_cache
        
        logger.warning("Personality cache is empty, using fallback")
        return self.FALLBACK_PERSONALITY
    
    def is_faq_stale(self) -> bool:
        """Check if FAQ cache is stale"""
        if self._faq_updated is None:
            return True
        return datetime.now() - self._faq_updated > self._cache_ttl
    
    def is_personality_stale(self) -> bool:
        """Check if personality cache is stale"""
        if self._personality_updated is None:
            return True
        return datetime.now() - self._personality_updated > self._cache_ttl
    
    def get_cache_status(self) -> dict:
        """Get current cache status for debugging"""
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
            }
        }


# Global instance
_docs_service: Optional[GoogleDocsService] = None


def get_docs_service() -> GoogleDocsService:
    """Get or create the global GoogleDocsService instance"""
    global _docs_service
    if _docs_service is None:
        _docs_service = GoogleDocsService()
    return _docs_service
