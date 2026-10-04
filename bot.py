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

# ============================================================
# НАСТРОЙКИ
# ============================================================

BOT_TOKEN = "7705314975:AAGpe-DrPVwxqeBvCK72dZIYP4YvPkzLBLQ"

MEMORY_FILE = Path("memory.json")
MAX_SEARCH_RESULTS = 5
MAX_AUTONOMOUS_STEPS = 5

# ============================================================
# ПАМЯТЬ
# ============================================================

def load_memory():
    default_structure = {
        "knowledge": [],
        "questions": [],
        "stats": {
            "questions": 0,
            "searches": 0,
            "learned": 0
        }
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
        print("Ошибка загрузки памяти:", e)
        return default_structure

memory = load_memory()

def save_memory():
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(memory, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Ошибка сохранения памяти:", e)

# ============================================================
# ОЧИСТКА И ФОРМАТИРОВАНИЕ
# ============================================================

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

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()
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
            [
                InlineKeyboardButton(text="🤖 Автономный режим", callback_data="autonomous")
            ],
            [
                InlineKeyboardButton(text="⛔ Остановить", callback_data="stop")
            ]
        ]
    )

# ============================================================
# РАБОЧИЙ ПОИСК (DuckDuckGo Lite)
# ============================================================

async def web_search(query: str, limit: int = MAX_SEARCH_RESULTS):
    encoded = quote(query)
    url = "https://lite.duckduckgo.com/lite/"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    try:
        timeout = aiohttp.ClientTimeout(total=12)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.post(url, data=f"q={encoded}") as response:
                if response.status != 200:
                    return []
                html_doc = await response.text()

        soup = BeautifulSoup(html_doc, "html.parser")
        results = []

        rows = soup.find_all("tr")
        for i in range(0, len(rows) - 1):
            link = rows[i].find("a", class_="result-link")
            snippet = rows[i + 1].find("td", class_="result-snippet") if i + 1 < len(rows) else None

            if link:
                title_text = clean_text(link.get_text())
                url_text = link.get("href", "")
                desc_text = clean_text(snippet.get_text()) if snippet else ""

                if url_text and title_text:
                    results.append({
                        "title": title_text,
                        "url": url_text,
                        "description": desc_text
                    })

                if len(results) >= limit:
                    break

        memory["stats"]["searches"] += 1
        save_memory()
        return results

    except Exception as e:
        print("Ошибка поиска:", e)
        return []

# ============================================================
# ПАМЯТЬ И ОБРАБОТКА
# ============================================================

def save_knowledge(question, answer, sources=None, confidence=0.7):
    if sources is None:
        sources = []

    q_clean = clean_text(question)
    a_clean = clean_text(answer)

    if not q_clean or not a_clean:
        return

    for item in memory["knowledge"]:
        if item["question"].lower() == q_clean.lower():
            item["answer"] = a_clean
            item["sources"] = sources
            item["confidence"] = confidence
            item["updated"] = time.time()
            save_memory()
            return

    memory["knowledge"].append({
        "question": q_clean,
        "answer": a_clean,
        "sources": sources,
        "confidence": confidence,
        "created": time.time(),
        "updated": time.time()
    })
    memory["stats"]["learned"] += 1
    save_memory()

def search_memory(question):
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

def build_answer(question, results):
    if not results:
        return None

    blocks = []
    for r in results:
        t = r["title"]
        d = r["description"]
        blocks.append(f"{t}. {d}" if d else t)

    full_text = clean_text(" ".join(blocks))
    if not full_text:
        return None

    sentences = re.split(r"(?<=[.!?])\s+", full_text)
    q_words = set(re.findall(r"[а-яА-Яa-zA-ZёЁ]{3,}", question.lower()))

    scored = []
    for s in sentences:
        s_words = set(re.findall(r"[а-яА-Яa-zA-ZёЁ]{3,}", s.lower()))
        score = len(q_words.intersection(s_words))
        if len(s) > 20:
            scored.append((score, s))

    scored.sort(key=lambda x: x[0], reverse=True)

    selected = []
    for score, s in scored:
        if s not in selected:
            selected.append(s)
        if len(selected) >= 4:
            break

    if not selected:
        selected = sentences[:3]

    ans = " ".join(selected)
    return ans[:1500] if len(ans) > 1500 else ans

# ============================================================
# ПРОВЕРКА НА БЫТОВЫЕ ФРАЗЫ (SMALL TALK)
# ============================================================

def check_small_talk(text: str) -> str | None:
    t = text.lower().strip()

    greetings = ["привет", "здравствуй", "добрый день", "добрый вечер", "доброе утро", "хай", "хеллоу"]
    if any(g in t for g in greetings) and len(t.split()) <= 3:
        return "👋 Привет! Я автономный бот. Задай мне любой информационный вопрос, и я найду на него ответ!"

    how_are_you = ["как дела", "как ты", "как жизнь", "что делаешь"]
    if any(h in t for h in how_are_you):
        return "🤖 У меня всё отлично! Готов искать информацию и сохранять знания. Что тебя интересует?"

    thanks = ["спасибо", "благодарю", "спс"]
    if any(th in t for th in thanks) and len(t.split()) <= 2:
        return "😊 Рад был помочь! Если есть еще вопросы — обращайся."

    who = ["кто ты", "что ты умеешь", "расскажи о себе"]
    if any(w in t for w in who):
        return (
            "🤖 Я обучаемый автономный бот.\n\n"
            "• Ищу ответы на вопросы в интернете;\n"
            "• Запоминаю новые факты в память;\n"
            "• Могу работать в автономном режиме самостоятельного обучения."
        )

    return None

# ============================================================
# ОБРАБОТКА ВОПРОСА
# ============================================================

async def answer_question(message: Message):
    raw_text = clean_text(message.text)
    if not raw_text:
        return

    # 1. Проверяем бытовые фразы
    small_talk_reply = check_small_talk(raw_text)
    if small_talk_reply:
        await message.answer(small_talk_reply)
        return

    memory["stats"]["questions"] += 1
    save_memory()

    status_msg = await message.answer("🤔 Проверяю память и ищу информацию...")

    # 2. Проверяем память
    remembered = search_memory(raw_text)
    if remembered:
        safe_ans = escape_html(remembered["answer"])
        conf = round(remembered["confidence"] * 100)
        await status_msg.edit_text(
            f"🧠 <b>Нашёл в памяти:</b>\n\n{safe_ans}\n\n📌 Уверенность: {conf}%"
        )
        return

    # 3. Ищем в сети
    results = await web_search(raw_text)
    if not results:
        await status_msg.edit_text("❌ Не удалось найти информацию по этому запросу.")
        return

    answer = build_answer(raw_text, results)
    if not answer:
        await status_msg.edit_text("❌ Результаты найдены, но сформулировать ответ не удалось.")
        return

    sources = [r["url"] for r in results[:4]]
    save_knowledge(raw_text, answer, sources)

    safe_ans = escape_html(answer)
    await status_msg.edit_text(
        f"🤖 <b>Ответ:</b>\n\n{safe_ans}\n\n🧠 <i>Сохранено в память.</i>"
    )

# ============================================================
# КОМАНДЫ TELEGRAM
# ============================================================

@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "🤖 <b>Бот запущен и готов к работе.</b>\n\n"
        "Напишите мне любой поисковый вопрос или используйте меню ниже.",
        reply_markup=main_keyboard()
    )

@dp.message(Command("search"))
async def search_command(message: Message):
    query = message.text.replace("/search", "", 1).strip()
    if not query:
        await message.answer("Пример: <code>/search погода в Киеве</code>")
        return

    status_msg = await message.answer("🌐 Ищу...")
    results = await web_search(query)

    if not results:
        await status_msg.edit_text("❌ Ничего не найдено.")
        return

    text = "🌐 <b>Результаты:</b>\n\n"
    for i, res in enumerate(results, start=1):
        t = escape_html(res['title'])
        d = escape_html(res['description'][:150])
        text += f"<b>{i}. {t}</b>\n{d}\n{res['url']}\n\n"

    await status_msg.edit_text(text[:4000])

@dp.message(Command("memory"))
async def memory_command(message: Message):
    await message.answer(
        "📚 <b>Память:</b>\n\n"
        f"🧠 Знаний: <b>{len(memory['knowledge'])}</b>\n"
        f"❓ Вопросов: <b>{memory['stats']['questions']}</b>\n"
        f"🌐 Поисков: <b>{memory['stats']['searches']}</b>"
    )

@dp.message(Command("status"))
async def status_command(message: Message):
    await message.answer(
        "📊 <b>Статус:</b>\n\n"
        f"🧠 Знаний: {len(memory['knowledge'])}\n"
        f"❓ Вопросов: {memory['stats']['questions']}\n"
        f"🌐 Поисков: {memory['stats']['searches']}\n"
        f"🤖 Активных задач: {len(running_tasks)}"
    )

# ============================================================
# АВТОНОМНЫЙ РЕЖИМ
# ============================================================

async def autonomous_learning(chat_id: int):
    if chat_id in running_tasks:
        return

    running_tasks[chat_id] = True
    try:
        await bot.send_message(chat_id, "🤖 <b>Автономное обучение запущено.</b>")

        topics = ["наука", "технологии", "космос", "история"]
        for step in range(MAX_AUTONOMOUS_STEPS):
            if chat_id not in running_tasks:
                break

            query = topics[step % len(topics)] + " интересные факты"
            results = await web_search(query, limit=3)

            if results:
                answer = build_answer(query, results)
                if answer:
                    sources = [r["url"] for r in results]
                    save_knowledge(query, answer, sources)
                    await bot.send_message(
                        chat_id,
                        f"🧠 <b>Новый факт ({step+1}/{MAX_AUTONOMOUS_STEPS}):</b>\n\n"
                        f"{escape_html(answer[:500])}..."
                    )

            await asyncio.sleep(4)

        await bot.send_message(chat_id, "✅ <b>Обучение завершено.</b>")
    except Exception as e:
        print("Ошибка обучения:", e)
    finally:
        running_tasks.pop(chat_id, None)

@dp.message(Command("autonomous"))
@dp.message(Command("learn"))
async def start_autonomous(message: Message):
    chat_id = message.chat.id
    if chat_id in running_tasks:
        await message.answer("🧠 Задача уже выполняется.")
        return
    asyncio.create_task(autonomous_learning(chat_id))

@dp.message(Command("stop"))
async def stop_command(message: Message):
    chat_id = message.chat.id
    if chat_id in running_tasks:
        running_tasks.pop(chat_id, None)
        await message.answer("⛔ Остановка...")
    else:
        await message.answer("Нет активных задач.")

# ============================================================
# CALLBACKS & ALL TEXT
# ============================================================

@dp.callback_query(F.data == "search")
async def cb_search(cb: CallbackQuery):
    await cb.answer()
    await cb.message.answer("Задайте вопрос текстом или используйте: <code>/search запрос</code>")

@dp.callback_query(F.data == "learn")
@dp.callback_query(F.data == "autonomous")
async def cb_learn(cb: CallbackQuery):
    await cb.answer()
    chat_id = cb.message.chat.id
    if chat_id in running_tasks:
        await cb.message.answer("🧠 Процесс уже идет.")
        return
    asyncio.create_task(autonomous_learning(chat_id))

@dp.callback_query(F.data == "memory")
async def cb_memory(cb: CallbackQuery):
    await cb.answer()
    await memory_command(cb.message)

@dp.callback_query(F.data == "status")
async def cb_status(cb: CallbackQuery):
    await cb.answer()
    await status_command(cb.message)

@dp.callback_query(F.data == "stop")
async def cb_stop(cb: CallbackQuery):
    await cb.answer()
    await stop_command(cb.message)

@dp.message(F.text)
async def handle_text(message: Message):
    if message.text.startswith("/"):
        return
    await answer_question(message)

# ============================================================
# ЗАПУСК
# ============================================================

async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")
