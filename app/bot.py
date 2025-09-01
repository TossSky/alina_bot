import asyncio, time
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, CallbackQueryHandler, filters
from .config import settings
from .prompts import SYSTEM_PROMPT, STYLE_HINTS, VERBOSITY_HINTS, MOOD_TEMPLATES
from .llm_client import LLMClient
from .typing_sim import human_typing
import app.db as db
from .payments import send_stars_invoice, precheckout_stars, on_successful_payment, build_redsys_start_url
from telegram.ext import PreCheckoutQueryHandler

db.init()
llm = LLMClient()
# простой рейт-лимит: не чаще 1 сообщения в 2 сек от пользователя
LAST_SEEN = {}

def build_messages(user_id:int, name:str, user_text:str):
    u = db.get_user(user_id)
    history = db.last_dialog(user_id, limit=12)

    style = (u["style"] or "gentle")
    verbosity = (u["verbosity"] or "normal")
    style_hint = STYLE_HINTS.get(style, "")
    verbose_hint = VERBOSITY_HINTS.get(verbosity, "")

    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"Имя собеседника: {name or 'друг'}."},
        {"role": "system", "content": f"{style_hint} {verbose_hint}".strip()}
    ]
    for h in history:
        msgs.append({"role": h["role"], "content": h["content"]})
    msgs.append({"role": "user", "content": user_text})
    return msgs

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = db.get_user(update.effective_user.id)
    text = (
        "Привет! Я Алина 💛\n"
        "Хочешь выговориться, поделиться переживаниями или просто поболтать?\n"
        "Попробуй написать:\n"
        "• «Мне грустно, поддержи»\n"
        "• «Помоги найти мотивацию»\n"
        "• «Поболтаем о чём-нибудь лёгком?»\n"
        f"Бесплатных сообщений осталось: {u['free_left'] or 0}.\n"
        "Команды: /profile /mood /subscribe /help"
    )
    await update.message.reply_text(text)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Я рядом, чтобы поговорить 💛\n"
        "Команды:\n"
        "• /profile — настроить стиль (нежно/по делу) и длину ответов\n"
        "• /mood — мягкий чек-ин настроения\n"
        "• /subscribe — продолжить общение без ограничений"
    )

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = db.get_user(update.effective_user.id)
    text = (
        "Давай настроим общение.\n"
        f"Текущий стиль: {u['style'] or 'gentle'}, длина: {u['verbosity'] or 'normal'}.\n\n"
        "Напиши, что выбрать:\n"
        "• Стиль: «нежно» или «по делу»\n"
        "• Длина: «коротко», «средне», «подробно»\n"
        "• Имя: «зови меня <Имя>»"
    )
    await update.message.reply_text(text)

async def mood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = (
        "Как ты сейчас? Выбери ближе всего: тревожно / грустно / злюсь / устал / нормально / окрылён.\n"
        "Можно просто написать слово. Я подстроюсь 💛"
    )
    await update.message.reply_text(prompt)

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Оплатить звёздами ⭐", callback_data="pay_stars")],
        [InlineKeyboardButton("Оплатить картой (Redsys)", callback_data="pay_redsys")]
    ])
    await update.message.reply_text(
        "Выбери способ, чтобы мы общались без ограничений 💛",
        reply_markup=kb
    )

async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = update.effective_user.id

    if q.data == "pay_stars":
        await send_stars_invoice(update, context)
    elif q.data == "pay_redsys":
        link = build_redsys_start_url(user_id=user_id, amount_eur_cents=499)  # 4.99 EUR
        await q.edit_message_text(
            "Перейди для оплаты картой:\n" + link + "\n\n"
            "После оплаты подписка активируется автоматически."
        )

def parse_profile_phrase(text: str):
    t = text.lower()
    style = None
    verbosity = None
    name = None

    if "нежно" in t:
        style = "gentle"
    if "по делу" in t or "по-деловому" in t:
        style = "direct"
    if "коротко" in t:
        verbosity = "short"
    if "средне" in t or "средне" in t:
        verbosity = "normal"
    if "подробно" in t or "развёрну" in t:
        verbosity = "long"
    if "зови меня" in t:
        # зови меня Васей -> возьмём всё после "зови меня"
        try:
            name = text.split("зови меня", 1)[1].strip(" :,.!?\n\t")
        except Exception:
            pass
    return style, verbosity, name

def is_rate_limited(user_id:int) -> bool:
    now = time.time()
    last = LAST_SEEN.get(user_id, 0)
    if now - last < 2.0:
        LAST_SEEN[user_id] = now  # обновим всё равно
        return True
    LAST_SEEN[user_id] = now
    return False

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text_in = (update.message.text or "").strip()

    # рейт-лимит
    if is_rate_limited(user_id):
        await update.message.reply_text("Дай мне секунду сформулировать ответ 🌿")
        return

    # быстрые настройки из произвольной фразы
    if any(k in text_in.lower() for k in ["нежно", "по делу", "по-деловому", "коротко", "средне", "подробно", "зови меня"]):
        style, verbosity, name = parse_profile_phrase(text_in)
        if name: db.set_name(user_id, name)
        if style or verbosity: db.set_style(user_id, style, verbosity)
        u = db.get_user(user_id)
        note = []
        if name: note.append(f"буду звать тебя {u['name']}")
        if style: note.append("настроила стиль")
        if verbosity: note.append("подобрала длину ответов")
        if note:
            await update.message.reply_text("Готово: " + ", ".join(note) + " 💛")
            return

    # обработка /mood ответов одним словом
    lower = text_in.lower()
    if lower in MOOD_TEMPLATES:
        plan = MOOD_TEMPLATES[lower]
        msgs = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": "Ответь как близкая подруга. Короткими абзацами."},
            {"role": "system", "content": f"Состояние собеседника: {lower}. {plan}"},
            {"role": "user", "content": "Поддержи меня, пожалуйста."}
        ]
        try:
            reply = await llm.chat(msgs, temperature=0.8, max_tokens=500)
        except Exception:
            reply = "Я рядом. Давай начнём с одного тёплого шага — и продолжим, как тебе комфортно 💛"
        await human_typing(context, update.effective_chat.id, reply)
        db.add_msg(user_id, "user", text_in)
        db.add_msg(user_id, "assistant", reply)
        await update.message.reply_text(reply)
        return

    # лимиты
    u = db.get_user(user_id)
    if not u["is_subscribed"]:
        if (u["free_left"] or 0) <= 0:
            await update.message.reply_text(
                "Похоже, бесплатные сообщения закончились. Хочешь продолжать без ограничений? "
                "Я буду рядом 💛 (команда /subscribe)"
            )
            return
        db.update_user(user_id, free_left=(u["free_left"] - 1))

    # диалог
    db.add_msg(user_id, "user", text_in)
    msgs = build_messages(user_id, u["name"] or update.effective_user.first_name, text_in)

    try:
        reply = await llm.chat(msgs, temperature=0.85, max_tokens=700)
    except Exception:
        reply = "Кажется, у меня заминка со связью. Давай попробуем ещё раз чуть позже 💛"

    # имитация набора — по планируемому ответу
    await human_typing(context, update.effective_chat.id, reply)
    db.add_msg(user_id, "assistant", reply)
    await update.message.reply_text(reply)

def main():
    app = Application.builder().token(settings.telegram_bot_token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("mood", mood))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CallbackQueryHandler(on_cb))
    # Payments (Stars): pre-checkout + successful
    
    app.add_handler(PreCheckoutQueryHandler(precheckout_stars))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_successful_payment))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()

if __name__ == "__main__":
    main()
