from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

import database as db

router = Router(name="score")


@router.message(Command("score"))
async def score_cmd(message: Message):
    # Priority 1: an active giveaway created by this user
    giveaways = await db.get_active_giveaways_by_creator(message.from_user.id)
    gid = None
    channel_title = None

    if giveaways:
        gid = str(giveaways[0]["_id"])
        channel_title = giveaways[0]["channel_title"]
    else:
        # Priority 2: a giveaway the user is participating in
        participant = await db.participants_col.find_one({"user_id": message.from_user.id})
        if participant:
            gid = participant["giveaway_id"]
            gw = await db.get_giveaway(gid)
            channel_title = gw["channel_title"] if gw else None

    if not gid:
        await message.answer("No giveaway found for you yet.")
        return

    leaderboard = await db.get_leaderboard(gid, 10)
    if not leaderboard:
        await message.answer("No participants yet.")
        return

    lines = [f"🏆 <b>Top 10 Scoreboard</b>"]
    if channel_title:
        lines.append(f"📢 {channel_title}")
    lines.append("")

    medals = ["🥇", "🥈", "🥉"]
    for i, p in enumerate(leaderboard):
        medal = medals[i] if i < 3 else f"{i + 1}."
        uname = f"@{p['username']}" if p.get("username") else p["first_name"]
        lines.append(f"{medal} {uname} (<code>{p['user_id']}</code>) — <b>{p['votes']}</b> votes")

    await message.answer("\n".join(lines))
