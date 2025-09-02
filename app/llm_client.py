# app/llm_client.py
from __future__ import annotations
import asyncio
import os
from typing import List, Dict, Optional

import httpx

from .config import settings
from .prompts import REFUSAL_STYLE

# Базовые дефолты (если не передано иначе)
DEFAULT_TEMPERATURE = 0.85
DEFAULT_MAX_TOKENS = 700

# Профили под длину ответа
VERBOSITY_PROFILES = {
    # немного короче и теплее: меньше токенов, чуть выше температура — звучит «живее»
    "short":  {"max_tokens": 280, "temperature": 0.9},
    # универсальный
    "normal": {"max_tokens": 600, "temperature": 0.85},
    # длиннее, но всё равно без «воды»
    "long":   {"max_tokens": 900, "temperature": 0.8},
}

def _pick_profile(verbosity: Optional[str]) -> Dict[str, float]:
    if not verbosity:
        return {"max_tokens": DEFAULT_MAX_TOKENS, "temperature": DEFAULT_TEMPERATURE}
    verbosity = verbosity.lower().strip()
    return VERBOSITY_PROFILES.get(verbosity, {"max_tokens": DEFAULT_MAX_TOKENS, "temperature": DEFAULT_TEMPERATURE})

def _postprocess(text: str) -> str:
    if not text:
        return text
    t = text.strip()
    # срежем возможные префиксы вроде «Алина:»
    for prefix in ("Алина:", "Алина —", "Алина -", "Алина — ", "Алина - "):
        if t.startswith(prefix):
            t = t[len(prefix):].lstrip("—-: \u2014 ")
            break
    # одно лишнее тире/двоеточие в начале
    while t and t[0] in ("—", "-", ":", " "):
        t = t[1:]
    return t.strip()

class LLMClient:
    """
    Унифицированный клиент к LLM-провайдерам.
    По умолчанию используем DeepSeek.

    Методы:
      chat(messages, temperature=?, max_tokens=?, verbosity=?, safety=?)
        - messages: список ролей/контента (system|user|assistant)
        - verbosity: 'short'|'normal'|'long' → подбирает max_tokens/temperature по профилю
        - safety: True → мягко подмешиваем стиль отказов (REFUSAL_STYLE) в системные сообщения
    """

    def __init__(self):
        # провайдер
        self.provider = (os.getenv("LLM_PROVIDER") or getattr(settings, "llm_provider", "deepseek")).lower()

        # DeepSeek
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY") or getattr(settings, "deepseek_api_key", None)
        self.deepseek_model = getattr(settings, "deepseek_model", "deepseek-chat")

        # OpenRouter (опционально)
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY") or getattr(settings, "openrouter_api_key", None)
        self.openrouter_model = getattr(settings, "openrouter_model", "openrouter/auto")

        # Ollama (опционально, локально)
        self.ollama_host = getattr(settings, "ollama_host", "http://127.0.0.1:11434")
        self.ollama_model = getattr(settings, "ollama_model", "qwen2.5")

        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            # аккуратные таймауты (подходит для бота)
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
        return self._client

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        *,
        verbosity: Optional[str] = None,
        safety: bool = False,
    ) -> str:
        """
        Универсальный метод генерации.
        - Если передан verbosity → подбираем max_tokens/temperature по профилю.
        - Если safety=True → мягко подмешиваем REFUSAL_STYLE в систему.
        """
        # применяем профиль длины
        prof = _pick_profile(verbosity)
        temperature = float(temperature if temperature is not None else prof["temperature"])
        max_tokens = int(max_tokens if max_tokens is not None else prof["max_tokens"])

        # мягкий safety: добавим правило отказа в начало system-сообщений
        if safety:
            # не ломаем порядок: вставим самым первым system-сообщением
            injected = False
            for i, m in enumerate(messages):
                if m.get("role") == "system":
                    messages = messages[:i] + [{"role": "system", "content": REFUSAL_STYLE}] + messages[i:]
                    injected = True
                    break
            if not injected:
                messages = [{"role": "system", "content": REFUSAL_STYLE}] + messages

        prov = self.provider
        if prov == "deepseek":
            return await self._chat_deepseek(messages, temperature, max_tokens)
        elif prov == "openrouter":
            return await self._chat_openrouter(messages, temperature, max_tokens)
        elif prov == "ollama":
            return await self._chat_ollama(messages, temperature, max_tokens)
        else:
            # дефолт — deepseek
            return await self._chat_deepseek(messages, temperature, max_tokens)

    # ------------------------- DeepSeek -------------------------

    async def _chat_deepseek(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> str:
        if not self.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY не задан")

        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.deepseek_model,      # "deepseek-chat" или "deepseek-reasoner"
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        client = await self._get_client()
        for attempt in range(2):
            try:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                txt = data["choices"][0]["message"]["content"]
                return _postprocess(txt)
            except (httpx.HTTPError, KeyError):
                if attempt == 0:
                    await asyncio.sleep(0.7)
                    continue
                raise

    # ------------------------- OpenRouter (опционально) -------------------------

    async def _chat_openrouter(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> str:
        if not self.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY не задан")
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.openrouter_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        client = await self._get_client()
        for attempt in range(2):
            try:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                txt = data["choices"][0]["message"]["content"]
                return _postprocess(txt)
            except (httpx.HTTPError, KeyError):
                if attempt == 0:
                    await asyncio.sleep(0.7)
                    continue
                raise

    # ------------------------- Ollama (локально, опционально) -------------------------

    async def _chat_ollama(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> str:
        url = f"{self.ollama_host.rstrip('/')}/api/chat"
        payload = {
            "model": self.ollama_model,
            "messages": messages,
            "options": {
                "temperature": float(temperature),
                "num_predict": int(max_tokens),
            },
            "stream": False,
        }
        client = await self._get_client()
        for attempt in range(2):
            try:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                if "message" in data and "content" in data["message"]:
                    return _postprocess(data["message"]["content"])
                if "messages" in data and data["messages"]:
                    return _postprocess(data["messages"][-1].get("content", ""))
                raise KeyError("unexpected ollama response")
            except (httpx.HTTPError, KeyError):
                if attempt == 0:
                    await asyncio.sleep(0.7)
                    continue
                raise

    async def aclose(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None
