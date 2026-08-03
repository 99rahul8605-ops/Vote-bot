"""
Vote Bot — single-file Telegram vote-giveaway bot.
aiogram v3 + MongoDB (motor)

Run:
    python bot.py

Requires a .env file with:
    BOT_TOKEN=...
    MONGO_URI=mongodb://localhost:27017
    DB_NAME=vote_bot
    OWNER_ID=123456789
"""

import asyncio
import logging
import os
import time
from datetime import datetime

from bson import ObjectId
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import DuplicateKeyError

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart, Filter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ============================================================
# CONFIG
# ============================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "vote_bot")
OWNER_ID = int(os.getenv("OWNER_ID", "0") or "0")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0") or "0")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set. Please add it to your .env file.")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("vote_bot")

# ============================================================
# DATABASE
# ============================================================

mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client[DB_NAME]

chats_col = db["chats"]
giveaways_col = db["giveaways"]
participants_col = db["participants"]
votes_col = db["votes"]
users_col = db["users"]


# ---------- USERS (for broadcast / stats) ----------

async def upsert_user(user_id: int, first_name: str, username):
    await users_col.update_one(
        {"user_id": user_id},
        {
            "$set": {"first_name": first_name, "username": username, "last_seen": datetime.utcnow()},
            "$setOnInsert": {"first_seen": datetime.utcnow()},
        },
        upsert=True,
    )


async def get_all_user_ids():
    cursor = users_col.find({}, {"user_id": 1})
    docs = await cursor.to_list(length=None)
    return [d["user_id"] for d in docs]


async def get_user_count():
    return await users_col.count_documents({})


# ---------- CHATS (Connect) ----------

async def upsert_chat(chat_id: int, title: str, type_: str, username, added_by: int):
    await chats_col.update_one(
        {"chat_id": chat_id},
        {
            "$set": {
                "title": title,
                "type": type_,
                "username": username,
                "added_by": added_by,
                "updated_at": datetime.utcnow(),
            },
            "$setOnInsert": {"added_at": datetime.utcnow()},
        },
        upsert=True,
    )


async def remove_chat(chat_id: int):
    await chats_col.delete_one({"chat_id": chat_id})


async def get_chats_by_owner(user_id: int):
    cursor = chats_col.find({"added_by": user_id}).sort("added_at", -1)
    return await cursor.to_list(length=100)


async def get_chat(chat_id: int):
    return await chats_col.find_one({"chat_id": chat_id})


async def get_chat_count():
    return await chats_col.count_documents({})


# ---------- GIVEAWAYS ----------

async def create_giveaway(channel_id: int, channel_title: str, channel_username, creator_id: int):
    doc = {
        "channel_id": channel_id,
        "channel_title": channel_title,
        "channel_username": channel_username,
        "creator_id": creator_id,
        "status": "active",
        "multi_vote": False,
        "created_at": datetime.utcnow(),
        "announce_message_id": None,
    }
    result = await giveaways_col.insert_one(doc)
    return str(result.inserted_id)


async def get_giveaway(giveaway_id: str):
    try:
        return await giveaways_col.find_one({"_id": ObjectId(giveaway_id)})
    except Exception:
        return None


async def set_announce_message(giveaway_id: str, message_id: int):
    await giveaways_col.update_one(
        {"_id": ObjectId(giveaway_id)}, {"$set": {"announce_message_id": message_id}}
    )


async def set_results_message(giveaway_id: str, message_id: int):
    await giveaways_col.update_one(
        {"_id": ObjectId(giveaway_id)}, {"$set": {"results_message_id": message_id}}
    )


async def set_invite_link(giveaway_id: str, invite_link: str):
    await giveaways_col.update_one(
        {"_id": ObjectId(giveaway_id)}, {"$set": {"invite_link": invite_link}}
    )


async def get_active_giveaways_by_creator(user_id: int):
    cursor = giveaways_col.find({"creator_id": user_id, "status": "active"}).sort("created_at", -1)
    return await cursor.to_list(length=100)


async def get_all_giveaways_by_creator(user_id: int):
    cursor = giveaways_col.find({"creator_id": user_id}).sort("created_at", -1)
    return await cursor.to_list(length=100)


async def end_giveaway(giveaway_id: str):
    await giveaways_col.update_one(
        {"_id": ObjectId(giveaway_id)},
        {"$set": {"status": "ended", "ended_at": datetime.utcnow()}},
    )


async def toggle_multi_vote(giveaway_id: str):
    gw = await get_giveaway(giveaway_id)
    if not gw:
        return None
    new_val = not gw.get("multi_vote", False)
    await giveaways_col.update_one({"_id": ObjectId(giveaway_id)}, {"$set": {"multi_vote": new_val}})
    return new_val


async def get_giveaway_counts():
    """Returns (total, live/active, completed/ended)."""
    total = await giveaways_col.count_documents({})
    active = await giveaways_col.count_documents({"status": "active"})
    return total, active, total - active


# ---------- PARTICIPANTS ----------

async def add_participant(giveaway_id: str, user_id: int, first_name: str, username, profile_message_id: int):
    doc = {
        "giveaway_id": giveaway_id,
        "user_id": user_id,
        "first_name": first_name,
        "username": username,
        "votes": 0,
        "logs": [],
        "profile_message_id": profile_message_id,
        "joined_at": datetime.utcnow(),
    }
    await participants_col.insert_one(doc)
    return doc


async def get_participant(giveaway_id: str, user_id: int):
    return await participants_col.find_one({"giveaway_id": giveaway_id, "user_id": user_id})


async def get_participant_count(giveaway_id: str):
    return await participants_col.count_documents({"giveaway_id": giveaway_id})


async def update_votes(giveaway_id: str, user_id: int, delta: int, log_line: str = None):
    update = {"$inc": {"votes": delta}}
    if log_line:
        update["$push"] = {"logs": {"text": log_line, "at": datetime.utcnow()}}
    await participants_col.update_one({"giveaway_id": giveaway_id, "user_id": user_id}, update)
    return await get_participant(giveaway_id, user_id)


async def get_leaderboard(giveaway_id: str, limit: int = 10):
    cursor = participants_col.find({"giveaway_id": giveaway_id}).sort("votes", -1).limit(limit)
    return await cursor.to_list(length=limit)


async def get_all_participants(giveaway_id: str):
    cursor = participants_col.find({"giveaway_id": giveaway_id})
    return await cursor.to_list(length=None)


async def get_participant_total():
    return await participants_col.count_documents({})


# ---------- VOTES (double-vote prevention) ----------

async def has_voted(giveaway_id: str, voter_id: int, participant_id: int, multi_vote: bool):
    """
    multi_vote == False -> a voter can cast only ONE vote total in this giveaway.
    multi_vote == True  -> a voter can vote for MULTIPLE different participants,
                            but still not twice for the same participant.
    """
    if multi_vote:
        existing = await votes_col.find_one(
            {"giveaway_id": giveaway_id, "voter_id": voter_id, "participant_id": participant_id}
        )
    else:
        existing = await votes_col.find_one({"giveaway_id": giveaway_id, "voter_id": voter_id})
    return existing is not None


async def record_vote(giveaway_id: str, voter_id: int, participant_id: int) -> bool:
    """Atomically records a vote. Returns False if this exact (giveaway, voter,
    participant) combo already exists — guarded by a unique DB index, so this
    catches double-taps / replayed requests that slip past the earlier check."""
    try:
        await votes_col.insert_one(
            {
                "giveaway_id": giveaway_id,
                "voter_id": voter_id,
                "participant_id": participant_id,
                "created_at": datetime.utcnow(),
            }
        )
        return True
    except DuplicateKeyError:
        return False


async def get_vote_total():
    return await votes_col.count_documents({})


# ============================================================
# FSM STATES
# ============================================================

class GiveawayCreate(StatesGroup):
    waiting_channel = State()


class ManageVote(StatesGroup):
    waiting_participant_id = State()
    waiting_amount = State()


# ============================================================
# FILTERS
# ============================================================

class IsOwner(Filter):
    async def __call__(self, message: Message) -> bool:
        return OWNER_ID != 0 and message.from_user.id == OWNER_ID


# ============================================================
# KEYBOARDS
# ============================================================

def main_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🔗 Connect", callback_data="menu:connect", style="primary")
    kb.button(text="🎉 Create Giveaway", callback_data="menu:create_giveaway", style="success")
    kb.button(text="⚙️ Manage", callback_data="menu:manage", style="primary")
    kb.adjust(1)
    return kb.as_markup()


def back_to_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Back", callback_data="menu:main")
    return kb.as_markup()


def connect_menu_kb(bot_username: str):
    kb = InlineKeyboardBuilder()
    admin_rights = "post_messages+edit_messages+delete_messages+pin_messages+invite_users"
    kb.button(
        text="📢 Add to Channel",
        url=f"https://t.me/{bot_username}?startchannel&admin={admin_rights}",
        style="primary",
    )
    kb.button(
        text="👥 Add to Group",
        url=f"https://t.me/{bot_username}?startgroup&admin=delete_messages+pin_messages+promote_members",
        style="primary",
    )
    kb.button(text="📃 View Connected Chats", callback_data="connect:list")
    kb.button(text="⬅️ Back", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def connect_list_kb(chats):
    kb = InlineKeyboardBuilder()
    for c in chats:
        label = c.get("title") or str(c["chat_id"])
        icon = "📢" if c["type"] == "channel" else "👥"
        kb.button(text=f"{icon} {label}", callback_data=f"connect:info:{c['chat_id']}")
    kb.button(text="⬅️ Back", callback_data="menu:connect")
    kb.adjust(1)
    return kb.as_markup()


def manage_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="📃 My Giveaways", callback_data="manage:list", style="primary")
    kb.button(text="⬅️ Back", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def manage_giveaway_list_kb(giveaways):
    kb = InlineKeyboardBuilder()
    for g in giveaways:
        gid = str(g["_id"])
        status_icon = "🟢" if g["status"] == "active" else "🔴"
        kb.button(text=f"{status_icon} {g.get('channel_title', gid)}", callback_data=f"manage:g:{gid}")
    kb.button(text="⬅️ Back", callback_data="menu:manage")
    kb.adjust(1)
    return kb.as_markup()


def manage_giveaway_actions_kb(gid: str, multi_vote: bool, active: bool):
    kb = InlineKeyboardBuilder()
    if active:
        kb.button(text="➕ Add Vote", callback_data=f"manage:addvote:{gid}", style="success")
        kb.button(text="➖ Remove Vote", callback_data=f"manage:removevote:{gid}", style="danger")
        kb.button(
            text=f"🔁 Multi-Vote: {'ON' if multi_vote else 'OFF'}",
            callback_data=f"manage:multitoggle:{gid}",
            style="primary",
        )
        kb.button(text="🏁 End Giveaway", callback_data=f"manage:end:{gid}", style="danger")
    kb.button(text="⬅️ Back", callback_data="manage:list")
    kb.adjust(1)
    return kb.as_markup()


def participate_confirm_kb(gid: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Yes, Participate", callback_data=f"confirm:{gid}:yes", style="success")
    kb.button(text="❌ No", callback_data=f"confirm:{gid}:no", style="danger")
    kb.adjust(2)
    return kb.as_markup()


def profile_post_kb(gid: str, user_id: int, bot_username: str, votes: int):
    kb = InlineKeyboardBuilder()
    kb.button(text=f"🗳 Vote ({votes})", callback_data=f"vote:{gid}:{user_id}", style="primary")
    kb.button(text="🎉 Participate", url=f"https://t.me/{bot_username}?start=join_{gid}", style="success")
    kb.adjust(1)
    return kb.as_markup()


def announce_kb(gid: str, bot_username: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="🎉 Participate", url=f"https://t.me/{bot_username}?start=join_{gid}", style="success")
    kb.adjust(1)
    return kb.as_markup()


def scoreboard_kb(gid: str, my_post_link: str = None):
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Refresh", callback_data=f"score:refresh:{gid}", style="primary")
    if my_post_link:
        kb.button(text="📌 See My Post", url=my_post_link, style="success")
    kb.adjust(1)
    return kb.as_markup()


def build_message_link(channel_id: int, channel_username, message_id: int) -> str:
    """Direct link to a specific message in a channel (works for public + private)."""
    if channel_username:
        return f"https://t.me/{channel_username}/{message_id}"
    cid = str(channel_id)
    if cid.startswith("-100"):
        cid = cid[4:]
    else:
        cid = cid.lstrip("-")
    return f"https://t.me/c/{cid}/{message_id}"


# ============================================================
# BOT / DISPATCHER
# ============================================================

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

START_TIME = time.time()


async def log_event(text: str):
    """Posts an audit entry to the configured log channel. Silently does
    nothing if LOG_CHANNEL_ID isn't set or the bot lacks access there —
    logging failures should never break the bot's actual functionality."""
    if not LOG_CHANNEL_ID:
        return
    try:
        await bot.send_message(LOG_CHANNEL_ID, text, disable_web_page_preview=True)
    except Exception:
        pass


WELCOME_TEXT = (
    "👋 <b>Welcome to Vote Bot!</b>\n\n"
    "I help you run <b>vote-based giveaways</b> in your channels and groups.\n\n"
    "🔗 <b>Connect</b> — link your channels/groups\n"
    "🎉 <b>Create Giveaway</b> — start a new vote giveaway\n"
    "⚙️ <b>Manage</b> — control votes and end giveaways\n\n"
    "Choose an option below to get started 👇"
)


# ---------- profile text / message helpers (shared) ----------

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


async def refresh_profile_message(gw, participant):
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
    gw = await get_giveaway(gid)
    if not gw:
        await message.answer("❌ This giveaway doesn't exist anymore.")
        return
    if gw["status"] != "active":
        await message.answer("⛔ This giveaway has already ended.")
        return

    existing = await get_participant(gid, message.from_user.id)
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


# ============================================================
# HANDLERS — /start + deep link
# ============================================================

@dp.message(CommandStart(deep_link=True))
async def start_deep_link(message: Message, command: CommandObject):
    await upsert_user(message.from_user.id, message.from_user.first_name or "User", message.from_user.username)
    payload = command.args or ""
    if payload.startswith("join_"):
        gid = payload.split("join_", 1)[1]
        await handle_join_payload(message, gid)
        return
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_kb())


@dp.message(CommandStart())
async def start_plain(message: Message):
    await upsert_user(message.from_user.id, message.from_user.first_name or "User", message.from_user.username)
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_kb())


@dp.callback_query(F.data == "menu:main")
async def back_to_main(call: CallbackQuery):
    await call.message.edit_text(WELCOME_TEXT, reply_markup=main_menu_kb())
    await call.answer()


# ============================================================
# HANDLERS — track chats bot is added/removed from
# ============================================================

@dp.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated):
    chat = event.chat
    new_status = event.new_chat_member.status

    if chat.type not in ("channel", "group", "supergroup"):
        return

    if new_status in ("administrator", "member"):
        type_ = "channel" if chat.type == "channel" else "group"
        await upsert_chat(chat.id, chat.title or str(chat.id), type_, chat.username, event.from_user.id)
    elif new_status in ("left", "kicked"):
        await remove_chat(chat.id)


# ============================================================
# HANDLERS — Connect
# ============================================================

@dp.callback_query(F.data == "menu:connect")
async def show_connect(call: CallbackQuery):
    bot_me = await bot.get_me()
    await call.message.edit_text(
        "🔗 <b>Connect</b>\n\n"
        "Tap a button below to add me to your channel or group.\n"
        "Telegram will open a picker so you can choose which chat to add me to, "
        "with the right admin permissions pre-selected.",
        reply_markup=connect_menu_kb(bot_me.username),
    )
    await call.answer()


@dp.callback_query(F.data == "connect:list")
async def show_connected_list(call: CallbackQuery):
    chats = await get_chats_by_owner(call.from_user.id)
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


@dp.callback_query(F.data.startswith("connect:info:"))
async def chat_info(call: CallbackQuery):
    chat_id = int(call.data.split(":")[2])
    chat = await get_chat(chat_id)
    if not chat:
        await call.answer("Not found.", show_alert=True)
        return

    lines = [f"{chat['title']}", f"Type: {chat['type']}", f"ID: {chat['chat_id']}"]
    if chat.get("username"):
        lines.append(f"Username: @{chat['username']}")

    await call.answer("\n".join(lines), show_alert=True)


# ============================================================
# HANDLERS — Create Giveaway
# ============================================================

@dp.callback_query(F.data == "menu:create_giveaway")
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


@dp.message(GiveawayCreate.waiting_channel, F.text == "/cancel")
async def cancel_create(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Cancelled.")


@dp.message(GiveawayCreate.waiting_channel)
async def receive_channel(message: Message, state: FSMContext):
    raw = message.text.strip()
    identifier = int(raw) if raw.lstrip("-").isdigit() else raw

    try:
        chat = await bot.get_chat(identifier)
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
        member = await bot.get_chat_member(chat.id, bot.id)
    except Exception:
        await message.answer("❌ I couldn't verify my membership there. Please add me and try again.")
        return

    if member.status not in ("administrator", "creator"):
        await message.answer(
            "❌ I'm not an admin there yet. Please add me as admin (with post &amp; pin rights) and try again."
        )
        return

    gid = await create_giveaway(chat.id, chat.title or str(chat.id), chat.username, message.from_user.id)
    bot_me = await bot.get_me()

    # Private channels have no public @username — auto-generate a real invite link
    # so participants (and DM messages) always have a working way to open the channel.
    if not chat.username:
        try:
            invite = await bot.create_chat_invite_link(chat.id, name="Vote Bot Giveaway")
            await set_invite_link(gid, invite.invite_link)
        except Exception:
            pass  # bot may lack "invite users" rights — falls back to post-link elsewhere

    announce_text = (
        "🎉 <b>Vote Giveaway Started!</b>\n\n"
        "Tap the button below to join and get your votes started.\n"
        "Good luck! 🍀"
    )
    sent = await bot.send_message(chat.id, announce_text, reply_markup=announce_kb(gid, bot_me.username))
    try:
        await bot.pin_chat_message(chat.id, sent.message_id, disable_notification=True)
    except Exception:
        pass
    await set_announce_message(gid, sent.message_id)

    await log_event(
        "🎉 <b>Giveaway Created</b>\n"
        f"Channel: {chat.title} (<code>{chat.id}</code>)\n"
        f"Creator: {message.from_user.first_name} [<code>{message.from_user.id}</code>]\n"
        f"Giveaway ID: <code>{gid}</code>"
    )

    link = f"https://t.me/{bot_me.username}?start=join_{gid}"

    await message.answer(
        f"✅ Giveaway started in <b>{chat.title}</b>!\n\n"
        f"🔗 Participate link:\n{link}\n\n"
        f"It has been posted and pinned in the channel.",
        reply_markup=back_to_menu_kb(),
    )
    await state.clear()


# ============================================================
# HANDLERS — Participate (join confirm + vote button)
# ============================================================

@dp.callback_query(F.data.startswith("confirm:"))
async def confirm_participate(call: CallbackQuery):
    _, gid, decision = call.data.split(":")

    if decision == "no":
        await call.message.edit_text("👍 No problem, maybe next time!")
        await call.answer()
        return

    gw = await get_giveaway(gid)
    if not gw or gw["status"] != "active":
        await call.message.edit_text("⛔ This giveaway is no longer active.")
        await call.answer()
        return

    existing = await get_participant(gid, call.from_user.id)
    if existing:
        await call.message.edit_text("✅ You're already participating in this giveaway!")
        await call.answer()
        return

    try:
        member = await bot.get_chat_member(gw["channel_id"], call.from_user.id)
        is_member = member.status in ("member", "administrator", "creator")
    except Exception:
        is_member = False

    if not is_member:
        await call.answer("⚠️ Please join the channel first, then tap Participate again.", show_alert=True)
        return

    user = call.from_user
    profile_text = build_profile_text(user.id, user.first_name or "User", user.username, votes=0)
    bot_me = await bot.get_me()
    sent = await bot.send_message(
        gw["channel_id"], profile_text, reply_markup=profile_post_kb(gid, user.id, bot_me.username, votes=0)
    )
    await add_participant(gid, user.id, user.first_name or "User", user.username, sent.message_id)

    await log_event(
        "🙋 <b>New Participant</b>\n"
        f"Giveaway: {gw['channel_title']}\n"
        f"User: {user.first_name or 'User'} (@{user.username or '—'}) [<code>{user.id}</code>]"
    )

    post_link = build_message_link(gw["channel_id"], gw.get("channel_username"), sent.message_id)
    if gw.get("channel_username"):
        channel_link = f"https://t.me/{gw['channel_username']}"
    elif gw.get("invite_link"):
        channel_link = gw["invite_link"]
    else:
        channel_link = post_link  # last-resort fallback if no invite link could be generated

    success_kb = InlineKeyboardBuilder()
    success_kb.button(text="📢 Open Channel", url=channel_link, style="primary")
    success_kb.button(text="📌 My Post", url=post_link, style="success")
    success_kb.adjust(1)

    await call.message.edit_text(
        "🎊 You're in! Your profile has been posted in the channel.\n"
        "Ask your friends to vote for you! 🗳\n\n"
        f"📢 Channel: {channel_link}\n"
        f"📌 Your post: {post_link}\n\n"
        "📊 Check your live score anytime by sending /score to me.",
        reply_markup=success_kb.as_markup(),
        disable_web_page_preview=True,
    )
    await call.answer()


@dp.callback_query(F.data.startswith("vote:"))
async def vote_callback(call: CallbackQuery):
    _, gid, participant_id_str = call.data.split(":")
    participant_id = int(participant_id_str)

    gw = await get_giveaway(gid)
    if not gw or gw["status"] != "active":
        await call.answer("⛔ This giveaway has ended.", show_alert=True)
        return

    try:
        member = await bot.get_chat_member(gw["channel_id"], call.from_user.id)
        is_member = member.status in ("member", "administrator", "creator")
    except Exception:
        is_member = False

    if not is_member:
        await call.answer("⚠️ Please join the channel first to vote!", show_alert=True)
        return

    already = await has_voted(gid, call.from_user.id, participant_id, gw.get("multi_vote", False))
    if already:
        await call.answer("✅ You have already voted!", show_alert=True)
        return

    participant = await get_participant(gid, participant_id)
    if not participant:
        await call.answer("Participant not found.", show_alert=True)
        return

    success = await record_vote(gid, call.from_user.id, participant_id)
    if not success:
        # DB-level unique index caught a race/replay — vote was already recorded
        await call.answer("✅ You have already voted!", show_alert=True)
        return

    participant = await update_votes(gid, participant_id, +1)

    voter = call.from_user
    await log_event(
        "🗳 <b>Vote Cast</b>\n"
        f"Giveaway: {gw['channel_title']}\n"
        f"Voter: {voter.first_name} (@{voter.username or '—'}) [<code>{voter.id}</code>]\n"
        f"Voted for: {participant['first_name']} (@{participant.get('username') or '—'}) [<code>{participant['user_id']}</code>]\n"
        f"New total: <b>{participant['votes']}</b>"
    )

    await refresh_profile_message(gw, participant)
    await call.answer("🗳 Vote counted! Thank you.")


# ============================================================
# HANDLERS — Manage
# ============================================================

@dp.callback_query(F.data == "menu:manage")
async def manage_menu(call: CallbackQuery):
    await call.message.edit_text("⚙️ <b>Manage</b>\n\nChoose an option:", reply_markup=manage_menu_kb())
    await call.answer()


@dp.callback_query(F.data == "manage:list")
async def manage_list(call: CallbackQuery):
    giveaways = await get_all_giveaways_by_creator(call.from_user.id)
    if not giveaways:
        await call.message.edit_text("You haven't created any giveaways yet.", reply_markup=back_to_menu_kb())
        await call.answer()
        return

    await call.message.edit_text(
        "📃 <b>Your Giveaways</b>\n\nSelect one to manage:", reply_markup=manage_giveaway_list_kb(giveaways)
    )
    await call.answer()


async def render_giveaway_panel(call: CallbackQuery, gid: str):
    gw = await get_giveaway(gid)
    if not gw:
        await call.answer("Not found.", show_alert=True)
        return
    count = await get_participant_count(gid)
    text = (
        f"🎉 <b>{gw['channel_title']}</b>\n"
        f"Status: {'🟢 Active' if gw['status'] == 'active' else '🔴 Ended'}\n"
        f"Participants: {count}\n"
        f"Multi-Vote: {'ON' if gw.get('multi_vote') else 'OFF'}"
    )
    await call.message.edit_text(
        text, reply_markup=manage_giveaway_actions_kb(gid, gw.get("multi_vote", False), gw["status"] == "active")
    )


@dp.callback_query(F.data.startswith("manage:g:"))
async def giveaway_actions(call: CallbackQuery):
    gid = call.data.split(":")[2]
    gw = await get_giveaway(gid)
    if not gw or gw["creator_id"] != call.from_user.id:
        await call.answer("⛔ You don't have permission to manage this giveaway.", show_alert=True)
        return
    await render_giveaway_panel(call, gid)
    await call.answer()


@dp.callback_query(F.data.startswith("manage:multitoggle:"))
async def multi_toggle(call: CallbackQuery):
    gid = call.data.split(":")[2]
    gw = await get_giveaway(gid)
    if not gw or gw["creator_id"] != call.from_user.id:
        await call.answer("⛔ You don't have permission to manage this giveaway.", show_alert=True)
        return
    new_val = await toggle_multi_vote(gid)
    await render_giveaway_panel(call, gid)
    await call.answer(f"Multi-vote turned {'ON' if new_val else 'OFF'}")


@dp.callback_query(F.data.startswith("manage:end:"))
async def end_giveaway_cb(call: CallbackQuery):
    gid = call.data.split(":")[2]
    gw = await get_giveaway(gid)
    if not gw or gw["creator_id"] != call.from_user.id:
        await call.answer("⛔ You don't have permission to manage this giveaway.", show_alert=True)
        return
    if gw["status"] != "active":
        await call.answer("Already ended.", show_alert=True)
        return

    leaderboard = await get_leaderboard(gid, 10)
    all_participants = await get_all_participants(gid)
    await end_giveaway(gid)

    lines = ["🏁 <b>Giveaway Ended!</b>", "", f"🏆 <b>Top {len(leaderboard)} Winners</b>", ""]
    medals = ["🥇", "🥈", "🥉"]
    for i, p in enumerate(leaderboard):
        medal = medals[i] if i < 3 else f"{i + 1}."
        uname = f"@{p['username']}" if p.get("username") else p["first_name"]
        lines.append(f"{medal} {uname} — <b>{p['votes']}</b> votes")
    lines.append("")
    lines.append("🎉 Congratulations to all winners! Thank you for participating.")
    text = "\n".join(lines)

    results_message_id = None
    try:
        sent = await bot.send_message(gw["channel_id"], text)
        results_message_id = sent.message_id
        await set_results_message(gid, results_message_id)
        if gw.get("announce_message_id"):
            await bot.unpin_chat_message(gw["channel_id"], gw["announce_message_id"])
    except Exception:
        pass

    # Notify every participant in DM with the final scoreboard
    dm_text = text
    if results_message_id:
        link = build_message_link(gw["channel_id"], gw.get("channel_username"), results_message_id)
        dm_text += f'\n\n🔗 <a href="{link}">View in channel</a>'

    notified = 0
    for p in all_participants:
        try:
            await bot.send_message(p["user_id"], dm_text, disable_web_page_preview=True)
            notified += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)  # throttle to stay under Telegram flood limits

    await log_event(
        "🏁 <b>Giveaway Ended</b>\n"
        f"Channel: {gw['channel_title']}\n"
        f"Ended by: {call.from_user.first_name} [<code>{call.from_user.id}</code>]\n"
        f"Total participants: {len(all_participants)}\n\n"
        + text
    )

    await call.message.edit_text(
        f"✅ Giveaway ended. Scoreboard posted in the channel.\n📩 Notified {notified}/{len(all_participants)} participants.",
        reply_markup=back_to_menu_kb(),
    )
    await call.answer()


@dp.callback_query(F.data.startswith("manage:addvote:"))
async def ask_addvote(call: CallbackQuery, state: FSMContext):
    gid = call.data.split(":")[2]
    gw = await get_giveaway(gid)
    if not gw or gw["creator_id"] != call.from_user.id:
        await call.answer("⛔ You don't have permission to manage this giveaway.", show_alert=True)
        return
    await state.update_data(gid=gid, action="add")
    await state.set_state(ManageVote.waiting_participant_id)
    await call.message.edit_text(
        "Send the participant's <b>user ID</b> or <b>@username</b> to add a vote.\nSend /cancel to abort."
    )
    await call.answer()


@dp.callback_query(F.data.startswith("manage:removevote:"))
async def ask_removevote(call: CallbackQuery, state: FSMContext):
    gid = call.data.split(":")[2]
    gw = await get_giveaway(gid)
    if not gw or gw["creator_id"] != call.from_user.id:
        await call.answer("⛔ You don't have permission to manage this giveaway.", show_alert=True)
        return
    await state.update_data(gid=gid, action="remove")
    await state.set_state(ManageVote.waiting_participant_id)
    await call.message.edit_text(
        "Send the participant's <b>user ID</b> or <b>@username</b> to remove a vote.\nSend /cancel to abort."
    )
    await call.answer()


@dp.message(ManageVote.waiting_participant_id, F.text == "/cancel")
@dp.message(ManageVote.waiting_amount, F.text == "/cancel")
async def cancel_manage(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Cancelled.")


@dp.message(ManageVote.waiting_participant_id)
async def receive_participant(message: Message, state: FSMContext):
    data = await state.get_data()
    gid = data["gid"]
    raw = message.text.strip().lstrip("@")

    participant = None
    if raw.isdigit():
        participant = await get_participant(gid, int(raw))
    else:
        cursor = participants_col.find({"giveaway_id": gid, "username": {"$regex": f"^{raw}$", "$options": "i"}})
        results = await cursor.to_list(length=1)
        participant = results[0] if results else None

    if not participant:
        await message.answer("❌ Participant not found in this giveaway. Try again or send /cancel.")
        return

    await state.update_data(participant_id=participant["user_id"])
    await state.set_state(ManageVote.waiting_amount)
    await message.answer("How many votes? Send a number (e.g. 1, 5).")


@dp.message(ManageVote.waiting_amount)
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

    gw = await get_giveaway(gid)
    participant = await update_votes(gid, participant_id, delta, log_line)
    await refresh_profile_message(gw, participant)

    await log_event(
        "🔧 <b>Manual Vote Adjustment</b>\n"
        f"Giveaway: {gw['channel_title']}\n"
        f"Admin: {message.from_user.first_name} [<code>{message.from_user.id}</code>]\n"
        f"Participant: {participant['first_name']} [<code>{participant['user_id']}</code>]\n"
        f"{'➕ Added' if action == 'add' else '➖ Removed'}: {amount} vote(s)\n"
        f"New total: <b>{participant['votes']}</b>"
    )

    await message.answer(f"✅ Done. {participant['first_name']} now has <b>{participant['votes']}</b> votes.")
    await state.clear()


# ============================================================
# HANDLERS — /score
# ============================================================

async def resolve_score_gid(user_id: int):
    """Pick the giveaway to show: (a) an active one this user created, else
    (b) the most recent giveaway they're participating in (active or ended)."""
    giveaways = await get_active_giveaways_by_creator(user_id)
    if giveaways:
        return str(giveaways[0]["_id"]), giveaways[0]["channel_title"]

    cursor = participants_col.find({"user_id": user_id}).sort("joined_at", -1)
    results = await cursor.to_list(length=1)
    if results:
        participant = results[0]
        gid = participant["giveaway_id"]
        gw = await get_giveaway(gid)
        return gid, (gw["channel_title"] if gw else None)

    return None, None


async def build_scoreboard_text(gid: str, channel_title, gw):
    leaderboard = await get_leaderboard(gid, 10)
    if not leaderboard:
        return "No participants yet.", leaderboard

    lines = ["🏆 <b>Top 10 Scoreboard</b>"]
    if channel_title:
        lines.append(f"📢 {channel_title}")
    lines.append("")

    medals = ["🥇", "🥈", "🥉"]
    for i, p in enumerate(leaderboard):
        medal = medals[i] if i < 3 else f"{i + 1}."
        uname = f"@{p['username']}" if p.get("username") else p["first_name"]
        link = build_message_link(gw["channel_id"], gw.get("channel_username"), p["profile_message_id"])
        lines.append(f'{medal} <a href="{link}">{uname}</a> (<code>{p["user_id"]}</code>) — <b>{p["votes"]}</b> votes')

    return "\n".join(lines), leaderboard


async def send_scoreboard(target, gid: str, channel_title, user_id: int, edit: bool):
    gw = await get_giveaway(gid)

    if not gw:
        text_out = "This giveaway no longer exists."
        kb = None

    elif gw["status"] != "active":
        # Ended: show a clear "ended" notice, no refresh (nothing will change anymore)
        board_text, _ = await build_scoreboard_text(gid, channel_title, gw)
        text_out = "🔴 <b>This giveaway has ended.</b>\n\n" + board_text

        kb_builder = InlineKeyboardBuilder()
        if gw.get("results_message_id"):
            results_link = build_message_link(gw["channel_id"], gw.get("channel_username"), gw["results_message_id"])
            kb_builder.button(text="🏆 View Final Results", url=results_link)
        kb_builder.adjust(1)
        kb = kb_builder.as_markup()

    else:
        text_out, _ = await build_scoreboard_text(gid, channel_title, gw)
        my_post_link = None
        participant = await get_participant(gid, user_id)
        if participant:
            my_post_link = build_message_link(gw["channel_id"], gw.get("channel_username"), participant["profile_message_id"])
        kb = scoreboard_kb(gid, my_post_link)

    if edit:
        try:
            await target.message.edit_text(text_out, reply_markup=kb, disable_web_page_preview=True)
        except Exception:
            pass
    else:
        await target.answer(text_out, reply_markup=kb, disable_web_page_preview=True)


@dp.message(Command("score"))
async def score_cmd(message: Message):
    gid, channel_title = await resolve_score_gid(message.from_user.id)
    if not gid:
        await message.answer("No giveaway found for you yet.")
        return
    await send_scoreboard(message, gid, channel_title, message.from_user.id, edit=False)


@dp.callback_query(F.data.startswith("score:refresh:"))
async def score_refresh(call: CallbackQuery):
    gid = call.data.split(":")[2]
    gw = await get_giveaway(gid)
    if not gw or gw["status"] != "active":
        await call.answer("This giveaway has ended.", show_alert=True)
        return
    channel_title = gw["channel_title"]
    await send_scoreboard(call, gid, channel_title, call.from_user.id, edit=True)
    await call.answer("Refreshed ✅")


# ============================================================
# HANDLERS — Owner-only: /stats, /broadcast, /id
# ============================================================

@dp.message(Command("stats"), IsOwner())
async def stats_cmd(message: Message):
    user_count = await get_user_count()
    chat_count = await get_chat_count()
    total_gw, live_gw, completed_gw = await get_giveaway_counts()
    participant_total = await get_participant_total()
    vote_total = await get_vote_total()

    uptime_seconds = int(time.time() - START_TIME)
    hours, rem = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(rem, 60)

    text = (
        "📊 <b>Bot Stats</b>\n\n"
        f"👤 Total Users: <b>{user_count}</b>\n"
        f"🔗 Connected Chats: <b>{chat_count}</b>\n\n"
        f"🎉 Total Giveaways: <b>{total_gw}</b>\n"
        f"🟢 Live Giveaways: <b>{live_gw}</b>\n"
        f"✅ Completed Giveaways: <b>{completed_gw}</b>\n\n"
        f"🙋 Total Participants: <b>{participant_total}</b>\n"
        f"🗳 Total Votes Cast: <b>{vote_total}</b>\n\n"
        f"⏱ Uptime: {hours}h {minutes}m {seconds}s"
    )
    await message.answer(text)


@dp.message(Command("broadcast"), IsOwner())
async def broadcast_cmd(message: Message, command: CommandObject):
    text_to_send = command.args if command.args else None
    source_message = message.reply_to_message

    if not text_to_send and not source_message:
        await message.answer(
            "Usage:\n"
            "<code>/broadcast your message here</code>\n"
            "or reply to any message with <code>/broadcast</code> to send that exact "
            "message (text, photo, etc.) to all users."
        )
        return

    user_ids = await get_all_user_ids()
    if not user_ids:
        await message.answer("No users to broadcast to yet.")
        return

    status_msg = await message.answer(f"📢 Broadcasting to {len(user_ids)} users...")

    sent = 0
    failed = 0
    for uid in user_ids:
        try:
            if source_message:
                await source_message.copy_to(uid)
            else:
                await bot.send_message(uid, text_to_send)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # throttle to stay under Telegram flood limits

    await status_msg.edit_text(f"✅ Broadcast complete.\n\nSent: {sent}\nFailed: {failed}")


@dp.message(Command("id"), IsOwner())
async def id_cmd(message: Message):
    lines = [f"👤 Your ID: <code>{message.from_user.id}</code>"]
    if message.chat.id != message.from_user.id:
        lines.append(f"💬 Chat ID: <code>{message.chat.id}</code>")
    if message.reply_to_message:
        lines.append(f"↩️ Replied user ID: <code>{message.reply_to_message.from_user.id}</code>")
    await message.answer("\n".join(lines))


# ============================================================
# ENTRYPOINT
# ============================================================

async def main():
    # Enforces one vote per (giveaway, voter, participant) at the database level,
    # so a double-tap or a scripted replay can never slip through as two votes.
    await votes_col.create_index(
        [("giveaway_id", 1), ("voter_id", 1), ("participant_id", 1)], unique=True
    )
    await bot.delete_webhook(drop_pending_updates=True)
    log.info("Vote Bot started. Polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
