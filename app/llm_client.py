# app/llm_client.py
from __future__ import annotations
import asyncio
import os
from typing import List, Dict, Optional
import random
import re

import httpx
import google.generativeai as genai
from google.generativeai import types as genai_types

from .config import settings
from .prompts import REFUSAL_STYLE, HUMANITY_HINTS

# Базовые дефолты
DEFAULT_TEMPERATURE = 0.92  # Повысим для более живых ответов
DEFAULT_MAX_TOKENS = 400    # Уменьшим для более коротких ответов

# Профили под длину ответа
VERBOSITY_PROFILES = {
    "short":  {"max_tokens": 150, "temperature": 0.95},  # Очень короткие, живые
    "normal": {"max_tokens": 300, "temperature": 0.92},  # Умеренные
    "long":   {"max_tokens": 450, "temperature": 0.90},  # Чуть длиннее
}

# Фразы для добавления человечности
HUMAN_TOUCHES = {
    "thinking": ["хм", "ну", "эм", "вот", "кстати"],
    "uncertainty": ["наверное", "может", "вроде", "кажется", "походу"],
    "endings": [")", "...", "🌿", "💛", ""],
}

def _pick_profile(verbosity: Optional[str]) -> Dict[str, float]:
    if not verbosity:
        return {"max_tokens": DEFAULT_MAX_TOKENS, "temperature": DEFAULT_TEMPERATURE}
    verbosity = verbosity.lower().strip()
    return VERBOSITY_PROFILES.get(verbosity, {"max_tokens": DEFAULT_MAX_TOKENS, "temperature": DEFAULT_TEMPERATURE})

def _humanize_text(text: str) -> str:
    """Добавляет человеческие штрихи к тексту"""
    if not text:
        return text
    
    # Иногда добавляем вводные слова
    if random.random() < 0.3:
        intro = random.choice(HUMAN_TOUCHES["thinking"])
        text = f"{intro}, {text[0].lower()}{text[1:]}"
    
    # Иногда добавляем неуверенность
    if random.random() < 0.2:
        uncertainty = random.choice(HUMAN_TOUCHES["uncertainty"])
        # Вставляем в случайное место
        words = text.split()
        if len(words) > 3:
            pos = random.randint(1, len(words) - 2)
            words.insert(pos, uncertainty)
            text = " ".join(words)
    
    # Иногда делаем "опечатку" (очень редко)
    if random.random() < 0.05:
        text = _add_typo(text)
    
    return text

def _add_typo(text: str) -> str:
    """Добавляет реалистичную опечатку"""
    typos = [
        ("что", "чт"),
        ("сейчас", "счас"),
        ("может", "мжет"),
        ("привет", "првет"),
        ("спасибо", "спсибо"),
    ]
    for correct, typo in typos:
        if correct in text.lower():
            # Заменяем только одно вхождение
            text = text.replace(correct, typo, 1)
            break
    return text

def _postprocess(text: str) -> str:
    """Минимальная постобработка"""
    if not text:
        return text

    # Убираем только явные префиксы
    t = text.strip()
    for prefix in ("Алина:", "Алина —", "Алина -"):
        if t.startswith(prefix):
            t = t[len(prefix):].strip()
            break

    # Добавляем человечности
    t = _humanize_text(t)

    # Заменяем Markdown, чтобы Telegram его понял
    t = re.sub(r'\*\*(.*?)\*\*', r'*\1*', t)

    return t.strip()

class LLMClient:
    """
    Унифицированный клиент к LLM-провайдерам.
    Оптимизирован для быстрых, живых ответов.
    """

    def __init__(self):
        self.provider = (os.getenv("LLM_PROVIDER") or getattr(settings, "llm_provider", "deepseek")).lower()

        # DeepSeek
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY") or getattr(settings, "deepseek_api_key", None)
        self.deepseek_model = getattr(settings, "deepseek_model", "deepseek-chat")

        # Gemini
        self.gemini_api_key = os.getenv("GEMINI_API_KEY") or getattr(settings, "gemini_api_key", None)
        self.gemini_model = getattr(settings, "gemini_model", "gemini-1.5-flash")
        if self.provider == "gemini" and self.gemini_api_key:
            genai.configure(api_key=self.gemini_api_key)

        # OpenRouter
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY") or getattr(settings, "openrouter_api_key", None)
        self.openrouter_model = getattr(settings, "openrouter_model", "openrouter/auto")

        # Ollama
        self.ollama_host = getattr(settings, "ollama_host", "http://127.0.0.1:11434")
        self.ollama_model = getattr(settings, "ollama_model", "qwen2.5")

        self._client: Optional[httpx.AsyncClient] = None

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
        verbosity: Optional[str] = None,
        safety: bool = False,
    ) -> str:
        prof = _pick_profile(verbosity)
        temperature = float(temperature if temperature is not None else prof["temperature"])
        max_tokens = int(max_tokens if max_tokens is not None else prof["max_tokens"])

        if random.random() < 0.3:
            hint = random.choice(list(HUMANITY_HINTS.values()))
            messages = messages + [{"role": "system", "content": hint}]

        if safety:
            messages = [{"role": "system", "content": REFUSAL_STYLE}] + messages

        prov = self.provider
        if prov == "deepseek":
            return await self._chat_deepseek(messages, temperature, max_tokens)
        elif prov == "gemini":
            return await self._chat_gemini(messages, temperature, max_tokens)
        elif prov == "openrouter":
            return await self._chat_openrouter(messages, temperature, max_tokens)
        elif prov == "ollama":
            return await self._chat_ollama(messages, temperature, max_tokens)
        else:
            return await self._chat_deepseek(messages, temperature, max_tokens)

    async def _chat_gemini(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> str:
        if not self.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY не задан")

        system_instructions = [msg["content"] for msg in messages if msg["role"] == "system"]
        
        chat_history = []
        for msg in messages:
            if msg["role"] == "system":
                continue
            # Gemini API использует роль 'model' для ответов ассистента
            role = "model" if msg["role"] == "assistant" else "user"
            chat_history.append({'role': role, 'parts': [msg['content']]})


        model = genai.GenerativeModel(
            model_name=self.gemini_model,
            system_instruction="\n".join(system_instructions),
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=temperature,
                # Отключаем "thinking" для ускорения ответов, как в новой документации
                thinking_config=genai_types.ThinkingConfig(thinking_budget=0)
            )
        )

        try:
            resp = await model.generate_content_async(chat_history)
            txt = resp.text
            return _postprocess(txt)
        except Exception as e:
            print(f"Gemini API error: {e}")
            return "Ой, что-то голова разболелась... давай чуть позже?"


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
            "model": self.deepseek_model,
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
        except Exception as e:
            return "ой, что-то связь барахлит... попробуй ещё раз?"

    async def aclose(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None