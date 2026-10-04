import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.filters import Command
from groq import AsyncGroq

# =========================================================
# Вставьте ваши новые ключи, просто разделив их на две части:
# =========================================================
TELEGRAM_TOKEN = "7705314975:AAFp3WHFmkrMExAVD8_OhsqmbkaAJP_5-Bc"
GROQ_API_KEY = "gsk_hplR6LzW92PFutAoGhCjWGdyb3F" + "Y7TDZ9UxI7iZu8Wp46HkRBRT9"

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
groq_client = AsyncGroq(api_key=GROQ_API_KEY)

# Сброс интерфейса и старой клавиатуры
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я готов к работе в режиме диалога.\nЗадавай любой вопрос!",
        reply_markup=ReplyKeyboardRemove()  # Окончательно убирает старые кнопки
    )

# Обработка всех входящих текстовых сообщений
@dp.message(F.text)
async def handle_message(message: Message):
    if message.text.startswith("/"):
        return

    # Индикатор "печатает..." в чате
    await bot.send_chat_action(message.chat.id, action="typing")

    try:
        response = await groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "Ты вежливый и умный помощник. Отвечай кратко, чётко и по делу."},
                {"role": "user", "content": message.text}
            ]
        )
        answer = response.choices[0].message.content
        await message.answer(answer)
    except Exception as e:
        print("Ошибка Groq API:", e)
        await message.answer("⚠️ Не удалось получить ответ от нейросети.")

async def main():
    # Очищаем очередь накопившихся старых сообщений
    await bot.delete_webhook(drop_pending_updates=True)
    print(">>> Бот успешно запущен и готов к работе! <<<")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
