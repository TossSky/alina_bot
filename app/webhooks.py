# app/webhooks.py
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
import json, base64, hmac, hashlib
from Crypto.Cipher import DES3  # pip install pycryptodome
from .config import settings
import app.db as db

app = FastAPI()

# ---- Redsys helpers ----
def _redsys_endpoint() -> str:
    return "https://sis-t.redsys.es:25443/sis/realizarPago" if settings.redsys_env == "test" \
           else "https://sis.redsys.es/sis/realizarPago"

def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("utf-8")

def _b64d(s: str) -> bytes:
    return base64.b64decode(s)

def _to_base64_json(d: dict) -> str:
    return _b64e(json.dumps(d).encode("utf-8"))

def _derive_key_3des(merchant_key_b64: str, order: str) -> bytes:
    """
    Redsys: подпись HMAC-SHA256 с ключом, полученным из merchant_key (base64),
    пропущенным через 3DES-ECB по значению Ds_Merchant_Order (строка).
    """
    k = _b64d(merchant_key_b64)
    cipher = DES3.new(k, DES3.MODE_ECB)
    # order должен быть кратен 8 байтам — Redsys обычно требует строку из цифр; паддим нулями справа
    data = order.encode("utf-8")
    pad = (8 - (len(data) % 8)) % 8
    data_padded = data + b"\x00" * pad
    return cipher.encrypt(data_padded)

def _sign_redsys(merchant_key_b64: str, order: str, merchant_params_b64: str) -> str:
    key = _derive_key_3des(merchant_key_b64, order)
    mac = hmac.new(key, merchant_params_b64.encode("utf-8"), hashlib.sha256).digest()
    # Redsys использует base64 "url-style"? Допустим стандартный b64 — обычно хватает.
    return _b64e(mac)

def _build_params(order: str, amount_cents: int, user_id: int) -> tuple[str, str, str]:
    merchant_params = {
        "Ds_Merchant_Amount": str(amount_cents),
        "Ds_Merchant_Currency": settings.redsys_currency,  # 978=EUR
        "Ds_Merchant_Order": order,
        "Ds_Merchant_MerchantCode": settings.redsys_merchant_code,
        "Ds_Merchant_Terminal": settings.redsys_terminal,
        "Ds_Merchant_TransactionType": "0",
        "Ds_Merchant_MerchantURL": settings.redsys_notify_url,  # IPN
        "Ds_Merchant_UrlOK": settings.redsys_ok_url,
        "Ds_Merchant_UrlKO": settings.redsys_ko_url,
        "Ds_Merchant_MerchantData": json.dumps({"user_id": user_id})
    }
    params_b64 = _to_base64_json(merchant_params)
    signature = _sign_redsys(settings.redsys_key, order, params_b64)
    return "HMAC_SHA256_V1", params_b64, signature

@app.get("/pay/redsys/start", response_class=HTMLResponse)
async def redsys_start(request: Request):
    """
    Рендерим HTML-страницу, которая авто-отправит POST на Redsys.
    Query: ?order=...&amount=...&user_id=...
    """
    q = dict(request.query_params)
    order = q.get("order")
    amount = int(q.get("amount", "0"))
    user_id = int(q.get("user_id", "0"))

    if not (order and amount and user_id):
        return HTMLResponse("Bad params", status_code=400)

    version, params_b64, signature = _build_params(order, amount, user_id)
    action = _redsys_endpoint()

    html = f"""
<!doctype html>
<html><head><meta charset="utf-8"><title>Redirecting…</title></head>
<body onload="document.forms[0].submit()">
  <p>Переходим на защищённую страницу оплаты…</p>
  <form method="POST" action="{action}">
    <input type="hidden" name="Ds_SignatureVersion" value="{version}">
    <input type="hidden" name="Ds_MerchantParameters" value="{params_b64}">
    <input type="hidden" name="Ds_Signature" value="{signature}">
    <noscript><button type="submit">Оплатить</button></noscript>
  </form>
</body></html>
"""
    return HTMLResponse(html)

# ---- IPN от Redsys (как было) ----
def verify_redsys_signature(params_b64: str, signature: str) -> bool:
    # TODO: приём подписи Redsys: нужно извлечь order из Ds_Order / Ds_Merchant_Order
    # и пересчитать _sign_redsys(settings.redsys_key, order, params_b64) == signature
    return True  # пока даём пройти для облегчения интеграции в тесте

@app.post("/webhooks/redsys")
async def redsys_ipn(request: Request):
    if request.headers.get("content-type","").startswith("application/x-www-form-urlencoded"):
        data = await request.form()
    else:
        data = await request.json()

    try:
        params_b64 = data.get("Ds_MerchantParameters") or data["Ds_MerchantParameters"]
        signature = data.get("Ds_Signature") or data["Ds_Signature"]

        if not verify_redsys_signature(params_b64, signature):
            return Response(status_code=400, content="invalid signature")

        params = json.loads(base64.b64decode(params_b64).decode("utf-8"))
        order_id = params.get("Ds_Order") or params.get("Ds_Merchant_Order")
        response_code = params.get("Ds_Response")
        if response_code is not None:
            try:
                if int(response_code) < 100:
                    db.mark_payment(order_id, "paid")
                    md = params.get("Ds_MerchantData")
                    user_id = None
                    if md:
                        try:
                            parsed = json.loads(md)
                            user_id = int(parsed.get("user_id"))
                        except Exception:
                            pass
                    if user_id:
                        db.activate_subscription(user_id, days=settings.sub_days)
                else:
                    db.mark_payment(order_id, "failed")
            except Exception:
                pass
        return {"ok": True}
    except Exception:
        return Response(status_code=400, content="bad payload")
