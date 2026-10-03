import asyncio
import json
import re
import time
from pathlib import Path
from collections import Counter
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

# Интервал автономной работы
AUTONOMOUS_INTERVAL = 300  # 5 минут


# ============================================================
# ПАМЯТЬ
# ============================================================

def load_memory():
    if not MEMORY_FILE.exists():
        return {
            "knowledge": [],
            "questions": [],
            "tasks": [],
            "stats": {
                "questions": 0,
                "searches": 0,
                "learned": 0
            }
        }

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        data.setdefault("knowledge", [])
        data.setdefault("questions", [])
        data.setdefault("tasks", [])
        data.setdefault("stats", {
            "questions": 0,
            "searches": 0,
            "learned": 0
        })

        return data

    except Exception:
        return {
            "knowledge": [],
            "questions": [],
            "tasks": [],
            "stats": {
                "questions": 0,
                "searches": 0,
                "learned": 0
            }
        }


memory = load_memory()


def save_memory():
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(memory, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Ошибка сохранения памяти:", e)


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
                InlineKeyboardButton(
                    text="🌐 Поиск",
                    callback_data="search"
                ),
                InlineKeyboardButton(
                    text="🧠 Учиться",
                    callback_data="learn"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📚 Память",
                    callback_data="memory"
                ),
                InlineKeyboardButton(
                    text="📊 Статус",
                    callback_data="status"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🤖 Автономный режим",
                    callback_data="autonomous"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⛔ Остановить",
                    callback_data="stop"
                )
            ]
        ]
    )


# ============================================================
# ОЧИСТКА ТЕКСТА
# ============================================================

def clean_text(text):
    if not text:
        return ""

    text = re.sub(r"\s+", " ", text)
    text = text.replace("\xa0", " ")

    return text.strip()


# ============================================================
# ПОИСК В ИНТЕРНЕТЕ
# ============================================================

async def web_search(query, limit=MAX_SEARCH_RESULTS):
    """
    Поиск через DuckDuckGo.
    """

    encoded = quote(query)

    url = (
        "https://html.duckduckgo.com/html/"
        f"?q={encoded}"
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/130 Safari/537.36"
        )
    }

    try:

        timeout = aiohttp.ClientTimeout(total=20)

        async with aiohttp.ClientSession(
            timeout=timeout,
            headers=headers
        ) as session:

            async with session.get(url) as response:

                if response.status != 200:
                    return []

                html = await response.text()

        soup = BeautifulSoup(html, "html.parser")

        results = []

        for result in soup.select(".result"):

            title = result.select_one(".result__title")
            link = result.select_one(".result__a")
            description = result.select_one(".result__snippet")

            if not title or not link:
                continue

            title_text = clean_text(title.get_text())
            url_text = link.get("href", "")
            description_text = (
                clean_text(description.get_text())
                if description
                else ""
            )

            if not url_text:
                continue

            results.append({
                "title": title_text,
                "url": url_text,
                "description": description_text
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

def save_knowledge(
    question,
    answer,
    sources=None,
    confidence=0.5
):

    if sources is None:
        sources = []

    question = clean_text(question)
    answer = clean_text(answer)

    if not question or not answer:
        return

    # Если такой вопрос уже есть — обновляем
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

    question_words = set(
        re.findall(
            r"[а-яА-Яa-zA-ZёЁ]{4,}",
            question.lower()
        )
    )

    if not question_words:
        return None

    best = None
    best_score = 0

    for item in memory["knowledge"]:

        text = (
            item["question"] + " " +
            item["answer"]
        ).lower()

        words = set(
            re.findall(
                r"[а-яА-Яa-zA-ZёЁ]{4,}",
                text
            )
        )

        common = question_words.intersection(words)

        score = len(common)

        if score > best_score:
            best_score = score
            best = item

    if best_score >= 2:
        return best

    return None


# ============================================================
# СОЗДАНИЕ ОТВЕТА
# ============================================================

def build_answer(question, results):

    if not results:
        return None

    # Собираем текст из найденных страниц
    texts = []

    for result in results:

        title = result["title"]
        description = result["description"]

        if description:
            texts.append(
                f"{title}. {description}"
            )
        else:
            texts.append(title)

    full_text = " ".join(texts)

    full_text = clean_text(full_text)

    if not full_text:
        return None

    # Разбиваем на предложения
    sentences = re.split(
        r"(?<=[.!?])\s+",
        full_text
    )

    # Слова вопроса
    question_words = set(
        re.findall(
            r"[а-яА-Яa-zA-ZёЁ]{4,}",
            question.lower()
        )
    )

    scored = []

    for sentence in sentences:

        words = set(
            re.findall(
                r"[а-яА-Яa-zA-ZёЁ]{4,}",
                sentence.lower()
            )
        )

        score = len(
            question_words.intersection(words)
        )

        if len(sentence) > 40:
            scored.append(
                (score, sentence)
            )

    scored.sort(
        key=lambda x: x[0],
        reverse=True
    )

    selected = []

    for score, sentence in scored:

        if sentence not in selected:

            selected.append(sentence)

        if len(selected) >= 5:
            break

    if not selected:
        selected = sentences[:4]

    answer = " ".join(selected)

    if len(answer) > 1800:
        answer = answer[:1800] + "..."

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

    # Ограничиваем историю
    if len(memory["questions"]) > 1000:
        memory["questions"] = memory["questions"][-1000:]

    save_memory()

    await message.answer(
        "🤔 Думаю над вопросом и проверяю информацию..."
    )

    # --------------------------------------------------------
    # Сначала проверяем собственную память
    # --------------------------------------------------------

    remembered = search_memory(question)

    if remembered:

        await message.answer(
            "🧠 <b>Нашёл это в своей памяти:</b>\n\n"
            + remembered["answer"]
            + "\n\n"
            "📌 Уровень уверенности: "
            + str(
                round(
                    remembered["confidence"] * 100
                )
            )
            + "%"
        )

        return

    # --------------------------------------------------------
    # Интернет
    # --------------------------------------------------------

    results = await web_search(question)

    if not results:

        await message.answer(
            "❌ Не получилось найти информацию в интернете.\n\n"
            "Попробуй сформулировать вопрос немного иначе."
        )

        return

    # --------------------------------------------------------
    # Формируем ответ
    # --------------------------------------------------------

    answer = build_answer(
        question,
        results
    )

    if not answer:

        await message.answer(
            "❌ Я нашёл страницы, но не смог "
            "извлечь нормальный ответ."
        )

        return

    # --------------------------------------------------------
    # Сохраняем знание
    # --------------------------------------------------------

    sources = [
        r["url"]
        for r in results[:5]
    ]

    save_knowledge(
        question,
        answer,
        sources,
        confidence=0.6
    )

    # --------------------------------------------------------
    # Ответ пользователю
    # --------------------------------------------------------

    response = (
        "🤖 <b>Ответ:</b>\n\n"
        f"{answer}\n\n"
        "🧠 Я сохранил эту информацию в память."
    )

    await message.answer(response)


# ============================================================
# START
# ============================================================

@dp.message(Command("start"))
async def start(message: Message):

    await message.answer(
        "🤖 <b>Автономный бот запущен.</b>\n\n"
        "Я умею:\n"
        "• отвечать на обычные вопросы;\n"
        "• искать информацию в интернете;\n"
        "• сохранять знания;\n"
        "• использовать накопленную память;\n"
        "• выполнять автономные задачи;\n"
        "• самостоятельно проверять накопленную информацию.\n\n"
        "Просто напиши мне любой вопрос.",
        reply_markup=main_keyboard()
    )


# ============================================================
# HELP
# ============================================================

@dp.message(Command("help"))
async def help_command(message: Message):

    await message.answer(
        "<b>Команды:</b>\n\n"
        "/start — главное меню\n"
        "/search — поиск\n"
        "/learn — обучение\n"
        "/memory — память\n"
        "/status — состояние\n"
        "/autonomous — автономный режим\n"
        "/stop — остановить задачи\n\n"
        "Также можно просто написать вопрос."
    )


# ============================================================
# SEARCH
# ============================================================

@dp.message(Command("search"))
async def search_command(message: Message):

    query = message.text.replace(
        "/search",
        "",
        1
    ).strip()

    if not query:

        await message.answer(
            "Напиши запрос:\n\n"
            "<code>/search погода в Киеве</code>"
        )

        return

    await message.answer(
        "🌐 Ищу информацию..."
    )

    results = await web_search(query)

    if not results:

        await message.answer(
            "❌ Ничего не найдено."
        )

        return

    text = "🌐 <b>Результаты:</b>\n\n"

    for i, result in enumerate(
        results,
        start=1
    ):

        text += (
            f"<b>{i}. "
            f"{result['title']}</b>\n"
            f"{result['description'][:300]}\n"
            f"{result['url']}\n\n"
        )

    await message.answer(text[:4000])


# ============================================================
# MEMORY
# ============================================================

@dp.message(Command("memory"))
async def memory_command(message: Message):

    count = len(
        memory["knowledge"]
    )

    await message.answer(
        "📚 <b>Моя память</b>\n\n"
        f"Знаний: <b>{count}</b>\n"
        f"Вопросов: <b>{memory['stats']['questions']}</b>\n"
        f"Поисков: <b>{memory['stats']['searches']}</b>\n"
        f"Изучено: <b>{memory['stats']['learned']}</b>"
    )


# ============================================================
# STATUS
# ============================================================

@dp.message(Command("status"))
async def status_command(message: Message):

    await message.answer(
        "📊 <b>Состояние:</b>\n\n"
        f"🧠 Знаний: {len(memory['knowledge'])}\n"
        f"❓ Вопросов: {memory['stats']['questions']}\n"
        f"🌐 Поисков: {memory['stats']['searches']}\n"
        f"📚 Изучено: {memory['stats']['learned']}\n"
        f"🤖 Активных задач: {len(running_tasks)}"
    )


# ============================================================
# АВТОНОМНОЕ ОБУЧЕНИЕ
# ============================================================

async def autonomous_learning(chat_id):

    if chat_id in running_tasks:
        return

    running_tasks[chat_id] = True

    try:

        await bot.send_message(
            chat_id,
            "🤖 <b>Автономное обучение запущено.</b>\n\n"
            "Я буду самостоятельно искать информацию "
            "и добавлять её в память."
        )

        for step in range(
            MAX_AUTONOMOUS_STEPS
        ):

            if chat_id not in running_tasks:
                break

            # ------------------------------------------------
            # Определяем тему
            # ------------------------------------------------

            if memory["knowledge"]:

                recent = memory["knowledge"][-1]

                base_topic = recent["question"]

            else:

                base_topic = (
                    "интересные научные факты "
                    "технологии история космос"
                )

            # ------------------------------------------------
            # Создаём новую исследовательскую тему
            # ------------------------------------------------

            topics = [
                "новые факты",
                "интересные факты",
                "как это работает",
                "история",
                "наука",
                "технологии",
                "космос",
                "компьютеры"
            ]

            topic = topics[
                step % len(topics)
            ]

            query = f"{topic} {base_topic}"

            results = await web_search(
                query,
                limit=5
            )

            if not results:
                continue

            answer = build_answer(
                query,
                results
            )

            if answer:

                sources = [
                    r["url"]
                    for r in results[:5]
                ]

                save_knowledge(
                    query,
                    answer,
                    sources,
                    confidence=0.5
                )

                await bot.send_message(
                    chat_id,
                    "🧠 <b>Я чему-то научился.</b>\n\n"
                    f"<b>Тема:</b> {query}\n\n"
                    f"{answer[:1000]}"
                )

            await asyncio.sleep(3)

        await bot.send_message(
            chat_id,
            "✅ <b>Цикл автономного обучения завершён.</b>\n\n"
            f"Всего знаний: {len(memory['knowledge'])}"
        )

    except Exception as e:

        print(
            "Ошибка автономного обучения:",
            e
        )

        try:
            await bot.send_message(
                chat_id,
                "❌ Автономное обучение остановилось "
                "из-за ошибки."
            )
        except Exception:
            pass

    finally:

        running_tasks.pop(
            chat_id,
            None
        )


# ============================================================
# LEARN
# ============================================================

@dp.message(Command("learn"))
async def learn_command(message: Message):

    chat_id = message.chat.id

    if chat_id in running_tasks:

        await message.answer(
            "🧠 Я уже учусь."
        )

        return

    asyncio.create_task(
        autonomous_learning(chat_id)
    )


# ============================================================
# AUTONOMOUS
# ============================================================

@dp.message(Command("autonomous"))
async def autonomous_command(message: Message):

    chat_id = message.chat.id

    if chat_id in running_tasks:

        await message.answer(
            "🤖 Автономный режим уже работает."
        )

        return

    asyncio.create_task(
        autonomous_learning(chat_id)
    )


# ============================================================
# STOP
# ============================================================

@dp.message(Command("stop"))
async def stop_command(message: Message):

    chat_id = message.chat.id

    if chat_id in running_tasks:

        running_tasks.pop(
            chat_id,
            None
        )

        await message.answer(
            "⛔ Автономная задача остановлена."
        )

    else:

        await message.answer(
            "Сейчас нет активной автономной задачи."
        )


# ============================================================
# КНОПКИ
# ============================================================

@dp.callback_query(F.data == "search")
async def button_search(callback: CallbackQuery):

    await callback.answer()

    await callback.message.answer(
        "🌐 Напиши мне любой поисковый запрос.\n\n"
        "Например:\n"
        "<code>новости космоса</code>"
    )


@dp.callback_query(F.data == "learn")
async def button_learn(callback: CallbackQuery):

    await callback.answer()

    chat_id = callback.message.chat.id

    if chat_id in running_tasks:

        await callback.message.answer(
            "🧠 Я уже учусь."
        )

        return

    asyncio.create_task(
        autonomous_learning(chat_id)
    )


@dp.callback_query(F.data == "memory")
async def button_memory(callback: CallbackQuery):

    await callback.answer()

    await callback.message.answer(
        "📚 <b>Память:</b>\n\n"
        f"Знаний: {len(memory['knowledge'])}\n"
        f"Вопросов: {memory['stats']['questions']}\n"
        f"Поисков: {memory['stats']['searches']}"
    )


@dp.callback_query(F.data == "status")
async def button_status(callback: CallbackQuery):

    await callback.answer()

    await callback.message.answer(
        "📊 <b>Статус:</b>\n\n"
        f"🧠 Знаний: {len(memory['knowledge'])}\n"
        f"❓ Вопросов: {memory['stats']['questions']}\n"
        f"🌐 Поисков: {memory['stats']['searches']}\n"
        f"🤖 Активных задач: {len(running_tasks)}"
    )


@dp.callback_query(F.data == "autonomous")
async def button_autonomous(callback: CallbackQuery):

    await callback.answer()

    chat_id = callback.message.chat.id

    if chat_id in running_tasks:

        await callback.message.answer(
            "🤖 Автономный режим уже работает."
        )

        return

    asyncio.create_task(
        autonomous_learning(chat_id)
    )


@dp.callback_query(F.data == "stop")
async def button_stop(callback: CallbackQuery):

    await callback.answer()

    chat_id = callback.message.chat.id

    if chat_id in running_tasks:

        running_tasks.pop(
            chat_id,
            None
        )

        await callback.message.answer(
            "⛔ Задача остановлена."
        )

    else:

        await callback.message.answer(
            "Активных задач нет."
        )


# ============================================================
# ГЛАВНЫЙ ОБРАБОТЧИК ТЕКСТА
# ============================================================

@dp.message(F.text)
async def all_text_messages(message: Message):

    text = message.text.strip()

    # Команды здесь не обрабатываем
    if text.startswith("/"):
        return

    # ЛЮБОЙ обычный текст считаем вопросом
    await answer_question(message)


# ============================================================
# ЗАПУСК
# ============================================================

async def main():

    print("================================")
    print("AUTONOMOUS BOT")
    print("Bot started")
    print("================================")

    await dp.start_polling(
        bot
    )


if __name__ == "__main__":

    try:
        asyncio.run(main())

    except KeyboardInterrupt:

        print(
            "Bot stopped."
        )