from datetime import datetime

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from config import MONGO_URI, DB_NAME

client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]

chats_col = db["chats"]
giveaways_col = db["giveaways"]
participants_col = db["participants"]
votes_col = db["votes"]


# ---------------- CHATS (Connect) ----------------

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


# ---------------- GIVEAWAYS ----------------

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


# ---------------- PARTICIPANTS ----------------

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


# ---------------- VOTES (double-vote prevention) ----------------

async def has_voted(giveaway_id: str, voter_id: int, participant_id: int, multi_vote: bool):
    """
    multi_vote == False -> a voter can cast only ONE vote total in this giveaway
                            (for any single participant).
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


async def record_vote(giveaway_id: str, voter_id: int, participant_id: int):
    await votes_col.insert_one(
        {
            "giveaway_id": giveaway_id,
            "voter_id": voter_id,
            "participant_id": participant_id,
            "created_at": datetime.utcnow(),
        }
    )
