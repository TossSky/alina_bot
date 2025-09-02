# app/bot.py
import asyncio, time, re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes,
    CallbackQueryHandler, PreCheckoutQueryHandler, filters
)

from .config import settings
from .prompts import SYSTEM_PROMPT, STYLE_HINTS, VERBOSITY_HINTS, MOOD_TEMPLATES
from .llm_client import LLMClient
from .typing_sim import human_typing
import app.db as db
from .payments import send_stars_invoice, precheckout_stars, on_successful_payment
from .reminders import schedule_one, deschedule_one, reschedule_all_for_user, _tzinfo_from_str

# -------------------- инициализация --------------------

db.init()
llm = LLMClient()

# простой рейт-лимит: не чаще 1 сообщения в 2 сек от пользователя
LAST_SEEN = {}

# для «узкой» кнопки корзины: визуальный наполнитель (em-space U+2003)
FILLER = " " * 10  # подбери число по вкусу

MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"
}

def _encode_hhmm(hhmm: str) -> str:
    # "09:30" -> "0930"
    return hhmm.replace(":", "").zfill(4)

def _decode_hhmm(compact: str) -> str:
    # "0930" -> "09:30"
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
    # сравниваем на «наивных» в UTC
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
            await update.message.reply_text("Не узнала такой часовой пояс. Пример: Europe/Tallinn или UTC+3")
            return
    db.set_tz(user_id, tz_str)
    reschedule_all_for_user(context.application, user_id)
    await update.message.reply_text(f"Готово! Буду ориентироваться на {tz_str}.")

async def tz_cmd(update, context):
    user_id = update.effective_user.id
    arg = " ".join(context.args) if context.args else ""
    if not arg:
        context.user_data["await_tz"] = True
        cur = db.get_tz(user_id) or "не задан"
        await update.message.reply_text(
            "Напиши твой часовой пояс одним сообщением.\n"
            "Примеры: Europe/Tallinn, Europe/Moscow, UTC+3, UTC-5\n"
            f"Сейчас: {cur}"
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
        # визуальный хак: растягиваем левую кнопку, корзина кажется узкой
        label = f"⏰ {r['time_local']} ({state}) — {rtype}{FILLER}"
        rows.append([
            InlineKeyboardButton(label, callback_data=f"rem|toggle|{rid}"),
            InlineKeyboardButton("🗑", callback_data=f"rem|del|{rid}")
        ])
    rows += [
        [InlineKeyboardButton("Добавить «Доброе утро» (09:00)",  callback_data="rem|add|morning|0900")],
        [InlineKeyboardButton("Добавить «Вечерний привет» (21:00)", callback_data="rem|add|evening|2100")],
        [InlineKeyboardButton("Добавить своё время…",   callback_data="rem|add|custom")],
    ]
    return InlineKeyboardMarkup(rows)

async def reminders_cmd(update, context):
    u = db.get_user(update.effective_user.id)
    tz = db.get_tz(u["user_id"]) or "UTC"
    text = (
        "Я могу сама писать первой — чтобы мы не терялись 💛\n"
        f"Твой часовой пояс: {tz}\n\n"
        "Нажми, чтобы включить/выключить, или добавь новые."
    )
    await update.message.reply_text(text, reply_markup=_reminders_kb(u["user_id"]))

# -------------------- status / start / help --------------------

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = db.get_user(update.effective_user.id)
    active, until, remain = _sub_state(u)
    if active:
        text = (
            "Статус: подписка активна 💛\n"
            f"Действует до: {format_dt(until)}\n"
            f"Осталось: {_humanize_td(remain)}"
        )
    else:
        left = u["free_left"] or 0
        text = (
            "Статус: подписка не активна.\n"
            f"Бесплатных сообщений осталось: {left}\n"
            "Оформить подписку: /subscribe"
        )
    await update.message.reply_text(text)

from .prompts import SYSTEM_PROMPT, STYLE_HINTS, VERBOSITY_HINTS, MOOD_TEMPLATES, TECH_BOUNDARY


def build_messages(user_id:int, name:str, user_text:str):
    u = db.get_user(user_id)
    history = db.last_dialog(user_id, limit=12)

    style = (u["style"] or "gentle")
    verbosity = (u["verbosity"] or "normal")

    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"Имя собеседника: {name or 'друг'}."},
        {"role": "system", "content": f"{STYLE_HINTS.get(style,'')} {VERBOSITY_HINTS.get(verbosity,'')}".strip()},
    ]

    # мягкая граница для технички
    if is_tech_question(user_text):
        msgs.append({"role": "system", "content": TECH_BOUNDARY})

    for h in history:
        msgs.append({"role": h["role"], "content": h["content"]})
    msgs.append({"role": "user", "content": user_text})
    return msgs, ("short" if is_tech_question(user_text) else verbosity)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = db.get_user(update.effective_user.id)
    active, until, remain = _sub_state(u)

    if active:
        text = (
            "Привет! Я Алина 💛\n"
            "Рада тебя видеть.\n"
            f"Подписка активна до {format_dt(until)} "
            f"(ещё {_humanize_td(remain)}).\n"
            "Пиши, о чём хочется поговорить 🌿"
        )
    else:
        text = (
            "Привет! Я Алина 💛\n"
            "Хочешь выговориться, поделиться переживаниями или просто поболтать?\n"
            "Попробуй написать:\n"
            "• «Мне грустно, поддержи»\n"
            "• «Помоги найти мотивацию»\n"
            "• «Поболтаем о чём-нибудь лёгком?»\n"
            f"Бесплатных сообщений осталось: {u['free_left'] or 0}.\n"
            "Команды: /profile /mood /subscribe /status /help"
        )

    # при /start перепланируем все пользовательские напоминания
    reschedule_all_for_user(context.application, update.effective_user.id)

    await update.message.reply_text(text)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Я рядом, чтобы поговорить 💛\n"
        "Команды:\n"
        "• /profile — настроить стиль (нежно/по делу) и длину ответов\n"
        "• /mood — мягкий чек-ин настроения\n"
        "• /reminders — когда мне писать первой\n"
        "• /tz — часовой пояс для напоминаний\n"
        "• /subscribe — оформить подписку звёздами\n"
        "• /status — статус подписки и лимитов\n"
        "• /jobs — отладка: что запланировано\n"
    )

# -------------------- профиль / режимы --------------------

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

    # Переключение существующего напоминания
    if parts[:2] == ["rem", "toggle"] and len(parts) == 3:
        rid = int(parts[2])
        rs = db.list_reminders(user_id)
        cur = next((r for r in rs if r["id"] == rid), None)
        if not cur:
            await q.edit_message_text("Не нашла напоминание.")
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

    # Удаление напоминания
    if parts[:2] == ["rem", "del"] and len(parts) == 3:
        rid = int(parts[2])
        deschedule_one(context.application, user_id, rid)
        db.delete_reminder(user_id, rid)
        await q.edit_message_reply_markup(reply_markup=_reminders_kb(user_id))
        return

    # Добавление пресета или custom
    if parts[:2] == ["rem", "add"]:
        # custom — просим время
        if len(parts) == 3 and parts[2] == "custom":
            await q.edit_message_text("Напиши время в формате HH:MM (например, 08:30)")
            context.user_data["await_custom_time"] = True
            return

        # пресеты: rem|add|<rtype>|<HHMM>, где rtype ∈ {morning, evening, checkin}
        if len(parts) == 4:
            rtype = parts[2]           # "morning" | "evening" | "checkin"
            hhmm = _decode_hhmm(parts[3])
            rid = db.add_reminder(user_id, rtype, hhmm)
            tz = db.get_tz(user_id) or "UTC"
            schedule_one(context.application, user_id, rid, rtype, hhmm, tz)
            await q.edit_message_text("Добавила! 🌿")
            await q.message.reply_text("Твои напоминания:", reply_markup=_reminders_kb(user_id))
            return

    # Платёжные кнопки
    if data.startswith("pay_stars:"):
        plan = data.split(":", 1)[1]
        await send_stars_invoice(update, context, plan)
        return

    await q.edit_message_text("Хм, не поняла действие. Давай попробуем ещё раз: /reminders")

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
    if now - last < 2.0:
        LAST_SEEN[user_id] = now
        return True
    LAST_SEEN[user_id] = now
    return False

# -------------------- text handler --------------------

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text_in = (update.message.text or "").strip()

    # ожидаем tz после /tz
    if context.user_data.get("await_tz"):
        context.user_data["await_tz"] = False
        tz_text = (update.message.text or "").strip()
        await _apply_tz(update, context, tz_text)
        return

    # рейт-лимит
    if is_rate_limited(user_id):
        await update.message.reply_text("Дай мне секунду сформулировать ответ 🌿")
        return

    # ожидаем время для custom reminder
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
                    await update.message.reply_text("Добавила ⏰ Готово!", reply_markup=_reminders_kb(user_id))
                    return
            except Exception:
                pass
        await update.message.reply_text("Не похоже на время. Напиши, пожалуйста, так: 09:30")
        return

    # быстрые настройки из произвольной фразы
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
            note.append("подобрала длину ответов")
        if note:
            await update.message.reply_text("Готово: " + ", ".join(note) + " 💛")
            return

    # /mood ответы одним словом
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
    msgs, pref_verbosity = build_messages(user_id, u["name"] or update.effective_user.first_name, text_in)
    try:
        reply = await llm.chat(
            msgs,
            verbosity=pref_verbosity,   # ← даст короткий ответ на техничку
            safety=True                 # ← мягкий стиль отказа на спорные вещи
        )
    except Exception:
        reply = "Кажется, у меня заминка со связью. Давай попробуем ещё раз чуть позже 💛"

    await human_typing(context, update.effective_chat.id, reply)
    db.add_msg(user_id, "assistant", reply)
    await update.message.reply_text(reply)

# -------------------- служебные команды (отладка) --------------------

async def pingme_cmd(update, context):
    """ /pingme 1  → пришлёт сообщение через 1 минуту """
    try:
        minutes = int(context.args[0]) if context.args else 1
    except Exception:
        minutes = 1
    when = datetime.now(timezone.utc) + timedelta(minutes=minutes)

    async def _once(ctx):
        await ctx.bot.send_message(chat_id=update.effective_user.id, text="Проверка напоминания: я рядом 💛")

    context.job_queue.run_once(_once, when=when, data={}, name=f"ping:{update.effective_user.id}")
    await update.message.reply_text(f"Окей, напишу через {minutes} мин.")

async def jobs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Покажет запланированные напоминания для текущего пользователя, с ближайшим временем."""
    jq = context.application.job_queue
    if jq is None:
        await update.message.reply_text("JobQueue не инициализирован. Установи extra: pip install 'python-telegram-bot[job-queue]'")
        return

    user_id = update.effective_user.id
    tz_str = db.get_tz(user_id) or "UTC"
    tzinfo = _tzinfo_from_str(tz_str)

    rems = db.list_reminders(user_id)
    if not rems:
        await update.message.reply_text("У тебя пока нет напоминаний. Добавь в /reminders 🌿")
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
            lines.append(f"• {r['time_local']} ({r.get('rtype') or 'checkin'}, {state}) → {when_local} ({tz_str})")
        else:
            lines.append(f"• {r['time_local']} ({r.get('rtype') or 'checkin'}, {state}) → не запланировано")

    await update.message.reply_text("Запланировано:\n" + "\n".join(lines))

TECH_HINT_WORDS = [
    "алгоритм", "сложность", "big o", "дерево", "граф", "дейкстр", "бфс", "дфс",
    "sql", "join", "индекс", "python", "код", "скрипт", "регулярк", "регэксп",
    "массив", "хеш-таблица", "структура данных", "компиляция", "типизация",
    "доказательство", "матан", "интеграл", "дериватив", "градиент", "ml", "nn"
]

def is_tech_question(text: str) -> bool:
    t = (text or "").lower()
    if "```" in t or "def " in t or "class " in t:
        return True
    return any(w in t for w in TECH_HINT_WORDS)


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

    # Payments (Stars): pre-checkout + successful
    app.add_handler(PreCheckoutQueryHandler(precheckout_stars))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_successful_payment))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()

if __name__ == "__main__":
    main()
