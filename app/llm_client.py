from typing import List, Dict
import os, httpx
from .config import settings

class LLMClient:
    async def chat(self, messages: List[Dict], temperature: float = 0.8, max_tokens: int = 700) -> str:
        provider = settings.llm_provider

        if provider == "deepseek":
            url = "https://api.deepseek.com/chat/completions"
            headers = {"Authorization": f"Bearer {settings.deepseek_api_key}"}
            payload = {"model": "deepseek-chat", "messages": messages,
                       "temperature": temperature, "max_tokens": max_tokens}
        elif provider == "openrouter":
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {"Authorization": f"Bearer {settings.openrouter_api_key}"}
            payload = {"model": settings.openrouter_model, "messages": messages,
                       "temperature": temperature, "max_tokens": max_tokens}
        else:  # локально через Ollama OpenAI-compatible
            url = "http://127.0.0.1:11434/v1/chat/completions"
            headers = {}
            payload = {"model": "deepseek-r1:latest", "messages": messages,
                       "temperature": temperature, "max_tokens": max_tokens}

        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"]
