from aiogram import Router, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import Message, CallbackQuery

from keyboards import main_menu_kb
from handlers.participate import handle_join_payload

router = Router(name="start")

WELCOME_TEXT = (
    "👋 <b>Welcome to Vote Bot!</b>\n\n"
    "I help you run <b>vote-based giveaways</b> in your channels and groups.\n\n"
    "🔗 <b>Connect</b> — link your channels/groups\n"
    "🎉 <b>Create Giveaway</b> — start a new vote giveaway\n"
    "⚙️ <b>Manage</b> — control votes and end giveaways\n\n"
    "Choose an option below to get started 👇"
)


@router.message(CommandStart(deep_link=True))
async def start_deep_link(message: Message, command: CommandObject):
    payload = command.args or ""
    if payload.startswith("join_"):
        gid = payload.split("join_", 1)[1]
        await handle_join_payload(message, gid)
        return
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_kb())


@router.message(CommandStart())
async def start_plain(message: Message):
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_kb())


@router.callback_query(F.data == "menu:main")
async def back_to_main(call: CallbackQuery):
    await call.message.edit_text(WELCOME_TEXT, reply_markup=main_menu_kb())
    await call.answer()
