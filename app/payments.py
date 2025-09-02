# app/payments.py (Stars-only)
from __future__ import annotations
import uuid
from telegram import LabeledPrice, PreCheckoutQuery, Update
from telegram.ext import ContextTypes
from .config import settings
import app.db as db

# Маппинг планов
PLANS = {
    "day":   {"amount": settings.stars_day_amount,   "days": settings.sub_days_day,   "title": "день общения"},
    "week":  {"amount": settings.stars_week_amount,  "days": settings.sub_days_week,  "title": "неделя общения"},
    "month": {"amount": settings.stars_month_amount, "days": settings.sub_days_month, "title": "месяц общения"},
}

def _payload(plan: str) -> str:
    return f"stars_{plan}_{uuid.uuid4()}"

async def send_stars_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE, plan: str) -> None:
    """Отправить инвойс в XTR для выбранного плана"""
    if plan not in PLANS:
        await update.effective_message.reply_text("выбери один из планов: день, неделя или месяц 💛")
        return

    user_id = update.effective_user.id
    meta = PLANS[plan]
    title = meta["title"]
    description = "поддержка без ограничений на выбранный период"
    payload = _payload(plan)
    currency = "XTR"
    prices = [LabeledPrice(title, meta["amount"])]

    # Сохраним как pending
    db.upsert_payment(
        user_id=user_id, provider="stars", order_id=payload,
        amount=meta["amount"], currency=currency, status="pending", raw=plan
    )

    await context.bot.send_invoice(
        chat_id=update.effective_chat.id,
        title=title,
        description=description,
        payload=payload,
        provider_token="",  # для Stars НЕ нужен
        currency=currency,
        prices=prices,
        start_parameter=f"stars-{plan}",
    )

async def precheckout_stars(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обязательный pre-checkout для Stars"""
    query: PreCheckoutQuery = update.pre_checkout_query
    await query.answer(ok=True)

def _extract_plan_from_payload(payload: str) -> str:
    # формат: stars_<plan>_<uuid>
    try:
        return payload.split("_", 2)[1]
    except Exception:
        return "month"

async def on_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sp = update.message.successful_payment
    payload = sp.invoice_payload
    plan = _extract_plan_from_payload(payload)
    meta = PLANS.get(plan, PLANS["month"])

    db.mark_payment(order_id=payload, status="paid")
    db.activate_subscription(update.effective_user.id, days=meta["days"])

    period_label = meta["title"].lower()
    # Обновленное сообщение
    await update.message.reply_text(f"спасибо! буду рядом: {period_label} 💛")