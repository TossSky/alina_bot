# app/reminders.py
from __future__ import annotations
import re
import random
from datetime import time as dtime, timezone, datetime, timedelta
from zoneinfo import ZoneInfo
from telegram.ext import ContextTypes, Application
from telegram.constants import ParseMode

import app.db as db
from .llm_client import LLMClient
from .prompts import SYSTEM_PROMPT

# ленивый клиент LLM
_llm = None
def _get_llm():
    global _llm
    if _llm is None:
        _llm = LLMClient()
    return _llm

# ----- TZ helpers -----
def _tzinfo_from_str(tz_str: str):
    if not tz_str:
        return timezone.utc
    m = re.fullmatch(r"UTC([+-])(\d{1,2})", tz_str.upper())
    if m:
        sign, hh = m.group(1), int(m.group(2))
        offset = timedelta(hours=hh if sign == "+" else -hh)
        return timezone(offset)
    try:
        return ZoneInfo(tz_str)
    except Exception:
        return timezone.utc

# ----- Более разнообразные и человечные фоллбеки -----
FALLBACKS = {
    "morning": [
        "доброе утро 💛 как спалось?",
        "утро! как дела?",
        "привет) уже проснулся?",
        "доброе утречко 🌿",
        "утро... кофе уже был?",
        "привет! как начался день?",
        "утро) что планируешь сегодня?",
        "доброе утро! выспался?",
        "утречко... как настроение?",
    ],
    "evening": [
        "как прошёл день?",
        "привет) как ты?",
        "вечер... устал?",
        "хей, как дела? 💛",
        "как день? всё ок?",
        "привет) что нового?",
        "как сегодня прошло?",
        "вечер) как настроение?",
        "как день прошёл? устал?",
    ],
    "checkin": [
        "привет) как ты?",
        "хей, что нового?",
        "как дела? 💛",
        "привет... всё хорошо?",
        "как настроение?",
        "что делаешь?",
        "как ты там?",
        "привет) не потерялся?",
        "хей) всё ок?",
        "как поживаешь?",
    ]
}

def _pick_fallback(rtype: str) -> str:
    """Выбирает случайное сообщение из фоллбеков"""
    messages = FALLBACKS.get(rtype, FALLBACKS["checkin"])
    return random.choice(messages)

# ----- job callback -----
async def _send_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Отправляет напоминание пользователю"""
    data = context.job.data or {}
    user_id = data.get("user_id")
    rtype = data.get("rtype", "checkin")
    chat_id = user_id

    # Профиль пользователя
    u = db.get_user(user_id)
    name = u.get("name") or ""
    style = "gentle"
    
    # В 80% случаев используем простой фоллбек
    if random.random() < 0.8:
        text = _pick_fallback(rtype)
    else:
        # Иногда генерируем через LLM для разнообразия
        mood_hints = {
            "morning": "напиши короткое доброе утреннее приветствие, как будто пишешь другу в мессенджере",
            "evening": "напиши короткое вечернее сообщение, спроси как день",
            "checkin": "напиши короткое дружеское сообщение, просто узнай как дела"
        }
        hint = mood_hints.get(rtype, mood_hints["checkin"])

        msgs = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": f"Тон: {style}. Имя: {name or 'друг'}."},
            {"role": "system", "content": hint},
            {"role": "system", "content": "ВАЖНО: пиши ОЧЕНЬ коротко (1-2 фразы), как в мессенджере, без лишних слов"},
            {"role": "user", "content": "напиши одно короткое сообщение"}
        ]

        try:
            llm = _get_llm()
            text = await llm.chat(msgs, temperature=1.0, max_tokens=100, verbosity="short")
            # Если сгенерировалось слишком длинное, обрезаем
            if text and len(text) > 150:
                text = text[:150].rsplit(" ", 1)[0] + "..."
        except Exception:
            text = _pick_fallback(rtype)

    # Отправляем с форматированием
    try:
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        # Если ошибка форматирования - отправляем без него
        await context.bot.send_message(chat_id=chat_id, text=text)

# ----- JobQueue glue -----
def _job_queue(app: Application):
    return getattr(app, "job_queue", None)

def _job_name(user_id: int, rid: int) -> str:
    return f"rem:{user_id}:{rid}"

def _parse_hhmm(s: str):
    try:
        hh, mm = s.strip().split(":")
        return int(hh), int(mm)
    except Exception:
        return None

def schedule_one(app: Application, user_id: int, rid: int, rtype: str, time_local: str, tz_str: str):
    """Планирует одно напоминание"""
    jq = _job_queue(app)
    if jq is None:
        return

    name = _job_name(user_id, rid)
    # Удаляем старые задачи с таким же именем
    for j in jq.get_jobs_by_name(name):
        j.schedule_removal()

    parsed = _parse_hhmm(time_local)
    if not parsed:
        return
    hh, mm = parsed

    tzinfo = _tzinfo_from_str(tz_str)

    try:
        jq.run_daily(
            callback=_send_reminder,
            time=dtime(hour=hh, minute=mm, tzinfo=tzinfo),
            data={"user_id": user_id, "rtype": rtype},
            name=name,
        )
    except Exception as e:
        print(f"Ошибка планирования напоминания: {e}")

def deschedule_one(app: Application, user_id: int, rid: int):
    """Отменяет одно напоминание"""
    jq = _job_queue(app)
    if jq is None:
        return
    name = _job_name(user_id, rid)
    for j in jq.get_jobs_by_name(name):
        j.schedule_removal()

def reschedule_all_for_user(app: Application, user_id: int):
    """Перепланирует все напоминания пользователя (при смене часового пояса)"""
    jq = _job_queue(app)
    if jq is None:
        return
    tz = db.get_tz(user_id) or "UTC"
    for r in db.list_reminders(user_id):
        if r["active"]:
            schedule_one(app, user_id, r["id"], r["rtype"], r["time_local"], tz)
        else:
            deschedule_one(app, user_id, r["id"])