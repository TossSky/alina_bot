# app/renewals.py
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from telegram.ext import Application, ContextTypes
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def _jq(app: Application):
    return getattr(app, "job_queue", None)

def _job_name(user_id: int, until_iso: str) -> str:
    # уникально для конкретного периода "времени рядом"
    return f"renew:{user_id}:{until_iso}"

def _parse_until(until_iso: str) -> datetime | None:
    """
    sub_until хранится как ISO без таймзоны (наивный UTC).
    Превратим в aware-UTC для JobQueue.
    """
    try:
        dt = datetime.fromisoformat(until_iso)
        # делаем aware в UTC
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None

async def _send_renewal_nudge(ctx: ContextTypes.DEFAULT_TYPE):
    data = ctx.job.data or {}
    user_id = data.get("user_id")

    text = (
        "Хочешь, я побуду рядом ещё немного? 💛\n"
        "Выбери, как тебе удобнее:"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ Ещё на день",   callback_data="pay_stars:day")],
        [InlineKeyboardButton("⭐ На неделю",     callback_data="pay_stars:week")],
        [InlineKeyboardButton("⭐ На месяц",      callback_data="pay_stars:month")],
    ])
    await ctx.bot.send_message(chat_id=user_id, text=text, reply_markup=kb)

def schedule_renewal_nudge(app: Application, user_id: int, sub_until_iso: str, hours_before: int = 12):
    """
    Планирует одноразовое тёплое напоминание за `hours_before` часов до конца текущего периода.
    Если JobQueue нет — тихо выходим.
    """
    jq = _jq(app)
    if jq is None or not sub_until_iso:
        return

    until_utc = _parse_until(sub_until_iso)
    if not until_utc:
        return

    when_utc = until_utc - timedelta(hours=hours_before)
    now_utc = datetime.now(timezone.utc)
    # если время уже прошло — не планируем (или можно сместить на +60с для немедленной проверки)
    if when_utc <= now_utc:
        return

    name = _job_name(user_id, until_utc.isoformat(timespec="seconds"))

    # удалим возможный дубль с тем же именем
    for j in jq.get_jobs_by_name(name):
        j.schedule_removal()

    jq.run_once(
        callback=_send_renewal_nudge,
        when=when_utc,
        data={"user_id": user_id},
        name=name,
    )
