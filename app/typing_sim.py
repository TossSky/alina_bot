import asyncio

def estimate_typing_seconds(text: str) -> float:
    # простая модель: 18-25 символов/сек, плюс пауза за абзацы
    base = max(1.0, min(5.0, len(text) / 140.0))
    bumps = text.count("\n") * 0.4
    return min(6.5, base + bumps)

async def human_typing(context, chat_id: int, planned_reply: str):
    secs = estimate_typing_seconds(planned_reply)
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    await asyncio.sleep(secs)
