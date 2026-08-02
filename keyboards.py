from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🔗 Connect", callback_data="menu:connect")
    kb.button(text="🎉 Create Giveaway", callback_data="menu:create_giveaway")
    kb.button(text="⚙️ Manage", callback_data="menu:manage")
    kb.adjust(1)
    return kb.as_markup()


def back_to_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Back", callback_data="menu:main")
    return kb.as_markup()


def connect_menu_kb(bot_username: str):
    kb = InlineKeyboardBuilder()
    admin_rights = "post_messages+edit_messages+delete_messages+pin_messages"
    kb.button(
        text="📢 Add to Channel",
        url=f"https://t.me/{bot_username}?startchannel&admin={admin_rights}",
    )
    kb.button(
        text="👥 Add to Group",
        url=f"https://t.me/{bot_username}?startgroup&admin=delete_messages+pin_messages+promote_members",
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
    kb.button(text="📃 My Giveaways", callback_data="manage:list")
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
        kb.button(text="➕ Add Vote", callback_data=f"manage:addvote:{gid}")
        kb.button(text="➖ Remove Vote", callback_data=f"manage:removevote:{gid}")
        kb.button(text=f"🔁 Multi-Vote: {'ON' if multi_vote else 'OFF'}", callback_data=f"manage:multitoggle:{gid}")
        kb.button(text="🏁 End Giveaway", callback_data=f"manage:end:{gid}")
    kb.button(text="⬅️ Back", callback_data="manage:list")
    kb.adjust(1)
    return kb.as_markup()


def participate_confirm_kb(gid: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Yes, Participate", callback_data=f"confirm:{gid}:yes")
    kb.button(text="❌ No", callback_data=f"confirm:{gid}:no")
    kb.adjust(2)
    return kb.as_markup()


def profile_post_kb(gid: str, user_id: int, bot_username: str, votes: int):
    kb = InlineKeyboardBuilder()
    kb.button(text=f"🗳 Vote ({votes})", callback_data=f"vote:{gid}:{user_id}")
    kb.button(text="🎉 Participate", url=f"https://t.me/{bot_username}?start=join_{gid}")
    kb.adjust(1)
    return kb.as_markup()


def announce_kb(gid: str, bot_username: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="🎉 Participate", url=f"https://t.me/{bot_username}?start=join_{gid}")
    kb.adjust(1)
    return kb.as_markup()
