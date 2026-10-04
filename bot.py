import asyncio
import json
import re
import time
import html
from pathlib import Path

from duckduckgo_search import DDGS

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ============================================================
# НАСТРОЙКИ
# ============================================================

BOT_TOKEN = "7705314975:AAGpe-DrPVwxqeBvCK72dZIYP4YvPkzLBLQ"
MEMORY_FILE = Path("memory.json")

class BotStates(StatesGroup):
    waiting_for_search_query = State()
    waiting_for_autonomous_goal = State()

# ============================================================
# ПАМЯТЬ И УТИЛИТЫ
# ============================================================

def load_memory():
    default_structure = {
        "knowledge": [],
        "stats": {"questions": 0, "searches": 0, "learned": 0}
    }
    if not MEMORY_FILE.exists():
        return default_structure
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default_structure

memory = load_memory()

def save_memory():
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(memory, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Ошибка сохранения памяти:", e)

def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.replace("\xa0", " ").strip()

def escape_html(text: str) -> str:
    return html.escape(clean_text(text))

# ============================================================
# НАДЕЖНЫЙ ПОИСК (DuckDuckGo Search SDK)
# ============================================================

async def web_search(query: str, max_results: int = 3):
    """Стабильный поиск без блокировок Cloudflare."""
    results = []
    try:
        # Запускаем синхронную библиотеку DDGS в отдельном потоке
        def _fetch():
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results))

        raw_results = await asyncio.to_thread(_fetch)
        for r in raw_results:
            results.append({
                "title": clean_text(r.get("title", "")),
                "url": r.get("href", ""),
                "description": clean_text(r.get("body", ""))
            })
    except Exception as e:
        print(f"Ошибка поиска для '{query}':", e)

    memory["stats"]["searches"] += 1
    save_memory()
    return results

# ============================================================
# ТЕЛЕГРАМ БОТ И КНОПКИ
# ============================================================

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

def main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🌐 Поиск", callback_data="search"),
                InlineKeyboardButton(text="🧠 Автономный режим", callback_data="autonomous")
            ],
            [
                InlineKeyboardButton(text="📚 Память", callback_data="memory"),
                InlineKeyboardButton(text="📊 Статус", callback_data="status")
            ]
        ]
    )

def cancel_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]]
    )

def is_small_talk(text: str) -> bool:
    t = text.lower().strip()
    words = ["привет", "здравствуй", "хай", "как дела", "спасибо", "кто ты", "отмена"]
    return any(w in t for w in words) or len(t.split()) <= 2

# ============================================================
# ОБРАБОТЧИКИ (HANDLERS)
# ============================================================

@dp.message(Command("start"))
async def start_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🤖 <b>Бот запущен.</b> Выберите действие или напишите вопрос:",
        reply_markup=main_keyboard()
    )

@dp.callback_query(F.data == "cancel")
async def cancel_cb(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer("Действие отменено.")
    await cb.message.answer("❌ Операция отменена.", reply_markup=main_keyboard())

# --- ПОИСК ---

@dp.callback_query(F.data == "search")
async def search_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(BotStates.waiting_for_search_query)
    await cb.message.answer("🌐 <b>Введите ваш поисковый запрос:</b>", reply_markup=cancel_keyboard())

@dp.message(BotStates.waiting_for_search_query)
async def process_search_input(message: Message, state: FSMContext):
    await state.clear()
    query = message.text.strip()

    if is_small_talk(query):
        await message.answer("👋 Это похоже на приветствие. Задайте конкретный поисковый вопрос!", reply_markup=main_keyboard())
        return

    msg = await message.answer(f"🔎 Поиск по запросу: <b>{escape_html(query)}</b>...")
    results = await web_search(query)

    if not results:
        await msg.edit_text("❌ Ничего не найдено. Попробуйте переформулировать запрос.")
        return

    text = f"🌐 <b>Результаты поиска ({len(results)}):</b>\n\n"
    for r in results:
        text += f"• <b>{escape_html(r['title'])}</b>\n{escape_html(r['description'])}\n🔗 {r['url']}\n\n"

    await msg.edit_text(text[:4000], disable_web_page_preview=True)

# --- АВТОНОМНЫЙ РЕЖИМ ---

@dp.callback_query(F.data == "autonomous")
async def autonomous_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(BotStates.waiting_for_autonomous_goal)
    await cb.message.answer(
        "🧠 <b>Автономный режим</b>\n\n"
        "Напишите тему или цель исследования.\n"
        "<i>Пример: Найди информацию про искусственный интеллект</i>",
        reply_markup=cancel_keyboard()
    )

@dp.message(BotStates.waiting_for_autonomous_goal)
async def process_autonomous_goal(message: Message, state: FSMContext):
    goal = message.text.strip()

    # Защита от перехвата обычного приветствия в автономный режим!
    if is_small_talk(goal):
        await state.clear()
        await message.answer("👋 Автономный режим отменен, так как вы написали приветствие/простую фразу.\nЧем могу помочь?", reply_markup=main_keyboard())
        return

    await state.clear()
    status_msg = await message.answer(f"🧠 <b>Начинаю автономную работу.</b>\n\nЦель: <i>{escape_html(goal)}</i>")

    sources = set()
    collected_facts = []

    for step in range(1, 4):
        await status_msg.edit_text(f"⚙️ <b>Шаг {step}/3:</b> Анализирую подтемы для «{escape_html(goal)}»...")
        
        search_query = f"{goal} факт {step}"
        results = await web_search(search_query, max_results=2)

        if results:
            for r in results:
                if r["description"]:
                    collected_facts.append(f"• {r['title']}: {r['description']}")
                if r["url"]:
                    sources.add(r["url"])
        
        await asyncio.sleep(2)

    if not collected_facts:
        await status_msg.edit_text("❌ В ходе автономного исследования не удалось собрать данные.")
        return

    final_text = (
        f"✅ <b>Автономная задача завершена!</b>\n\n"
        f"🎯 <b>Цель:</b> {escape_html(goal)}\n\n"
        f"📝 <b>Собранные факты:</b>\n" + "\n".join(collected_facts[:5]) + "\n\n"
        f"🔗 <b>Найдено источников:</b> {len(sources)}"
    )

    await status_msg.edit_text(final_text[:4000], disable_web_page_preview=True)

# --- ОБРАБОТКА ОБЫЧНЫХ СООБЩЕНИЙ ---

@dp.message(F.text)
async def handle_general_text(message: Message):
    if message.text.startswith("/"):
        return

    t = message.text.lower().strip()

    if "привет" in t or "здравствуй" in t or "хай" in t:
        await message.answer("👋 Привет! Я готов к работе. Задайте вопрос или выберите режим в меню.", reply_markup=main_keyboard())
        return

    if "как дела" in t:
        await message.answer("🤖 Всё работает отлично! Что ищем сегодня?", reply_markup=main_keyboard())
        return

    # Если отправлен обычный вопрос без кнопок
    msg = await message.answer("🔎 Ищу информацию...")
    results = await web_search(message.text)

    if not results:
        await msg.edit_text("❌ Ничего не найдено по вашему тексту.")
        return

    res_text = f"🌐 <b>Ответ по запросу:</b>\n\n"
    for r in results[:3]:
        res_text += f"• <b>{escape_html(r['title'])}</b>\n{escape_html(r['description'])}\n\n"

    await msg.edit_text(res_text[:4000])

# ============================================================
# ЗАПУСК
# ============================================================

async def main():
    print("Бот успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")
