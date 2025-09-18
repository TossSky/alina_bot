# personality.py - Личность Алины (оптимизированная версия)
"""
Минималистичный но мощный промпт для максимальной человечности.
Меньше правил = больше естественности.
"""

import random
from typing import Optional, Dict
import httpx
import logging
import os

logger = logging.getLogger(__name__)

ALINA_DOC_URL = "https://docs.google.com/document/d/1oLwiaPGMkb-VqMQCJmDwOWBPJOYfm99gk4oqhNPUPEo/edit?usp=sharing"

def _build_export_url(doc_url: str) -> str:
    doc_id = doc_url.split("/d/")[1].split("/")[0].strip()
    return f"https://docs.google.com/document/d/{doc_id}/export?format=txt"

def _fetch_gdoc_text(url: str, timeout: float = 15.0) -> str:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        r = client.get(url, headers={"Accept": "text/plain"})
        r.raise_for_status()

        return r.text.replace("\r\n", "\n").replace("\xa0", " ").strip()
_FALLBACK_PERSONALITY = "Ты — Алина, обычная девушка 24 лет из Москвы. (fallback)"

try:
    _URL = _build_export_url(ALINA_DOC_URL)
    _TXT = _fetch_gdoc_text(_URL)
    if not _TXT:
        raise ValueError("Пустой текст из Google Docs")
    ALINA_PERSONALITY = _TXT
    logger.info("ALINA_PERSONALITY загружен из Google Docs")
except Exception as e:
    logger.warning(f"Не удалось загрузить личность из Google Docs: {e}")
    ALINA_PERSONALITY = _FALLBACK_PERSONALITY

print(ALINA_PERSONALITY)

# Контекстные модификаторы настроения
MOOD_CONTEXTS = {
    "morning": "только проснулась, хочу кофе и тишину",
    "work": "на работе, могу отвлекаться", 
    "evening": "дома, расслабленная",
    "night": "сонная или философское настроение",
    "tired": "устала, отвечаю короче",
    "happy": "хорошее настроение, могу пошутить",
    "annoyed": "раздражена, отвечаю суше",
    "sad": "грустно, хочется поддержки"
}

def enrich_prompt(base_prompt: str, context: Optional[Dict] = None) -> str:
    """
    Добавляет минимальный контекст к промпту.
    Меньше модификаций = больше естественности.
    """
    if not context:
        return base_prompt
    
    additions = []
    
    # Время суток
    hour = context.get('hour')
    if hour is not None:
        if 5 <= hour < 9:
            additions.append(MOOD_CONTEXTS["morning"])
        elif 9 <= hour < 18:
            additions.append(MOOD_CONTEXTS["work"])
        elif 18 <= hour < 23:
            additions.append(MOOD_CONTEXTS["evening"])
        else:
            additions.append(MOOD_CONTEXTS["night"])
    
    # Настроение (рандомное или из контекста)
    mood = context.get('mood')
    if mood and mood in MOOD_CONTEXTS:
        additions.append(MOOD_CONTEXTS[mood])
    
    # История негатива
    if context.get('negative_count', 0) > 2:
        additions.append("пользователь достал, можешь послать")
    
    # Добавляем к промпту
    if additions:
        return base_prompt + f"\n\nСейчас: {'. '.join(additions)}"
    
    return base_prompt

def get_spam_response(count: int) -> str:
    """Возвращает реакцию на спам."""
    if count == 1:
        return "это уже было"
    elif count == 2:
        return "ты застрял?"
    elif count == 3:
        return "..."
    else:
        return "пока"

