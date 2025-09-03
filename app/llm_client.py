# app/llm_client.py
from __future__ import annotations
import asyncio
import os
import sys
import traceback
from typing import List, Dict, Optional
import random
import re

import httpx

from .config import settings
from .prompts import REFUSAL_STYLE

# Базовые дефолты
DEFAULT_TEMPERATURE = 0.92
DEFAULT_MAX_TOKENS = 600  # Увеличено с 400 для длинных ответов

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
            # Увеличиваем timeout для длинных ответов
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))
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
        
        # Адаптивный max_tokens в зависимости от контекста
        if verbosity == "short":
            max_tokens = 200
        elif max_tokens is None:
            # Если в сообщении упоминаются числа больше 10, увеличиваем лимит
            last_msg = messages[-1].get("content", "")
            if any(word in last_msg.lower() for word in ["20", "15", "10", "много", "несколько", "факт"]):
                max_tokens = 1200  # Больший лимит для списков
            else:
                max_tokens = DEFAULT_MAX_TOKENS
        else:
            max_tokens = int(max_tokens)

        if safety:
            messages = [{"role": "system", "content": REFUSAL_STYLE}] + messages

        # Добавляем явное указание про форматирование списков
        messages.append({
            "role": "system", 
            "content": "ВАЖНО: Если пишешь список, ОБЯЗАТЕЛЬНО делай перенос строки после каждого пункта! Но помни - максимум 5 пунктов, даже если просили больше."
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

        # Отладочный вывод
        print(f"[LLM] Запрос с max_tokens={max_tokens}, температура={temperature}")
        
        client = await self._get_client()
        try:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            
            # Проверяем, есть ли finish_reason
            choice = data.get("choices", [{}])[0]
            finish_reason = choice.get("finish_reason")
            
            if finish_reason == "length":
                print(f"[LLM] ВНИМАНИЕ: Ответ обрезан из-за лимита токенов (max_tokens={max_tokens})")
                
            txt = choice.get("message", {}).get("content", "")
            
            # Отладка длины ответа
            print(f"[LLM] Получен ответ: {len(txt)} символов")
            
            return _postprocess(txt)
            
        except httpx.HTTPStatusError as e:
            print(f"[LLM] HTTP ошибка {e.response.status_code}: {e.response.text}", file=sys.stderr)
            
            if e.response.status_code == 401:
                return "ой, проблемы с ключом API... проверь настройки"
            elif e.response.status_code == 429:
                return "секунду, слишком много сообщений... попробуй чуть позже?"
            elif e.response.status_code == 400:
                # Возможно, слишком длинный запрос
                error_detail = e.response.text
                print(f"[LLM] Детали ошибки 400: {error_detail}", file=sys.stderr)
                return "хм, что-то сложновато... давай попроще?"
            else:
                return "что-то с подключением... попробуй ещё раз?"
                
        except httpx.TimeoutException as e:
            print(f"[LLM] Timeout ошибка: {e}", file=sys.stderr)
            return "ответ занимает слишком много времени... может, попроще спросить?"
            
        except Exception as e:
            # Полный traceback для отладки
            print(f"[LLM] Неожиданная ошибка: {e}", file=sys.stderr)
            traceback.print_exc()
            return "ой, что-то связь барахлит... попробуй ещё раз?"

    async def aclose(self):
        """Закрывает HTTP клиент"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None