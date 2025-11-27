import os, re, io, json
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters
from telegram.request import HTTPXRequest
import logging

# ------------------------------------------------------
# TOKEN
# ------------------------------------------------------

TOKEN = "7557465115:AAHtCuBW-voeMluoYQVRcIwvLtRixC0w28U"

# ------------------------------------------------------
# Логування
# ------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ADMIN_ID = 968915110

ACCESS_FILE = "access.json"
META_FILE  = "access_meta.json"

ACCESS_CODES = {
    "hb24": timedelta(hours=24),
    "hb14": timedelta(days=14),
    "bot10": timedelta(minutes=10),
}

BOT10_LIMIT = 3

CHECKIN_TIME  = "15:00"
CHECKOUT_TIME = "12:00"

# ------------------------------------------------------
# JSON-функції
# ------------------------------------------------------

def _load_json(path: str):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _get_bot10_uses() -> int:
    return int(_load_json(META_FILE).get("bot10_uses", 0))

def _inc_bot10_uses():
    meta = _load_json(META_FILE)
    meta["bot10_uses"] = _get_bot10_uses() + 1
    _save_json(META_FILE, meta)

def has_access(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return True

    data = _load_json(ACCESS_FILE)
    exp = data.get(str(user_id))
    if not exp:
        return False

    try:
        if datetime.fromisoformat(exp) > datetime.now():
            return True
        # термін вийшов — видаляємо
        del data[str(user_id)]
        _save_json(ACCESS_FILE, data)
    except Exception:
        pass

    return False

def grant_access(user_id: int, duration: timedelta):
    data = _load_json(ACCESS_FILE)
    data[str(user_id)] = (datetime.now() + duration).isoformat()
    _save_json(ACCESS_FILE, data)

# ------------------------------------------------------
# Категорії номерів
# ------------------------------------------------------

HVOYA_I = {
    "STUDIO": "https://hotelhvoya.com/accommodation/apartamenty-typu-studio/",
    "SUPERIOR STUDIO": "https://hotelhvoya.com/accommodation/apartamenty-typu-superior-studio/",
    "SUPERIOR STUDIO WITH MOUNTAIN VIEW": "https://hotelhvoya.com/accommodation/apartamenty-typu-superior-studio-with-mountain-view/",
    "PREMIUM STUDIO WITH MOUNTAIN VIEW": "https://hotelhvoya.com/accommodation/premium-studio-with-mountain-view/",
    "SUITE": "https://hotelhvoya.com/accommodation/apartamenty-typu-suite/",
    "SUPERIOR SUITE WITH MOUNTAIN VIEW": "https://hotelhvoya.com/accommodation/apartamenty-typu-superior-suite-with-mountain-view/",
    "THREE ROOM SUITE": "https://hotelhvoya.com/accommodation/three-room-suite/",
}

HVOYA_II = {
    "STANDART APARTMENT": "https://hotelhvoya.com/accommodation/apartamenty-typu-standart/",
    "SUPERIOR APARTMENT": "https://hotelhvoya.com/accommodation/apartamenty-typu-superior/",
    "SUPERIOR APARTMENT WITH MOUNTAIN VIEW": "https://hotelhvoya.com/accommodation/apartamenty-typu-superior-with-mountain-view/",
    "PREMIUM APARTMENT": "https://hotelhvoya.com/accommodation/apartamenty-typu-premium/",
    "PREMIUM APARTMENT WITH MOUNTAIN VIEW": "https://hotelhvoya.com/accommodation/apartamenty-typu-premium-with-mountain-view/",
    "DELUXE APARTMENT": "https://hotelhvoya.com/accommodation/apartamenty-typu-deluxe/",
    "TYPE 1": "https://hotelhvoya.com/accommodation/type-1/",
    "TYPE 1 WITH MOUNTAIN VIEW": "https://hotelhvoya.com/accommodation/type-1-with-mountain-view/",
    "TYPE 2": "https://hotelhvoya.com/accommodation/type-2/",
    "TYPE 3": "https://hotelhvoya.com/accommodation/apartamenty-typu-type-3/",
    "TYPE 3 WITH MOUNTAIN VIEW": "https://hotelhvoya.com/accommodation/apartamenty-typu-type-3-with-mountain-view/",
    "TYPE 4 WITH MOUNTAIN VIEW": "https://hotelhvoya.com/accommodation/type-4-with-mountain-view/",
    "TYPE 5": "https://hotelhvoya.com/accommodation/type-5/",
    "TYPE 6": "https://hotelhvoya.com/accommodation/type-6/",
    "TYPE 7": "https://hotelhvoya.com/accommodation/type-7/",
    "THREE ROOM APARTMENT": "https://hotelhvoya.com/accommodation/three-room-apartment/",
}

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).upper()

ROOM_LINKS = { _norm(k): v for k, v in {**HVOYA_I, **HVOYA_II}.items() }
SET_I = set(map(_norm, HVOYA_I.keys()))
SET_II = set(map(_norm, HVOYA_II.keys()))

# ------------------------------------------------------
# Кнопки меню
# ------------------------------------------------------

BTN_PAY   = "💳 Оплатити доступ"
BTN_WORK  = "💼 Товкти копійку"
BTN_INFO  = "ℹ️ Інформація"
BTN_GRANT = "🔑 Видати доступ"

BTN_PAY_NOW      = "Оплатити зараз"
BTN_PAY_PARTS    = "Оплата частинами"
BTN_PAY_DEBT     = "В борг"
BTN_PAY_OK       = "✅ Я оплатив"
BTN_BACK         = "⬅️ Назад"

def main_menu(user_id: int | None = None):
    keyboard = [
        [BTN_PAY],
        [BTN_WORK, BTN_INFO],
    ]
    if user_id == ADMIN_ID:
        keyboard.append([BTN_GRANT])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def duration_menu():
    return ReplyKeyboardMarkup([["10 хвилин", "1 день", "14 днів"]], resize_keyboard=True)

# ------------------------------------------------------
# Парсинг дат та полів
# ------------------------------------------------------

UA_MONTHS = {
    "січня":1,"лютого":2,"березня":3,"квітня":4,"травня":5,"червня":6,
    "липня":7,"серпня":8,"вересня":9,"жовтня":10,"листопада":11,"грудня":12,
}

def parse_ua_date(s: str) -> datetime | None:
    parts = s.strip().split()
    if len(parts) < 3:
        return None
    try:
        day = int(re.sub(r"\D", "", parts[0]))
        month = UA_MONTHS.get(parts[1].lower())
        year = int(re.sub(r"\D", "", parts[2]))
        if not month:
            return None
        return datetime(year, month, day)
    except Exception:
        return None

def extract_dates(text: str):
    m = re.search(
        r"(\d{1,2}\s+\w+\s+\d{4})\s*[-–—]\s*(\d{1,2}\s+\w+\s+\d{4})",
        text,
        flags=re.I,
    )
    return (parse_ua_date(m.group(1)), parse_ua_date(m.group(2))) if m else (None, None)

def extract_room_raw(text: str) -> str:
    m = re.search(r"Тип кімнати:\s*(.+)", text, flags=re.I)
    return m.group(1).strip() if m else ""

def extract_adults(text: str) -> int:
    m = re.search(r"Дорослі гості:\s*(\d+)", text, flags=re.I)
    return int(m.group(1)) if m else 2

def extract_kids(text: str) -> int:
    m = re.search(r"Маленькі гості:\s*(\d+)", text, flags=re.I)
    return int(m.group(1)) if m else 0

def extract_amount(text: str) -> float:
    m = re.search(r"Сума:\s*([\d\s.,]+)", text, flags=re.I)
    if not m:
        return 0.0
    raw = m.group(1).replace(" ", "").replace(",", ".")
    try:
        return float(raw)
    except Exception:
        return 0.0

def format_uah(amount: float) -> str:
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",")

def extract_body_without_id(text: str) -> str:
    idx = text.find("👥Ім'я:")
    if idx != -1:
        return text[idx:].strip()

    lines = []
    for line in text.splitlines():
        if re.match(r"^\s*#\d+", line):
            continue
        if "Бронювання" in line or "✌️" in line:
            continue
        lines.append(line)
    return "\n".join(lines).strip()

NUM_WORDS = {
    1:"одного",2:"двох",3:"трьох",4:"чотирьох",
    5:"п’яти",6:"шести",7:"семи",8:"восьми",9:"дев’яти",10:"десяти",
}

def guests_phrase(ad: int, kids: int) -> str:
    adt = "для одного дорослого" if ad == 1 else f"для {NUM_WORDS.get(ad, str(ad))} дорослих"
    if kids == 0:
        return adt
    if kids == 1:
        return adt + " і однієї дитини"
    return adt + f" і {NUM_WORDS.get(kids, str(kids))} дітей"

# ------------------------------------------------------
# Логіка попереджень (будівництво + передплата)
# ------------------------------------------------------

def find_corpus(room_title: str) -> int:
    key = _norm(room_title)
    if key in SET_I:
        return 1
    if key in SET_II:
        return 2
    return 1

def pick_warning(room_title: str, d1: datetime | None, days_left: int | None) -> str:
    warning_list: list[str] = []

    key = _norm(room_title)

    # 1. Будівництво
    if key in {
        "SUPERIOR APARTMENT",
        "DELUXE APARTMENT",
        "STANDART APARTMENT",
    }:
        warning_list.append(
            "❗️Зверніть увагу, що Ви забронювали номер з виглядом на дорогу та активне будівництво, "
            "що може спричиняти шум на прилеглій території."
        )

    # 2. Передплата
    if d1:
        today = datetime.now().date()
        arrival = d1.date()

        diff_days = (arrival - today).days

        # Менше ніж 3 дні → без передплати
        if diff_days < 3:
            pass
        else:
            # З 1 грудня → якщо >10 днів до заїзду → 100%
            dec1 = datetime(today.year, 12, 1).date()
            if today >= dec1 and diff_days > 10:
                warning_list.append(
                    "❗️Зверніть увагу, на обраний Вами період бронювання "
                    "здійснюється тільки по передплаті 100% від загальної вартості номера."
                )
            else:
                # З 10 грудня до 1 квітня → 100%
                high_start = datetime(today.year, 12, 10).date()
                high_end   = datetime(today.year + 1, 4, 1).date()

                if arrival >= high_start and arrival < high_end:
                    warning_list.append(
                        "❗️Зверніть увагу, на обраний Вами період бронювання "
                        "здійснюється тільки по передплаті 100% від загальної вартості номера."
                    )
                else:
                    warning_list.append(
                        "❗️Зверніть увагу, на обраний Вами період бронювання "
                        "здійснюється тільки по передплаті 50% від загальної вартості номера."
                    )

    return "\n".join(warning_list)

# ------------------------------------------------------
# Привітання
# ------------------------------------------------------

def get_greeting() -> str:
    hour = datetime.now().hour
    if 5 <= hour < 10:
        return "Доброго ранку!"
    elif 10 <= hour < 18:
        return "Добрий день!"
    else:
        return "Добрий вечір!"

# ------------------------------------------------------
# Перше повідомлення
# ------------------------------------------------------

def build_client_draft(body: str, warning: str) -> str:
    greeting = get_greeting()
    msg = (
        f"{greeting}\n"
        "Ви залишали заявку на нашому сайті для бронювання номеру\n\n"
        f"{body}\n\n"
    )
    if warning:
        msg += warning + "\n\n"
    msg += "Підкажіть, будь ласка, чи заявка залишається актуальною для Вас?"
    return msg

# ------------------------------------------------------
# Друге повідомлення (повний текст)
# ------------------------------------------------------

def build_confirmation(room_title: str, corpus: int, ad: int, kids: int,
                       amount: float, d1: datetime, d2: datetime) -> str:

    nights = (d2.date() - d1.date()).days if (d1 and d2) else 0
    link = ROOM_LINKS.get(_norm(room_title), "https://hotelhvoya.com/accommodation/")
    amount_str = format_uah(amount)
    room_line = f"{room_title} (корпус №{corpus}) {guests_phrase(ad, kids)}"
    checkin_str = d1.strftime("%d.%m.%Y")
    checkout_str = d2.strftime("%d.%m.%Y")

    msg = (
        "Ваше бронювання в готелі HVOYA.\n\n"
        "Апартаменти типу\n"
        f"{room_line}.\n\n"
        f"{link}\n\n"
        f"До оплати за проживання - {amount_str} грн.\n"
        f"Заїзд {checkin_str} з {CHECKIN_TIME}\n"
        f"Виїзд {checkout_str} до {CHECKOUT_TIME}.\n\n"
        f"Ночей - {nights}.\n\n"
        "Перед оплатою просимо перевірити правильність деталей бронювання: кількість осіб, "
        "дати заїзду та виїзду та категорію номеру.\n"
        "Важливо: дітки віком до 5 років (включно) проживають у нашому готелі безкоштовно - "
        "без претензій на послуги, саме тому в надісланих рахунках не вказані.\n\n"
        "У вартість проживання входить:\n"
        "✅ сніданок, який проходить з 8:00 до 11:00 у форматі шведсько лінії;\n"
        "✅ безлімітне користування СПА комплексом з 09:00 до 21:00 для всіх гостей + нічне СПА з 21:00 до 01:00 для гостей віком від 16 р., "
        "яке включає дорослий басейн 206 м. з різними видами гідромасажу, дитячий басейном 4*3 м., фінську, карпатську і римо-турецьку (хамам) "
        "сауни, соляну кімнату, холодну купіль і гідромасажний басейном 53 м.;\n"
        "✅ безлімітне користування спортивною залою;\n"
        "✅ безкоштовні заняття по пілатесу, стрейчингу та барре-тренування з п'ятниці по неділю;\n"
        "✅ безкоштовний паркінг: підземний або відкритий в 150 м. від готелю, попереднє бронювання не здійснюється, тому місце для паркування "
        "надається на тому паркінгу, який буде доступний на момент поселення;\n"
        "✅безкоштовний доступ до дитячої кімнати з аніматором 4 год. на день з 09:00 до 21:00, час провітрювання: 14:30-15:00 та 18:30-19:00 "
        "(діти до 2.99 р. під наглядом батьків, під час провітрювання дитяча кімната не працює);\n"
        "✅ безкоштовний доступ до зони з більярдом, настільним футболом  та аерохокеєм(можливі обмеження у часі роботи під час проведення конференцій);\n"
        "✅ безкоштовний доступ до зони з ігровими приставками Sony PlayStation 5;\n"
        "✅ кімната для зберігання лижного спорядження (лижна кімната) — безкоштовно для всіх гостей готелю, "
        "обладнана сушками для черевиків.\n\n"
        "Переглянути всі деталі про номер Ви зможете на нашому сайті: https://hotelhvoya.com/apartamenty/\n\n"
        "Геолокація готелю: https://maps.app.goo.gl/RPzMNUiuoQKyekvSA\n\n"
        "Додаткова інформація (додаткові послуги)\n"
        "◼️ Проживання з тваринами - під повну відповідальність гостя (в т.ч. матеріальну) та  за додаткову оплату (вартість - 700 грн/ніч).\n\n"
        "◼️ Паркінг у готелі безкоштовний.  Попередньо резервація паркомісця не здійснюється. Паркінг надається по факту заселення в залежності від наявних вільних паркомісць "
        "(підземний або відкритий паркінг, або ж Паркінг 2 ТК \"Буковель\").\n"
        "Всі інші додаткові послуги, які надає ТК «Буковель» у вартість проживання не входять.\n\n"
        "HVOYA Apart-Hotel & SPA з повагою до Вас!"
    )

    return msg

# ------------------------------------------------------
# Відправлення довгих повідомлень
# ------------------------------------------------------

async def send_single_or_file(update: Update, text: str, fname: str, user_id: int):
    if len(text) <= 4000:
        await update.message.reply_text(
            text,
            disable_web_page_preview=True,
            reply_markup=main_menu(user_id),
        )
    else:
        buf = io.BytesIO(text.encode("utf-8"))
        buf.name = fname
        await update.message.reply_document(
            document=buf,
            filename=fname,
            caption="Повний текст (перевищено ліміт повідомлення).",
            reply_markup=main_menu(user_id),
        )

# ------------------------------------------------------
# Основна логіка обробки повідомлень
# ------------------------------------------------------

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = (update.message.text or "").strip()
    uid  = update.effective_user.id

    # --- Адмінська видача доступу ---
    if uid == ADMIN_ID and context.user_data.get("grant_step") == "await_duration":
        choice = text.lower()
        if choice == "10 хвилин":
            context.user_data["grant_duration"] = timedelta(minutes=10)
        elif choice == "1 день":
            context.user_data["grant_duration"] = timedelta(days=1)
        elif choice == "14 днів":
            context.user_data["grant_duration"] = timedelta(days=14)
        else:
            await update.message.reply_text("⚠️ Обери один з варіантів.", reply_markup=duration_menu())
            return

        context.user_data["grant_step"] = "await_user_id"
        await update.message.reply_text("Введи ID користувача:", reply_markup=main_menu(uid))
        return

    if uid == ADMIN_ID and context.user_data.get("grant_step") == "await_user_id":
        try:
            target_id = int(text)
        except Exception:
            await update.message.reply_text("⚠️ Введи числовий ID.", reply_markup=main_menu(uid))
            return

        duration = context.user_data.get("grant_duration")
        grant_access(target_id, duration)
        context.user_data.clear()

        await update.message.reply_text(
            f"Готово. Доступ видано {target_id}.",
            reply_markup=main_menu(uid),
        )
        return

    # --- Меню ---
    if text in (
        BTN_PAY, BTN_WORK, BTN_INFO, BTN_GRANT,
        BTN_PAY_NOW, BTN_PAY_PARTS, BTN_PAY_DEBT,
        BTN_PAY_OK, BTN_BACK,
    ):

        if text == BTN_PAY:
            keyboard = [[BTN_PAY_NOW, BTN_PAY_PARTS], [BTN_PAY_DEBT], [BTN_BACK]]
            await update.message.reply_text(
                "💰 Обери спосіб оплати:",
                reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
            )
            return

        if text == BTN_PAY_NOW:
            await update.message.reply_text("Спосіб оплати недоступний.", reply_markup=main_menu(uid))
            return

        if text == BTN_PAY_PARTS:
            await update.message.reply_text("Яка оплата частинами?", reply_markup=main_menu(uid))
            return

        if text == BTN_PAY_DEBT:
            await update.message.reply_text("В борг? Ні 😂", reply_markup=main_menu(uid))
            return

        if text == BTN_PAY_OK:
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"Користувач підтвердив оплату: {uid}")
            await update.message.reply_text("Очікую підтвердження.", reply_markup=main_menu(uid))
            return

        if text == BTN_INFO:
            await update.message.reply_text("ℹ️ Робе, аби було легше 😎", reply_markup=main_menu(uid))
            return

        if text == BTN_WORK:
            if has_access(uid):
                await update.message.reply_text("Кидай анкету — я працюю 💪", reply_markup=main_menu(uid))
            else:
                await update.message.reply_text("⛔️ Доступ обмежено.", reply_markup=main_menu(uid))
            return

        if text == BTN_GRANT and uid == ADMIN_ID:
            context.user_data["grant_step"] = "await_duration"
            await update.message.reply_text("⏱ Обери тривалість:", reply_markup=duration_menu())
            return

        if text == BTN_BACK:
            await update.message.reply_text("Повертаємось у меню", reply_markup=main_menu(uid))
            return

    # --- Коди доступу ---
    low = text.lower()
    if low in ACCESS_CODES:

        if low == "bot10":
            if _get_bot10_uses() >= BOT10_LIMIT:
                await update.message.reply_text("⛔ Ліміт коду bot10 вичерпано.", reply_markup=main_menu(uid))
                return
            _inc_bot10_uses()

        grant_access(uid, ACCESS_CODES[low])
        human = "24 години" if low == "hb24" else ("14 днів" if low == "hb14" else "10 хвилин")

        await update.message.reply_text(
            f"Доступ активовано на {human}.",
            reply_markup=main_menu(uid),
        )
        return

    # --- Доступу нема ---
    if not has_access(uid):
        await update.message.reply_text("⛔️ Доступ обмежено.", reply_markup=main_menu(uid))
        return

    # --- Парсимо контент анкети ---
    body   = extract_body_without_id(text)
    d1, d2 = extract_dates(text)
    ad     = extract_adults(text)
    kids   = extract_kids(text)
    amount = extract_amount(text)
    room_title = extract_room_raw(text)
    corpus = find_corpus(room_title)

    days_left = (d1.date() - datetime.now().date()).days if d1 else None

    # --- Генеруємо попередження ---
    warning = pick_warning(room_title, d1, days_left)

    # --- Надсилаємо перше повідомлення ---
    draft = build_client_draft(body, warning)
    await send_single_or_file(update, draft, "zayavka.txt", uid)

    # --- Друге повідомлення, якщо є дати ---
    if d1 and d2:
        confirmation = build_confirmation(
            room_title, corpus, ad, kids, amount, d1, d2,
        )
        await send_single_or_file(update, confirmation, "pidtverdzhennya.txt", uid)

# ------------------------------------------------------
# Запуск бота
# ------------------------------------------------------

def main():

    request = HTTPXRequest(
        connect_timeout=30,
        read_timeout=30,
        write_timeout=30,
        pool_timeout=30,
        trust_env=False,
    )

    app = Application.builder().token(TOKEN).request(request).build()

    app.add_handler(CommandHandler(
        "start",
        lambda u, c: u.message.reply_text(
            "👋 Вітаю! Я працюю.", reply_markup=main_menu(u.effective_user.id)
        ),
    ))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    logger.info("Бот запущений.")
    app.run_polling(allowed_updates=[])

if __name__ == "__main__":
    main()
