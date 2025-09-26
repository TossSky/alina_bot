# llm.py - LLM клиент с поддержкой токенов
"""
Клиент для работы с OpenAI API.
Поддерживает прокси, подсчет токенов и кеширование.
"""

import os
import random
import logging
from typing import List, Dict, Optional, Tuple

import tiktoken
import httpx
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# Тарифы OpenAI ($ за 1M токенов) для gpt-4o-mini
PRICE_INPUT = 0.00125      # обычный input
PRICE_CACHED = 0.00013     # cached input  
PRICE_OUTPUT = 0.01        # output


class AlinaLLM:
    """Клиент для работы с языковой моделью."""
    
    def __init__(
        self, 
        api_key: str, 
        model: str = "gpt-4o-mini",
        use_proxy: bool = True,
        proxy_url: Optional[str] = None
    ):
        if not api_key:
            raise ValueError("API key is required")
        if use_proxy and not proxy_url:
            raise ValueError("Proxy URL is required when use_proxy=True")
        
        self.api_key = api_key
        self.model = model
        self.use_proxy = use_proxy
        self.proxy_url = proxy_url
        self.base_url = os.getenv("OPENAI_BASE_URL", "").strip() or None
        self._encoder = None
    
    async def _create_client(self) -> AsyncOpenAI:
        """Создает клиент OpenAI с настройками прокси."""
        http_client = None
        if self.use_proxy:
            http_client = httpx.AsyncClient(
                proxy=self.proxy_url,
                timeout=httpx.Timeout(60.0, connect=20.0)
            )
        
        if self.base_url:
            return AsyncOpenAI(
                api_key=self.api_key, 
                base_url=self.base_url.rstrip("/"),
                http_client=http_client
            )
        
        return AsyncOpenAI(api_key=self.api_key, http_client=http_client)
    
    def _get_generation_params(self, context: Optional[Dict] = None) -> Dict:
        """Возвращает параметры для генерации с учетом контекста."""
        base_temp = 0.85 + random.uniform(-0.05, 0.1)
        
        if context:
            is_emotional = context.get("is_emotional", False)
            conversation_length = context.get("conversation_length", 0)
            
            if is_emotional:
                base_temp = min(0.95, base_temp + 0.05)
            elif conversation_length > 20:
                base_temp = min(0.9, base_temp + 0.03)
        
        return {
            "temperature": base_temp,
            "top_p": 0.95,
            "frequency_penalty": 0.3 + random.uniform(0, 0.2),
            "presence_penalty": 0.3 + random.uniform(0, 0.2),
        }
    
    def _get_encoder(self) -> tiktoken.Encoding:
        """Получает энкодер для подсчета токенов."""
        if not self._encoder:
            try:
                self._encoder = tiktoken.encoding_for_model(self.model)
            except Exception:
                self._encoder = tiktoken.get_encoding("cl100k_base")
        return self._encoder
    
    def count_tokens_text(self, text: str) -> int:
        """Считает количество токенов в тексте."""
        enc = self._get_encoder()
        return len(enc.encode(text or ""))
    
    def count_tokens_messages(self, messages: List[Dict[str, str]]) -> int:
        """
        Считает токены для списка сообщений.
        Использует схему ChatML с учетом служебных токенов.
        """
        enc = self._get_encoder()
        tokens_per_message = 3  # <|im_start|>role\n{content}<|im_end|>\n
        tokens_per_name = 1
        
        total = 0
        for message in messages:
            total += tokens_per_message
            total += len(enc.encode(message.get("content") or ""))
            if message.get("name"):
                total += tokens_per_name
        
        total += 3  # <|im_start|>assistant
        return total
    
    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        context: Optional[Dict] = None
    ) -> Tuple[str, int]:
        """
        Генерирует ответ на основе сообщений.
        
        Returns:
            Tuple[str, int]: (текст ответа, общее количество токенов)
        """
        params = self._get_generation_params(context)
        
        # Подсчет входных токенов
        input_tokens = self.count_tokens_messages(messages)
        
        client = None
        try:
            client = await self._create_client()
            
            # Запрос к API с кешированием системного промпта
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                prompt_cache_key="alina:system:v1",
                **params
            )
            
            response_text = (response.choices[0].message.content or "").strip()
            output_tokens = self.count_tokens_text(response_text)
            total_tokens = input_tokens + output_tokens
            
            # Логирование использования API
            usage = getattr(response, "usage", None)
            if usage:
                cached = getattr(usage.prompt_tokens_details, "cached_tokens", 0)
                self._log_usage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cached_tokens=cached,
                    total_tokens=total_tokens
                )
            else:
                logger.info(f"Token usage: input={input_tokens}, output={output_tokens}, total={total_tokens}")
            
            return response_text, total_tokens
            
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return "ой, кажется, я зависла. повторишь ещё раз?", 0
            
        finally:
            if client:
                await client.close()
    
    def _log_usage(self, input_tokens: int, output_tokens: int, cached_tokens: int, total_tokens: int):
        """Логирует использование API с расчетом стоимости."""
        net_input = input_tokens - cached_tokens
        
        cost_input = net_input * PRICE_INPUT / 1_000_000
        cost_cached = cached_tokens * PRICE_CACHED / 1_000_000
        cost_output = output_tokens * PRICE_OUTPUT / 1_000_000
        cost_total = cost_input + cost_cached + cost_output
        
        logger.info(
            f"Token usage: input={input_tokens} (cached={cached_tokens}), "
            f"output={output_tokens}, total={total_tokens} | "
            f"cost: ${cost_total:.6f} (in=${cost_input:.6f}, cached=${cost_cached:.6f}, out=${cost_output:.6f})"
        )
