
import os
import json
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict, deque

from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.enums import ContentType
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

# Очереди по темам
queues = defaultdict(deque)
# Активные чаты {user_id: partner_id}
active_chats = {}
# Профили
profiles = {}
# Жалобы и блокировки
complaints = defaultdict(int)
blocked = {}

# Темы
TOPICS = ["🎮 Игры", "🎵 Музыка", "📚 Книги", "💬 Просто чат"]
topic_kb = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text=topic, callback_data=f"topic:{topic}")] for topic in TOPICS]
)

main_kb = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    [KeyboardButton(text="➡️ Следующий"), KeyboardButton(text="❌ Стоп"), KeyboardButton(text="⚠️ Жалоба")],
    [KeyboardButton(text="📄 Профиль")]
])

def is_blocked(user_id):
    if user_id in blocked:
        if datetime.utcnow() >= blocked[user_id]:
            del blocked[user_id]
        else:
            return True
    return False

@router.message(F.text == "/start")
async def cmd_start(message: Message):
    if is_blocked(message.chat.id):
        remaining = blocked[message.chat.id] - datetime.utcnow()
        await message.answer(f"Вы заблокированы. Осталось: {remaining}")
        return
    await message.answer("Выберите тему для чата:", reply_markup=topic_kb)

@router.callback_query(F.data.startswith("topic:"))
async def choose_topic(callback: types.CallbackQuery):
    topic = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    await callback.message.answer(f"Ожидание собеседника по теме {topic}...", reply_markup=main_kb)

    if user_id in active_chats:
        await callback.message.answer("Вы уже в чате.")
        return

    queue = queues[topic]
    if queue:
        partner_id = queue.popleft()
        active_chats[user_id] = partner_id
        active_chats[partner_id] = user_id
        await bot.send_message(partner_id, f"Собеседник найден по теме {topic}.", reply_markup=main_kb)
        await callback.message.answer(f"Собеседник найден по теме {topic}.")
        update_profiles(user_id)
        update_profiles(partner_id)
    else:
        queue.append(user_id)

def update_profiles(user_id):
    if user_id not in profiles:
        profiles[user_id] = {
            "chats": 0,
            "complaints": 0,
            "rating": 0,
            "rated_by": 0
        }
    profiles[user_id]["chats"] += 1

@router.message(F.text == "❌ Стоп")
async def stop_chat(message: Message):
    user_id = message.chat.id
    partner_id = active_chats.pop(user_id, None)
    if partner_id:
        active_chats.pop(partner_id, None)
        await bot.send_message(partner_id, "Собеседник покинул чат. Оцените его: /like или /dislike")
        await message.answer("Вы покинули чат. Оцените собеседника: /like или /dislike")
    else:
        for queue in queues.values():
            if user_id in queue:
                queue.remove(user_id)
                await message.answer("Вы покинули очередь.")
                return
        await message.answer("Вы не в чате.")

@router.message(F.text == "➡️ Следующий")
async def next_chat(message: Message):
    await stop_chat(message)
    await cmd_start(message)

@router.message(F.text == "⚠️ Жалоба")
async def complaint(message: Message):
    partner_id = active_chats.get(message.chat.id)
    if not partner_id:
        await message.answer("Вы не в чате.")
        return
    complaints[partner_id] += 1
    profiles[partner_id]["complaints"] += 1
    await message.answer("Жалоба отправлена.")
    if complaints[partner_id] >= 10:
        blocked[partner_id] = datetime.utcnow() + timedelta(hours=24)
        await bot.send_message(partner_id, "Вы получили 10 жалоб и были заблокированы на 24 часа.")

@router.message(F.text == "📄 Профиль")
async def profile(message: Message):
    user_id = message.chat.id
    p = profiles.get(user_id, {
        "chats": 0,
        "complaints": 0,
        "rating": 0,
        "rated_by": 0
    })
    avg_rating = p["rating"] / p["rated_by"] if p["rated_by"] else 0
    await message.answer(
    f"📊 Профиль:\n"
    f"Чатов: {p['chats']}\n"
    f"Жалоб: {p['complaints']}\n"
    f"Рейтинг: {avg_rating:.1f} ⭐️"
)


@router.message(F.text == "/like")
async def like(message: Message):
    partner_id = None
    for uid, pid in active_chats.items():
        if pid == message.chat.id:
            partner_id = uid
            break
    if partner_id and partner_id in profiles:
        profiles[partner_id]["rating"] += 1
        profiles[partner_id]["rated_by"] += 1
        await message.answer("Спасибо за оценку!")
    else:
        await message.answer("Нет собеседника для оценки.")

@router.message(F.text == "/dislike")
async def dislike(message: Message):
    partner_id = None
    for uid, pid in active_chats.items():
        if pid == message.chat.id:
            partner_id = uid
            break
    if partner_id and partner_id in profiles:
        profiles[partner_id]["rated_by"] += 1
        await message.answer("Спасибо за оценку!")
    else:
        await message.answer("Нет собеседника для оценки.")

@router.message()
async def relay(message: Message):
    partner_id = active_chats.get(message.chat.id)
    if not partner_id:
        await message.answer("Вы не в чате. Нажмите /start.")
        return
    try:
        ct = message.content_type
        if ct == ContentType.TEXT:
            await bot.send_message(partner_id, message.text)
        elif ct == ContentType.PHOTO:
            await bot.send_photo(partner_id, message.photo[-1].file_id, caption=message.caption)
        elif ct == ContentType.VIDEO:
            await bot.send_video(partner_id, message.video.file_id, caption=message.caption)
        elif ct == ContentType.VOICE:
            await bot.send_voice(partner_id, message.voice.file_id)
        else:
            await message.reply("Тип контента не поддерживается.")
    except Exception as e:
        await message.reply("Ошибка при пересылке.")

async def main():
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
