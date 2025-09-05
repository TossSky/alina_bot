# llm.py - Оптимизированный клиент для работы с OpenAI API
"""
Клиент настроен специально для создания человекоподобных ответов.
Использует динамические параметры в зависимости от контекста.
"""

import asyncio
import random
from typing import List, Dict, Optional
import httpx
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion
import logging

logger = logging.getLogger(__name__)


class AlinaLLM:
    """
    Специализированный клиент для генерации человекоподобных ответов Алины.
    """
    
    def __init__(self, api_key: str, model: str = "gpt-4o-mini", use_proxy: bool = False, proxy_url: str = None):
        self.api_key = api_key
        self.model = model
        self.use_proxy = use_proxy
        self.proxy_url = proxy_url
        
        # Базовые параметры для человекоподобности
        self.base_params = {
            "temperature": 0.8,      # Оптимальный баланс креативности
            "top_p": 1.0,           # Не ограничиваем, используем temperature
            "frequency_penalty": 0.4, # Лёгкий штраф за повторения
            "presence_penalty": 0.4,  # Поощряем новые темы
        }
    
    async def _create_client(self) -> AsyncOpenAI:
        """Создаёт клиент с правильными настройками."""
        if self.use_proxy and self.proxy_url:
            http_client = httpx.AsyncClient(
                proxy=self.proxy_url,
                timeout=httpx.Timeout(30.0, connect=10.0)
            )
            return AsyncOpenAI(api_key=self.api_key, http_client=http_client)
        else:
            return AsyncOpenAI(api_key=self.api_key)
    
    def _get_dynamic_params(self, context: Dict[str, any]) -> Dict[str, any]:
        """
        Динамически подстраивает параметры под контекст разговора.
        """
        params = self.base_params.copy()
        
        # Анализируем контекст
        message_length = len(context.get("last_message", ""))
        conversation_length = context.get("conversation_length", 0)
        is_emotional = context.get("is_emotional", False)
        is_question = context.get("is_question", False)
        
        # Адаптируем temperature
        if is_emotional:
            params["temperature"] = 0.9  # Больше эмпатии и вариативности
        elif conversation_length > 10:
            params["temperature"] = 0.85  # Немного больше разнообразия в длинных диалогах
        
        # Адаптируем max_tokens
        if message_length < 20:
            params["max_tokens"] = 150  # Короткий вопрос - короткий ответ
        elif message_length > 200:
            params["max_tokens"] = 400  # Длинное сообщение - можно ответить подробнее
        else:
            params["max_tokens"] = 250  # Стандартный ответ
        
        # Адаптируем penalties для избежания повторений в длинных диалогах
        if conversation_length > 20:
            params["frequency_penalty"] = 0.6
            params["presence_penalty"] = 0.5
        
        # Добавляем немного рандома для непредсказуемости
        params["temperature"] += random.uniform(-0.05, 0.05)
        params["temperature"] = max(0.7, min(1.0, params["temperature"]))
        
        logger.debug(f"Dynamic params: {params}")
        return params
    
    async def generate_response(
        self, 
        messages: List[Dict[str, str]], 
        context: Optional[Dict[str, any]] = None
    ) -> str:
        """
        Генерирует ответ Алины с учётом контекста.
        
        Args:
            messages: История сообщений
            context: Дополнительный контекст (длина диалога, эмоциональность и т.д.)
        
        Returns:
            Сгенерированный ответ
        """
        if context is None:
            context = {}
        
        # Получаем динамические параметры
        params = self._get_dynamic_params(context)
        
        client = None
        try:
            client = await self._create_client()
            
            # Делаем запрос к API
            response: ChatCompletion = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                **params
            )
            
            # Извлекаем ответ
            content = response.choices[0].message.content
            
            # Постобработка для большей естественности
            content = self._postprocess_response(content)
            
            return content
            
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            # Возвращаем человечный фоллбек
            fallbacks = [
                "ой, что-то я задумалась... что ты говорил?",
                "секунду, кот отвлёк... можешь повторить?",
                "блин, интернет тупит( давай ещё раз",
                "сорри, не поняла.. ещё раз можно?"
            ]
            return random.choice(fallbacks)
            
        finally:
            if client:
                await client.close()
    
    def _postprocess_response(self, text: str) -> str:
        """
        Постобработка ответа для большей естественности.
        """
        # Убираем слишком формальные начала если они есть
        formal_starts = [
            "Привет! ", "Здравствуй! ", "Добрый день! ",
            "Я понимаю, что ", "Мне кажется, что "
        ]
        
        for start in formal_starts:
            if text.startswith(start):
                text = text[len(start):].lower()
                break
        
        # Иногда добавляем многоточие вместо точки для естественности
        if random.random() < 0.2 and text.endswith("."):
            text = text[:-1] + "..."
        
        # Иногда убираем заглавную букву в начале (как в мессенджерах)
        if random.random() < 0.3 and text and text[0].isupper():
            text = text[0].lower() + text[1:]
        
        return text
    
    def analyze_context(self, user_message: str, history_length: int) -> Dict[str, any]:
        """
        Анализирует контекст для подстройки параметров.
        """
        context = {
            "last_message": user_message,
            "conversation_length": history_length,
            "is_emotional": False,
            "is_question": False,
        }
        
        # Проверяем на эмоциональность
        emotional_markers = [
            "грустн", "плох", "одинок", "устал", "тоск",
            "радост", "счаст", "весел", "круто", "класс",
            "злюсь", "бесит", "ненавиж", "достал"
        ]
        
        message_lower = user_message.lower()
        for marker in emotional_markers:
            if marker in message_lower:
                context["is_emotional"] = True
                break
        
        # Проверяем, является ли сообщение вопросом
        if "?" in user_message or any(q in message_lower for q in ["что", "как", "где", "когда", "почему", "зачем"]):
            context["is_question"] = True
        
        return context