import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from groq import AsyncGroq

TELEGRAM_TOKEN = "7705314975:AAGpe-DrPVwxqeBvCK72dZIYP4YvPkzLBLQ"
GROQ_API_KEY = "ТВОЙ_GROQ_API_KEY"

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
groq_client = AsyncGroq(api_key=GROQ_API_KEY)

@dp.message(F.text)
async def handle_message(message: Message):
    if message.text.startswith("/"):
        return

    await bot.send_chat_action(message.chat.id, action="typing")

    try:
        response = await groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",  # Быстрая и умная модель
            messages=[
                {"role": "system", "content": "Ты вежливый помощник. Отвечай кратко и естественным языком."},
                {"role": "user", "content": message.text}
            ]
        )
        answer = response.choices[0].message.content
        await message.answer(answer)
    except Exception as e:
        print("Ошибка Groq:", e)
        await message.answer("⚠️ Не удалось получить ответ от нейросети.")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
