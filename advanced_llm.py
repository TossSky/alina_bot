# fixed_advanced_llm.py - LLM клиент с фокусом на человечность
"""
Упрощенная версия с правильными параметрами для человечных ответов.
Меньше анализа, больше естественности.
"""

import asyncio
import json
import random
from typing import List, Dict, Optional, AsyncGenerator, Any
from datetime import datetime
import httpx
from openai import AsyncOpenAI
import logging
import os

logger = logging.getLogger(__name__)

# ============================================================================
# УПРОЩЕННЫЙ LLM КЛИЕНТ
# ============================================================================

class HumanLikeAlinaLLM:
    """LLM клиент оптимизированный для человечных ответов."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        use_mcp: bool = False,
        sentiment_url: Optional[str] = None,
    ):
        self.api_key = api_key
        self.model = model
        self.sentiment_url = sentiment_url
        
        # Оптимальные параметры для человечности (из исследований)
        self.human_params = {
            "chat": {
                "temperature": 0.9,      # Высокая креативность
                "top_p": 0.95,          # Максимальное разнообразие
                "frequency_penalty": 0.4,  # Умеренный штраф за повторения
                "presence_penalty": 0.4,   # Поощряем новые темы
            },
            "emotional": {
                "temperature": 0.92,
                "top_p": 1.0,
                "frequency_penalty": 0.3,
                "presence_penalty": 0.5,
            },
            "tired": {
                "temperature": 0.85,
                "top_p": 0.9,
                "frequency_penalty": 0.5,
                "presence_penalty": 0.3,
            }
        }
    
    async def _create_client(self) -> AsyncOpenAI:
        """Создаёт клиента OpenAI."""
        base_url = os.getenv("OPENAI_BASE_URL", "").strip()
        api_key = self.api_key or os.getenv("OPENAI_API_KEY", "")
        proxy_url = os.getenv("PROXY_URL", "").strip()

        http_client = None
        if proxy_url:
            http_client = httpx.AsyncClient(
                proxy=proxy_url,
                timeout=httpx.Timeout(30.0, connect=10.0)
            )

        if base_url:
            return AsyncOpenAI(
                api_key=api_key,
                base_url=base_url.rstrip("/"),
                http_client=http_client,
            )

        return AsyncOpenAI(
            api_key=api_key,
            http_client=http_client,
        )
    
    def _get_dynamic_params(self, context: Dict) -> Dict:
        """
        Динамически подстраивает параметры для человечности.
        """
        # Определяем режим
        hour = datetime.now().hour
        if hour >= 22 or hour < 6:
            mode = "tired"
        elif context.get("is_emotional"):
            mode = "emotional"
        else:
            mode = "chat"
        
        params = self.human_params[mode].copy()
        
        # Добавляем небольшую вариативность
        params["temperature"] += random.uniform(-0.03, 0.03)
        params["temperature"] = max(0.85, min(0.95, params["temperature"]))
        
        # Адаптируем длину ответа
        message_length = len(context.get("last_message", ""))
        if message_length < 20:
            params["max_tokens"] = random.randint(100, 200)
        elif message_length > 200:
            params["max_tokens"] = random.randint(200, 350)
        else:
            params["max_tokens"] = random.randint(150, 250)
        
        return params
    
    async def generate_response(
        self,
        messages: List[Dict],
        context: Optional[Dict] = None
    ) -> str:
        """
        Генерирует человечный ответ БЕЗ излишнего анализа.
        """
        if context is None:
            context = {}
        
        # Проверяем на эмоциональность (просто)
        last_message = messages[-1]["content"] if messages else ""
        context["last_message"] = last_message
        context["is_emotional"] = any(
            word in last_message.lower() 
            for word in ["грустно", "плохо", "радость", "счастье", "злюсь", "бесит"]
        )
        
        # Получаем параметры
        params = self._get_dynamic_params(context)
        
        client = None
        try:
            client = await self._create_client()
            
            # Делаем запрос
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                **params
            )
            
            content = response.choices[0].message.content
            
            # Постобработка для естественности
            content = self._humanize_response(content)
            
            return content
            
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            
            # Человечные fallback ответы
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
    
    def _humanize_response(self, text: str) -> str:
        """
        Делает ответ более человечным.
        """
        # Убираем слишком формальные начала
        formal_starts = [
            "Привет! ", "Здравствуй! ", "Добрый день! ",
            "Я понимаю, что ", "Мне кажется, что ",
            "Спасибо за вопрос! ", "Отличный вопрос! "
        ]
        
        for start in formal_starts:
            if text.startswith(start):
                text = text[len(start):]
                # Делаем первую букву строчной
                if text:
                    text = text[0].lower() + text[1:]
                break
        
        # Иногда добавляем многоточие
        if random.random() < 0.15 and text.endswith("."):
            text = text[:-1] + "..."
        
        # Иногда убираем заглавную букву
        if random.random() < 0.25 and text and text[0].isupper():
            # Но не для имён и "Я"
            if not text.startswith(("Я ", "Москв", "Алин", "Настя", "Макс")):
                text = text[0].lower() + text[1:]
        
        return text
    
    async def generate_with_memory(
        self,
        messages: List[Dict],
        user_memory: Dict,
        context: Dict
    ) -> str:
        """
        Генерирует ответ с учётом памяти о пользователе.
        """
        # Если есть память, добавляем её мягко в контекст
        if user_memory:
            memory_context = []
            if "name" in user_memory:
                memory_context.append(f"(помнишь, что собеседника зовут {user_memory['name']})")
            if "pet" in user_memory:
                memory_context.append(f"(у собеседника есть {user_memory['pet']})")
            
            if memory_context:
                # Добавляем в системное сообщение
                if messages and messages[0]["role"] == "system":
                    messages[0]["content"] += "\n" + " ".join(memory_context)
        
        return await self.generate_response(messages, context)
    
    async def analyze_for_memory(self, message: str) -> Optional[Dict]:
        """
        Простой анализ для запоминания важной информации.
        НЕ используем structured output для этого!
        """
        message_lower = message.lower()
        
        # Простые паттерны для определения что запомнить
        if "меня зовут" in message_lower or "я -" in message_lower:
            # Пытаемся найти имя
            words = message.split()
            for i, word in enumerate(words):
                if word.lower() in ["зовут", "-"] and i + 1 < len(words):
                    potential_name = words[i + 1].strip(".,!?")
                    if len(potential_name) > 1 and potential_name[0].isupper():
                        return {"key": "name", "value": potential_name}
        
        if "у меня есть кот" in message_lower or "моего кота зовут" in message_lower:
            return {"key": "pet", "value": "кот"}
        
        if "у меня есть собака" in message_lower or "мою собаку зовут" in message_lower:
            return {"key": "pet", "value": "собака"}
        
        if "работаю" in message_lower:
            # Простое определение работы
            work_keywords = ["программист", "дизайнер", "менеджер", "учитель", "врач", "юрист"]
            for keyword in work_keywords:
                if keyword in message_lower:
                    return {"key": "work", "value": keyword}
        
        return None
    
    async def get_simple_sentiment(self, text: str) -> str:
        """
        Простое определение настроения БЕЗ внешних сервисов.
        """
        text_lower = text.lower()
        
        # Негативные эмоции
        if any(word in text_lower for word in ["грустно", "плохо", "устал", "одиноко", "печально"]):
            return "sad"
        
        # Позитивные эмоции
        if any(word in text_lower for word in ["радость", "счастье", "круто", "супер", "ура"]):
            return "happy"
        
        # Злость
        if any(word in text_lower for word in ["злюсь", "бесит", "ненавижу", "достало"]):
            return "angry"
        
        return "neutral"
    
    async def stream_response(
        self,
        messages: List[Dict],
        context: Optional[Dict] = None
    ) -> AsyncGenerator[str, None]:
        """
        Стриминг ответа для длинных сообщений.
        """
        if context is None:
            context = {}
        
        params = self._get_dynamic_params(context)
        
        client = None
        try:
            client = await self._create_client()
            
            stream = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                **params
            )
            
            full_response = ""
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_response += content
                    yield content
            
            # В конце можем добавить человечности
            if random.random() < 0.1:
                ending = random.choice(["", ")", "...", " 😊"])
                if ending and not full_response.endswith((".", "!", "?", ")", "...")):
                    yield ending
                    
        except Exception as e:
            logger.error(f"Error streaming response: {e}")
            yield "ой, что-то пошло не так..."
        finally:
            if client:
                await client.close()

# ============================================================================
# ФУНКЦИИ-ХЕЛПЕРЫ
# ============================================================================

def should_use_functions(message: str) -> bool:
    """
    Определяет, нужно ли использовать функции.
    Используем их РЕДКО, только когда действительно нужно.
    """
    triggers = [
        "запомни",
        "сколько времени",
        "который час",
        "какая погода"
    ]
    
    message_lower = message.lower()
    return any(trigger in message_lower for trigger in triggers)

def extract_memory_from_response(response: str) -> Optional[Dict]:
    """
    Извлекает информацию для запоминания из ответа.
    """
    # Если Алина говорит "запомню" или "буду помнить"
    if "запомню" in response.lower() or "буду помнить" in response.lower():
        # Простая эвристика для определения что запомнить
        return {"action": "remember", "content": response}
    
    return None

# ============================================================================
# ЭКСПОРТ
# ============================================================================

# Для обратной совместимости
AdvancedAlinaLLM = HumanLikeAlinaLLM