# app/bot.py
import asyncio, time, re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes,
    CallbackQueryHandler, PreCheckoutQueryHandler, filters
)

from .config import settings
from .prompts import SYSTEM_PROMPT, STYLE_HINTS, VERBOSITY_HINTS, MOOD_TEMPLATES, TECH_BOUNDARY, AVOID_PATTERNS
from .llm_client import LLMClient
from .typing_sim import human_typing
import app.db as db
from .payments import send_stars_invoice, precheckout_stars, on_successful_payment
from .reminders import schedule_one, deschedule_one, reschedule_all_for_user, _tzinfo_from_str



# -------------------- инициализация --------------------

db.init()
llm = LLMClient()

# простой рейт-лимит: не чаще 1 сообщения в секунду от пользователя
LAST_SEEN = {}

# для «узкой» кнопки корзины: визуальный наполнитель
FILLER = " " * 10

MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"
}

def _encode_hhmm(hhmm: str) -> str:
    return hhmm.replace(":", "").zfill(4)

def _decode_hhmm(compact: str) -> str:
    compact = compact.zfill(4)
    return f"{compact[:2]}:{compact[2:]}"

def format_dt(dt: datetime) -> str:
    return f"{dt.day} {MONTHS_RU[dt.month]} {dt.year}, {dt.strftime('%H:%M')} (UTC)"

def _sub_state(user_row):
    su = user_row.get("sub_until") if isinstance(user_row, dict) else user_row["sub_until"]
    if not su:
        return False, None, None
    try:
        until = datetime.fromisoformat(su)
    except Exception:
        return False, None, None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if until <= now:
        return False, until, timedelta(0)
    return True, until, until - now

def _humanize_td(td: timedelta) -> str:
    total = int(td.total_seconds())
    if total < 0:
        total = 0
    days = total // 86400
    hours = (total % 86400) // 3600
    minutes = (total % 3600) // 60
    if days > 0:
        return f"{days} дн. {hours} ч."
    if hours > 0:
        return f"{hours} ч. {minutes} мин."
    return f"{minutes} мин."

# -------------------- tz --------------------

async def _apply_tz(update, context, tz_text: str):
    user_id = update.effective_user.id
    tz_str = None
    m = re.fullmatch(r"UTC([+-])(\d{1,2})", tz_text.upper())
    if m:
        sign, hh = m.group(1), int(m.group(2))
        tz_str = f"UTC{sign}{hh}"
    else:
        try:
            _ = ZoneInfo(tz_text)
            tz_str = tz_text
        except Exception:
            await update.message.reply_text("Не узнала такой часовой пояс... Попробуй, например, Europe/Moscow или UTC+3")
            return
    db.set_tz(user_id, tz_str)
    reschedule_all_for_user(context.application, user_id)
    await update.message.reply_text(f"Окей, запомнила: {tz_str}")

async def tz_cmd(update, context):
    user_id = update.effective_user.id
    arg = " ".join(context.args) if context.args else ""
    if not arg:
        context.user_data["await_tz"] = True
        cur = db.get_tz(user_id) or "не задан"
        await update.message.reply_text(
            f"Напиши свой часовой пояс одним сообщением (например, Europe/Moscow или UTC+3).\n"
            f"Сейчас у тебя: {cur}"
        )
        return
    await _apply_tz(update, context, arg.strip())

# -------------------- reminders UI --------------------

def _reminders_kb(user_id: int):
    rs = db.list_reminders(user_id)
    rows = []
    for r in rs:
        state = "вкл" if r["active"] else "выкл"
        rid = r["id"]
        rtype = r.get("rtype") or "checkin"
        label = f"⏰ {r['time_local']} ({state}) — {rtype}{FILLER}"
        rows.append([
            InlineKeyboardButton(label, callback_data=f"rem|toggle|{rid}"),
            InlineKeyboardButton("🗑", callback_data=f"rem|del|{rid}")
        ])
    rows += [
        [InlineKeyboardButton("Добавить «Доброе утро» (09:00)", callback_data="rem|add|morning|0900")],
        [InlineKeyboardButton("Добавить «Вечерний привет» (21:00)", callback_data="rem|add|evening|2100")],
        [InlineKeyboardButton("Добавить своё время…", callback_data="rem|add|custom")],
    ]
    return InlineKeyboardMarkup(rows)

async def reminders_cmd(update, context):
    u = db.get_user(update.effective_user.id)
    tz = db.get_tz(u["user_id"]) or "UTC"
    text = (
        f"Могу писать тебе первой, чтобы не теряться 💛\n"
        f"Твой часовой пояс: {tz}\n\n"
        "Нажми, чтобы включить/выключить или добавить новые напоминания."
    )
    await update.message.reply_text(text, reply_markup=_reminders_kb(u["user_id"]))

# -------------------- status / start / help --------------------

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = db.get_user(update.effective_user.id)
    active, until, remain = _sub_state(u)
    if active:
        text = (
            f"Подписка активна 💛\n"
            f"До: {format_dt(until)}\n"
            f"Осталось: {_humanize_td(remain)}"
        )
    else:
        left = u["free_left"] or 0
        text = (
            f"Подписка не активна.\n"
            f"Бесплатных сообщений: {left}\n"
            "Оформить: /subscribe"
        )
    await update.message.reply_text(text)

TECH_KEYWORDS = [
    "алгоритм", "код", "программ", "python", "javascript", "java", "sql",
    "функци", "класс", "метод", "массив", "цикл", "for", "while", "if",
    "дейкстр", "граф", "дерев", "хеш", "сложност", "big o", "o(n)",
    "база данн", "таблиц", "запрос", "индекс", "join", "select",
    "компил", "интерпрет", "debug", "git", "docker", "api", "rest",
    "матриц", "вектор", "интеграл", "производн", "уравнен", "формул",
    "машинн", "нейрон", "ml", "ai", "датасет", "модел", "обучен",
    "структур данн", "стек", "очеред", "связн списк", "рекурс",
    "```", "def ", "class ", "function", "import", "return", "console.log"
]

def is_tech_question(text: str) -> bool:
    """Определяет, является ли вопрос техническим"""
    if not text:
        return False
    t = text.lower()
    return any(keyword in t for keyword in TECH_KEYWORDS)

def build_messages(user_id: int, db_name: str | None, user_text: str):
    u = db.get_user(user_id)
    history = db.last_dialog(user_id, limit=20)
    
    style = u.get("style", "gentle")
    verbosity = u.get("verbosity", "normal")
    style_hint = STYLE_HINTS.get(style, "")
    verbose_hint = VERBOSITY_HINTS.get(verbosity, "")
    
    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": AVOID_PATTERNS},
    ]
    if db_name:
        msgs.append({"role": "system", "content": f"Собеседник попросил звать его: {db_name}."})
    
    msgs.append({"role": "system", "content": f"{style_hint} {verbose_hint}".strip()})
    
    if is_tech_question(user_text):
        msgs.append({"role": "system", "content": TECH_BOUNDARY})
        msgs.append({
            "role": "system",
            "content": "ПОМНИ: ты НЕ помогаешь с техническими вопросами. Отвечай как обычная девушка, которая в этом не разбирается."
        })
    
    for h in history:
        msgs.append({"role": h["role"], "content": h["content"]})
    
    msgs.append({"role": "user", "content": user_text})
    
    final_verbosity = "short" if is_tech_question(user_text) else verbosity
    
    return msgs, final_verbosity

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = db.get_user(update.effective_user.id)
    active, until, remain = _sub_state(u)

    if active:
        text = (
            f"Привет! Я Алина 💛\n"
            f"Рада тебя видеть)\n"
            f"Подписка активна до {format_dt(until)} "
            f"(ещё {_humanize_td(remain)})\n"
            "Пиши, о чём хочешь поговорить 🌿"
        )
    else:
        text = (
            "Привет! Я Алина 💛\n"
            "Хочешь выговориться или просто поболтать?\n"
            "Можешь написать, например:\n"
            "- Мне грустно\n"
            "- Расскажи что-нибудь\n"
            "- Как твой день?\n"
            f"Бесплатных сообщений: {u['free_left'] or 0}\n"
            "Команды: /profile /mood /subscribe /status /help"
        )

    reschedule_all_for_user(context.application, update.effective_user.id)
    await update.message.reply_text(text)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Я рядом, если захочешь поговорить 💛\n\n"
        "Команды:\n"
        "/profile — настроить стиль общения\n"
        "/mood — как ты себя чувствуешь\n"
        "/reminders — когда мне писать первой\n"
        "/tz — твой часовой пояс\n"
        "/subscribe — оформить подписку\n"
        "/status — статус подписки"
    )

# -------------------- профиль / режимы --------------------

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = db.get_user(update.effective_user.id)
    text = (
        f"Давай настроим наше общение.\n"
        f"Сейчас так: стиль «{u['style'] or 'нежный'}», длина сообщений «{u['verbosity'] or 'средняя'}».\n\n"
        "Напиши, как тебе больше нравится:\n"
        "– Стиль: нежно или по делу\n"
        "– Длина: коротко, средне, подробно\n"
        "– Имя: зови меня <имя>"
    )
    await update.message.reply_text(text)

async def mood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Тревожно", callback_data="mood|тревожно"),
            InlineKeyboardButton("Грустно", callback_data="mood|грустно"),
            InlineKeyboardButton("Злюсь", callback_data="mood|злюсь"),
        ],
        [
            InlineKeyboardButton("Устал(а)", callback_data="mood|устал"),
            InlineKeyboardButton("Нормально", callback_data="mood|нормально"),
            InlineKeyboardButton("Окрылён(а)", callback_data="mood|окрылён"),
        ]
    ])
    await update.message.reply_text("Как ты сейчас? 💛", reply_markup=kb)


async def subscribe(update, context):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ День", callback_data="pay_stars:day")],
        [InlineKeyboardButton("⭐ Неделя", callback_data="pay_stars:week")],
        [InlineKeyboardButton("⭐ Месяц", callback_data="pay_stars:month")],
    ])
    await update.message.reply_text("Выбери удобный вариант 💛", reply_markup=kb)

# -------------------- callbacks --------------------

async def on_cb(update, context):
    q = update.callback_query
    await q.answer()
    user_id = update.effective_user.id
    data = q.data or ""
    parts = data.split("|")

    if parts[0] == "mood" and len(parts) == 2:
        mood_text = parts[1]
        reply = MOOD_TEMPLATES.get(mood_text)
        if reply:
            await q.edit_message_text(f"Ты выбрал(а): {mood_text}")
            await human_typing(context, update.effective_chat.id, reply)
            db.add_msg(user_id, "user", mood_text)
            db.add_msg(user_id, "assistant", reply)
            await q.message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)
        else:
            await q.edit_message_text("Что-то пошло не так... Попробуй ещё раз.")
        return

    if parts[:2] == ["rem", "toggle"] and len(parts) == 3:
        rid = int(parts[2])
        rs = db.list_reminders(user_id)
        cur = next((r for r in rs if r["id"] == rid), None)
        if not cur:
            await q.edit_message_text("Не нашла такое напоминание...")
            return
        new_active = 0 if cur["active"] else 1
        db.toggle_reminder(user_id, rid, new_active)
        if new_active:
            tz = db.get_tz(user_id) or "UTC"
            schedule_one(context.application, user_id, rid, cur["rtype"], cur["time_local"], tz)
        else:
            deschedule_one(context.application, user_id, rid)
        await q.edit_message_reply_markup(reply_markup=_reminders_kb(user_id))
        return

    if parts[:2] == ["rem", "del"] and len(parts) == 3:
        rid = int(parts[2])
        deschedule_one(context.application, user_id, rid)
        db.delete_reminder(user_id, rid)
        await q.edit_message_reply_markup(reply_markup=_reminders_kb(user_id))
        return

    if parts[:2] == ["rem", "add"]:
        if len(parts) == 3 and parts[2] == "custom":
            await q.edit_message_text("Напиши время в формате HH:MM (например, 08:30)")
            context.user_data["await_custom_time"] = True
            return

        if len(parts) == 4:
            rtype = parts[2]
            hhmm = _decode_hhmm(parts[3])
            rid = db.add_reminder(user_id, rtype, hhmm)
            tz = db.get_tz(user_id) or "UTC"
            schedule_one(context.application, user_id, rid, rtype, hhmm, tz)
            await q.edit_message_text("Добавила! 🌿")
            await q.message.reply_text("Твои напоминания:", reply_markup=_reminders_kb(user_id))
            return

    if data.startswith("pay_stars:"):
        plan = data.split(":", 1)[1]
        await send_stars_invoice(update, context, plan)
        return

    await q.edit_message_text("Хм, не поняла... Попробуй ещё раз: /reminders")

# -------------------- парсер быстрых фраз профиля --------------------

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
    if "средне" in t:
        verbosity = "normal"
    if "подробно" in t or "развёрну" in t:
        verbosity = "long"
    if "зови меня" in t:
        try:
            name = text.split("зови меня", 1)[1].strip(" :,.!?\n\t")
        except Exception:
            pass
    return style, verbosity, name

def is_rate_limited(user_id: int) -> bool:
    now = time.time()
    last = LAST_SEEN.get(user_id, 0)
    if now - last < 1.0:
        LAST_SEEN[user_id] = now
        return True
    LAST_SEEN[user_id] = now
    return False

# -------------------- text handler --------------------

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text_in = (update.message.text or "").strip()

    if context.user_data.get("await_tz"):
        context.user_data["await_tz"] = False
        tz_text = (update.message.text or "").strip()
        await _apply_tz(update, context, tz_text)
        return

    if is_rate_limited(user_id):
        await update.message.reply_text("Секунду... печатаю 🌿")
        return

    if context.user_data.get("await_custom_time"):
        txt = (update.message.text or "").strip()
        if re.fullmatch(r"\d{1,2}:\d{2}", txt):
            try:
                hh, mm = txt.split(":")
                h, m = int(hh), int(mm)
                if 0 <= h <= 23 and 0 <= m <= 59:
                    hhmm = f"{h:02d}:{m:02d}"
                    rid = db.add_reminder(user_id, "checkin", hhmm)
                    tz = db.get_tz(user_id) or "UTC"
                    schedule_one(context.application, user_id, rid, "checkin", hhmm, tz)
                    context.user_data["await_custom_time"] = False
                    await update.message.reply_text("Добавила ⏰", reply_markup=_reminders_kb(user_id))
                    return
            except Exception:
                pass
        await update.message.reply_text("Не похоже на время... напиши, например, 09:30")
        return

    if any(k in text_in.lower() for k in ["нежно", "по делу", "по-деловому", "коротко", "средне", "подробно", "зови меня"]):
        style, verbosity, name = parse_profile_phrase(text_in)
        if name:
            db.set_name(user_id, name)
        if style or verbosity:
            db.set_style(user_id, style, verbosity)
        u = db.get_user(user_id)
        note = []
        if name:
            note.append(f"буду звать тебя {u['name']}")
        if style:
            note.append("настроила стиль")
        if verbosity:
            note.append("подобрала длину")
        if note:
            await update.message.reply_text("Готово: " + ", ".join(note) + " 💛")
            return

    u = db.get_user(user_id)
    if not u["is_subscribed"]:
        if (u["free_left"] or 0) <= 0:
            await update.message.reply_text(
                "Ой, бесплатные сообщения закончились...\n"
                "Хочешь продолжить? /subscribe 💛"
            )
            return
        db.update_user(user_id, free_left=(u["free_left"] - 1))

    db.add_msg(user_id, "user", text_in)
    db_name = u["name"]
    msgs, pref_verbosity = build_messages(user_id, db_name, text_in)

    try:
        reply = await llm.chat(
            msgs,
            verbosity=pref_verbosity,
            safety=True
        )
        reply = _sanitize_name_address(reply, update.effective_user, db_name)
    except Exception:
        reply = "Что-то с интернетом... попробуй ещё раз?"

    await human_typing(context, update.effective_chat.id, reply)
    db.add_msg(user_id, "assistant", reply)
    await update.message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)

# -------------------- служебные команды (отладка) --------------------
def _sanitize_name_address(reply: str, tg_user, db_name: str | None) -> str:
    if not reply:
        return reply

    allowed = set()
    if db_name:
        allowed.add(db_name.strip())

    candidates = set()
    if getattr(tg_user, "first_name", None):
        candidates.add(tg_user.first_name.strip())
    if getattr(tg_user, "last_name", None):
        candidates.add(tg_user.last_name.strip())
    if getattr(tg_user, "username", None):
        candidates.add(f"@{tg_user.username.strip()}")

    banned = candidates if not db_name else (candidates - allowed)
    banned = {c for c in banned if c}

    if not banned:
        return reply

    escaped = [re.escape(x) for x in sorted(banned, key=len, reverse=True)]
    pattern = r"^\s*(?:%s)\s*[,:\-–—]\s*" % "|".join(escaped)
    return re.sub(pattern, "", reply, flags=re.IGNORECASE)

async def pingme_cmd(update, context):
    try:
        minutes = int(context.args[0]) if context.args else 1
    except Exception:
        minutes = 1
    when = datetime.now(timezone.utc) + timedelta(minutes=minutes)

    async def _once(ctx):
        await ctx.bot.send_message(chat_id=update.effective_user.id, text="Привет! Я тут 💛")

    context.job_queue.run_once(_once, when=when, data={}, name=f"ping:{update.effective_user.id}")
    await update.message.reply_text(f"Окей, напишу через {minutes} мин.")

async def jobs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    jq = context.application.job_queue
    if jq is None:
        await update.message.reply_text("JobQueue не работает...")
        return

    user_id = update.effective_user.id
    tz_str = db.get_tz(user_id) or "UTC"
    tzinfo = _tzinfo_from_str(tz_str)

    rems = db.list_reminders(user_id)
    if not rems:
        await update.message.reply_text("У тебя пока нет напоминаний. Добавь их в /reminders 🌿")
        return

    lines = []
    for r in rems:
        name = f"rem:{user_id}:{r['id']}"
        jobs = jq.get_jobs_by_name(name)
        state = "вкл" if r["active"] else "выкл"
        if jobs:
            j = jobs[0]
            nr = getattr(j, "next_run_time", None)
            when_local = nr.astimezone(tzinfo).strftime("%Y-%m-%d %H:%M:%S") if nr else "?"
            lines.append(f"{r['time_local']} ({r.get('rtype') or 'checkin'}, {state}) → {when_local} ({tz_str})")
        else:
            lines.append(f"{r['time_local']} ({r.get('rtype') or 'checkin'}, {state}) → не запланировано")

    await update.message.reply_text("Запланировано:\n" + "\n".join(lines))

# -------------------- main --------------------

def main():
    app = Application.builder().token(settings.telegram_bot_token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("mood", mood))
    app.add_handler(CommandHandler("reminders", reminders_cmd))
    app.add_handler(CommandHandler("tz", tz_cmd))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("pingme", pingme_cmd))
    app.add_handler(CommandHandler("jobs", jobs_cmd))

    app.add_handler(CallbackQueryHandler(on_cb))

    app.add_handler(PreCheckoutQueryHandler(precheckout_stars))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_successful_payment))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()

if __name__ == "__main__":
    main()