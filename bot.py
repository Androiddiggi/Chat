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
MAX_SEARCH_RESULTS = 6
MAX_AUTONOMOUS_STEPS = 5


# ============================================================
# ПАМЯТЬ
# ============================================================

def load_memory():
    default_structure = {
        "knowledge": [],
        "questions": [],
        "tasks": [],
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
# ОЧИСТКА И ЭКРАНИРОВАНИЕ ТЕКСТА
# ============================================================

def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    text = text.replace("\xa0", " ")
    return text.strip()


def escape_html(text: str) -> str:
    """Безопасное экранирование текста для HTML-режима Telegram."""
    return html.escape(clean_text(text))


# ============================================================
# TELEGRAM
# ============================================================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher()
running_tasks = {}


# ============================================================
# КНОПКИ
# ============================================================

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
# ПОИСК В ИНТЕРНЕТЕ (Рабочий через DuckDuckGo Lite)
# ============================================================

async def web_search(query: str, limit: int = MAX_SEARCH_RESULTS):
    encoded = quote(query)
    url = "https://lite.duckduckgo.com/lite/"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Content-Type": "application/x-www-form-urlencoded"
    }

    try:
        timeout = aiohttp.ClientTimeout(total=15)

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
# СОХРАНЕНИЕ ЗНАНИЯ
# ============================================================

def save_knowledge(question, answer, sources=None, confidence=0.5):
    if sources is None:
        sources = []

    question = clean_text(question)
    answer = clean_text(answer)

    if not question or not answer:
        return

    for item in memory["knowledge"]:
        if item["question"].lower() == question.lower():
            item["answer"] = answer
            item["sources"] = sources
            item["confidence"] = confidence
            item["updated"] = time.time()
            save_memory()
            return

    memory["knowledge"].append({
        "question": question,
        "answer": answer,
        "sources": sources,
        "confidence": confidence,
        "created": time.time(),
        "updated": time.time()
    })

    memory["stats"]["learned"] += 1
    save_memory()


# ============================================================
# ПОИСК В СОБСТВЕННОЙ ПАМЯТИ
# ============================================================

def search_memory(question):
    # Извлекаем слова длиной от 3 символов
    question_words = set(re.findall(r"[а-яА-Яa-zA-ZёЁ]{3,}", question.lower()))

    if not question_words:
        return None

    best = None
    best_score = 0

    for item in memory["knowledge"]:
        text = (item["question"] + " " + item["answer"]).lower()
        words = set(re.findall(r"[а-яА-Яa-zA-ZёЁ]{3,}", text))

        common = question_words.intersection(words)
        score = len(common)

        if score > best_score:
            best_score = score
            best = item

    if best_score >= 2:
        return best

    return None


# ============================================================
# АЛГОРИТМ ФОРМИРОВАНИЯ ОТВЕТА ИЗ ТЕКСТА
# ============================================================

def build_answer(question, results):
    if not results:
        return None

    full_blocks = []
    for r in results:
        title = r["title"]
        desc = r["description"]
        if desc:
            full_blocks.append(f"{title}. {desc}")
        else:
            full_blocks.append(title)

    raw_text = " ".join(full_blocks)
    raw_text = clean_text(raw_text)

    if not raw_text:
        return None

    # Разбиваем на предложения
    sentences = re.split(r"(?<=[.!?])\s+", raw_text)

    question_words = set(re.findall(r"[а-яА-Яa-zA-ZёЁ]{3,}", question.lower()))

    scored = []
    for sentence in sentences:
        words = set(re.findall(r"[а-яА-Яa-zA-ZёЁ]{3,}", sentence.lower()))
        match_score = len(question_words.intersection(words))

        # Оцениваем информативность предложения
        if len(sentence) > 25:
            scored.append((match_score, sentence))

    scored.sort(key=lambda x: x[0], reverse=True)

    selected = []
    for score, sentence in scored:
        if sentence not in selected:
            selected.append(sentence)
        if len(selected) >= 5:
            break

    if not selected:
        selected = sentences[:3]

    answer = " ".join(selected)

    if len(answer) > 1500:
        answer = answer[:1500] + "..."

    return answer


# ============================================================
# ОБРАБОТКА ВОПРОСА
# ============================================================

async def answer_question(message: Message):
    question = clean_text(message.text)

    if not question:
        return

    memory["stats"]["questions"] += 1
    memory["questions"].append({
        "user_id": message.from_user.id,
        "question": question,
        "time": time.time()
    })

    if len(memory["questions"]) > 1000:
        memory["questions"] = memory["questions"][-1000:]

    save_memory()

    status_msg = await message.answer("🤔 Проверяю информацию и память...")

    # 1. Проверяем собственную память
    remembered = search_memory(question)

    if remembered:
        safe_ans = escape_html(remembered["answer"])
        conf_percent = round(remembered["confidence"] * 100)
        
        await status_msg.edit_text(
            f"🧠 <b>Нашёл в своей памяти:</b>\n\n"
            f"{safe_ans}\n\n"
            f"📌 Уровень уверенности: {conf_percent}%"
        )
        return

    # 2. Ищем в интернете
    results = await web_search(question)

    if not results:
        await status_msg.edit_text(
            "❌ Не получилось найти информацию в интернете.\n\n"
            "Попробуй сформулировать вопрос иначе."
        )
        return

    # 3. Собираем ответ
    answer = build_answer(question, results)

    if not answer:
        await status_msg.edit_text(
            "❌ Нашёл страницы, но не удалось составить ответ."
        )
        return

    # 4. Сохраняем и выдаем
    sources = [r["url"] for r in results[:5]]
    save_knowledge(question, answer, sources, confidence=0.7)

    safe_ans = escape_html(answer)

    await status_msg.edit_text(
        f"🤖 <b>Ответ:</b>\n\n"
        f"{safe_ans}\n\n"
        f"🧠 <i>Информация сохранена в память.</i>"
    )


# ============================================================
# КОМАНДЫ
# ============================================================

@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "🤖 <b>Автономный бот запущен.</b>\n\n"
        "Я умею:\n"
        "• Отвечать на обычные вопросы;\n"
        "• Искать информацию в интернете;\n"
        "• Сохранять знания в свою память;\n"
        "• Выполнять автономные задачи и обучаться.\n\n"
        "Просто напиши любой вопрос.",
        reply_markup=main_keyboard()
    )


@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "<b>Команды:</b>\n\n"
        "/start — главное меню\n"
        "/search — поиск в сети\n"
        "/learn — обучение\n"
        "/memory — обзоры памяти\n"
        "/status — состояние\n"
        "/autonomous — автономный режим\n"
        "/stop — остановить задачи"
    )


@dp.message(Command("search"))
async def search_command(message: Message):
    query = message.text.replace("/search", "", 1).strip()

    if not query:
        await message.answer("Укажите запрос: <code>/search новости науки</code>")
        return

    status_msg = await message.answer("🌐 Ищу информацию...")
    results = await web_search(query)

    if not results:
        await status_msg.edit_text("❌ Ничего не найдено.")
        return

    text = "🌐 <b>Результаты поиска:</b>\n\n"
    for i, res in enumerate(results, start=1):
        t = escape_html(res['title'])
        d = escape_html(res['description'][:200])
        text += f"<b>{i}. {t}</b>\n{d}\n{res['url']}\n\n"

    await status_msg.edit_text(text[:4000])


@dp.message(Command("memory"))
async def memory_command(message: Message):
    await message.answer(
        "📚 <b>Моя память:</b>\n\n"
        f"Знаний: <b>{len(memory['knowledge'])}</b>\n"
        f"Вопросов: <b>{memory['stats']['questions']}</b>\n"
        f"Поисков: <b>{memory['stats']['searches']}</b>\n"
        f"Изучено: <b>{memory['stats']['learned']}</b>"
    )


@dp.message(Command("status"))
async def status_command(message: Message):
    await message.answer(
        "📊 <b>Состояние:</b>\n\n"
        f"🧠 Знаний: {len(memory['knowledge'])}\n"
        f"❓ Вопросов: {memory['stats']['questions']}\n"
        f"🌐 Поисков: {memory['stats']['searches']}\n"
        f"🤖 Активных задач: {len(running_tasks)}"
    )


# ============================================================
# АВТОНОМНОЕ ОБУЧЕНИЕ
# ============================================================

async def autonomous_learning(chat_id: int):
    if chat_id in running_tasks:
        return

    running_tasks[chat_id] = True

    try:
        await bot.send_message(
            chat_id,
            "🤖 <b>Автономное обучение запущено.</b>\n"
            "Начинаю поиск новых фактов..."
        )

        topics = [
            "интересные научные факты",
            "новые технологии",
            "исследования космоса",
            "исторические открытия",
            "устройство компьютера"
        ]

        for step in range(MAX_AUTONOMOUS_STEPS):
            if chat_id not in running_tasks:
                break

            query = topics[step % len(topics)]
            results = await web_search(query, limit=5)

            if results:
                answer = build_answer(query, results)

                if answer:
                    sources = [r["url"] for r in results[:5]]
                    save_knowledge(query, answer, sources, confidence=0.6)

                    safe_ans = escape_html(answer[:600])
                    safe_q = escape_html(query)

                    await bot.send_message(
                        chat_id,
                        f"🧠 <b>Я кое-что изучил ({step + 1}/{MAX_AUTONOMOUS_STEPS}):</b>\n\n"
                        f"<b>Тема:</b> {safe_q}\n\n"
                        f"{safe_ans}..."
                    )

            await asyncio.sleep(4)

        await bot.send_message(
            chat_id,
            f"✅ <b>Цикл завершен. Всего знаний: {len(memory['knowledge'])}</b>"
        )

    except Exception as e:
        print("Ошибка обучения:", e)
    finally:
        running_tasks.pop(chat_id, None)


@dp.message(Command("learn"))
@dp.message(Command("autonomous"))
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
        await message.answer("⛔ Автономный процесс остановлен.")
    else:
        await message.answer("Сейчас нет активных задач.")


# ============================================================
# КНОПКИ КЛАВИАТУРЫ
# ============================================================

@dp.callback_query(F.data == "search")
async def cb_search(cb: CallbackQuery):
    await cb.answer()
    await cb.message.answer("Используйте команду: <code>/search Ваш запрос</code>")


@dp.callback_query(F.data == "learn")
@dp.callback_query(F.data == "autonomous")
async def cb_learn(cb: CallbackQuery):
    await cb.answer()
    chat_id = cb.message.chat.id
    if chat_id in running_tasks:
        await cb.message.answer("🧠 Обучение уже запущено.")
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


# ============================================================
# ТЕКСТОВЫЙ ОБРАБОТЧИК
# ============================================================

@dp.message(F.text)
async def all_text_messages(message: Message):
    if message.text.startswith("/"):
        return

    await answer_question(message)


# ============================================================
# ЗАПУСК
# ============================================================

async def main():
    print("================================")
    print("AUTONOMOUS BOT STARTED")
    print("================================")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped.")
