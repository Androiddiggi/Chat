import asyncio
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())

class Survey(StatesGroup):
    country = State()
    gender = State()
    age = State()

user_profiles = {}
search_queue = []
user_search_preferences = {}
chat_pairs = {}
complaints = {}
blocked_users = {}
premium_users = set()

AGE_PRIORITY = ["До 14", "14–17", "17–21", "21–30", "Старше 30"]

# Клавиатуры

def main_menu_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🔍 Искать собеседника")],
        [KeyboardButton(text="🌍 Сменить страну"), KeyboardButton(text="👫 Сменить пол")],
        [KeyboardButton(text="🎂 Сменить возраст"), KeyboardButton(text="📄 Профиль")],
        [KeyboardButton(text="⭐ Премиум")]
    ], resize_keyboard=True)

def chat_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🚫 Пожаловаться / Завершить")]
    ], resize_keyboard=True)

def country_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Украина"), KeyboardButton(text="Россия")],
        [KeyboardButton(text="Казахстан"), KeyboardButton(text="Беларусь")]
    ], resize_keyboard=True)

def gender_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")]
    ], resize_keyboard=True)

def age_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="До 14"), KeyboardButton(text="14–17")],
        [KeyboardButton(text="17–21"), KeyboardButton(text="21–30")],
        [KeyboardButton(text="Старше 30")]
    ], resize_keyboard=True)

def search_gender_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [
            KeyboardButton(text="🔍 Найти девушку"),
            KeyboardButton(text="🔎 Случайный пол"),
            KeyboardButton(text="🔍 Найти парня")
        ],
        [KeyboardButton(text="⬅️ Назад")]
    ], resize_keyboard=True)

# Анкета
@dp.message(F.text == "/start")
async def start(message: types.Message, state: FSMContext):
    await message.answer("🌍 Выберите страну:", reply_markup=country_kb())
    await state.set_state(Survey.country)

@dp.message(Survey.country)
async def set_country(message: types.Message, state: FSMContext):
    await state.update_data(country=message.text)
    await message.answer("👫 Укажите пол:", reply_markup=gender_kb())
    await state.set_state(Survey.gender)

@dp.message(Survey.gender)
async def set_gender(message: types.Message, state: FSMContext):
    await state.update_data(gender=message.text)
    await message.answer("🎂 Выберите возраст:", reply_markup=age_kb())
    await state.set_state(Survey.age)

@dp.message(Survey.age)
async def set_age(message: types.Message, state: FSMContext):
    data = await state.update_data(age=message.text)
    user_profiles[message.from_user.id] = data
    await state.clear()
    await message.answer("✅ Анкета заполнена!", reply_markup=main_menu_kb())

@dp.message(F.text == "🌍 Сменить страну")
async def change_country(message: types.Message, state: FSMContext):
    await message.answer("🌍 Выберите страну:", reply_markup=country_kb())
    await state.set_state(Survey.country)

@dp.message(F.text == "👫 Сменить пол")
async def change_gender(message: types.Message, state: FSMContext):
    await message.answer("👫 Укажите пол:", reply_markup=gender_kb())
    await state.set_state(Survey.gender)

@dp.message(F.text == "🎂 Сменить возраст")
async def change_age(message: types.Message, state: FSMContext):
    await message.answer("🎂 Выберите возраст:", reply_markup=age_kb())
    await state.set_state(Survey.age)

@dp.message(F.text == "📄 Профиль")
async def show_profile(message: types.Message):
    profile = user_profiles.get(message.from_user.id)
    if profile:
        await message.answer(
            f"<b>🌍 Страна:</b> {profile['country']}\n"
            f"<b>👫 Пол:</b> {profile['gender']}\n"
            f"<b>🎂 Возраст:</b> {profile['age']}"
        )
    else:
        await message.answer("❗ Сначала заполните анкету: /start")

@dp.message(F.text == "🔍 Искать собеседника")
async def search_menu(message: types.Message):
    await message.answer("Выберите параметры поиска:", reply_markup=search_gender_kb())

@dp.message(F.text.in_(["🔍 Найти девушку", "🔍 Найти парня", "🔎 Случайный пол"]))
async def find_chat(message: types.Message):
    user_id = message.from_user.id
    if user_id in blocked_users:
        if datetime.now() < blocked_users[user_id]:
            await message.answer("❌ Вы временно заблокированы из-за жалоб.")
            return
        else:
            del blocked_users[user_id]

    user_data = user_profiles.get(user_id)
    if not user_data:
        await message.answer("❗ Сначала пройдите анкету: /start")
        return

    preferred_gender = None
    if message.text == "🔍 Найти девушку":
        preferred_gender = "Женский"
    elif message.text == "🔍 Найти парня":
        preferred_gender = "Мужской"

    for partner_id in search_queue:
        if partner_id == user_id:
            continue
        partner_data = user_profiles.get(partner_id)
        if not partner_data:
            continue
        if partner_data['country'] != user_data['country']:
            continue
        if partner_data['age'] != user_data['age']:
            continue
        if preferred_gender and partner_data['gender'] != preferred_gender:
            continue
        search_queue.remove(partner_id)
        chat_pairs[user_id] = partner_id
        chat_pairs[partner_id] = user_id
        await bot.send_message(partner_id, "🌟 Найден собеседник!", reply_markup=chat_kb())
        await bot.send_message(user_id, "🌟 Найден собеседник!", reply_markup=chat_kb())
        return

    if user_id not in search_queue:
        if user_id in premium_users:
            search_queue.insert(0, user_id)
        else:
            search_queue.append(user_id)
    await message.answer("⌛ Ожидаем собеседника...")

@dp.message(F.text == "⬅️ Назад")
async def back_to_main(message: types.Message):
    await message.answer("Вы вернулись в главное меню.", reply_markup=main_menu_kb())

@dp.message(F.text == "🚫 Пожаловаться / Завершить")
async def end_chat(message: types.Message):
    user_id = message.from_user.id
    partner_id = chat_pairs.pop(user_id, None)
    if partner_id:
        chat_pairs.pop(partner_id, None)
        await bot.send_message(partner_id, "⛔ Собеседник завершил чат.", reply_markup=main_menu_kb())
        await bot.send_message(user_id, "✉️ Жалоба отправлена.", reply_markup=main_menu_kb())
        complaints[partner_id] = complaints.get(partner_id, 0) + 1
        if complaints[partner_id] >= 10:
            blocked_users[partner_id] = datetime.now() + timedelta(days=1)
    else:
        await message.answer("❗ Вы не в чате", reply_markup=main_menu_kb())

@dp.message()
async def chat_forward(message: types.Message):
    user_id = message.from_user.id
    partner_id = chat_pairs.get(user_id)
    if partner_id:
        await bot.send_message(partner_id, message.text)

async def main():
    print("✅ Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
