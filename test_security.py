"""
test_security.py — Verifies vote bot's security fixes:
  1. Non-owner users CANNOT manage someone else's giveaway
     (End / Add Vote / Remove Vote / Multi-Vote toggle).
  2. A single voter CANNOT get double-counted even under a race
     (rapid double-tap / replayed request).

Run this in the SAME folder as bot.py, with the same .env present:

    python3 test_security.py

Safe to run: it does NOT start polling, does NOT send real Telegram
messages, and does NOT touch your real giveaways/votes (test data uses
a throwaway giveaway ID and negative voter/participant IDs that can
never collide with real Telegram user IDs, and is cleaned up after).
"""

import asyncio
from unittest.mock import AsyncMock

import bot as bot_module  # imports your real bot.py (does not start polling)


# ============================================================
# Fake Telegram objects (no network calls)
# ============================================================

class FakeUser:
    def __init__(self, user_id):
        self.id = user_id


class FakeMessage:
    def __init__(self):
        self.edited_texts = []

    async def edit_text(self, text, reply_markup=None, **kwargs):
        self.edited_texts.append(text)


class FakeCallbackQuery:
    def __init__(self, data, user_id):
        self.data = data
        self.from_user = FakeUser(user_id)
        self.message = FakeMessage()
        self.answers = []  # list of (text, show_alert)

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


# ============================================================
# Test data
# ============================================================

FAKE_GID = "aaaaaaaaaaaaaaaaaaaaaaaa"  # valid-looking ObjectId hex, never a real giveaway
CREATOR_ID = 111111111                 # pretend this is the real giveaway owner
ATTACKER_ID = 999999999                # pretend this is a random other user

FAKE_GW = {
    "_id": FAKE_GID,
    "creator_id": CREATOR_ID,
    "channel_id": -1001234567890,
    "channel_title": "Test Channel",
    "status": "active",
    "multi_vote": False,
}


async def fake_get_giveaway(gid):
    return FAKE_GW if gid == FAKE_GID else None


def was_blocked(call: FakeCallbackQuery) -> bool:
    return any("permission" in (text or "").lower() for text, _ in call.answers)


# ============================================================
# TEST 1 — Manage ownership enforcement
# ============================================================

async def test_ownership_enforced():
    print("=== TEST 1: Manage ownership enforcement ===")
    original_get_giveaway = bot_module.get_giveaway
    bot_module.get_giveaway = fake_get_giveaway

    try:
        results = []

        # --- Attacker (not the creator) tries every manage action ---
        call = FakeCallbackQuery(f"manage:g:{FAKE_GID}", ATTACKER_ID)
        await bot_module.giveaway_actions(call)
        results.append(("Open manage panel", was_blocked(call)))

        call = FakeCallbackQuery(f"manage:multitoggle:{FAKE_GID}", ATTACKER_ID)
        await bot_module.multi_toggle(call)
        results.append(("Toggle Multi-Vote", was_blocked(call)))

        call = FakeCallbackQuery(f"manage:end:{FAKE_GID}", ATTACKER_ID)
        await bot_module.end_giveaway_cb(call)
        results.append(("End Giveaway", was_blocked(call)))

        call = FakeCallbackQuery(f"manage:addvote:{FAKE_GID}", ATTACKER_ID)
        await bot_module.ask_addvote(call, state=AsyncMock())
        results.append(("Add Vote", was_blocked(call)))

        call = FakeCallbackQuery(f"manage:removevote:{FAKE_GID}", ATTACKER_ID)
        await bot_module.ask_removevote(call, state=AsyncMock())
        results.append(("Remove Vote", was_blocked(call)))

        all_blocked = True
        for label, blocked in results:
            status = "PASS ✅" if blocked else "FAIL ⚠️  (attacker was NOT blocked!)"
            print(f"  Attacker blocked from '{label}': {status}")
            all_blocked = all_blocked and blocked

        # --- Real creator should NOT be blocked ---
        call = FakeCallbackQuery(f"manage:g:{FAKE_GID}", CREATOR_ID)
        await bot_module.giveaway_actions(call)
        creator_ok = not was_blocked(call)
        print(f"  Real creator allowed access: {'PASS ✅' if creator_ok else 'FAIL ⚠️'}")

        print(
            "\n  RESULT:",
            "ALL PASSED ✅" if (all_blocked and creator_ok) else "SOME FAILED ⚠️  — recheck your ownership checks!",
        )

    finally:
        bot_module.get_giveaway = original_get_giveaway  # restore real function


# ============================================================
# TEST 2 — Double-vote / race protection
# ============================================================

async def test_vote_race_protection():
    print("\n=== TEST 2: Double-vote race protection ===")

    test_gid = "racetest0000000000000001"
    test_voter_id = -1        # negative IDs can never be real Telegram users
    test_participant_id = -2

    # make sure the unique index exists (main() also creates it on real startup)
    await bot_module.votes_col.create_index(
        [("giveaway_id", 1), ("voter_id", 1), ("participant_id", 1)], unique=True
    )

    # clean slate
    await bot_module.votes_col.delete_many({"giveaway_id": test_gid, "voter_id": test_voter_id})

    # fire 20 "simultaneous" vote attempts for the SAME voter + participant
    attempts = 20
    results = await asyncio.gather(
        *[bot_module.record_vote(test_gid, test_voter_id, test_participant_id) for _ in range(attempts)]
    )
    successes = sum(1 for r in results if r)

    print(f"  Concurrent vote attempts: {attempts}")
    print(f"  Successfully recorded: {successes}")
    print(
        "  RESULT:",
        "PASS ✅ (exactly 1 vote recorded)"
        if successes == 1
        else f"FAIL ⚠️  ({successes} recorded — race condition NOT fixed!)",
    )

    # cleanup test data
    await bot_module.votes_col.delete_many({"giveaway_id": test_gid, "voter_id": test_voter_id})


# ============================================================
# ENTRYPOINT
# ============================================================

async def main():
    await test_ownership_enforced()
    await test_vote_race_protection()
    print("\nDone. If any test shows FAIL, share the output and I'll help fix it.")


if __name__ == "__main__":
    asyncio.run(main())
