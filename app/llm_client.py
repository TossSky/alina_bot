# app/llm_client.py
from __future__ import annotations
import sys
import traceback
from typing import List, Dict, Optional
import re

import httpx
from openai import AsyncOpenAI
from openai import AuthenticationError, PermissionDeniedError, APITimeoutError

from .config import settings
from .prompts import REFUSAL_STYLE

# Базовые дефолты
DEFAULT_TEMPERATURE = 0.92
DEFAULT_max_completion_tokens = 500
MAX_RESPONSE_LENGTH = 800
SHORT_RESPONSE_LENGTH = 300

def _format_lists(text: str) -> str:
    """Форматирует нумерованные списки с переносами строк"""
    if not text:
        return text
    
    # Паттерн для поиска нумерованных списков
    patterns = [
        (r'(\d+)\.\s+([^.!?]+?)(?=\s*\d+\.|$)', r'\1. \2'),
        (r'(\d+)\)\s+([^.!?]+?)(?=\s*\d+\)|$)', r'\1) \2'),
    ]
    
    for pattern, replacement in patterns:
        matches = list(re.finditer(pattern, text))
        if matches:
            parts = []
            last_end = 0
            
            for match in matches:
                if match.start() > last_end:
                    parts.append(text[last_end:match.start()].rstrip())
                
                item = match.group(1) + '. ' + match.group(2).strip()
                parts.append('\n' + item)
                last_end = match.end()
            
            if last_end < len(text):
                remaining = text[last_end:].lstrip()
                if remaining:
                    parts.append('\n' + remaining)
            
            text = ''.join(parts).strip()
            break
    
    text = re.sub(r'(?:^|\s)[-•]\s+', '\n• ', text)
    return text

def _postprocess(text: str) -> str:
    """Постобработка ответа"""
    if not text:
        return text

    t = text.strip()
    for prefix in ("Алина:", "Алина —", "Алина -"):
        if t.startswith(prefix):
            t = t[len(prefix):].strip()
            break

    t = _format_lists(t)
    t = re.sub(r'\*\*(.*?)\*\*', r'*\1*', t)
    t = re.sub(r'\n{3,}', '\n\n', t)
    return t.strip()

class LLMClient:
    """Клиент для работы с OpenAI API"""

    def __init__(self):
        self.api_key = settings.openai_api_key
        self.model = settings.openai_model
        self.use_proxy = settings.openai_use_proxy
        self.proxy_address = settings.openai_proxy_address

        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY не задан в .env файле")

    async def _create_http_client(self) -> httpx.AsyncClient:
        """Создает HTTP клиент с правильными настройками"""
        if self.use_proxy and self.proxy_address:
            print(f"[LLM] Создаем HTTP клиент с прокси: {self.proxy_address}")
            return httpx.AsyncClient(
                proxy=self.proxy_address,
                timeout=httpx.Timeout(30.0, connect=10.0)
            )
        else:
            print("[LLM] Создаем HTTP клиент без прокси")
            return httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0)
            )

    async def _make_request(self, messages: List[Dict[str, str]], temperature: float, max_completion_tokens: int) -> str:
        """Выполняет запрос к OpenAI API"""
        http_client = None
        openai_client = None
        
        try:
            # Создаем HTTP клиент
            http_client = await self._create_http_client()
            print("[LLM] HTTP клиент создан успешно")
            
            # Создаем OpenAI клиент
            openai_client = AsyncOpenAI(
                api_key=self.api_key,
                http_client=http_client,
                max_retries=2
            )
            print("[LLM] OpenAI клиент создан успешно")
            
            # Выполняем запрос
            print(f"[LLM] Отправляем запрос к модели {self.model}")
            response = await openai_client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_completion_tokens=max_completion_tokens,
                top_p=0.95,
                frequency_penalty=0.3,
            )
            
            choice = response.choices[0]
            finish_reason = choice.finish_reason
            
            if finish_reason == "length":
                print(f"[LLM] ВНИМАНИЕ: Ответ обрезан из-за лимита токенов (max_completion_tokens={max_completion_tokens})")
            
            content = choice.message.content or ""
            print(f"[LLM] Получен ответ длиной {len(content)} символов")
            return content
            
        except PermissionDeniedError as e:
            print(f"[LLM] Permission denied: {e}", file=sys.stderr)
            if self.use_proxy:
                return "ой, проблемы с прокси... проверь настройки"
            else:
                return "доступ ограничен... может, нужен прокси?"
                
        except AuthenticationError as e:
            print(f"[LLM] Authentication error: {e}", file=sys.stderr)
            return "ой, проблемы с ключом API... проверь настройки"
            
        except APITimeoutError as e:
            print(f"[LLM] Timeout error: {e}", file=sys.stderr)
            return "хм, что-то долго думаю... может, спросишь попроще?"
            
        except Exception as e:
            print(f"[LLM] Unexpected error: {e}", file=sys.stderr)
            print(f"[LLM] Error type: {type(e).__name__}", file=sys.stderr)
            traceback.print_exc()
            return "ой, что-то связь барахлит... попробуй ещё раз?"
            
        finally:
            # Закрываем клиенты
            if openai_client:
                try:
                    await openai_client.close()
                    print("[LLM] OpenAI клиент закрыт")
                except Exception as e:
                    print(f"[LLM] Ошибка закрытия OpenAI клиента: {e}")
            
            if http_client:
                try:
                    await http_client.aclose()
                    print("[LLM] HTTP клиент закрыт")
                except Exception as e:
                    print(f"[LLM] Ошибка закрытия HTTP клиента: {e}")

    async def _shorten_response(self, original_text: str) -> str:
        """Сокращает слишком длинный ответ"""
        print(f"[LLM] Сокращаем длинный ответ ({len(original_text)} символов)")
        
        messages = [
            {"role": "system", "content": "Ты Алина. Сократи свой ответ, оставив только самое важное и интересное. Максимум 5 пунктов для списков. Сохрани тёплый тон."},
            {"role": "assistant", "content": original_text},
            {"role": "user", "content": "Это слишком длинно. Сократи до самого интересного, оставь максимум 5 пунктов если это список."}
        ]
        
        try:
            shortened = await self._make_request(messages, temperature=0.7, max_completion_tokens=400)
            print(f"[LLM] Ответ сокращён до {len(shortened)} символов")
            return shortened
        except Exception as e:
            print(f"[LLM] Ошибка при сокращении: {e}")
            # Механическое сокращение
            lines = original_text.split('\n')
            if len(lines) > 7:
                result = '\n'.join(lines[:5])
                result += "\n\nхочешь ещё? могу рассказать больше 💛"
                return result
            return original_text[:MAX_RESPONSE_LENGTH] + "..."

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_completion_tokens: Optional[int] = None,
        *,
        verbosity: Optional[str] = None,
        safety: bool = False,
    ) -> str:
        """Отправляет запрос к OpenAI API"""
        
        temperature = float(temperature if temperature is not None else DEFAULT_TEMPERATURE)
        
        # Адаптивный max_completion_tokens
        if verbosity == "short":
            max_completion_tokens = SHORT_RESPONSE_LENGTH
        elif verbosity == "long":
            max_completion_tokens = MAX_RESPONSE_LENGTH  
        else:
            max_completion_tokens = int(max_completion_tokens if max_completion_tokens is not None else DEFAULT_max_completion_tokens)

        if safety:
            messages = [{"role": "system", "content": REFUSAL_STYLE}] + messages

        # Добавляем указания про ограничение списков
        last_user_msg = messages[-1].get("content", "").lower()
        if any(word in last_user_msg for word in ["факт", "пункт", "список", "причин", "способ"]):
            messages.append({
                "role": "system", 
                "content": "ВАЖНО: Даже если просят много пунктов, дай максимум 5 самых интересных. Каждый пункт с новой строки. В конце можешь спросить, хочет ли человек ещё."
            })
        else:
            messages.append({
                "role": "system", 
                "content": "Отвечай кратко и по существу. Если ответ получается длинным, сосредоточься на главном."
            })

        print(f"[LLM] Запрос к {self.model} с max_completion_tokens={max_completion_tokens}, температура={temperature}")
        
        try:
            txt = await self._make_request(messages, temperature, max_completion_tokens)
            
            # Проверяем длину ответа
            if len(txt) > MAX_RESPONSE_LENGTH:
                txt = await self._shorten_response(txt)
            
            return _postprocess(txt)
            
        except Exception as e:
            print(f"[LLM] Финальная ошибка в chat(): {e}", file=sys.stderr)
            return "что-то пошло не так... попробуй ещё раз?"

    async def aclose(self):
        """Заглушка для совместимости"""
        pass