from aiogram.fsm.state import State, StatesGroup


class GiveawayCreate(StatesGroup):
    waiting_channel = State()


class ManageVote(StatesGroup):
    waiting_participant_id = State()
    waiting_amount = State()
