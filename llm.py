# llm.py - Оптимизированный LLM клиент
"""
Упрощенный клиент для естественной генерации.
Фокус на качестве, а не на сложности.
"""

import asyncio
import random
import os
from typing import List, Dict, Optional
import httpx
from openai import AsyncOpenAI
import logging

logger = logging.getLogger(__name__)


class AlinaLLM:
    """Простой но эффективный клиент для Алины."""
    
    def __init__(self, api_key: str, model: str = "gpt-4o-mini", use_proxy: bool = False, proxy_url: str = None):
        self.api_key = api_key
        self.model = model
        self.use_proxy = use_proxy
        self.proxy_url = proxy_url
    
    async def _create_client(self) -> AsyncOpenAI:
        """Создает клиент с учетом прокси и кастомных URL."""
        # Поддержка кастомных API endpoints (OpenRouter, Together, etc)
        base_url = os.getenv("OPENAI_BASE_URL", "").strip()
        
        # Настройка прокси если нужно
        http_client = None
        if self.use_proxy and self.proxy_url:
            http_client = httpx.AsyncClient(
                proxy=self.proxy_url,
                timeout=httpx.Timeout(30.0, connect=10.0)
            )
        
        # Создаем клиент
        if base_url:
            return AsyncOpenAI(
                api_key=self.api_key,
                base_url=base_url.rstrip("/"),
                http_client=http_client
            )
        
        return AsyncOpenAI(
            api_key=self.api_key,
            http_client=http_client
        )
    
    def _get_generation_params(self, context: Dict) -> Dict:
        """
        Динамические параметры для естественности.
        Упрощенная версия - меньше логики, больше рандома.
        """
        # Базовая температура для человечности
        base_temp = 0.85 + random.uniform(-0.05, 0.1)  # 0.8-0.95
        
        # Модификация по контексту
        is_emotional = context.get("is_emotional", False)
        message_length = len(context.get("last_message", ""))
        conversation_length = context.get("conversation_length", 0)
        
        # Температура
        if is_emotional:
            temperature = min(0.95, base_temp + 0.05)
        elif conversation_length > 20:
            temperature = min(0.9, base_temp + 0.03)
        else:
            temperature = base_temp
        
        # Длина ответа
        if message_length < 20:
            max_tokens = random.randint(50, 150)
        elif message_length > 150:
            max_tokens = random.randint(150, 300)
        else:
            max_tokens = random.randint(80, 200)
        
        return {
            "temperature": temperature,
            "top_p": 0.95,  # Немного ограничиваем для связности
            "frequency_penalty": 0.3 + random.uniform(0, 0.2),  # 0.3-0.5
            "presence_penalty": 0.3 + random.uniform(0, 0.2),   # 0.3-0.5
            "max_tokens": max_tokens
        }
    
    async def generate_response(self, messages: List[Dict], context: Optional[Dict] = None) -> str:
        """
        Генерирует ответ Алины.
        Упрощенная версия без лишней логики.
        """
        if context is None:
            context = {}
        
        params = self._get_generation_params(context)
        
        client = None
        try:
            client = await self._create_client()
            
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                **params
            )
            
            content = response.choices[0].message.content
            
            # Легкая постобработка
            content = self._postprocess(content, context)
            
            return content
            
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            
            # Человечные фоллбеки
            fallbacks = [
                "блин, что-то туплю... что ты написал?",
                "ой сорри, отвлеклась. можешь повторить?",
                "секунду, кот на клаве... что там было?",
                "не поняла, давай еще раз"
            ]
            return random.choice(fallbacks)
            
        finally:
            if client:
                await client.close()
    
    def _postprocess(self, text: str, context: Dict) -> str:
        """
        Минимальная постобработка для естественности.
        Не перебарщиваем с модификациями.
        """
        # Убираем слишком формальные начала
        formal_starts = [
            "Привет! ", "Здравствуйте! ", "Добрый день! ",
            "Я понимаю, ", "Мне кажется, ", "Хочу сказать, "
        ]
        
        for start in formal_starts:
            if text.startswith(start):
                text = text[len(start):]
                if text and text[0].isupper():
                    text = text[0].lower() + text[1:]
                break
        
        # Иногда убираем заглавную букву (30% шанс)
        if random.random() < 0.3 and text and text[0].isupper():
            text = text[0].lower() + text[1:]
        
        # Иногда меняем точку на многоточие (15% шанс)
        if random.random() < 0.15 and text.endswith("."):
            text = text[:-1] + "..."
        
        # Убираем двойные пробелы
        text = " ".join(text.split())
        
        return text
    
    def analyze_context(self, message: str, history_length: int) -> Dict:
        """
        Простой анализ контекста.
        Без оверинжиниринга.
        """
        context = {
            "last_message": message,
            "conversation_length": history_length,
            "is_emotional": False,
            "is_question": False,
        }
        
        message_lower = message.lower()
        
        # Эмоциональность
        emotional_words = [
            "грустн", "плох", "одинок", "устал", "тоск", "скучн",
            "радост", "счаст", "весел", "круто", "класс", "супер",
            "злюсь", "бесит", "ненавиж", "достал", "надоел"
        ]
        
        for word in emotional_words:
            if word in message_lower:
                context["is_emotional"] = True
                break
        
        # Вопрос
        if "?" in message or any(q in message_lower for q in ["что", "как", "где", "когда", "почему"]):
            context["is_question"] = True
        
        return context
