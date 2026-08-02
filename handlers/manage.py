from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import database as db
from states import ManageVote
from keyboards import manage_menu_kb, manage_giveaway_list_kb, manage_giveaway_actions_kb, back_to_menu_kb
from handlers.participate import refresh_profile_message

router = Router(name="manage")


@router.callback_query(F.data == "menu:manage")
async def manage_menu(call: CallbackQuery):
    await call.message.edit_text("⚙️ <b>Manage</b>\n\nChoose an option:", reply_markup=manage_menu_kb())
    await call.answer()


@router.callback_query(F.data == "manage:list")
async def manage_list(call: CallbackQuery):
    giveaways = await db.get_all_giveaways_by_creator(call.from_user.id)
    if not giveaways:
        await call.message.edit_text("You haven't created any giveaways yet.", reply_markup=back_to_menu_kb())
        await call.answer()
        return

    await call.message.edit_text(
        "📃 <b>Your Giveaways</b>\n\nSelect one to manage:",
        reply_markup=manage_giveaway_list_kb(giveaways),
    )
    await call.answer()


async def render_giveaway_panel(call: CallbackQuery, gid: str):
    gw = await db.get_giveaway(gid)
    if not gw:
        await call.answer("Not found.", show_alert=True)
        return
    count = await db.get_participant_count(gid)
    text = (
        f"🎉 <b>{gw['channel_title']}</b>\n"
        f"Status: {'🟢 Active' if gw['status'] == 'active' else '🔴 Ended'}\n"
        f"Participants: {count}\n"
        f"Multi-Vote: {'ON' if gw.get('multi_vote') else 'OFF'}"
    )
    await call.message.edit_text(
        text,
        reply_markup=manage_giveaway_actions_kb(gid, gw.get("multi_vote", False), gw["status"] == "active"),
    )


@router.callback_query(F.data.startswith("manage:g:"))
async def giveaway_actions(call: CallbackQuery):
    gid = call.data.split(":")[2]
    await render_giveaway_panel(call, gid)
    await call.answer()


@router.callback_query(F.data.startswith("manage:multitoggle:"))
async def multi_toggle(call: CallbackQuery):
    gid = call.data.split(":")[2]
    new_val = await db.toggle_multi_vote(gid)
    await render_giveaway_panel(call, gid)
    await call.answer(f"Multi-vote turned {'ON' if new_val else 'OFF'}")


@router.callback_query(F.data.startswith("manage:end:"))
async def end_giveaway_cb(call: CallbackQuery):
    gid = call.data.split(":")[2]
    gw = await db.get_giveaway(gid)
    if not gw or gw["status"] != "active":
        await call.answer("Already ended.", show_alert=True)
        return

    leaderboard = await db.get_leaderboard(gid, 10)
    await db.end_giveaway(gid)

    lines = ["🏁 <b>Giveaway Ended!</b>", "", f"🏆 <b>Top {len(leaderboard)} Winners</b>", ""]
    medals = ["🥇", "🥈", "🥉"]
    for i, p in enumerate(leaderboard):
        medal = medals[i] if i < 3 else f"{i + 1}."
        uname = f"@{p['username']}" if p.get("username") else p["first_name"]
        lines.append(f"{medal} {uname} — <b>{p['votes']}</b> votes")
    lines.append("")
    lines.append("🎉 Congratulations to all winners! Thank you for participating.")
    text = "\n".join(lines)

    try:
        await call.bot.send_message(gw["channel_id"], text)
        if gw.get("announce_message_id"):
            await call.bot.unpin_chat_message(gw["channel_id"], gw["announce_message_id"])
    except Exception:
        pass

    await call.message.edit_text(
        "✅ Giveaway ended. Scoreboard posted in the channel.", reply_markup=back_to_menu_kb()
    )
    await call.answer()


@router.callback_query(F.data.startswith("manage:addvote:"))
async def ask_addvote(call: CallbackQuery, state: FSMContext):
    gid = call.data.split(":")[2]
    await state.update_data(gid=gid, action="add")
    await state.set_state(ManageVote.waiting_participant_id)
    await call.message.edit_text(
        "Send the participant's <b>user ID</b> or <b>@username</b> to add a vote.\nSend /cancel to abort."
    )
    await call.answer()


@router.callback_query(F.data.startswith("manage:removevote:"))
async def ask_removevote(call: CallbackQuery, state: FSMContext):
    gid = call.data.split(":")[2]
    await state.update_data(gid=gid, action="remove")
    await state.set_state(ManageVote.waiting_participant_id)
    await call.message.edit_text(
        "Send the participant's <b>user ID</b> or <b>@username</b> to remove a vote.\nSend /cancel to abort."
    )
    await call.answer()


@router.message(ManageVote.waiting_participant_id, F.text == "/cancel")
@router.message(ManageVote.waiting_amount, F.text == "/cancel")
async def cancel_manage(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Cancelled.")


@router.message(ManageVote.waiting_participant_id)
async def receive_participant(message: Message, state: FSMContext):
    data = await state.get_data()
    gid = data["gid"]
    raw = message.text.strip().lstrip("@")

    participant = None
    if raw.isdigit():
        participant = await db.get_participant(gid, int(raw))
    else:
        cursor = db.participants_col.find(
            {"giveaway_id": gid, "username": {"$regex": f"^{raw}$", "$options": "i"}}
        )
        results = await cursor.to_list(length=1)
        participant = results[0] if results else None

    if not participant:
        await message.answer("❌ Participant not found in this giveaway. Try again or send /cancel.")
        return

    await state.update_data(participant_id=participant["user_id"])
    await state.set_state(ManageVote.waiting_amount)
    await message.answer("How many votes? Send a number (e.g. 1, 5).")


@router.message(ManageVote.waiting_amount)
async def receive_amount(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("Please send a valid positive number.")
        return

    amount = int(message.text.strip())
    data = await state.get_data()
    gid = data["gid"]
    action = data["action"]
    participant_id = data["participant_id"]

    delta = amount if action == "add" else -amount
    log_line = f"{'➕' if action == 'add' else '➖'} {amount} vote(s) {'added' if action == 'add' else 'removed'} by admin"

    gw = await db.get_giveaway(gid)
    participant = await db.update_votes(gid, participant_id, delta, log_line)
    await refresh_profile_message(message.bot, gw, participant)

    await message.answer(f"✅ Done. {participant['first_name']} now has <b>{participant['votes']}</b> votes.")
    await state.clear()
