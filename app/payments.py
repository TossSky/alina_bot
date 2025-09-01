# app/payments.py
# -*- coding: utf-8 -*-
"""
Оплаты: Telegram Stars + Redsys (полный модуль)
- Stars: инвойс в XTR, pre-checkout, успешная оплата -> активация подписки
- Redsys: генерация параметров и подписи, стартовая ссылка на наш /pay/redsys/start,
          валидация подписи IPN (используй verify_redsys_signature() в webhooks)

Требует:
  - python-telegram-bot v21+
  - pycryptodome (DES3)
  - конфиг в app/config.py и .env (см. поля REDSYS_* и STARS_MONTH_AMOUNT, SUB_DAYS)
"""

from __future__ import annotations
import base64
import json
import time
import uuid
import hmac
import hashlib
from typing import Tuple, Dict, Any

from telegram import LabeledPrice, PreCheckoutQuery, Update
from telegram.ext import ContextTypes
from Crypto.Cipher import DES3  # pip install pycryptodome

from .config import settings
import app.db as db


# ============================================================================
#                           TELEGRAM STARS (XTR)
# ============================================================================

async def send_stars_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Показываем инвойс на оплату звёздами (XTR). provider_token не требуется.
    """
    user_id = update.effective_user.id
    title = "Подписка на месяц"
    description = "Неограничённое общение в течение 30 дней."
    payload = f"stars_sub_{uuid.uuid4()}"
    currency = "XTR"
    prices = [LabeledPrice("Месяц общения", settings.stars_month_amount)]  # цена в XTR

    # Сохраняем платеж как pending
    db.upsert_payment(
        user_id=user_id,
        provider="stars",
        order_id=payload,
        amount=settings.stars_month_amount,
        currency=currency,
        status="pending",
        raw=""
    )

    await context.bot.send_invoice(
        chat_id=update.effective_chat.id,
        title=title,
        description=description,
        payload=payload,
        provider_token="",  # для Stars НЕ указывается токен
        currency=currency,
        prices=prices,
        start_parameter="stars-sub",
    )


async def precheckout_stars(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обязательный pre-checkout для любого инвойса (в т.ч. Stars).
    """
    query: PreCheckoutQuery = update.pre_checkout_query
    # Здесь можно делать собственные проверки payload/лимитов.
    await query.answer(ok=True)


async def on_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Общий обработчик успешной оплаты (в т.ч. Stars).
    """
    sp = update.message.successful_payment
    payload = sp.invoice_payload

    # Отмечаем платёж как paid и активируем подписку на N дней
    db.mark_payment(order_id=payload, status="paid")
    user_id = update.effective_user.id
    db.activate_subscription(user_id, days=settings.sub_days)

    await update.message.reply_text("Спасибо! Я рядом без ограничений в течение месяца 💛")


# ============================================================================
#                                 REDSYS
# ============================================================================

def redsys_endpoint() -> str:
    """
    Возвращает URL платежного шлюза в зависимости от окружения.
    """
    if settings.redsys_env == "test":
        return "https://sis-t.redsys.es:25443/sis/realizarPago"  # Sandbox
    return "https://sis.redsys.es/sis/realizarPago"               # Production


def make_order_id() -> str:
    """
    Генерация номера заказа Ds_Merchant_Order (обычно до 12 символов).
    У Redsys к формату есть требования; timestamp обычно подходит в песочнице.
    """
    return str(int(time.time()))


def _b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")


def _b64d(data_b64: str) -> bytes:
    return base64.b64decode(data_b64)


def _json_to_b64(d: Dict[str, Any]) -> str:
    return _b64e(json.dumps(d).encode("utf-8"))


def derive_3des_key(merchant_key_b64: str, order: str) -> bytes:
    """
    По спецификации Redsys: для подписи нужно получить рабочий ключ как
    3DES-ECB(merchant_key, order_padded), где merchant_key — base64-ключ мерчанта,
    а order — строка Ds_Merchant_Order, дополненная нулями до кратности 8.
    """
    k = _b64d(merchant_key_b64)
    cipher = DES3.new(k, DES3.MODE_ECB)
    data = order.encode("utf-8")
    pad = (8 - (len(data) % 8)) % 8
    data_padded = data + b"\x00" * pad
    return cipher.encrypt(data_padded)


def sign_redsys(merchant_key_b64: str, order: str, merchant_params_b64: str) -> str:
    """
    Подпись Redsys: HMAC-SHA256(base64(params)) с ключом из derive_3des_key(order),
    результат — base64.
    """
    key = derive_3des_key(merchant_key_b64, order)
    mac = hmac.new(key, merchant_params_b64.encode("utf-8"), hashlib.sha256).digest()
    return _b64e(mac)


def build_redsys_merchant_params(order: str, amount_eur_cents: int, user_id: int) -> Tuple[str, str, str]:
    """
    Собирает тройку (version, params_b64, signature) для POST на Redsys.
    - version: 'HMAC_SHA256_V1'
    - params_b64: base64(JSON с Ds_Merchant_* полями)
    - signature: base64(HMAC-SHA256(...)) по правилам Redsys
    """
    merchant_params = {
        "Ds_Merchant_Amount": str(amount_eur_cents),
        "Ds_Merchant_Currency": settings.redsys_currency,       # 978 (EUR)
        "Ds_Merchant_Order": order,
        "Ds_Merchant_MerchantCode": settings.redsys_merchant_code,  # FUC
        "Ds_Merchant_Terminal": settings.redsys_terminal,           # обычно "1"
        "Ds_Merchant_TransactionType": "0",                         # продажа
        "Ds_Merchant_MerchantURL": settings.redsys_notify_url,      # IPN/notify
        "Ds_Merchant_UrlOK": settings.redsys_ok_url,                # куда вернуть юзера (успех)
        "Ds_Merchant_UrlKO": settings.redsys_ko_url,                # куда вернуть юзера (ошибка)
        # Мы передаём user_id для последующей активации подписки
        "Ds_Merchant_MerchantData": json.dumps({"user_id": user_id}),
    }

    params_b64 = _json_to_b64(merchant_params)
    signature = sign_redsys(settings.redsys_key, order, params_b64)
    version = "HMAC_SHA256_V1"
    return version, params_b64, signature


def build_redsys_start_url(user_id: int, amount_eur_cents: int) -> str:
    """
    Возвращает ссылку на НАШ стартовый эндпоинт (/pay/redsys/start),
    который отдаст HTML с авто-POST формой на Redsys (см. app/webhooks.py).
    Сохраняем платёж как pending.
    """
    order = make_order_id()
    # Сохраним pending платёж
    db.upsert_payment(
        user_id=user_id,
        provider="redsys",
        order_id=order,
        amount=amount_eur_cents,
        currency="EUR",
        status="pending",
        raw=""
    )

    # Базовый URL берём из REDSYS_NOTIFY_URL (удалим хвост /webhooks/redsys)
    base = settings.redsys_notify_url
    base = base.rsplit("/webhooks/redsys", 1)[0]
    return f"{base}/pay/redsys/start?order={order}&amount={amount_eur_cents}&user_id={user_id}"


def verify_redsys_signature(params_b64: str, signature_b64: str) -> bool:
    """
    Проверка подписи Redsys на IPN (webhooks).
    Алгоритм:
      1) decode params_b64 -> JSON
      2) извлечь order = Ds_Order или Ds_Merchant_Order
      3) пересчитать sign_redsys(settings.redsys_key, order, params_b64)
      4) сравнить с signature_b64 (в реальности Redsys может присылать URL-safe base64)
    Возвращает True/False.
    """
    try:
        data = json.loads(base64.b64decode(params_b64).decode("utf-8"))
        order = data.get("Ds_Order") or data.get("Ds_Merchant_Order")
        if not order:
            return False

        expected = sign_redsys(settings.redsys_key, order, params_b64)

        # Нормализуем обе подписи: некоторые реализации Redsys присылают URL-safe base64
        def _norm(s: str) -> bytes:
            # Приведём к обычному b64 (замена URL-safe символов и выравнивание паддинга)
            s = s.replace("-", "+").replace("_", "/")
            # Добьём '=' до кратности 4
            pad = (4 - (len(s) % 4)) % 4
            s += "=" * pad
            return base64.b64decode(s)

        got = _norm(signature_b64)
        exp = base64.b64decode(expected)
        return hmac.compare_digest(got, exp)
    except Exception:
        return False
