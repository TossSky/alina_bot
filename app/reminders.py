# app/reminders.py
from __future__ import annotations
from datetime import time as dtime, timezone, datetime
from zoneinfo import ZoneInfo
from telegram.ext import ContextTypes, Application
import app.db as db

def _parse_hhmm(s: str):
    try:
        hh, mm = s.strip().split(":")
        return int(hh), int(mm)
    except Exception:
        return None

async def _send_reminder(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data or {}
    user_id = data.get("user_id")
    rtype = data.get("rtype", "checkin")
    chat_id = user_id  # приватный чат == user_id

    if rtype == "checkin":
        text = (
            "Привет, как ты? 💛 Хочешь, просто расскажи пару фраз.\n"
            "Если хочешь, я могу предложить маленькое упражнение 🌿"
        )
    else:  # care
        text = (
            "Немного заботы о себе 🌿 Сделай глоток воды, пару глубоких вдохов, "
            "проверь, не голоден ли."
        )
    await context.bot.send_message(chat_id=chat_id, text=text)

def _job_queue(app: Application):
    # Без установленного extra (ptb[job-queue]) app.job_queue будет None
    return getattr(app, "job_queue", None)

def _job_name(user_id:int, rid:int) -> str:
    return f"rem:{user_id}:{rid}"

def schedule_one(app: Application, user_id:int, rid:int, rtype:str, time_local:str, tz_str:str):
    jq = _job_queue(app)
    if jq is None:
        # JobQueue не установлен — просто выходим тихо
        return

    name = _job_name(user_id, rid)
    for j in jq.get_jobs_by_name(name):
        j.schedule_removal()

    parsed = _parse_hhmm(time_local)
    if not parsed:
        return
    hh, mm = parsed

    try:
        tzinfo = ZoneInfo(tz_str) if tz_str else timezone.utc
    except Exception:
        tzinfo = timezone.utc

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
