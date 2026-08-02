from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import database as db
from states import GiveawayCreate
from keyboards import back_to_menu_kb, announce_kb

router = Router(name="giveaway")


@router.callback_query(F.data == "menu:create_giveaway")
async def ask_channel(call: CallbackQuery, state: FSMContext):
    await state.set_state(GiveawayCreate.waiting_channel)
    await call.message.edit_text(
        "🎉 <b>Create Giveaway</b>\n\n"
        "Send me the channel's <b>username</b> (e.g. <code>@mychannel</code>) or its numeric <b>ID</b> "
        "where you want to start the vote giveaway.\n\n"
        "⚠️ Make sure I'm added as <b>admin</b> there with post &amp; pin permissions.\n\n"
        "Send /cancel to abort.",
        reply_markup=back_to_menu_kb(),
    )
    await call.answer()


@router.message(GiveawayCreate.waiting_channel, F.text == "/cancel")
async def cancel_create(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Cancelled.")


@router.message(GiveawayCreate.waiting_channel)
async def receive_channel(message: Message, state: FSMContext):
    raw = message.text.strip()
    identifier = int(raw) if raw.lstrip("-").isdigit() else raw

    try:
        chat = await message.bot.get_chat(identifier)
    except Exception:
        await message.answer(
            "❌ I couldn't find that channel, or I'm not added there.\n"
            "Please check the username/ID and try again, or send /cancel."
        )
        return

    if chat.type not in ("channel", "group", "supergroup"):
        await message.answer("❌ That doesn't look like a channel or group. Try again.")
        return

    try:
        member = await message.bot.get_chat_member(chat.id, message.bot.id)
    except Exception:
        await message.answer("❌ I couldn't verify my membership there. Please add me and try again.")
        return

    if member.status not in ("administrator", "creator"):
        await message.answer(
            "❌ I'm not an admin there yet. Please add me as admin (with post &amp; pin rights) and try again."
        )
        return

    gid = await db.create_giveaway(chat.id, chat.title or str(chat.id), chat.username, message.from_user.id)
    bot_me = await message.bot.get_me()

    announce_text = (
        "🎉 <b>Vote Giveaway Started!</b>\n\n"
        "Tap the button below to join and get your votes started.\n"
        "Good luck! 🍀"
    )
    sent = await message.bot.send_message(chat.id, announce_text, reply_markup=announce_kb(gid, bot_me.username))
    try:
        await message.bot.pin_chat_message(chat.id, sent.message_id, disable_notification=True)
    except Exception:
        pass
    await db.set_announce_message(gid, sent.message_id)

    link = f"https://t.me/{bot_me.username}?start=join_{gid}"

    # notify creator (admin)
    await message.answer(
        f"✅ Giveaway started in <b>{chat.title}</b>!\n\n"
        f"🔗 Participate link:\n{link}\n\n"
        f"It has been posted and pinned in the channel.",
        reply_markup=back_to_menu_kb(),
    )
    await state.clear()
