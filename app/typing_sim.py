# app/typing_sim.py
import asyncio
import random

def estimate_typing_seconds(text: str) -> float:
    """
    Более реалистичная и быстрая симуляция печати.
    Девушка печатает быстро на телефоне.
    """
    # Базовая скорость: ~30-40 символов в секунду на телефоне
    char_count = len(text)
    
    # Очень короткие сообщения - почти мгновенно
    if char_count < 20:
        return random.uniform(0.5, 1.0)
    
    # Короткие сообщения - быстро
    if char_count < 50:
        return random.uniform(1.0, 1.8)
    
    # Средние сообщения
    if char_count < 100:
        return random.uniform(1.8, 2.5)
    
    # Длинные сообщения - но не дольше 3.5 сек
    base_time = min(3.5, char_count / 35.0)
    
    # Добавляем небольшую случайность
    variation = random.uniform(-0.2, 0.3)
    
    return max(0.5, min(3.5, base_time + variation))

async def human_typing(context, chat_id: int, planned_reply: str):
    """
    Имитация набора текста человеком.
    Быстрая и естественная.
    """
    secs = estimate_typing_seconds(planned_reply)
    
    # Показываем "печатает..."
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    # Ждём
    await asyncio.sleep(secs)