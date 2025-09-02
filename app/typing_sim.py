import asyncio
import random

def estimate_typing_seconds(text: str) -> float:
    """
    Более реалистичная и быстрая симуляция печати.
    Девушка печатает быстро на телефоне.
    """
    char_count = len(text)
    
    if char_count < 20:
        return random.uniform(0.5, 1.0)
    if char_count < 50:
        return random.uniform(1.0, 1.8)
    if char_count < 100:
        return random.uniform(1.8, 2.5)
    
    base_time = min(3.5, char_count / 35.0)
    variation = random.uniform(-0.2, 0.3)
    return max(0.5, min(3.5, base_time + variation))

async def human_typing(context, chat_id: int, planned_reply: str):
    """
    Имитация набора текста человеком.
    Отправляет "печатает..." каждые 2 сек до конца задержки.
    """
    secs = estimate_typing_seconds(planned_reply)
    elapsed = 0
    interval = 2.0

    while elapsed < secs:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        await asyncio.sleep(interval)
        elapsed += interval

    # Если осталось меньше интервала — досыпаем
    if elapsed < secs:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        await asyncio.sleep(secs - elapsed)
