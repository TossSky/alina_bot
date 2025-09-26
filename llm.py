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
import tiktoken

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

    def _get_encoder(self):
        """Подбираем энкодер для модели; fallback на cl100k_base."""
        try:
            return tiktoken.encoding_for_model(self.model)
        except Exception:
            return tiktoken.get_encoding("cl100k_base")

    def count_tokens_text(self, text: str) -> int:
        enc = self._get_encoder()
        return len(enc.encode(text or ""))

    def count_tokens_messages(self, messages: List[Dict[str, str]]) -> int:
        """
        Приближённый подсчёт токенов для chat-комплишнов по схеме ChatML.
        Берём параметры как в OpenAI Cookbook (актуально для gpt-3.5/4/4o),
        что хорошо приближает и 4o/5-семейства:
        - tokens_per_message = 3
        - tokens_per_name    = 1
        """
        enc = self._get_encoder()
        tokens_per_message = 3
        tokens_per_name = 1

        total = 0
        for m in messages:
            total += tokens_per_message
            total += len(enc.encode(m.get("content") or ""))
            # role обычно не кодируется в контент, но ChatML включает метаданную токенизацию
            # добавим 1 токен, если есть name (на будущее)
            if m.get("name"):
                total += tokens_per_name
        # плюс токены на завершающий примаркер assistant'а
        total += 3
        return total

    
    async def generate_response(self, messages: List[Dict[str, str]], context: Optional[Dict] = None) -> tuple[str, int]:
        """Отправляет сообщения в модель и возвращает ответ и количество токенов.
        
        Returns:
            tuple: (текст ответа, количество использованных токенов)
        """
        if context is None:
            context = {}

        params = self._get_generation_params(context)

        client = None
        try:
            client = await self._create_client()
            
            # Подсчитываем токены во входных сообщениях
            input_tokens = self.count_tokens_messages(messages)
            
            resp = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                **params
            )
            
            response_text = (resp.choices[0].message.content or "").strip()
            
            # Подсчитываем токены в ответе
            output_tokens = self.count_tokens_text(response_text)
            total_tokens = input_tokens + output_tokens
            
            # Логируем использование токенов
            logger.info(f"Token usage: input={input_tokens}, output={output_tokens}, total={total_tokens}")
            
            return response_text, total_tokens
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return "ой, кажется, я зависла. повторишь ещё раз?", 0
        finally:
            if client:
                await client.close()
