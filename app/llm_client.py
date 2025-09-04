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
DEFAULT_temperature = 1.1
DEFAULT_MAX_TOKENS = 2000  # Увеличиваем дефолт для полных ответов


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
    
    # Форматируем списки с тире
    text = re.sub(r'(?:^|\s)[-•]\s+', '\n• ', text)
    return text


def _postprocess(text: str) -> str:
    """Постобработка ответа"""
    if not text:
        return text

    t = text.strip()
    
    # Убираем префикс "Алина:"
    for prefix in ("Алина:", "Алина —", "Алина -"):
        if t.startswith(prefix):
            t = t[len(prefix):].strip()
            break

    # Форматируем списки
    t = _format_lists(t)
    
    # Заменяем жирный шрифт на курсив для Telegram
    t = re.sub(r'\*\*(.*?)\*\*', r'*\1*', t)
    
    # Убираем лишние переносы строк
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

    async def _make_request(
        self, 
        messages: List[Dict[str, str]], 
        temperature: float, 
        max_tokens: int
    ) -> str:
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
            print(f"[LLM] Параметры: temperature={temperature}, max_tokens={max_tokens}")
            
            response = await openai_client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,  # Используем max_tokens вместо max_completion_tokens
            )
            
            choice = response.choices[0]
            finish_reason = choice.finish_reason
            
            if finish_reason == "length":
                print(f"[LLM] ВНИМАНИЕ: Ответ достиг лимита токенов (max_tokens={max_tokens})")
            
            content = choice.message.content or ""
            print(f"[LLM] Получен ответ длиной {len(content)} символов, finish_reason={finish_reason}")
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

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        *,
        verbosity: Optional[str] = None,
        safety: bool = False,
    ) -> str:
        """Отправляет запрос к OpenAI API"""
        
        temperature = float(temperature if temperature is not None else DEFAULT_TEMPERATURE)
        
        # Определяем max_tokens на основе verbosity
        if verbosity == "short":
            max_tokens = 300  # Короткие ответы
        elif verbosity == "long":
            max_tokens = 1500  # Длинные ответы для списков
        elif verbosity == "normal" or verbosity is None:
            max_tokens = int(max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS)
        else:
            max_tokens = int(max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS)

        if safety:
            messages = [{"role": "system", "content": REFUSAL_STYLE}] + messages

        # Добавляем указания про формат ответа
        last_user_msg = messages[-1].get("content", "").lower()
        # if any(word in last_user_msg for word in ["факт", "пункт", "список", "причин", "способ"]):
        #     messages.append({
        #         "role": "system", 
        #         "content": "Отвечай полно и интересно. Если нужен список - делай его с переносами строк, каждый пункт с новой строки."
        #     })

        print(f"[LLM] Запрос к {self.model} с max_tokens={max_tokens}, температура={temperature}, verbosity={verbosity}")
        
        try:
            txt = await self._make_request(messages, temperature, max_tokens)
            return _postprocess(txt)
            
        except Exception as e:
            print(f"[LLM] Финальная ошибка в chat(): {e}", file=sys.stderr)
            return "что-то пошло не так... попробуй ещё раз?"

    async def aclose(self):
        """Заглушка для совместимости"""
        pass