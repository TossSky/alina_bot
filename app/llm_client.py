# app/llm_client.py
from __future__ import annotations
import asyncio
import os
from typing import List, Dict, Optional
import random
import re

import httpx

from .config import settings
from .prompts import REFUSAL_STYLE

# Базовые дефолты
DEFAULT_TEMPERATURE = 0.92
DEFAULT_MAX_TOKENS = 400

def _format_lists(text: str) -> str:
    """Форматирует нумерованные списки с переносами строк"""
    if not text:
        return text
    
    # Паттерн для поиска нумерованных списков
    # Ищем паттерны вида "1. текст 2. текст" или "1) текст 2) текст"
    patterns = [
        (r'(\d+)\.\s+([^.!?]+?)(?=\s*\d+\.|$)', r'\1. \2'),
        (r'(\d+)\)\s+([^.!?]+?)(?=\s*\d+\)|$)', r'\1) \2'),
    ]
    
    for pattern, replacement in patterns:
        matches = list(re.finditer(pattern, text))
        if matches:
            # Собираем новый текст с переносами
            parts = []
            last_end = 0
            
            for match in matches:
                # Добавляем текст до списка
                if match.start() > last_end:
                    parts.append(text[last_end:match.start()].rstrip())
                
                # Добавляем элемент списка с переносом
                item = match.group(1) + '. ' + match.group(2).strip()
                parts.append('\n' + item)
                last_end = match.end()
            
            # Добавляем остаток текста
            if last_end < len(text):
                remaining = text[last_end:].lstrip()
                if remaining:
                    parts.append('\n' + remaining)
            
            text = ''.join(parts).strip()
            break
    
    # Также обработаем маркированные списки (- или •)
    text = re.sub(r'(?:^|\s)[-•]\s+', '\n• ', text)
    
    return text

def _postprocess(text: str) -> str:
    """Постобработка ответа"""
    if not text:
        return text

    # Убираем префиксы
    t = text.strip()
    for prefix in ("Алина:", "Алина —", "Алина -"):
        if t.startswith(prefix):
            t = t[len(prefix):].strip()
            break

    # Форматируем списки
    t = _format_lists(t)

    # Заменяем Markdown для Telegram
    t = re.sub(r'\*\*(.*?)\*\*', r'*\1*', t)
    
    # Убираем множественные переносы строк
    t = re.sub(r'\n{3,}', '\n\n', t)

    return t.strip()

class LLMClient:
    """Клиент для работы с DeepSeek API"""

    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY") or getattr(settings, "deepseek_api_key", None)
        self.model = getattr(settings, "deepseek_model", "deepseek-chat")
        self._client: Optional[httpx.AsyncClient] = None

        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY не задан в .env файле")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0))
        return self._client

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        *,
        verbosity: Optional[str] = None,  # Оставляем для совместимости
        safety: bool = False,
    ) -> str:
        """Отправляет запрос к DeepSeek API"""
        
        temperature = float(temperature if temperature is not None else DEFAULT_TEMPERATURE)
        if verbosity == "short":
            max_tokens = 150
        else:
            max_tokens = int(max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS)

        if safety:
            messages = [{"role": "system", "content": REFUSAL_STYLE}] + messages

        # Добавляем явное указание про форматирование списков
        messages.append({
            "role": "system", 
            "content": "ВАЖНО: Если пишешь список, ОБЯЗАТЕЛЬНО делай перенос строки после каждого пункта!"
        })

        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": 0.95,
            "frequency_penalty": 0.3,
        }

        client = await self._get_client()
        try:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            txt = data["choices"][0]["message"]["content"]
            return _postprocess(txt)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return "ой, проблемы с ключом API... проверь настройки"
            elif e.response.status_code == 429:
                return "секунду, слишком много сообщений... попробуй чуть позже?"
            else:
                return "что-то с подключением... попробуй ещё раз?"
        except Exception:
            return "ой, что-то связь барахлит... попробуй ещё раз?"

    async def aclose(self):
        """Закрывает HTTP клиент"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None