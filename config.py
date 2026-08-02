import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "vote_bot")
OWNER_ID = int(os.getenv("OWNER_ID", "0") or "0")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set. Please add it to your .env file.")
