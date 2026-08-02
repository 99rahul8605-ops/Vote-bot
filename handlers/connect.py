from aiogram import Router, F
from aiogram.types import CallbackQuery

import database as db
from keyboards import connect_menu_kb, connect_list_kb, back_to_menu_kb

router = Router(name="connect")


@router.callback_query(F.data == "menu:connect")
async def show_connect(call: CallbackQuery):
    bot_me = await call.bot.get_me()
    await call.message.edit_text(
        "🔗 <b>Connect</b>\n\n"
        "Tap a button below to add me to your channel or group.\n"
        "Telegram will open a picker so you can choose which chat to add me to, "
        "with the right admin permissions pre-selected.",
        reply_markup=connect_menu_kb(bot_me.username),
    )
    await call.answer()


@router.callback_query(F.data == "connect:list")
async def show_connected_list(call: CallbackQuery):
    chats = await db.get_chats_by_owner(call.from_user.id)
    if not chats:
        await call.message.edit_text(
            "📃 <b>Connected Chats</b>\n\n"
            "No channels or groups found yet.\n\n"
            "➡️ Use the buttons in Connect to add me to one first.",
            reply_markup=back_to_menu_kb(),
        )
        await call.answer()
        return

    await call.message.edit_text(
        "📃 <b>Connected Chats</b>\n\nHere are the channels/groups I'm added to:",
        reply_markup=connect_list_kb(chats),
    )
    await call.answer()


@router.callback_query(F.data.startswith("connect:info:"))
async def chat_info(call: CallbackQuery):
    chat_id = int(call.data.split(":")[2])
    chat = await db.get_chat(chat_id)
    if not chat:
        await call.answer("Not found.", show_alert=True)
        return

    lines = [f"{chat['title']}", f"Type: {chat['type']}", f"ID: {chat['chat_id']}"]
    if chat.get("username"):
        lines.append(f"Username: @{chat['username']}")

    await call.answer("\n".join(lines), show_alert=True)
