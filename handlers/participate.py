from aiogram import Router, F
from aiogram.types import CallbackQuery, Message

import database as db
from keyboards import participate_confirm_kb, profile_post_kb

router = Router(name="participate")


def build_profile_text(user_id, first_name, username, votes, logs=None):
    lines = [
        "🙋 <b>Giveaway Participant</b>",
        "",
        f"👤 Name: {first_name}",
        f"🆔 ID: <code>{user_id}</code>",
    ]
    if username:
        lines.append(f"🔗 Username: @{username}")
    lines.append(f"🗳 Votes: <b>{votes}</b>")
    if logs:
        lines.append("")
        lines.append("📜 <b>Log:</b>")
        for l in logs[-5:]:
            lines.append(f"• {l['text']}")
    return "\n".join(lines)


async def refresh_profile_message(bot, gw, participant):
    bot_me = await bot.get_me()
    text = build_profile_text(
        participant["user_id"],
        participant["first_name"],
        participant.get("username"),
        participant["votes"],
        participant.get("logs"),
    )
    try:
        await bot.edit_message_text(
            text,
            chat_id=gw["channel_id"],
            message_id=participant["profile_message_id"],
            reply_markup=profile_post_kb(
                str(gw["_id"]), participant["user_id"], bot_me.username, participant["votes"]
            ),
        )
    except Exception:
        pass


async def handle_join_payload(message: Message, gid: str):
    gw = await db.get_giveaway(gid)
    if not gw:
        await message.answer("❌ This giveaway doesn't exist anymore.")
        return
    if gw["status"] != "active":
        await message.answer("⛔ This giveaway has already ended.")
        return

    existing = await db.get_participant(gid, message.from_user.id)
    if existing:
        await message.answer(
            f"✅ You're already participating in this giveaway with <b>{existing['votes']}</b> votes!"
        )
        return

    await message.answer(
        f"🎉 You've been invited to join the vote giveaway in "
        f"<b>{gw['channel_title']}</b>!\n\nDo you want to participate?",
        reply_markup=participate_confirm_kb(gid),
    )


@router.callback_query(F.data.startswith("confirm:"))
async def confirm_participate(call: CallbackQuery):
    _, gid, decision = call.data.split(":")

    if decision == "no":
        await call.message.edit_text("👍 No problem, maybe next time!")
        await call.answer()
        return

    gw = await db.get_giveaway(gid)
    if not gw or gw["status"] != "active":
        await call.message.edit_text("⛔ This giveaway is no longer active.")
        await call.answer()
        return

    existing = await db.get_participant(gid, call.from_user.id)
    if existing:
        await call.message.edit_text("✅ You're already participating in this giveaway!")
        await call.answer()
        return

    # must have joined the channel to participate
    try:
        member = await call.bot.get_chat_member(gw["channel_id"], call.from_user.id)
        is_member = member.status in ("member", "administrator", "creator")
    except Exception:
        is_member = False

    if not is_member:
        await call.answer(
            "⚠️ Please join the channel first, then tap Participate again.",
            show_alert=True,
        )
        return

    user = call.from_user
    profile_text = build_profile_text(user.id, user.first_name or "User", user.username, votes=0)
    bot_me = await call.bot.get_me()
    sent = await call.bot.send_message(
        gw["channel_id"],
        profile_text,
        reply_markup=profile_post_kb(gid, user.id, bot_me.username, votes=0),
    )
    await db.add_participant(gid, user.id, user.first_name or "User", user.username, sent.message_id)

    await call.message.edit_text(
        "🎊 You're in! Your profile has been posted in the channel.\n"
        "Ask your friends to vote for you! 🗳"
    )
    await call.answer()


@router.callback_query(F.data.startswith("vote:"))
async def vote_callback(call: CallbackQuery):
    _, gid, participant_id_str = call.data.split(":")
    participant_id = int(participant_id_str)

    gw = await db.get_giveaway(gid)
    if not gw or gw["status"] != "active":
        await call.answer("⛔ This giveaway has ended.", show_alert=True)
        return

    if call.from_user.id == participant_id:
        await call.answer("🚫 You can't vote for yourself!", show_alert=True)
        return

    try:
        member = await call.bot.get_chat_member(gw["channel_id"], call.from_user.id)
        is_member = member.status in ("member", "administrator", "creator")
    except Exception:
        is_member = False

    if not is_member:
        await call.answer("⚠️ Please join the channel first to vote!", show_alert=True)
        return

    already = await db.has_voted(gid, call.from_user.id, participant_id, gw.get("multi_vote", False))
    if already:
        await call.answer("✅ You have already voted!", show_alert=True)
        return

    participant = await db.get_participant(gid, participant_id)
    if not participant:
        await call.answer("Participant not found.", show_alert=True)
        return

    await db.record_vote(gid, call.from_user.id, participant_id)
    participant = await db.update_votes(gid, participant_id, +1)

    await refresh_profile_message(call.bot, gw, participant)
    await call.answer("🗳 Vote counted! Thank you.")
