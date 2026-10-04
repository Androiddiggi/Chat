import asyncio
import json
import re
import time
import html
from pathlib import Path
from urllib.parse import quote

import aiohttp
from bs4 import BeautifulSoup

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
MAX_SEARCH_RESULTS = 5
MAX_AUTONOMOUS_STEPS = 5

# Состояния для корректной работы кнопок
class BotStates(StatesGroup):
    waiting_for_search_query = State()

# ============================================================
# ПАМЯТЬ
# ============================================================

def load_memory():
    default_structure = {
        "knowledge": [],
        "questions": [],
        "stats": {"questions": 0, "searches": 0, "learned": 0}
    }
    if not MEMORY_FILE.exists():
        return default_structure
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for key in default_structure:
            data.setdefault(key, default_structure[key])
        return data
    except Exception as e:
        print("Ошибка памяти:", e)
        return default_structure

memory = load_memory()

def save_memory():
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(memory, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Ошибка сохранения:", e)

def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.replace("\xa0", " ").strip()

def escape_html(text: str) -> str:
    return html.escape(clean_text(text))

# ============================================================
# TELEGRAM BOT
# ============================================================

bot = Bot(token=BOT_TOKEN, default_bot_properties=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
running_tasks = {}

def main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🌐 Поиск", callback_data="search"),
                InlineKeyboardButton(text="🧠 Учиться", callback_data="learn")
            ],
            [
                InlineKeyboardButton(text="📚 Память", callback_data="memory"),
                InlineKeyboardButton(text="📊 Статус", callback_data="status")
            ],
            [InlineKeyboardButton(text="🤖 Автономный режим", callback_data="autonomous")],
            [InlineKeyboardButton(text="⛔ Остановить", callback_data="stop")]
        ]
    )

# ============================================================
# НАДЕЖНЫЙ МНОГОУРОВНЕВЫЙ ПОИСК (DuckDuckGo + Wikipedia Fallback)
# ============================================================

async def web_search(query: str, limit: int = MAX_SEARCH_RESULTS):
    """Надежный поисковик с автозаменой заголовков и защитой от блокировок."""
    clean_q = clean_text(query)
    encoded = quote(clean_q)
    
    # 1. Запрос к DuckDuckGo Lite с эмуляцией браузера
    url = "https://html.duckduckgo.com/html/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    results = []

    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, data={"q": clean_q}, headers=headers) as response:
                if response.status == 200:
                    html_doc = await response.text()
                    soup = BeautifulSoup(html_doc, "html.parser")
                    
                    for res in soup.select(".result"):
                        title_elem = res.select_one(".result__title")
                        snippet_elem = res.select_one(".result__snippet")
                        url_elem = res.select_one(".result__url")

                        if title_elem:
                            title = clean_text(title_elem.get_text())
                            snippet = clean_text(snippet_elem.get_text()) if snippet_elem else ""
                            link = clean_text(url_elem.get_text()) if url_elem else ""

                            if title and len(title) > 3:
                                results.append({"title": title, "url": link, "description": snippet})

                        if len(results) >= limit:
                            break
    except Exception as e:
        print("Ошибка DDG:", e)

    # 2. Если DDG заблокировал, делаем резервный поиск по Wikipedia API
    if not results:
        try:
            wiki_url = f"https://ru.wikipedia.org/w/api.php?action=query&list=search&srsearch={encoded}&format=json"
            async with aiohttp.ClientSession() as session:
                async with session.get(wiki_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        search_items = data.get("query", {}).get("search", [])
                        for item in search_items[:limit]:
                            snippet_clean = re.sub(r"<[^>]+>", "", item.get("snippet", ""))
                            results.append({
                                "title": item.get("title", ""),
                                "url": f"https://ru.wikipedia.org/wiki/{quote(item.get('title', ''))}",
                                "description": clean_text(snippet_clean)
                            })
        except Exception as e:
            print("Ошибка Wiki:", e)

    memory["stats"]["searches"] += 1
    save_memory()
    return results

# ============================================================
# АНАЛИЗ И СБОРКА ОТВЕТА
# ============================================================

def build_answer(question: str, results: list):
    if not results:
        return None

    text_blocks = []
    for r in results:
        if r["description"]:
            text_blocks.append(f"• <b>{r['title']}</b>: {r['description']}")
        else:
            text_blocks.append(f"• <b>{r['title']}</b>")

    return "\n\n".join(text_blocks)

def search_memory(question: str):
    words_q = set(re.findall(r"[а-яА-Яa-zA-ZёЁ]{3,}", question.lower()))
    if not words_q:
        return None

    best = None
    best_score = 0

    for item in memory["knowledge"]:
        text = f"{item['question']} {item['answer']}".lower()
        words_item = set(re.findall(r"[а-яА-Яa-zA-ZёЁ]{3,}", text))
        score = len(words_q.intersection(words_item))

        if score > best_score:
            best_score = score
            best = item

    return best if best_score >= 2 else None

def save_knowledge(question, answer, sources=None):
    if sources is None:
        sources = []
    q_clean = clean_text(question)
    a_clean = clean_text(answer)

    memory["knowledge"].append({
        "question": q_clean,
        "answer": a_clean,
        "sources": sources,
        "created": time.time()
    })
    memory["stats"]["learned"] += 1
    save_memory()

# ============================================================
# РАЗГОВОРНЫЙ ФИЛЬТР (SMALL TALK)
# ============================================================

def check_small_talk(text: str) -> str | None:
    t = text.lower().strip()

    greetings = ["привет", "здравствуй", "добрый день", "добрый вечер", "доброе утро", "хай", "хеллоу"]
    if any(g == t or t.startswith(g) for g in greetings) and len(t.split()) <= 3:
        return "👋 Привет! Чем я могу помочь? Задай мне любой вопрос или используй кнопку «Поиск»."

    how_are_you = ["как дела", "как ты", "что делаешь"]
    if any(h in t for h in how_are_you):
        return "🤖 У меня всё отлично! Готов искать информацию в сети и отвечать на твои вопросы."

    thanks = ["спасибо", "благодарю", "спс"]
    if any(th in t for th in thanks) and len(t.split()) <= 2:
        return "😊 Всегда рад помочь!"

    return None

# ============================================================
# ОБРАБОТЧИКИ СООБЩЕНИЙ
# ============================================================

async def process_search_and_reply(message: Message, query: str):
    status_msg = await message.answer("🔎 Ищу информацию...")

    # 1. Проверяем собственную память
    remembered = search_memory(query)
    if remembered:
        safe_ans = escape_html(remembered["answer"])
        await status_msg.edit_text(f"🧠 <b>Нашёл в своей памяти:</b>\n\n{safe_ans}")
        return

    # 2. Ищем через рабочий парсер
    results = await web_search(query)
    if not results:
        await status_msg.edit_text("❌ По вашему запросу ничего не найдено. Попробуйте уточнить формулировку.")
        return

    answer = build_answer(query, results)
    sources = [r["url"] for r in results if r["url"]]
    save_knowledge(query, answer, sources)

    await status_msg.edit_text(f"🌐 <b>Результаты поиска по запросу «{escape_html(query)}»:</b>\n\n{answer}")

@dp.message(Command("start"))
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🤖 <b>Бот готов к работе.</b>\n\nЗадайте вопрос текстом или выберите действие:",
        reply_markup=main_keyboard()
    )

@dp.callback_query(F.data == "search")
async def cb_search(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(BotStates.waiting_for_search_query)
    await cb.message.answer("🔍 <b>Введите поисковый запрос:</b>")

@dp.message(BotStates.waiting_for_search_query)
async def handle_search_state(message: Message, state: FSMContext):
    await state.clear()
    await process_search_and_reply(message, message.text)

@dp.message(F.text)
async def handle_all_text(message: Message):
    if message.text.startswith("/"):
        return

    # Проверка на обычное приветствие/разговор
    small_talk = check_small_talk(message.text)
    if small_talk:
        await message.answer(small_talk)
        return

    # Если не приветствие — выполняем поиск
    await process_search_and_reply(message, message.text)

# ============================================================
# КНОПКИ И СТАCУСЫ
# ============================================================

@dp.message(Command("memory"))
@dp.callback_query(F.data == "memory")
async def show_memory(event):
    msg = event.message if isinstance(event, CallbackQuery) else event
    if isinstance(event, CallbackQuery): await event.answer()
    await msg.answer(
        f"📚 <b>Состояние памяти:</b>\n\n"
        f"🧠 Сохранено знаний: <b>{len(memory['knowledge'])}</b>\n"
        f"🌐 Поисков выполнено: <b>{memory['stats']['searches']}</b>"
    )

@dp.message(Command("status"))
@dp.callback_query(F.data == "status")
async def show_status(event):
    msg = event.message if isinstance(event, CallbackQuery) else event
    if isinstance(event, CallbackQuery): await event.answer()
    await msg.answer(f"📊 Бот работает штатно.\nЗадач в памяти: {len(memory['knowledge'])}")

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
