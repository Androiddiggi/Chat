import asyncio
import logging
import sqlite3
import random
import time
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton, 
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery,
    LabeledPrice, PreCheckoutQuery
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

TOKEN = "YOUR_BOT_TOKEN_HERE"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- ТАРИФЫ И КОНСТАНТЫ ---
STARS_PRICES = {"7days": 60, "1month": 120, "6months": 300, "1year": 600}
UNBAN_PRICE = 20  # Цена разбана в звездах

INTERESTS_LIST = [
    "Ролевые игры", "Мемы", "Одиночество", "Флирт",
    "Игры", "Музыка", "Путешествия", "Аниме",
    "Фильмы", "Питомцы", "Книги", "Спорт"
]

ICEBREAK_QUESTIONS = [
    "Расскажи о своем самом неловком свидании.",
    "Какое твое самое странное увлечение, о котором мало кто знает?",
    "Если бы у тебя был 1 миллион долларов, на что бы ты его потратил прямо сейчас?",
    "Какой фильм или сериал ты готов пересматривать бесконечно?",
    "Опиши свой идеальный день от начала и до конца.",
    "Какую суперсилу вы бы выбрали и почему?",
    "Что тебя больше всего раздражает в людях?",
    "Какое твое самое яркое воспоминание из детства?",
    "Веришь ли ты в любовь с первого взгляда или это миф?",
    "Какое самое безумное решение ты принимал в своей жизни?",
    "Если бы ты мог изменить одно правило в мире, что бы это было?",
    "Твой любимый способ расслабиться после тяжелого дня?",
    "Кем ты мечтал стать в детстве и кем стал в итоге?",
    "Какая песня у тебя сейчас на репите?",
    "Поделись своим главным страхом."
]

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect("anon_ultimate_bot.db")
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        gender TEXT DEFAULT 'M',
        age INTEGER DEFAULT 18,
        interests TEXT DEFAULT '',
        is_vip INTEGER DEFAULT 0,
        vip_until INTEGER DEFAULT 0,
        karma INTEGER DEFAULT 100,
        last_daily INTEGER DEFAULT 0,
        referrer_id INTEGER DEFAULT 0
    )""")
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
    conn = sqlite3.connect("anon_ultimate_bot.db")
    cur = conn.cursor()
    cur.execute("SELECT gender, age, interests, is_vip, vip_until, karma, last_daily, referrer_id FROM users WHERE user_id = ?", (user_id,))
    res = cur.fetchone()
    conn.close()
    
    if res:
        gender, age, interests, is_vip, vip_until, karma, last_daily, referrer_id = res
        if is_vip == 1 and vip_until > 0 and vip_until < int(time.time()):
            update_user_db(user_id, "is_vip", 0)
            update_user_db(user_id, "vip_until", 0)
            is_vip = 0
        return gender, age, interests, is_vip, vip_until, karma, last_daily, referrer_id
        
    conn = sqlite3.connect("anon_ultimate_bot.db")
    cur = conn.cursor()
    cur.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()
    return ('M', 18, '', 0, 0, 100, 0, 0)

def update_user_db(user_id, field, value):
    conn = sqlite3.connect("anon_ultimate_bot.db")
    cur = conn.cursor()
    cur.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    conn.close()

def change_karma(user_id, amount):
    conn = sqlite3.connect("anon_ultimate_bot.db")
    cur = conn.cursor()
    cur.execute("UPDATE users SET karma = karma + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def get_user_stats(user_id):
    conn = sqlite3.connect("anon_ultimate_bot.db")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM ratings WHERE to_id = ? AND rating_type = 'like'", (user_id,))
    likes = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM ratings WHERE to_id = ? AND rating_type = 'dislike'", (user_id,))
    dislikes = cur.fetchone()[0]
    conn.close()
    return likes, dislikes

def save_rating(from_id, to_id, rating_type):
    conn = sqlite3.connect("anon_ultimate_bot.db")
    cur = conn.cursor()
    try:
        cur.execute("INSERT OR REPLACE INTO ratings (from_id, to_id, rating_type) VALUES (?, ?, ?)", (from_id, to_id, rating_type))
        conn.commit()
    except Exception: pass
    finally: conn.close()

def add_vip_days(user_id, days):
    _, _, _, is_vip, vip_until, _, _, _ = get_user_db(user_id)
    now = int(time.time())
    if is_vip == 1 and vip_until > now:
        new_until = vip_until + (days * 86400)
    else:
        new_until = now + (days * 86400)
    
    conn = sqlite3.connect("anon_ultimate_bot.db")
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_vip = 1, vip_until = ? WHERE user_id = ?", (new_until, user_id))
    conn.commit()
    conn.close()

def count_referrals(user_id):
    conn = sqlite3.connect("anon_ultimate_bot.db")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,))
    count = cur.fetchone()[0]
    conn.close()
    return count

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
BTN_PROFILE = "👤 Мой профиль"

def get_search_menu_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=BTN_SEARCH_ANY)],
        [KeyboardButton(text=BTN_SEARCH_F), KeyboardButton(text=BTN_SEARCH_M)],
        [KeyboardButton(text=BTN_INTERESTS), KeyboardButton(text=BTN_PROFILE)]
    ], resize_keyboard=True)

def get_stars_periods_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"⏳ 7 дней — ⭐ {STARS_PRICES['7days']} Stars", callback_data="buy_stars_7days")],
        [InlineKeyboardButton(text=f"📅 1 месяц — ⭐ {STARS_PRICES['1month']} Stars", callback_data="buy_stars_1month")],
        [InlineKeyboardButton(text=f"📦 6 месяцев — ⭐ {STARS_PRICES['6months']} Stars", callback_data="buy_stars_6months")],
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
        [InlineKeyboardButton(text="🔄 Сменить пол", callback_data="toggle_gender"), InlineKeyboardButton(text="🔢 Изменить возраст", callback_data="change_age")],
        [InlineKeyboardButton(text="🔗 Реферальная система", callback_data="open_refs"), InlineKeyboardButton(text="💎 Купить VIP", callback_data="open_vip_menu")]
    ])

def get_game_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Задать случайный вопрос", callback_data="play_icebreaker")]
    ])

def get_unban_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"⚡ Мгновенный разбан — ⭐ {UNBAN_PRICE} Stars", callback_data="buy_unban")]
    ])

# --- ЛОГИКА ПОИСКА ---
async def try_match(user_id, target_gender):
    _, _, interests, is_vip, _, karma, _, _ = get_user_db(user_id)
    
    if karma < 20:
        await bot.send_message(
            user_id, 
            "⚠️ *Вы заблокированы!*\nВаша карма опустилась ниже допустимого уровня (20) из-за жалоб пользователей.\n\n"
            "Вы можете дождаться амнистии или разблокировать аккаунт прямо сейчас.",
            parse_mode="Markdown", reply_markup=get_unban_kb()
        )
        return

    u_ints = set(interests.split(",")) if interests else set()
    partner_id = None
    
    for peer in queue:
        p_id = peer["user_id"]
        p_target_gender = peer["target_gender"]
        if p_id == user_id: continue
            
        _, p_age, p_interests, p_vip, _, p_karma, _, _ = get_user_db(p_id)
        p_ints = set(p_interests.split(",")) if p_interests else set()

        u_gen, _, _, _, _, _, _, _ = get_user_db(user_id)
        p_gen, _, _, _, _, _, _, _ = get_user_db(p_id)
        
        if target_gender != "ANY" and target_gender != p_gen: continue
        if p_target_gender != "ANY" and p_target_gender != u_gen: continue

        interests_match = True
        if u_ints or p_ints:
            if not u_ints.intersection(p_ints): interests_match = False

        if interests_match:
            partner_id = p_id
            queue.remove(peer)
            break

    if partner_id:
        active_chats[user_id] = partner_id
        active_chats[partner_id] = partner_id
        active_chats[partner_id] = user_id
        
        await bot.send_message(user_id, "🎉 Собеседник найден! Приятного общения.\n💡 Используйте кнопку ниже, чтобы разнообразить диалог.", reply_markup=get_game_kb())
        await bot.send_message(partner_id, "🎉 Собеседник найден! Приятного общения.\n💡 Используйте кнопку ниже, чтобы разнообразить диалог.", reply_markup=get_game_kb())
    else:
        if not any(q["user_id"] == user_id for q in queue):
            data = {"user_id": user_id, "target_gender": target_gender}
            if is_vip: queue.insert(0, data)
            else: queue.append(data)
        await bot.send_message(user_id, "🔍 Ищу собеседника... Ожидайте.")

async def close_chat(user_id, partner_id, initiator_id):
    active_chats.pop(user_id, None)
    active_chats.pop(partner_id, None)
    
    text_report = (
        "Если хотите, оставьте мнение о вашем собеседнике.\n\n"
        "⚠️ Если ваш собеседник нарушал правила чата, вы можете отправить на него жалобу."
    )

    await bot.send_message(initiator_id, "Вы закончили связь с собеседником 🙄\n\n" + text_report, reply_markup=get_report_kb(partner_id if initiator_id == user_id else user_id))
    await bot.send_message(partner_id if initiator_id == user_id else user_id, "Собеседник прервал диалог 😢\n\n" + text_report, reply_markup=get_report_kb(initiator_id))

# --- ХЕНДЛЕР СТАРТА С РЕФЕРАЛЬНОЙ СИСТЕМОЙ ---
@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    args = message.text.split()
    
    conn = sqlite3.connect("anon_ultimate_bot.db")
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    exists = cur.fetchone()
    conn.close()
    
    gender, age, interests, is_vip, vip_until, karma, last_daily, referrer_id = get_user_db(user_id)
    
    if not exists and len(args) > 1 and args[1].isdigit():
        ref_id = int(args[1])
        if ref_id != user_id:
            update_user_db(user_id, "referrer_id", ref_id)
            change_karma(ref_id, 20)
            add_vip_days(ref_id, 1)
            try:
                await bot.send_message(ref_id, "🎉 По вашей ссылке зарегистрировался новый пользователь!\n🎁 Вам начислено: *+20 Кармы* и *1 день VIP*!", parse_mode="Markdown")
            except Exception: pass

    await message.answer("👋 Добро пожаловать в анонимный чат!\n\nИспользуйте меню для поиска собеседников.", reply_markup=get_search_menu_kb())

# --- ХЕНДЛЕР ПРОФИЛЯ С ЕЖЕДНЕВНОЙ НАГРАДОЙ ---
@dp.message(F.text == BTN_PROFILE)
@dp.message(Command("profile"))
async def cmd_profile(message: Message):
    user_id = message.from_user.id
    gender, age, _, is_vip, vip_until, karma, last_daily, _ = get_user_db(user_id)
    likes, dislikes = get_user_stats(user_id)
    
    now = int(time.time())
    daily_bonus_applied = False
    if now - last_daily >= 86400:
        change_karma(user_id, 2)
        update_user_db(user_id, "last_daily", now)
        karma += 2
        daily_bonus_applied = True

    g_text = "👨 Мужской" if gender == "M" else "👩 Женский"
    
    if is_vip:
        time_left = vip_until - now
        days_left = max(1, round(time_left / 86400))
        v_text = f"💎 Premium (осталось {days_left} дн.)"
    else:
        v_text = "Обычный пользователь"
        
    profile_text = (
        f"👤 *Ваш профиль:*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 *Пол:* {g_text}\n"
        f"🔢 *Возраст:* {age} лет\n"
        f"👑 *Статус:* {v_text}\n\n"
        f"📊 *Статистика отзывов:*\n"
        f"🔋 *Общая Карма:* {karma}\n"
        f"👍 *Лайков:* {likes} | 👎 *Дизлайков:* {dislikes}\n"
    )
    if daily_bonus_applied:
        profile_text += "\n🎁 *Вам начислена ежедневная награда: +2 к Карме!*"

    await message.answer(profile_text, parse_mode="Markdown", reply_markup=get_profile_inline_kb())

# --- ИГРА «ЛЕДОКОЛ» ВНУТРИ ЧАТА ---
@dp.callback_query(F.data == "play_icebreaker")
async def callback_icebreaker(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in active_chats:
        await callback.answer("Вы не находитесь в активном диалоге.", show_alert=True)
        return
        
    partner_id = active_chats[user_id]
    question = random.choice(ICEBREAK_QUESTIONS)
    
    game_msg = f"🎲 *Игра «Разговорный ледокол»*\n━━━━━━━━━━━━━━━━━━━━\nВопрос для обсуждения:\n\n_\"{question}\"_"
    
    await bot.send_message(user_id, game_msg, parse_mode="Markdown")
    await bot.send_message(partner_id, game_msg, parse_mode="Markdown")
    await callback.answer()

# --- ИНЛАЙН ОБРАБОТКА РЕФЕРАЛОВ И VIP ---
@dp.callback_query(F.data == "open_refs")
async def callback_open_refs(callback: CallbackQuery):
    user_id = callback.from_user.id
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
    ref_count = count_referrals(user_id)
    
    text = (
        f"🔗 *Ваша реферальная ссылка:*\n`{ref_link}`\n\n"
        f"👥 Приглашено друзей: *{ref_count}*\n\n"
        f"🎁 За каждого приглашенного друга вы получаете:\n"
        f"• *+20 к Карме*\n"
        f"• *1 день VIP-статуса бесплатно!*"
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_profile")]]))

@dp.callback_query(F.data == "open_vip_menu")
@dp.callback_query(F.data == "back_to_periods")
async def callback_vip_menu(callback: CallbackQuery):
    await callback.message.edit_text("👑 *Покупка Premium доступа за Telegram Stars:*\n\nВыберите нужный период подписки:", reply_markup=get_stars_periods_kb())

@dp.callback_query(F.data == "back_to_profile")
async def callback_back_profile(callback: CallbackQuery):
    await callback.message.delete()
    gender, age, _, is_vip, vip_until, karma, _, _ = get_user_db(callback.from_user.id)
    likes, dislikes = get_user_stats(callback.from_user.id)
    g_text = "👨 Мужской" if gender == "M" else "👩 Женский"
    v_text = "💎 Premium" if is_vip else "Обычный"
    profile_text = f"👤 *Ваш профиль:*\n━━━━━━━━━━━━━━━━━━━━\n📝 *Пол:* {g_text}\n🔢 *Возраст:* {age} лет\n👑 *Статус:* {v_text}\n\n📊 *Статистика откликов:*\n🔋 *Общая Карма:* {karma}\n👍 *Лайков:* {likes} | 👎 *Дизлайков:* {dislikes}"
    await callback.message.answer(profile_text, parse_mode="Markdown", reply_markup=get_profile_inline_kb())

# --- ПОИСК И ДИАЛОГИ ---
@dp.message(F.text.in_([BTN_SEARCH_F, BTN_SEARCH_M]))
async def search_by_gender(message: Message):
    user_id = message.from_user.id
    _, _, _, is_vip, _, _, _, _ = get_user_db(user_id)
    if not is_vip:
        await message.answer("⚠️ *Поиск по полу доступен только Premium пользователям!*", parse_mode="Markdown", reply_markup=get_stars_periods_kb())
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

# --- ПРЯМАЯ ПЕРЕСЫЛКА КОНТЕНТА БЕЗ ОГРАНИЧЕНИЙ ---
@dp.message()
async def chat_router(message: Message):
    user_id = message.from_user.id
    
    if user_id not in active_chats:
        await message.answer("Вы не находитесь в чате. Нажмите кнопку поиска.", reply_markup=get_search_menu_kb())
        return
        
    partner_id = active_chats[user_id]
    
    # Свободная пересылка любого типа сообщений (Текст, Ссылки, Фото, Видео, Голосовые, Кружочки и т.д.)
    try:
        await message.send_copy(chat_id=partner_id)
    except Exception:
        await message.answer("⚠️ Сообщение не доставлено. Возможно, собеседник отключился.")

# --- ПРИЕМ ПЛАТЕЖЕЙ И КУПЛЯ РАЗБАНА (STARS) ---
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
        provider_token="", currency="XTR",
        prices=[LabeledPrice(label=f"Premium {ru_names[period]}", amount=stars_amount)]
    )

@dp.callback_query(F.data == "buy_unban")
async def process_unban_invoice(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer_invoice(
        title="Мгновенная разблокировка аккаунта",
        description="Сброс штрафной кармы до базовых 100 единиц и допуск ко всем поискам.",
        payload="unban_stars",
        provider_token="", currency="XTR",
        prices=[LabeledPrice(label="Снятие блокировки", amount=UNBAN_PRICE)]
    )

@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def process_successful_payment(message: Message):
    user_id = message.from_user.id
    payload = message.successful_payment.invoice_payload
    
    if "vip_stars_" in payload:
        period = payload.split("vip_stars_")[1]
        days = {"7days": 7, "1month": 30, "6months": 180, "1year": 365}[period]
        add_vip_days(user_id, days)
        await message.answer("🎉 *VIP-статус успешно активирован!*", parse_mode="Markdown", reply_markup=get_search_menu_kb())
        
    elif payload == "unban_stars":
        update_user_db(user_id, "karma", 100)
        await message.answer("⚡ *Ваш аккаунт успешно разблокирован!* Ваша карма восстановлена до 100. Приятного общения.", parse_mode="Markdown", reply_markup=get_search_menu_kb())

# --- ХЕНДЛЕРЫ ОТЗЫВОВ И НАСТРОЕК (ПОЛ/ВОЗРАСТ/ИНТЕРЕСЫ) ---
@dp.callback_query(F.data.startswith("rate_"))
async def process_rating(callback: CallbackQuery):
    data_parts = callback.data.split("_")
    action, target_id = data_parts[1], int(data_parts[2])
    save_rating(callback.from_user.id, target_id, action)
    change_karma(target_id, 1 if action == "like" else -1)
    await callback.answer("Оценка учтена!")
    await callback.message.edit_text(text=callback.message.text + f"\n\n✅ *Вы поставили: {'Лайк 👍' if action == 'like' else 'Дизлайк 👎'}*", parse_mode="Markdown", reply_markup=None)

@dp.callback_query(F.data.startswith("report_"))
async def process_reporting(callback: CallbackQuery):
    data_parts = callback.data.split("_")
    reason, target_id = data_parts[1], int(data_parts[2])
    penalty = {"spam": -10, "nsfw": -15, "minor": -25, "other": -5}[reason]
    change_karma(target_id, penalty)
    await callback.answer("Жалоба отправлена!", show_alert=True)
    await callback.message.edit_text(text=callback.message.text + f"\n\n✅ *Отправлена жалоба на собеседника.*", parse_mode="Markdown", reply_markup=None)

@dp.callback_query(F.data == "toggle_gender")
async def inline_toggle_gender(callback: CallbackQuery):
    user_id = callback.from_user.id
    gender, _, _, _, _, _, _, _ = get_user_db(user_id)
    update_user_db(user_id, "gender", "F" if gender == "M" else "M")
    await callback.answer("Пол изменен!")
    await callback.message.delete()
    await cmd_profile(callback.message)

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
        await message.answer("✅ Возраст изменен!", reply_markup=get_search_menu_kb())
    else:
        await message.answer("Введите корректное число.")

def build_interests_keyboard(user_interests_str):
    active_set = set(user_interests_str.split(",")) if user_interests_str else set()
    buttons = []
    for i in range(0, len(INTERESTS_LIST), 2):
        row = []
        for j in range(2):
            if i + j < len(INTERESTS_LIST):
                item = INTERESTS_LIST[i + j]
                row.append(InlineKeyboardButton(text=f"✅ {item}" if item in active_set else item, callback_data=f"tag_toggle_{item}"))
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Сбросить", callback_data="tag_reset")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(F.text == BTN_INTERESTS)
async def cmd_interests(message: Message):
    _, _, interests, _, _, _, _, _ = get_user_db(message.from_user.id)
    await message.answer("Выберите ваши интересы для точного поиска:", reply_markup=build_interests_keyboard(interests))

@dp.callback_query(F.data.startswith("tag_toggle_"))
async def callback_tag_toggle(callback: CallbackQuery):
    item = callback.data.split("tag_toggle_")[1]
    _, _, interests, _, _, _, _, _ = get_user_db(callback.from_user.id)
    active_set = set(interests.split(",")) if interests else set()
    if item in active_set: active_set.remove(item)
    else: active_set.add(item)
    update_user_db(callback.from_user.id, "interests", ",".join(filter(None, active_set)))
    await callback.message.edit_reply_markup(reply_markup=build_interests_keyboard(",".join(filter(None, active_set))))
    await callback.answer()

@dp.callback_query(F.data == "tag_reset")
async def callback_tag_reset(callback: CallbackQuery):
    update_user_db(callback.from_user.id, "interests", "")
    await callback.message.edit_reply_markup(reply_markup=build_interests_keyboard(""))
    await callback.answer("Сброшено")

async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()
    print("Бот запущен. Ограничения на пересылку медиа успешно убраны!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
