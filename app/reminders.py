# app/reminders.py
from __future__ import annotations
import re
from datetime import time as dtime, timezone, datetime, timedelta
from zoneinfo import ZoneInfo
from telegram.ext import ContextTypes, Application

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

# ----- TZ helpers (поддержка 'Europe/…' и 'UTC+/-H') -----
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

# ----- фоллбеки, если LLM недоступен -----
FALLBACKS = {
    "morning": [
        "Доброе утро 💛 Как ты проснулся(ась)?",
        "Утро! Я рядом. Расскажешь, что сегодня хочется для себя?",
        "С добрым утром 🌿 Давай начнём мягко. Как твоё состояние?"
    ],
    "evening": [
        "Как прошёл день? Хочу услышать тебя 💛",
        "Вечер. Если хочешь — просто выговорись, я рядом.",
        "Обними себя мысленно за всё, что получилось сегодня 🌙"
    ],
    "checkin": [
        "Привет. Как ты? Можно просто парой слов 💛",
        "Я тут. Расскажешь немного про своё состояние?",
        "Заглянула к тебе. Что внутри прямо сейчас?"
    ]
}

def _pick_fallback(rtype: str) -> str:
    import random
    return random.choice(FALLBACKS.get(rtype, FALLBACKS["checkin"]))

# ----- job callback -----
async def _send_reminder(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data or {}
    user_id = data.get("user_id")
    rtype = data.get("rtype", "checkin")
    chat_id = user_id

    # профиль для подсказки стилю
    u = db.get_user(user_id)
    name = u.get("name") or ""
    style = u.get("style") or "gentle"
    verbosity = u.get("verbosity") or "normal"

    mood_hints = {
        "morning": "Напиши короткое доброе утреннее сообщение, без советов и инструкций. Тёплое, бодрящее, ласковое.",
        "evening": "Напиши короткое вечернее сообщение-поддержку, мягкое и тёплое. Без оценок, без советов.",
        "checkin": "Напиши короткое дружеское сообщение, чтобы человек ответил, как чувствует себя. Без советов."
    }
    hint = mood_hints.get(rtype, mood_hints["checkin"])

    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"Тон: {style}. Длина: {verbosity}. Имя собеседника: {name or 'друг'}."},
        {"role": "system", "content": hint},
        {"role": "user", "content": "Напиши одно короткое сообщение от Алины без подписи. Эмодзи — умеренно."}
    ]

    text = None
    try:
        llm = _get_llm()
        text = await llm.chat(msgs, temperature=0.9, max_tokens=120)
        if text and len(text) > 400:
            text = text[:400] + "…"
    except Exception:
        text = None

    if not text:
        text = _pick_fallback(rtype)

    await context.bot.send_message(chat_id=chat_id, text=text)

# ----- JobQueue glue -----
def _job_queue(app: Application):
    return getattr(app, "job_queue", None)

def _job_name(user_id:int, rid:int) -> str:
    return f"rem:{user_id}:{rid}"

def _parse_hhmm(s: str):
    try:
        hh, mm = s.strip().split(":")
        return int(hh), int(mm)
    except Exception:
        return None

def schedule_one(app: Application, user_id:int, rid:int, rtype:str, time_local:str, tz_str:str):
    jq = _job_queue(app)
    if jq is None:
        return

    name = _job_name(user_id, rid)
    for j in jq.get_jobs_by_name(name):
        j.schedule_removal()

    parsed = _parse_hhmm(time_local)
    if not parsed:
        return
    hh, mm = parsed

    tzinfo = _tzinfo_from_str(tz_str)

    jq.run_daily(
        callback=_send_reminder,
        time=dtime(hour=hh, minute=mm, tzinfo=tzinfo),
        data={"user_id": user_id, "rtype": rtype},
        name=name,
    )

def deschedule_one(app: Application, user_id:int, rid:int):
    jq = _job_queue(app)
    if jq is None:
        return
    name = _job_name(user_id, rid)
    for j in jq.get_jobs_by_name(name):
        j.schedule_removal()

def reschedule_all_for_user(app: Application, user_id:int):
    jq = _job_queue(app)
    if jq is None:
        return
    tz = db.get_tz(user_id) or "UTC"
    for r in db.list_reminders(user_id):
        if r["active"]:
            schedule_one(app, user_id, r["id"], r["rtype"], r["time_local"], tz)
        else:
            deschedule_one(app, user_id, r["id"])
