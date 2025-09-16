# llm.py - Минимальный LLM клиент
"""
Простой клиент: отправка сообщений в модель.
— Использует прокси (обязательно при use_proxy=True)
— Генерация с параметрами temperature, top_p, penalties
— max_tokens не задаём (чтобы не ограничивать длину)
"""

import os
import random
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

        self.base_url = os.getenv("OPENAI_BASE_URL", "").strip() or None

    async def _create_client(self) -> AsyncOpenAI:
        http_client = None
        if self.use_proxy:
            http_client = httpx.AsyncClient(
                proxy=self.proxy_url,
                timeout=httpx.Timeout(60.0, connect=20.0)
            )

        if self.base_url:
            return AsyncOpenAI(api_key=self.api_key, base_url=self.base_url.rstrip("/"), http_client=http_client)

        return AsyncOpenAI(api_key=self.api_key, http_client=http_client)

    def _get_generation_params(self, context: Dict) -> Dict:
        """Подбирает параметры генерации под контекст."""
        base_temp = 0.85 + random.uniform(-0.05, 0.1)  # 0.8–0.95

        is_emotional = context.get("is_emotional", False)
        conversation_length = context.get("conversation_length", 0)

        if is_emotional:
            temperature = min(0.95, base_temp + 0.05)
        elif conversation_length > 20:
            temperature = min(0.9, base_temp + 0.03)
        else:
            temperature = base_temp

        return {
            "temperature": temperature,
            "top_p": 0.95,
            "frequency_penalty": 0.3 + random.uniform(0, 0.2),  # 0.3–0.5
            "presence_penalty": 0.3 + random.uniform(0, 0.2),   # 0.3–0.5
        }

    async def generate_response(self, messages: List[Dict[str, str]], context: Optional[Dict] = None) -> str:
        """Отправляет сообщения в модель и возвращает контент первого ответа."""
        if context is None:
            context = {}

        params = self._get_generation_params(context)

        client = None
        try:
            client = await self._create_client()
            resp = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                **params
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return "ой, кажется, я зависла. повторишь ещё раз?"
        finally:
            if client:
                await client.aclose()
