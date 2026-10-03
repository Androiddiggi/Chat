import asyncio
import json
import os
import re
from pathlib import Path
from urllib.parse import quote

import aiohttp
from bs4 import BeautifulSoup

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

# =========================================================
# НАСТРОЙКИ
# =========================================================

# ВСТАВЬ СЮДА ТОКЕН ОТ @BotFather
BOT_TOKEN = "7705314975:AAGpe-DrPVwxqeBvCK72dZIYP4YvPkzLBLQ"

# Максимальное количество шагов автономной задачи
MAX_STEPS = 5

# Файл постоянной памяти
MEMORY_FILE = Path("memory.json")


# =========================================================
# ПРОВЕРКА
# =========================================================

if BOT_TOKEN == "ВСТАВЬ_СЮДА_ТОКЕН":
    raise RuntimeError(
        "Вставь токен Telegram-бота в переменную BOT_TOKEN"
    )


# =========================================================
# TELEGRAM
# =========================================================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher()


# =========================================================
# ПАМЯТЬ
# =========================================================

memory = {}


def load_memory():
    global memory

    if not MEMORY_FILE.exists():
        memory = {}
        return

    try:
        with open(
            MEMORY_FILE,
            "r",
            encoding="utf-8"
        ) as file:
            memory = json.load(file)

    except Exception:
        memory = {}


def save_memory():

    try:
        with open(
            MEMORY_FILE,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                memory,
                file,
                ensure_ascii=False,
                indent=2
            )

    except Exception as error:

        print(
            "Ошибка памяти:",
            error
        )


def add_memory(
    user_id,
    text
):

    user_id = str(user_id)

    if user_id not in memory:
        memory[user_id] = []

    memory[user_id].append(text)

    # Чтобы файл не разрастался бесконечно
    memory[user_id] = memory[user_id][-100:]

    save_memory()


# =========================================================
# СОСТОЯНИЯ
# =========================================================

user_modes = {}

running_tasks = {}


# =========================================================
# КЛАВИАТУРА
# =========================================================

def main_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="🌐 Поиск",
                    callback_data="search"
                ),

                InlineKeyboardButton(
                    text="🧠 Автономная задача",
                    callback_data="auto"
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
                    text="⛔ Остановить",
                    callback_data="stop"
                )
            ]
        ]
    )


# =========================================================
# ИНТЕРНЕТ-ПОИСК
# =========================================================

async def web_search(
    query,
    limit=5
):

    url = (
        "https://html.duckduckgo.com/html/?q="
        + quote(query)
    )

    headers = {
        "User-Agent":
            "Mozilla/5.0"
    }

    timeout = aiohttp.ClientTimeout(
        total=30
    )

    async with aiohttp.ClientSession(
        timeout=timeout,
        headers=headers
    ) as session:

        async with session.get(
            url
        ) as response:

            if response.status != 200:
                return []

            html = await response.text()

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    results = []

    for item in soup.select(
        ".result"
    )[:limit]:

        title = item.select_one(
            ".result__a"
        )

        description = item.select_one(
            ".result__snippet"
        )

        if not title:
            continue

        results.append({
            "title":
                title.get_text(
                    " ",
                    strip=True
                ),

            "url":
                title.get(
                    "href",
                    ""
                ),

            "description":
                (
                    description.get_text(
                        " ",
                        strip=True
                    )
                    if description
                    else ""
                )
        })

    return results


# =========================================================
# КОМАНДЫ
# =========================================================

@dp.message(CommandStart())
async def start(
    message: Message
):

    await message.answer(
        "🤖 <b>Автономный бот</b>\n\n"
        "Это версия без нейросети и API.\n\n"
        "Я могу искать информацию в интернете, "
        "сохранять результаты и выполнять "
        "простые автономные задачи.",
        reply_markup=main_keyboard()
    )


@dp.message(Command("help"))
async def help_command(
    message: Message
):

    await message.answer(
        "📖 <b>Команды</b>\n\n"
        "/start — главное меню\n"
        "/search текст — поиск\n"
        "/goal текст — автономная задача\n"
        "/memory — память\n"
        "/stop — остановить задачу"
    )


@dp.message(Command("search"))
async def search_command(
    message: Message
):

    query = message.text[
        len("/search"):
    ].strip()

    if not query:

        await message.answer(
            "Напиши запрос после /search"
        )

        return

    await perform_search(
        message,
        query
    )


@dp.message(Command("goal"))
async def goal_command(
    message: Message
):

    goal = message.text[
        len("/goal"):
    ].strip()

    if not goal:

        await message.answer(
            "Напиши цель после /goal"
        )

        return

    await start_autonomous(
        message,
        goal
    )


@dp.message(Command("memory"))
async def memory_command(
    message: Message
):

    user_id = str(
        message.from_user.id
    )

    data = memory.get(
        user_id,
        []
    )

    if not data:

        await message.answer(
            "📚 Память пустая."
        )

        return

    result = (
        "📚 <b>Память:</b>\n\n"
    )

    for item in data[-10:]:

        result += (
            "• "
            + item[:700]
            + "\n\n"
        )

    await message.answer(
        result[:4000]
    )


@dp.message(Command("stop"))
async def stop_command(
    message: Message
):

    user_id = message.from_user.id

    task = running_tasks.get(
        user_id
    )

    if task:

        task.cancel()

        running_tasks.pop(
            user_id,
            None
        )

        await message.answer(
            "⛔ Задача остановлена."
        )

    else:

        await message.answer(
            "ℹ️ Активных задач нет."
        )


# =========================================================
# КНОПКА ПОИСКА
# =========================================================

@dp.callback_query(
    F.data == "search"
)
async def search_button(
    callback: CallbackQuery
):

    await callback.answer()

    user_modes[
        callback.from_user.id
    ] = "search"

    await callback.message.answer(
        "🌐 <b>Поиск</b>\n\n"
        "Напиши поисковый запрос."
    )


# =========================================================
# КНОПКА АВТОНОМНОЙ ЗАДАЧИ
# =========================================================

@dp.callback_query(
    F.data == "auto"
)
async def auto_button(
    callback: CallbackQuery
):

    await callback.answer()

    user_modes[
        callback.from_user.id
    ] = "auto"

    await callback.message.answer(
        "🧠 <b>Автономный режим</b>\n\n"
        "Напиши цель.\n\n"
        "Например:\n"
        "<code>Найди информацию о Python "
        "и собери основные факты.</code>"
    )


# =========================================================
# ПАМЯТЬ
# =========================================================

@dp.callback_query(
    F.data == "memory"
)
async def memory_button(
    callback: CallbackQuery
):

    await callback.answer()

    user_id = str(
        callback.from_user.id
    )

    data = memory.get(
        user_id,
        []
    )

    if not data:

        await callback.message.answer(
            "📚 Память пустая."
        )

        return

    result = (
        "📚 <b>Последние записи:</b>\n\n"
    )

    for item in data[-10:]:

        result += (
            "• "
            + item[:700]
            + "\n\n"
        )

    await callback.message.answer(
        result[:4000]
    )


# =========================================================
# STATUS
# =========================================================

@dp.callback_query(
    F.data == "status"
)
async def status_button(
    callback: CallbackQuery
):

    await callback.answer()

    active = (
        callback.from_user.id
        in running_tasks
    )

    await callback.message.answer(
        "📊 <b>Статус</b>\n\n"
        "🤖 Нейросеть: отключена\n"
        "🌐 Интернет: доступен\n"
        "📚 Память: включена\n"
        "🧠 Автономный режим: "
        + (
            "🟢 работает"
            if active
            else "⚪ свободен"
        )
    )


# =========================================================
# STOP BUTTON
# =========================================================

@dp.callback_query(
    F.data == "stop"
)
async def stop_button(
    callback: CallbackQuery
):

    await callback.answer()

    user_id = callback.from_user.id

    task = running_tasks.get(
        user_id
    )

    if task:

        task.cancel()

        running_tasks.pop(
            user_id,
            None
        )

        await callback.message.answer(
            "⛔ Автономная задача остановлена."
        )

    else:

        await callback.message.answer(
            "ℹ️ Активных задач нет."
        )


# =========================================================
# ПОИСК
# =========================================================

async def perform_search(
    message: Message,
    query: str
):

    await message.answer(
        "🔎 Ищу информацию..."
    )

    try:

        results = await web_search(
            query
        )

    except Exception as error:

        await message.answer(
            "❌ Ошибка поиска:\n"
            f"<code>{str(error)[:1000]}</code>"
        )

        return

    if not results:

        await message.answer(
            "🔎 Ничего не найдено."
        )

        return

    output = (
        f"🔎 <b>Результаты:</b>\n\n"
    )

    for number, result in enumerate(
        results,
        1
    ):

        title = result[
            "title"
        ]

        description = result[
            "description"
        ]

        url = result[
            "url"
        ]

        output += (
            f"<b>{number}. "
            f"{title}</b>\n"
            f"{description}\n"
            f"{url}\n\n"
        )

    add_memory(
        message.from_user.id,
        "Поиск: "
        + query
        + "\n"
        + output[:2000]
    )

    await message.answer(
        output[:4000]
    )


# =========================================================
# АВТОНОМНАЯ ЛОГИКА
# =========================================================

async def autonomous_task(
    message: Message,
    goal: str
):

    user_id = message.from_user.id

    try:

        await message.answer(
            "🧠 <b>Начинаю автономную работу.</b>\n\n"
            f"Цель:\n{goal}"
        )

        add_memory(
            user_id,
            "Начата задача: "
            + goal
        )

        current_query = goal

        collected = []

        for step in range(
            1,
            MAX_STEPS + 1
        ):

            await message.answer(
                f"⚙️ Шаг {step}/{MAX_STEPS}"
            )

            # -------------------------------------------------
            # ШАГ 1: ПОИСК
            # -------------------------------------------------

            results = await web_search(
                current_query,
                limit=5
            )

            if not results:

                await message.answer(
                    "🔎 Информация не найдена."
                )

                break

            # -------------------------------------------------
            # СОХРАНЕНИЕ
            # -------------------------------------------------

            for result in results:

                collected.append(
                    result
                )

            # -------------------------------------------------
            # ПРОСТОЙ АНАЛИЗ
            # -------------------------------------------------

            words = {}

            for result in results:

                text = (
                    result["title"]
                    + " "
                    + result["description"]
                ).lower()

                text = re.sub(
                    r"[^а-яa-z0-9 ]",
                    " ",
                    text
                )

                for word in text.split():

                    if len(word) < 4:
                        continue

                    words[word] = (
                        words.get(
                            word,
                            0
                        )
                        + 1
                    )

            common_words = sorted(
                words.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10]

            summary = (
                f"Шаг {step}.\n"
                f"Запрос: {current_query}\n\n"
                "Найдено результатов: "
                f"{len(results)}\n\n"
                "Наиболее часто встречающиеся "
                "слова:\n"
            )

            for word, count in common_words:

                summary += (
                    f"• {word}: {count}\n"
                )

            # -------------------------------------------------
            # ПАМЯТЬ
            # -------------------------------------------------

            add_memory(
                user_id,
                summary
            )

            # -------------------------------------------------
            # ОТПРАВКА
            # -------------------------------------------------

            await message.answer(
                "📊 <b>Результат шага:</b>\n\n"
                + summary[:3000]
            )

            # -------------------------------------------------
            # АВТОНОМНОЕ ПЕРЕПЛАНИРОВАНИЕ
            # -------------------------------------------------

            if step < MAX_STEPS:

                # Берём наиболее информативный
                # результат и формируем новый запрос.

                best = results[0]

                current_query = (
                    goal
                    + " "
                    + best["title"]
                )

                await asyncio.sleep(
                    2
                )

            else:

                break

        # =====================================================
        # ФИНАЛЬНЫЙ ОТЧЁТ
        # =====================================================

        unique = {}

        for item in collected:

            unique[
                item["url"]
            ] = item

        final_text = (
            "✅ <b>Автономная задача завершена.</b>\n\n"
            f"Цель:\n{goal}\n\n"
            f"Выполнено шагов: "
            f"{MAX_STEPS}\n"
            f"Найдено уникальных источников: "
            f"{len(unique)}\n\n"
            "<b>Источники:</b>\n"
        )

        for item in list(
            unique.values()
        )[:10]:

            final_text += (
                "• "
                + item["title"]
                + "\n"
                + item["url"]
                + "\n\n"
            )

        await message.answer(
            final_text[:4000]
        )

        add_memory(
            user_id,
            "Завершена задача: "
            + goal
        )

    except asyncio.CancelledError:

        await message.answer(
            "⛔ Автономная задача остановлена."
        )

    except Exception as error:

        await message.answer(
            "❌ Ошибка автономной задачи:\n"
            f"<code>{str(error)[:1000]}</code>"
        )

    finally:

        running_tasks.pop(
            user_id,
            None
        )

        user_modes.pop(
            user_id,
            None
        )


# =========================================================
# ЗАПУСК АВТОНОМНОЙ ЗАДАЧИ
# =========================================================

async def start_autonomous(
    message: Message,
    goal: str
):

    user_id = message.from_user.id

    if user_id in running_tasks:

        await message.answer(
            "⚠️ У тебя уже выполняется задача."
        )

        return

    task = asyncio.create_task(
        autonomous_task(
            message,
            goal
        )
    )

    running_tasks[
        user_id
    ] = task


# =========================================================
# ОБЫЧНЫЙ ТЕКСТ
# =========================================================

@dp.message(F.text)
async def text_handler(
    message: Message
):

    text = message.text.strip()

    user_id = message.from_user.id

    mode = user_modes.get(
        user_id
    )

    # -------------------------------------------------------
    # ПОИСК
    # -------------------------------------------------------

    if mode == "search":

        user_modes.pop(
            user_id,
            None
        )

        await perform_search(
            message,
            text
        )

        return

    # -------------------------------------------------------
    # АВТОНОМНЫЙ РЕЖИМ
    # -------------------------------------------------------

    if mode == "auto":

        user_modes.pop(
            user_id,
            None
        )

        await start_autonomous(
            message,
            text
        )

        return

    # -------------------------------------------------------
    # ЕСЛИ ПРОСТО НАПИСАЛ ТЕКСТ
    # -------------------------------------------------------

    await message.answer(
        "🤖 Я работаю без нейросети.\n\n"
        "Выбери действие:",
        reply_markup=main_keyboard()
    )


# =========================================================
# MAIN
# =========================================================

async def main():

    load_memory()

    print(
        "================================"
    )

    print(
        "AUTONOMOUS TELEGRAM BOT"
    )

    print(
        "AI: OFF"
    )

    print(
        "WEB SEARCH: ON"
    )

    print(
        "MEMORY: ON"
    )

    print(
        "================================"
    )

    await dp.start_polling(
        bot
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print(
            "Бот остановлен."
        )
    ```

### Что нужно установить на Bot-Hosting

В зависимости от того, как там задаются зависимости, нужны:

```text
aiogram
aiohttp
beautifulsoup4