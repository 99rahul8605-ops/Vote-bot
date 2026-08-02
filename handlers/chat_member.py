from aiogram import Router
from aiogram.types import ChatMemberUpdated

import database as db

router = Router(name="chat_member")


@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated):
    chat = event.chat
    new_status = event.new_chat_member.status

    if chat.type not in ("channel", "group", "supergroup"):
        return

    if new_status in ("administrator", "member"):
        type_ = "channel" if chat.type == "channel" else "group"
        await db.upsert_chat(chat.id, chat.title or str(chat.id), type_, chat.username, event.from_user.id)
    elif new_status in ("left", "kicked"):
        await db.remove_chat(chat.id)
