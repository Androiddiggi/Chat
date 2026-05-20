import asyncio
import logging
import sqlite3
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery,
    LabeledPrice, PreCheckoutQuery
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

TOKEN = "7705314975:AAGKTnADtMLtstoc2XdUY5ysepmnAp-bn6w"

bot = Bot(token=TOKEN)
dp = Dispatcher()

STARS_PRICES = {
    "7days": 60,
    "1month": 120,
    "6months": 300,
    "1year": 600
}

INTERESTS_LIST = [
    "Ролевые игры", "Мемы", "Одиночество", "Флирт",
    "Игры", "Музыка", "Путешествия", "Аниме",
    "Фильмы", "Питомцы", "Книги", "Спорт"
]


# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect("anon_stars_karma.db")
    cur = conn.cursor()
    # Таблица пользователей
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        gender TEXT DEFAULT 'M',
        age INTEGER DEFAULT 18,
        interests TEXT DEFAULT '',
        is_vip INTEGER DEFAULT 0,
        karma INTEGER DEFAULT 100
    )""")
    # Новая таблица логирования оценок для подсчета лайков/дизлайков
    cur.execute("""
    CREATE TABLE IF NOT EXISTS ratings (
        from_id INTEGER,
        to_id INTEGER,
        rating_type TEXT,
        PRIMARY KEY (from_id, to_id)
    )""")
    conn.commit()
    conn.close()


def get_user_db(user_id):
    conn = sqlite3.connect("anon_stars_karma.db")
    cur = conn.cursor()
    cur.execute("SELECT gender, age, interests, is_vip, karma FROM users WHERE user_id = ?", (user_id,))
    res = cur.fetchone()
    conn.close()
    if not res:
        conn = sqlite3.connect("anon_stars_karma.db")
        cur = conn.cursor()
        cur.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        conn.close()
        return ('M', 18, '', 0, 100)
    return res


def update_user_db(user_id, field, value):
    conn = sqlite3.connect("anon_stars_karma.db")
    cur = conn.cursor()
    cur.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    conn.close()


def change_karma(user_id, amount):
    conn = sqlite3.connect("anon_stars_karma.db")
    cur = conn.cursor()
    cur.execute("UPDATE users SET karma = karma + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()


# Функция подсчета детальной статистики лайков и дизлайков для профиля
def get_user_stats(user_id):
    conn = sqlite3.connect("anon_stars_karma.db")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM ratings WHERE to_id = ? AND rating_type = 'like'", (user_id,))
    likes = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM ratings WHERE to_id = ? AND rating_type = 'dislike'", (user_id,))
    dislikes = cur.fetchone()[0]
    conn.close()
    return likes, dislikes


# Запись оценки в базу данных
def save_rating(from_id, to_id, rating_type):
    conn = sqlite3.connect("anon_stars_karma.db")
    cur = conn.cursor()
    try:
        cur.execute("INSERT OR REPLACE INTO ratings (from_id, to_id, rating_type) VALUES (?, ?, ?)",
                    (from_id, to_id, rating_type))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


# --- СТРУКТУРЫ ДАННЫХ ---
queue = []
active_chats = {}


class SettingsStates(StatesGroup):
    waiting_for_age = State()


# --- КЛАВИАТУРЫ ---
BTN_SEARCH_ANY = "🚀 Поиск любого собеседника"
BTN_SEARCH_F = "🙋‍♀️ Поиск Ж (Premium 💎)"
BTN_SEARCH_M = "🙋‍♂️ Поиск М (Premium 💎)"
BTN_INTERESTS = "📖 Интересы поиска"
BTN_PROFILE = "👤 Мой профиль"  # Новая кнопка


def get_search_menu_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=BTN_SEARCH_ANY)],
        [KeyboardButton(text=BTN_SEARCH_F), KeyboardButton(text=BTN_SEARCH_M)],
        [KeyboardButton(text=BTN_INTERESTS), KeyboardButton(text=BTN_PROFILE)]  # Добавили кнопку на нижний ряд
    ], resize_keyboard=True)


def get_stars_periods_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"⏳ 7 дней — ⭐ {STARS_PRICES['7days']} Stars", callback_data="buy_stars_7days")],
        [InlineKeyboardButton(text=f"📅 1 месяц — ⭐ {STARS_PRICES['1month']} Stars", callback_data="buy_stars_1month")],
        [InlineKeyboardButton(text=f"📦 6 месяцев — ⭐ {STARS_PRICES['6months']} Stars",
                              callback_data="buy_stars_6months")],
        [InlineKeyboardButton(text=f"👑 1 год — ⭐ {STARS_PRICES['1year']} Stars", callback_data="buy_stars_1year")]
    ])


def get_report_kb(target_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👍 Лайк", callback_data=f"rate_like_{target_id}"),
            InlineKeyboardButton(text="👎 Дизлайк", callback_data=f"rate_dislike_{target_id}")
        ],
        [InlineKeyboardButton(text="📰 Спам и реклама", callback_data=f"report_spam_{target_id}")],
        [InlineKeyboardButton(text="❌ Пошлый собеседник", callback_data=f"report_nsfw_{target_id}")],
        [InlineKeyboardButton(text="🔞 Несовершеннолетний", callback_data=f"report_minor_{target_id}")],
        [InlineKeyboardButton(text="⚠️ Другая жалоба →", callback_data=f"report_other_{target_id}")]
    ])


def get_profile_inline_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Сменить мой пол", callback_data="toggle_gender")],
        [InlineKeyboardButton(text="🔢 Изменить возраст", callback_data="change_age")]
    ])


# --- ЛОГИКА ПОИСКА ---
async def try_match(user_id, target_gender):
    u_gender, u_age, u_interests, u_vip, u_karma = get_user_db(user_id)

    if u_karma < 20:
        await bot.send_message(user_id,
                               "⚠️ Ваша карма слишком низкая из-за постоянных жалоб. Поиск временно заблокирован.")
        return

    u_ints = set(u_interests.split(",")) if u_interests else set()
    partner_id = None

    for peer in queue:
        p_id = peer["user_id"]
        p_target_gender = peer["target_gender"]
        if p_id == user_id: continue

        p_gender, p_age, p_interests, p_vip, p_karma = get_user_db(p_id)
        p_ints = set(p_interests.split(",")) if p_interests else set()

        match_my_req = (target_gender == "ANY" or target_gender == p_gender)
        match_peer_req = (p_target_gender == "ANY" or p_target_gender == u_gender)

        interests_match = True
        if u_ints or p_ints:
            if not u_ints.intersection(p_ints): interests_match = False

        if match_my_req and match_peer_req and interests_match:
            partner_id = p_id
            queue.remove(peer)
            break

    if partner_id:
        active_chats[user_id] = partner_id
        active_chats[partner_id] = user_id
        await bot.send_message(user_id, "🎉 Собеседник найден! Приятного общения.")
        await bot.send_message(partner_id, "🎉 Собеседник найден! Приятного общения.")
    else:
        if not any(q["user_id"] == user_id for q in queue):
            data = {"user_id": user_id, "target_gender": target_gender}
            if u_vip:
                queue.insert(0, data)
            else:
                queue.append(data)
        await bot.send_message(user_id, "🔍 Ищу собеседника... Ожидайте.")


async def close_chat(user_id, partner_id, initiator_id):
    active_chats.pop(user_id, None)
    active_chats.pop(partner_id, None)

    text_report = (
        "Если хотите, оставьте мнение о вашем собеседнике. Это поможет находить вам подходящих собеседников.\n\n"
        "⚠️ Если ваш собеседник неадекватно общался или нарушал правила чата, вы можете на него пожаловаться, используя кнопки ниже."
    )

    await bot.send_message(
        initiator_id,
        "Вы закончили связь с вашим собеседником 🙄\nНапишите /search чтобы найти следующего\n\n" + text_report,
        reply_markup=get_report_kb(partner_id if initiator_id == user_id else user_id)
    )

    receiver_id = partner_id if initiator_id == user_id else user_id
    await bot.send_message(
        receiver_id,
        "Собеседник прервал диалог 😢\nНапишите /search чтобы найти следующего\n\n" + text_report,
        reply_markup=get_report_kb(initiator_id)
    )


# --- ХЕНДЛЕРЫ КНОПОК МЕНЮ ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    get_user_db(message.from_user.id)
    await message.answer("👋 Привет в анонимном чате!\n\n🔍 Нажми кнопку ниже, чтобы начать поиск.",
                         reply_markup=get_search_menu_kb())


# Отображение профиля по кнопке из Reply-меню или по команде /profile
@dp.message(F.text == BTN_PROFILE)
@dp.message(Command("profile"))
@dp.message(Command("settings"))
async def cmd_profile(message: Message):
    user_id = message.from_user.id
    gender, age, _, is_vip, karma = get_user_db(user_id)
    likes, dislikes = get_user_stats(user_id)

    g_text = "👨 Мужской" if gender == "M" else "👩 Женский"
    v_text = "💎 Premium подписка" if is_vip else "Обычный пользователь"

    profile_text = (
        f"👤 *Ваш профиль:*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 *Пол:* {g_text}\n"
        f"🔢 *Возраст:* {age} лет\n"
        f"👑 *Статус:* {v_text}\n\n"
        f"📊 *Статистика отзывов:*\n"
        f"🔋 *Общая Карма:* {karma}\n"
        f"👍 *Лайков получено:* {likes}\n"
        f"👎 *Дизлайков получено:* {dislikes}"
    )
    await message.answer(profile_text, parse_mode="Markdown", reply_markup=get_profile_inline_kb())


@dp.message(F.text.in_([BTN_SEARCH_F, BTN_SEARCH_M]))
async def search_by_gender(message: Message):
    user_id = message.from_user.id
    _, _, _, is_vip, _ = get_user_db(user_id)

    if not is_vip:
        await message.answer(
            "⚠️ *Поиск по полу доступен только Premium пользователям!*\n\n"
            "Приобретите VIP-статус за Telegram Stars.",
            parse_mode="Markdown", reply_markup=get_stars_periods_kb()
        )
        return

    if user_id in active_chats: return
    target = "F" if message.text == BTN_SEARCH_F else "M"
    await try_match(user_id, target)


@dp.message(F.text == BTN_SEARCH_ANY)
async def search_any(message: Message):
    user_id = message.from_user.id
    if user_id in active_chats: return
    await try_match(user_id, "ANY")


@dp.message(Command("stop"))
async def cmd_stop(message: Message):
    user_id = message.from_user.id
    global queue
    queue = [q for q in queue if q["user_id"] != user_id]

    if user_id in active_chats:
        partner_id = active_chats[user_id]
        await close_chat(user_id, partner_id, initiator_id=user_id)
    else:
        await message.answer("Ты сейчас ни с кем не общаешься.", reply_markup=get_search_menu_kb())


# --- ОБРАБОТКА ОЦЕНОК И ЖАЛОБ ---

@dp.callback_query(F.data.startswith("rate_"))
async def process_rating(callback: CallbackQuery):
    data_parts = callback.data.split("_")
    action = data_parts[1]
    target_id = int(data_parts[2])
    from_id = callback.from_user.id

    if action == "like":
        save_rating(from_id, target_id, "like")
        change_karma(target_id, 1)
        await callback.answer("Вы поставили лайк! 👍", show_alert=False)
    else:
        save_rating(from_id, target_id, "dislike")
        change_karma(target_id, -1)
        await callback.answer("Вы поставили дизлайк! 👎", show_alert=False)

    # Изменяем сообщение: убираем инлайн-кнопки и выводим статус
    await callback.message.edit_text(
        text=callback.message.text + f"\n\n✅ *Вы поставили: {'Лайк 👍' if action == 'like' else 'Дизлайк 👎'}*",
        parse_mode="Markdown",
        reply_markup=None
    )


@dp.callback_query(F.data.startswith("report_"))
async def process_reporting(callback: CallbackQuery):
    data_parts = callback.data.split("_")
    reason = data_parts[1]
    target_id = int(data_parts[2])

    penalty = -5
    reason_ru = "жалобу"

    if reason == "spam":
        penalty = -10
        reason_ru = "Спам и реклама (Карма -10)"
    elif reason == "nsfw":
        penalty = -15
        reason_ru = "Пошлый собеседник (Карма -15)"
    elif reason == "minor":
        penalty = -25
        reason_ru = "Несовершеннолетний (Карма -25)"
    elif reason == "other":
        penalty = -5
        reason_ru = "Другая жалоба (Карма -5)"

    change_karma(target_id, penalty)
    await callback.answer(f"Жалоба отправлена!", show_alert=True)

    await callback.message.edit_text(
        text=callback.message.text + f"\n\n✅ *Отправлена жалоба по причине:* {reason_ru}",
        parse_mode="Markdown",
        reply_markup=None
    )


# --- ИНЛАЙН НАСТРОЙКИ ПОЛ/ВОЗРАСТ В ПРОФИЛЕ ---

@dp.callback_query(F.data == "toggle_gender")
async def inline_toggle_gender(callback: CallbackQuery):
    user_id = callback.from_user.id
    gender, age, _, is_vip, karma = get_user_db(user_id)
    new_gender = "F" if gender == "M" else "M"
    update_user_db(user_id, "gender", new_gender)

    await callback.answer("Пол изменен!")

    likes, dislikes = get_user_stats(user_id)
    g_text = "👨 Мужской" if new_gender == "M" else "👩 Женский"
    v_text = "💎 Premium подписка" if is_vip else "Обычный пользователь"

    await callback.message.edit_text(
        f"👤 *Ваш профиль:*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 *Пол:* {g_text}\n"
        f"🔢 *Возраст:* {age} лет\n"
        f"👑 *Статус:* {v_text}\n\n"
        f"📊 *Статистика отзывов:*\n"
        f"🔋 *Общая Карма:* {karma}\n"
        f"👍 *Лайков получено:* {likes}\n"
        f"👎 *Дизлайков получено:* {dislikes}",
        parse_mode="Markdown", reply_markup=get_profile_inline_kb()
    )


@dp.callback_query(F.data == "change_age")
async def inline_change_age(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("Введите ваш новый возраст (числом):")
    await state.set_state(SettingsStates.waiting_for_age)


@dp.message(SettingsStates.waiting_for_age)
async def process_change_age(message: Message, state: FSMContext):
    if message.text.isdigit():
        update_user_db(message.from_user.id, "age", int(message.text))
        await state.clear()
        await message.answer(f"✅ Возраст изменен! Нажмите «{BTN_PROFILE}», чтобы проверить.",
                             reply_markup=get_search_menu_kb())
    else:
        await message.answer("Введите корректное число.")


# --- ПРИЕМ STARS (ОПЛАТА) ---
@dp.callback_query(F.data.startswith("buy_stars_"))
async def process_stars_invoice(callback: CallbackQuery):
    await callback.answer()
    period = callback.data.split("buy_stars_")[1]
    stars_amount = STARS_PRICES[period]
    ru_names = {"7days": "7 дней", "1month": "1 месяц", "6months": "6 месяцев", "1year": "1 год"}

    await callback.message.answer_invoice(
        title=f"VIP Premium ({ru_names[period]})",
        description=f"Активация VIP-доступа на {ru_names[period]} за Telegram Stars.",
        payload=f"vip_stars_{period}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=f"Premium {ru_names[period]}", amount=stars_amount)]
    )


@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@dp.message(F.successful_payment)
async def process_successful_payment(message: Message):
    user_id = message.from_user.id
    update_user_db(user_id, "is_vip", 1)
    await message.answer("🎉 *VIP-статус успешно активирован!*", parse_mode="Markdown",
                         reply_markup=get_search_menu_kb())


# --- ИНТЕРЕСЫ И ДИАЛОГИ ---
def build_interests_keyboard(user_interests_str):
    active_set = set(user_interests_str.split(",")) if user_interests_str else set()
    buttons = []
    for i in range(0, len(INTERESTS_LIST), 2):
        row = []
        for j in range(2):
            if i + j < len(INTERESTS_LIST):
                item = INTERESTS_LIST[i + j]
                display_text = f"✅ {item}" if item in active_set else item
                row.append(InlineKeyboardButton(text=display_text, callback_data=f"tag_toggle_{item}"))
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Сбросить интересы", callback_data="tag_reset")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.message(F.text == BTN_INTERESTS)
async def cmd_interests(message: Message):
    _, _, interests, _, _ = get_user_db(message.from_user.id)
    await message.answer("Выберите ваши интересы:", reply_markup=build_interests_keyboard(interests))


@dp.callback_query(F.data.startswith("tag_toggle_"))
async def callback_tag_toggle(callback: CallbackQuery):
    item = callback.data.split("tag_toggle_")[1]
    _, _, interests, _, _ = get_user_db(callback.from_user.id)
    active_set = set(interests.split(",")) if interests else set()
    if item in active_set:
        active_set.remove(item)
    else:
        active_set.add(item)
    new_str = ",".join(filter(None, active_set))
    update_user_db(callback.from_user.id, "interests", new_str)
    await callback.message.edit_reply_markup(reply_markup=build_interests_keyboard(new_str))
    await callback.answer()


@dp.callback_query(F.data == "tag_reset")
async def callback_tag_reset(callback: CallbackQuery):
    update_user_db(callback.from_user.id, "interests", "")
    await callback.message.edit_reply_markup(reply_markup=build_interests_keyboard(""))
    await callback.answer("Сброшено")


@dp.message()
async def echo_handler(message: Message):
    user_id = message.from_user.id
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        try:
            await message.send_copy(chat_id=partner_id)
        except Exception:
            await message.answer("⚠️ Сообщение не доставлено.")
    else:
        await message.answer("Ты не в чате. Нажми кнопку поиска.", reply_markup=get_search_menu_kb())


async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()
    print("Бот с кнопкой профиля и подсчетом лайков/дизлайков запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
