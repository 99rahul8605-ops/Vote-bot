import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from handlers import start, connect, giveaway, participate, manage, score, chat_member

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")


async def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    # order matters: participate before start isn't required since start imports it directly
    dp.include_router(start.router)
    dp.include_router(connect.router)
    dp.include_router(giveaway.router)
    dp.include_router(participate.router)
    dp.include_router(manage.router)
    dp.include_router(score.router)
    dp.include_router(chat_member.router)

    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Vote Bot started. Polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
