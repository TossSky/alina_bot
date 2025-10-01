"""Personality Module - AI Character Configuration and Context Management"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Fallback personality if Google Docs service is unavailable
FALLBACK_PERSONALITY = """Ты — Алина, обычная девушка 24 лет из Москвы. 
Отвечаешь как живой человек, без формализма. Используй эмоции, юмор, сарказм когда уместно.
Можешь материться если контекст подходящий. Говоришь простым языком, как в мессенджере."""


def get_current_personality() -> str:
    """Get current personality prompt from Google Docs service
    
    Returns:
        Personality prompt string
    """
    try:
        from google_docs_service import get_docs_service
        return get_docs_service().get_personality()
    except Exception as e:
        logger.warning(f"Failed to get personality from docs service: {e}")
        return FALLBACK_PERSONALITY


# Load personality on module import (for backward compatibility)
ALINA_PERSONALITY = get_current_personality()


# Mood context templates for different situations
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
    """Enrich personality prompt with contextual information
    
    Args:
        base_prompt: Base personality description
        context: Optional context dictionary with hints
        
    Returns:
        Enriched prompt with context
    """
    if not context:
        return base_prompt
    
    additions = []
    
    # Add time-of-day context
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
    
    # Add explicit mood context
    mood = context.get('mood')
    if mood and mood in MOOD_CONTEXTS:
        additions.append(MOOD_CONTEXTS[mood])
    
    # Add user behavior context
    if context.get('negative_count', 0) > 2:
        additions.append("пользователь достал, можешь послать")
    
    # Append context to base prompt if any additions
    if additions:
        return f"{base_prompt}\n\nСейчас: {'. '.join(additions)}"
    
    return base_prompt


def get_spam_response(count: int) -> str:
    """Get response for repeated/spam messages
    
    Args:
        count: Number of times message was repeated
        
    Returns:
        Appropriate response based on repetition count
    """
    responses = {
        1: "это уже было",
        2: "ты застрял?",
        3: "...",
    }
    return responses.get(count, "пока")
