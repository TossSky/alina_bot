"""LLM Client Module - OpenAI API Integration"""

import base64
import hashlib
import io
import logging
import os
import random
from typing import Dict, List, Optional, Tuple

import httpx
import tiktoken
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# Pricing constants (per 1M tokens)
PRICE_INPUT = 0.00125
PRICE_CACHED = 0.00013
PRICE_OUTPUT = 0.01

# Image token pricing for gpt-5-chat-latest
IMAGE_BASE_TOKENS = 70
IMAGE_TILE_TOKENS = 140


class AlinaLLM:
    """OpenAI API client with token counting and cost tracking"""
    
    def __init__(
        self, 
        api_key: str, 
        model: str = "gpt-5-chat-latest",
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
        """Create async OpenAI client with optional proxy"""
        http_client = None
        if self.use_proxy:
            http_client = httpx.AsyncClient(
                proxy=self.proxy_url,
                timeout=httpx.Timeout(60.0, connect=20.0)
            )
        
        kwargs = {"api_key": self.api_key, "http_client": http_client}
        if self.base_url:
            kwargs["base_url"] = self.base_url.rstrip("/")
        
        return AsyncOpenAI(**kwargs)
    
    def _get_encoder(self):
        """Get tokenizer for the model with caching"""
        if self._encoder is None:
            try:
                self._encoder = tiktoken.encoding_for_model(self.model)
            except Exception:
                self._encoder = tiktoken.get_encoding("cl100k_base")
        return self._encoder
    
    def count_tokens_text(self, text: str) -> int:
        """Count tokens in plain text"""
        return len(self._get_encoder().encode(text or ""))
    
    def count_tokens_messages(self, messages: List[Dict]) -> int:
        """Count tokens in chat messages including images using ChatML format"""
        enc = self._get_encoder()
        total = 0
        
        # ChatML format overhead
        tokens_per_message = 3
        
        for message in messages:
            total += tokens_per_message
            
            content = message.get("content")
            
            # Если контент - просто строка
            if isinstance(content, str):
                total += len(enc.encode(content or ""))
            # Если контент - массив (текст + изображения)
            elif isinstance(content, list):
                for item in content:
                    if item.get("type") == "text":
                        total += len(enc.encode(item.get("text") or ""))
                    elif item.get("type") == "image_url":
                        # Считаем токены для изображения
                        image_url_obj = item.get("image_url", {})
                        if isinstance(image_url_obj, dict):
                            total += self._calculate_image_tokens(image_url_obj.get("url", ""))
                        else:
                            total += self._calculate_image_tokens(image_url_obj)
        
        # Assistant reply overhead
        total += 3
        return total
    
    def _calculate_image_tokens(self, image_url: str) -> int:
        """
        Calculate image tokens for gpt-5-chat-latest
        Based on: base_tokens=70, tile_tokens=140
        
        Для упрощения используем среднее значение ~500 токенов
        Точный расчет требует знания размеров изображения
        """
        # Приблизительная оценка: base + несколько тайлов
        # Для большинства изображений это будет в районе 300-800 токенов
        return IMAGE_BASE_TOKENS + (IMAGE_TILE_TOKENS * 3)  # ~490 tokens
    
    def _get_generation_params(self, context: Optional[Dict] = None) -> Dict:
        """Get generation parameters with some randomness for variety"""
        base_temp = 0.85 + random.uniform(-0.05, 0.1)
        
        if context:
            if context.get("is_emotional"):
                base_temp = min(0.95, base_temp + 0.05)
            elif context.get("conversation_length", 0) > 20:
                base_temp = min(0.9, base_temp + 0.03)
        
        return {
            "temperature": base_temp,
            "top_p": 0.95,
            "frequency_penalty": 0.3 + random.uniform(0, 0.2),
            "presence_penalty": 0.3 + random.uniform(0, 0.2),
        }
    
    async def generate_response(
        self, 
        messages: List[Dict], 
        context: Optional[Dict] = None
    ) -> Tuple[str, int]:
        """
        Generate response from OpenAI API
        
        Returns:
            tuple: (response_text, total_tokens_used)
        """
        params = self._get_generation_params(context)
        client = None
        
        try:
            client = await self._create_client()
            
            # Count input tokens for estimation
            input_tokens = self.count_tokens_messages(messages)
            
            # Make API call with caching
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                prompt_cache_key="alina:system:v1",
                **params
            )
            
            response_text = (response.choices[0].message.content or "").strip()
            output_tokens = self.count_tokens_text(response_text)
            total_tokens = input_tokens + output_tokens
            
            # Log usage details if available
            if hasattr(response, "usage") and response.usage:
                usage = response.usage
                cached = getattr(usage.prompt_tokens_details, "cached_tokens", 0) if hasattr(usage, "prompt_tokens_details") else 0
                
                # Calculate costs
                net_input = input_tokens - cached
                cost_input = net_input * PRICE_INPUT / 1_000_000
                cost_cached = cached * PRICE_CACHED / 1_000_000
                cost_output = output_tokens * PRICE_OUTPUT / 1_000_000
                cost_total = cost_input + cost_cached + cost_output
                
                logger.info(
                    f"Tokens: in={input_tokens} (cached={cached}), out={output_tokens}, "
                    f"total={total_tokens} | Cost: ${cost_total:.6f}"
                )
            
            return response_text, total_tokens
            
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return "ой, кажется, я зависла. повторишь ещё раз?", 0
        finally:
            if client:
                await client.close()


def encode_image_to_base64(image_bytes: bytes) -> str:
    """Encode image bytes to base64 string"""
    return base64.b64encode(image_bytes).decode('utf-8')


def get_image_hash(image_bytes: bytes) -> str:
    """Get SHA256 hash of image for duplicate detection"""
    return hashlib.sha256(image_bytes).hexdigest()


def create_image_message(image_bytes: bytes, text: str = "", is_duplicate: bool = False,
                         mime_type: str = "image/jpeg", detail: str = "auto") -> Dict:
    """
    Create a message with image content in OpenAI Chat Completions format
    
    Args:
        image_bytes: Image data as bytes
        text: Text prompt/caption from user
        is_duplicate: Whether this image was already sent before
        mime_type: MIME type of the image (e.g., "image/jpeg", "image/png")
        detail: Detail level ("low", "high", "auto")
    
    Returns:
        Dict with message in OpenAI format
    """
    base64_image = encode_image_to_base64(image_bytes)
    
    # Если текста нет и это не повтор - пустой текст (система сама сгенерирует реакцию)
    # Если повтор - добавляем контекст
    if not text and is_duplicate:
        text = "[пользователь отправил эту же картинку снова]"
    elif not text:
        text = ""
    
    return {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": text
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{base64_image}",
                    "detail": detail
                }
            }
        ]
    }
