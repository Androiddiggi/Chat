import asyncio
import json
import os
from pathlib import Path
from urllib.parse import quote

import aiohttp
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

# =========================================================
# НАСТРОЙКИ
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "7705314975:AAGpe-DrPVwxqeBvCK72dZIYP4YvPkzLBLQ")

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://127.0.0.1:11434"
)

MODEL = os.getenv(
    "OLLAMA_MODEL",
    "qwen2.5:3b"
)

MAX_STEPS = 8

MEMORY_FILE = Path("memory.json")


# =========================================================
# ПРОВЕРКА ТОКЕНА
# =========================================================

if BOT_TOKEN == "ВСТАВЬ_СЮДА_ТОКЕН":
    raise RuntimeError(
        "Вставь токен Telegram-бота в BOT_TOKEN"
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
        ) as f:

            memory = json.load(f)

    except Exception:

        memory = {}


def save_memory():

    try:

        with open(
            MEMORY_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                memory,
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        print(
            "Ошибка сохранения памяти:",
            e
        )


def add_memory(
    user_id,
    role,
    text
):

    uid = str(user_id)

    if uid not in memory:
        memory[uid] = []

    memory[uid].append({
        "role": role,
        "content": text
    })

    # Храним последние 40 сообщений
    memory[uid] = memory[uid][-40:]

    save_memory()


def get_memory(user_id):

    return memory.get(
        str(user_id),
        []
    )


# =========================================================
# СОСТОЯНИЯ
# =========================================================

user_mode = {}

running_tasks = {}


# =========================================================
# КЛАВИАТУРА
# =========================================================

def keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="💬 Чат",
                    callback_data="chat"
                ),

                InlineKeyboardButton(
                    text="🧠 Автономный режим",
                    callback_data="auto"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🌐 Интернет",
                    callback_data="web"
                ),

                InlineKeyboardButton(
                    text="📚 Память",
                    callback_data="memory"
                )
            ],

            [
                InlineKeyboardButton(
                    text="📊 Статус",
                    callback_data="status"
                ),

                InlineKeyboardButton(
                    text="⛔ Стоп",
                    callback_data="stop"
                )
            ]

        ]
    )


# =========================================================
# OLLAMA
# =========================================================

async def ask_ai(
    messages
):

    url = (
        OLLAMA_URL
        + "/api/chat"
    )

    data = {
        "model": MODEL,
        "messages": messages,
        "stream": False
    }

    timeout = aiohttp.ClientTimeout(
        total=600
    )

    async with aiohttp.ClientSession(
        timeout=timeout
    ) as session:

        async with session.post(
            url,
            json=data
        ) as response:

            if response.status != 200:

                error = await response.text()

                raise RuntimeError(
                    f"Ollama ошибка "
                    f"{response.status}: "
                    f"{error[:500]}"
                )

            result = await response.json()

            return result[
                "message"
            ][
                "content"
            ]


# =========================================================
# SYSTEM PROMPT
# =========================================================

SYSTEM = """
Ты — автономный локальный AI.

Ты работаешь внутри Telegram-бота.

Твои возможности:

1. Общение с пользователем.
2. Анализ информации.
3. Интернет-поиск через специальный инструмент.
4. Долговременная память.
5. Планирование задач.
6. Автономное исследование.

В автономном режиме:

- разбивай большую задачу на маленькие шаги;
- проверяй информацию;
- используй интернет, когда это необходимо;
- анализируй найденную информацию;
- сохраняй полезные результаты в память.

Не придумывай результаты поиска.

Не утверждай, что выполнил действие,
если оно фактически не выполнялось.

Не пытайся получить пароли,
токены или секретные данные.

Не выполняй опасные действия.
"""


# =========================================================
# INTERNET SEARCH
# =========================================================

async def search_web(
    query
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

    for result in soup.select(
        ".result"
    )[:5]:

        title = result.select_one(
            ".result__a"
        )

        description = result.select_one(
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
# ПОИСК + AI
# =========================================================

async def internet_answer(
    user_id,
    query
):

    results = await search_web(
        query
    )

    if not results:

        return (
            "🌐 Ничего не найдено."
        )

    text = ""

    for i, item in enumerate(
        results,
        1
    ):

        text += (
            f"\n{i}. {item['title']}\n"
            f"{item['url']}\n"
            f"{item['description']}\n"
        )

    prompt = f"""
Пользователь попросил найти:

{query}

Вот результаты поиска:

{text}

Проанализируй результаты и дай
пользователю понятный ответ.

Не придумывай информацию,
которой нет в результатах.
"""

    answer = await ask_ai([
        {
            "role": "system",
            "content": SYSTEM
        },

        {
            "role": "user",
            "content": prompt
        }
    ])

    add_memory(
        user_id,
        "user",
        "Поиск: " + query
    )

    add_memory(
        user_id,
        "assistant",
        answer
    )

    return answer


# =========================================================
# /START
# =========================================================

@dp.message(
    CommandStart()
)
async def start(
    message: Message
):

    await message.answer(
        "🤖 <b>Local AI</b>\n\n"
        "Я готов к работе.\n\n"
        "Выбери режим:",
        reply_markup=keyboard()
    )


# =========================================================
# /HELP
# =========================================================

@dp.message(
    Command("help")
)
async def help_command(
    message: Message
):

    await message.answer(
        "🤖 <b>Local AI</b>\n\n"

        "💬 <b>Чат</b> — обычное общение.\n"
        "🧠 <b>Автономный режим</b> — "
        "ИИ получает цель и самостоятельно "
        "разбирает её.\n"
        "🌐 <b>Интернет</b> — поиск информации.\n"
        "📚 <b>Память</b> — сохранённая история.\n"
        "📊 <b>Статус</b> — состояние системы.\n"
        "⛔ <b>Стоп</b> — остановить автономную задачу."
    )


# =========================================================
# КНОПКА ЧАТ
# =========================================================

@dp.callback_query(
    F.data == "chat"
)
async def chat_button(
    callback: CallbackQuery
):

    await callback.answer()

    user_mode[
        callback.from_user.id
    ] = "chat"

    await callback.message.answer(
        "💬 <b>Чат включён.</b>\n\n"
        "Напиши сообщение."
    )


# =========================================================
# КНОПКА ИНТЕРНЕТ
# =========================================================

@dp.callback_query(
    F.data == "web"
)
async def web_button(
    callback: CallbackQuery
):

    await callback.answer()

    user_mode[
        callback.from_user.id
    ] = "web"

    await callback.message.answer(
        "🌐 <b>Режим поиска.</b>\n\n"
        "Напиши, что мне найти."
    )


# =========================================================
# КНОПКА АВТОНОМНОГО РЕЖИМА
# =========================================================

@dp.callback_query(
    F.data == "auto"
)
async def auto_button(
    callback: CallbackQuery
):

    await callback.answer()

    user_mode[
        callback.from_user.id
    ] = "auto"

    await callback.message.answer(
        "🧠 <b>Автономный режим.</b>\n\n"
        "Напиши цель.\n\n"
        "Например:\n"
        "<code>Изучи Python и "
        "составь программу обучения.</code>"
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

    history = get_memory(
        callback.from_user.id
    )

    if not history:

        await callback.message.answer(
            "📚 Память пока пустая."
        )

        return

    result = (
        "📚 <b>Последние записи:</b>\n\n"
    )

    for item in history[-10:]:

        role = (
            "Ты"
            if item["role"] == "user"
            else "ИИ"
        )

        text = item[
            "content"
        ]

        if len(text) > 500:
            text = text[:500] + "..."

        result += (
            f"<b>{role}:</b>\n"
            f"{text}\n\n"
        )

    await callback.message.answer(
        result
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

    running = (
        callback.from_user.id
        in running_tasks
    )

    await callback.message.answer(
        "📊 <b>Статус</b>\n\n"
        f"Модель: <code>{MODEL}</code>\n"
        f"Ollama: <code>{OLLAMA_URL}</code>\n"
        f"Автономный режим: "
        f"{'🟢 работает' if running else '⚪ выключен'}"
    )


# =========================================================
# STOP
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
            "ℹ️ Автономных задач нет."
        )


# =========================================================
# АВТОНОМНЫЙ AI
# =========================================================

async def autonomous(
    message: Message,
    goal: str
):

    user_id = message.from_user.id

    context = ""

    try:

        await message.answer(
            "🧠 <b>Автономный режим запущен.</b>\n\n"
            f"Цель:\n{goal}"
        )

        for step in range(
            1,
            MAX_STEPS + 1
        ):

            prompt = f"""
Твоя задача:

{goal}

Текущий шаг:

{step}

Предыдущий результат:

{context}

Реши, что делать дальше.

Если нужна информация из интернета:

ACTION: SEARCH
QUERY: запрос

Если нужно проанализировать уже
полученную информацию:

ACTION: ANALYZE
TEXT: текст

Если задача закончена:

ACTION: FINISH
TEXT: итоговый ответ
"""

            decision = await ask_ai([
                {
                    "role":
                        "system",
                    "content":
                        SYSTEM
                },

                {
                    "role":
                        "user",
                    "content":
                        prompt
                }
            ])

            # -----------------------------
            # SEARCH
            # -----------------------------

            if "ACTION: SEARCH" in decision:

                query = ""

                if "QUERY:" in decision:

                    query = decision.split(
                        "QUERY:",
                        1
                    )[1].strip()

                if not query:
                    query = goal

                await message.answer(
                    f"🔎 <b>Шаг {step}</b>\n\n"
                    f"Ищу:\n{query}"
                )

                results = await search_web(
                    query
                )

                context = json.dumps(
                    results,
                    ensure_ascii=False
                )

            # -----------------------------
            # ANALYZE
            # -----------------------------

            elif "ACTION: ANALYZE" in decision:

                analysis = await ask_ai([
                    {
                        "role":
                            "system",
                        "content":
                            SYSTEM
                    },

                    {
                        "role":
                            "user",
                        "content":
                            f"""
Проанализируй:

{context}
"""
                    }
                ])

                context = analysis

                await message.answer(
                    f"🧠 <b>Шаг {step}</b>\n\n"
                    f"{analysis[:3500]}"
                )

                add_memory(
                    user_id,
                    "assistant",
                    analysis
                )

            # -----------------------------
            # FINISH
            # -----------------------------

            elif "ACTION: FINISH" in decision:

                if "TEXT:" in decision:

                    result = decision.split(
                        "TEXT:",
                        1
                    )[1].strip()

                else:

                    result = decision

                await message.answer(
                    "✅ <b>Задача завершена.</b>\n\n"
                    f"{result[:4000]}"
                )

                add_memory(
                    user_id,
                    "autonomous",
                    result
                )

                return

            else:

                context = decision

            await asyncio.sleep(1)

        await message.answer(
            "ℹ️ Достигнут максимальный "
            f"лимит шагов: {MAX_STEPS}"
        )

    except asyncio.CancelledError:

        await message.answer(
            "⛔ Автономный режим остановлен."
        )

    except Exception as e:

        await message.answer(
            "❌ Ошибка:\n"
            f"<code>{str(e)[:1000]}</code>"
        )

    finally:

        running_tasks.pop(
            user_id,
            None
        )

        user_mode.pop(
            user_id,
            None
        )


# =========================================================
# ОБРАБОТКА ТЕКСТА
# =========================================================

@dp.message(
    F.text
)
async def text_handler(
    message: Message
):

    text = message.text.strip()

    user_id = message.from_user.id

    mode = user_mode.get(
        user_id,
        "chat"
    )

    # =====================================================
    # АВТОНОМНЫЙ РЕЖИМ
    # =====================================================

    if mode == "auto":

        if user_id in running_tasks:

            await message.answer(
                "⚠️ У тебя уже выполняется задача."
            )

            return

        task = asyncio.create_task(
            autonomous(
                message,
                text
            )
        )

        running_tasks[
            user_id
        ] = task

        return

    # =====================================================
    # ИНТЕРНЕТ
    # =====================================================

    if mode == "web":

        await message.answer(
            "🔎 Ищу..."
        )

        try:

            answer = await internet_answer(
                user_id,
                text
            )

            await message.answer(
                answer[:4000]
            )

        except Exception as e:

            await message.answer(
                "❌ Ошибка поиска:\n"
                f"<code>{str(e)[:1000]}</code>"
            )

        user_mode.pop(
            user_id,
            None
        )

        return

    # =====================================================
    # ОБЫЧНЫЙ ЧАТ
    # =====================================================

    add_memory(
        user_id,
        "user",
        text
    )

    history = get_memory(
        user_id
    )

    messages = [
        {
            "role":
                "system",
            "content":
                SYSTEM
        }
    ]

    messages.extend(
        history[-25:]
    )

    await message.bot.send_chat_action(
        message.chat.id,
        "typing"
    )

    try:

        answer = await ask_ai(
            messages
        )

        add_memory(
            user_id,
            "assistant",
            answer
        )

        # Разбиваем длинные ответы Telegram
        for i in range(
            0,
            len(answer),
            3900
        ):

            await message.answer(
                answer[i:i + 3900]
            )

    except Exception as e:

        await message.answer(
            "❌ Не удалось подключиться "
            "к AI.\n\n"
            f"<code>{str(e)[:1000]}</code>"
        )


# =========================================================
# ЗАПУСК
# =========================================================

async def main():

    load_memory()

    print()
    print("==============================")
    print("       LOCAL AI BOT")
    print("==============================")
    print(
        "Model:",
        MODEL
    )
    print(
        "Ollama:",
        OLLAMA_URL
    )
    print("==============================")
    print()

    await dp.start_polling(
        bot
    )


if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print(
            "Бот остановлен."
        )