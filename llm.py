# llm.py - Минимальный LLM клиент
"""
Простой клиент: отправка сообщений в модель.
— Без ограничений длины ответа (max_tokens не задаётся)
— Без рандома и постобработки
— Прокси обязателен
"""

import os
import logging
from typing import List, Dict, Optional

import httpx
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class AlinaLLM:
    def __init__(self, api_key: str, model: str = "gpt-4o-mini", use_proxy: bool = True, proxy_url: Optional[str] = None):
        if not api_key:
            raise ValueError("AlinaLLM: api_key is required")
        if use_proxy and not proxy_url:
            raise ValueError("AlinaLLM: proxy_url is required when use_proxy=True")

        self.api_key = api_key
        self.model = model
        self.use_proxy = use_proxy
        self.proxy_url = proxy_url

        # Поддержка кастомного base_url (например, OpenRouter)
        self.base_url = os.getenv("OPENAI_BASE_URL", "").strip() or None

    async def _create_client(self) -> AsyncOpenAI:
        http_client = None
        if self.use_proxy:
            http_client = httpx.AsyncClient(
                proxy=self.proxy_url,  # прокси обязателен
                timeout=httpx.Timeout(60.0, connect=20.0)
            )

        if self.base_url:
            return AsyncOpenAI(api_key=self.api_key, base_url=self.base_url.rstrip("/"), http_client=http_client)

        return AsyncOpenAI(api_key=self.api_key, http_client=http_client)

    async def generate_response(self, messages: List[Dict[str, str]], context: Optional[Dict] = None) -> str:
        """
        Отправляет сообщения в модель и возвращает контент первого ответа.
        context оставлен для совместимости, но не используется.
        """
        client = None
        try:
            client = await self._create_client()
            resp = await client.chat.completions.create(
                model=self.model,
                messages=messages
                # ВАЖНО: max_tokens НЕ задаём — модель отвечает полной длиной в рамках лимита модели
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return "ой, кажется, я зависла. повторишь ещё раз?"
        finally:
            if client:
                await client.close()
