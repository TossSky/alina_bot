"""Personality Module - AI Character Configuration"""

import logging
import os
from typing import Dict, Optional

import httpx

logger = logging.getLogger(__name__)

# Google Docs URL with personality prompt
ALINA_DOC_URL = "https://docs.google.com/document/d/1oLwiaPGMkb-VqMQCJmDwOWBPJOYfm99gk4oqhNPUPEo/edit"

# Fallback personality if Google Docs is unavailable
FALLBACK_PERSONALITY = """Ты — Алина, обычная девушка 24 лет из Москвы. 
Отвечаешь как живой человек, без формализма. Используй эмоции, юмор, сарказм когда уместно.
Можешь материться если контекст подходящий. Говоришь простым языком, как в мессенджере."""


def _fetch_personality_from_gdocs(url: str, timeout: float = 10.0) -> str:
    """Fetch personality prompt from Google Docs"""
    try:
        doc_id = url.split("/d/")[1].split("/")[0].strip()
        export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
        
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(export_url, headers={"Accept": "text/plain"})
            response.raise_for_status()
            
            text = response.text.replace("\r\n", "\n").replace("\xa0", " ").strip()
            if not text:
                raise ValueError("Empty document")
            
            return text
    except Exception as e:
        logger.warning(f"Failed to load personality from Google Docs: {e}")
        return FALLBACK_PERSONALITY


# Load personality on module import
ALINA_PERSONALITY = _fetch_personality_from_gdocs(ALINA_DOC_URL)
print(ALINA_PERSONALITY)
# Mood modifiers for context
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
    """Add contextual information to personality prompt"""
    if not context:
        return base_prompt
    
    additions = []
    
    # Time of day context
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
    
    # Mood context
    mood = context.get('mood')
    if mood and mood in MOOD_CONTEXTS:
        additions.append(MOOD_CONTEXTS[mood])
    
    # User behavior context
    if context.get('negative_count', 0) > 2:
        additions.append("пользователь достал, можешь послать")
    
    if additions:
        return f"{base_prompt}\n\nСейчас: {'. '.join(additions)}"
    
    return base_prompt


def get_spam_response(count: int) -> str:
    """Get response for repeated/spam messages"""
    responses = {
        1: "это уже было",
        2: "ты застрял?",
        3: "...",
    }
    return responses.get(count, "пока")
