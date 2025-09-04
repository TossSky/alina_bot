# app/llm_client.py
from __future__ import annotations
import asyncio
import sys
import traceback
from typing import List, Dict, Optional
import random
import re

import httpx
from openai import AsyncOpenAI, DefaultHttpxClient
from openai import AuthenticationError, PermissionDeniedError, APITimeoutError

from .config import settings
from .prompts import REFUSAL_STYLE

# Базовые дефолты
DEFAULT_TEMPERATURE = 0.92
DEFAULT_MAX_TOKENS = 500  # Уменьшено для избежания таймаутов
MAX_RESPONSE_LENGTH = 800  # Максимальная длина ответа в символах
SHORT_RESPONSE_LENGTH = 300

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
    """Клиент для работы с OpenAI API через прокси (аналогично ai-synthesizer)"""

    def __init__(self):
        self.api_key = settings.openai_api_key
        self.model = settings.openai_model
        self.use_proxy = settings.openai_use_proxy
        self.proxy_address = settings.openai_proxy_address
        self._client: Optional[AsyncOpenAI] = None

        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY не задан в .env файле")

    async def _get_client(self) -> AsyncOpenAI:
        """Ленивое создание клиента с настройкой прокси"""
        if self._client is None:
            # Настройка HTTP клиента с прокси (аналогично ai-synthesizer)
            http_client = None
            if self.use_proxy and self.proxy_address:
                http_client = DefaultHttpxClient(
                    proxy=self.proxy_address,
                    transport=httpx.HTTPTransport(local_address="0.0.0.0"),
                    timeout=httpx.Timeout(20.0, connect=5.0)
                )
                print(f"[LLM] Используется прокси: {self.proxy_address}")
            else:
                http_client = DefaultHttpxClient(
                    timeout=httpx.Timeout(20.0, connect=5.0)
                )
                print("[LLM] Прямое подключение к OpenAI API")

            self._client = AsyncOpenAI(
                api_key=self.api_key,
                http_client=http_client,
                max_retries=2
            )
        
        return self._client

    def _openai_error_handler(func):
        """Декоратор для обработки ошибок OpenAI (аналогично ai-synthesizer)"""
        async def wrapper(self, *args, **kwargs):
            try:
                return await func(self, *args, **kwargs)
            
            except PermissionDeniedError as error:
                if self.use_proxy:
                    error_message = "ой, проблемы с прокси... проверь настройки"
                else:
                    error_message = "доступ ограничен... может, нужен прокси?"
                print(f"[LLM] Permission denied: {error}", file=sys.stderr)
                return error_message
                
            except AuthenticationError as error:
                print(f"[LLM] Authentication error: {error}", file=sys.stderr)
                return "ой, проблемы с ключом API... проверь настройки"
                
            except APITimeoutError as error:
                print(f"[LLM] Timeout error: {error}", file=sys.stderr)
                return "хм, что-то долго думаю... может, спросишь попроще?"
                
            except Exception as error:
                print(f"[LLM] Unexpected error: {error}", file=sys.stderr)
                traceback.print_exc()
                return "ой, что-то связь барахлит... попробуй ещё раз?"
        
        return wrapper

    async def _shorten_response(self, original_text: str) -> str:
        """Сокращает слишком длинный ответ через дополнительный запрос"""
        print(f"[LLM] Сокращаем длинный ответ ({len(original_text)} символов)")
        
        messages = [
            {"role": "system", "content": "Ты Алина. Сократи свой ответ, оставив только самое важное и интересное. Максимум 5 пунктов для списков. Сохрани тёплый тон."},
            {"role": "assistant", "content": original_text},
            {"role": "user", "content": "Это слишком длинно. Сократи до самого интересного, оставь максимум 5 пунктов если это список."}
        ]
        
        try:
            shortened = await self._make_request(messages, temperature=0.7, max_tokens=400)
            print(f"[LLM] Ответ сокращён до {len(shortened)} символов")
            return shortened
        except Exception as e:
            print(f"[LLM] Ошибка при сокращении: {e}")
            # Если не удалось сократить через API, обрезаем механически
            lines = original_text.split('\n')
            if len(lines) > 7:
                # Берём первые 5 строк + добавляем фразу
                result = '\n'.join(lines[:5])
                result += "\n\nхочешь ещё? могу рассказать больше 💛"
                return result
            return original_text[:MAX_RESPONSE_LENGTH] + "..."

    @_openai_error_handler
    async def _make_request(self, messages: List[Dict[str, str]], temperature: float, max_tokens: int) -> str:
        """Внутренний метод для выполнения запроса к OpenAI API"""
        client = await self._get_client()
        
        response = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=0.95,
            frequency_penalty=0.3,
        )
        
        # Проверяем finish_reason
        choice = response.choices[0]
        finish_reason = choice.finish_reason
        
        if finish_reason == "length":
            print(f"[LLM] ВНИМАНИЕ: Ответ обрезан из-за лимита токенов (max_tokens={max_tokens})")
        
        return choice.message.content or ""

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        *,
        verbosity: Optional[str] = None,
        safety: bool = False,
    ) -> str:
        """Отправляет запрос к OpenAI API с умным ограничением длины"""
        
        temperature = float(temperature if temperature is not None else DEFAULT_TEMPERATURE)
        
        # Адаптивный max_tokens, но с разумными ограничениями
        if verbosity == "short":
            max_tokens = SHORT_RESPONSE_LENGTH
        elif verbosity == "long":
            # Для длинных ответов ограничиваем, чтобы избежать таймаутов
            max_tokens = MAX_RESPONSE_LENGTH  
        else:
            max_tokens = int(max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS)

        if safety:
            messages = [{"role": "system", "content": REFUSAL_STYLE}] + messages

        # Добавляем указание про ограничение списков
        last_user_msg = messages[-1].get("content", "").lower()
        if any(word in last_user_msg for word in ["факт", "пункт", "список", "причин", "способ"]):
            # Если просят список, явно ограничиваем
            messages.append({
                "role": "system", 
                "content": "ВАЖНО: Даже если просят много пунктов, дай максимум 5 самых интересных. Каждый пункт с новой строки. В конце можешь спросить, хочет ли человек ещё."
            })
        else:
            messages.append({
                "role": "system", 
                "content": "Отвечай кратко и по существу. Если ответ получается длинным, сосредоточься на главном."
            })

        # Отладочный вывод
        print(f"[LLM] Запрос к {self.model} с max_tokens={max_tokens}, температура={temperature}")
        
        try:
            txt = await self._make_request(messages, temperature, max_tokens)
            
            # Проверяем длину ответа
            if len(txt) > MAX_RESPONSE_LENGTH:
                txt = await self._shorten_response(txt)
            
            # Отладка длины ответа
            print(f"[LLM] Получен ответ: {len(txt)} символов")
            
            return _postprocess(txt)
            
        except Exception as e:
            # Обработка ошибок уже происходит в декораторе
            print(f"[LLM] Финальная ошибка: {e}", file=sys.stderr)
            return "что-то пошло не так... попробуй ещё раз?"

    async def aclose(self):
        """Закрывает OpenAI клиент"""
        if self._client is not None:
            await self._client.close()
            self._client = None