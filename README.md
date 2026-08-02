# Vote Bot

Telegram vote-giveaway bot — single file (`bot.py`), aiogram v3 + MongoDB.

## Files

```
vote-bot/
├── bot.py             # everything: config, DB, keyboards, handlers, entrypoint
├── requirements.txt
└── .env.example
```

## Features

- `/start` → Connect / Create Giveaway / Manage (inline menu)
- **Connect** → "Add to Channel" / "Add to Group" buttons open Telegram's native
  picker, adding the bot with the right admin rights pre-selected. "View Connected
  Chats" shows chats already added.
- **Create Giveaway** — verify channel/username → post + pin announcement with a
  deep-link "Participate" button
- **Deep link join** → bot DM asks "Participate? Yes/No"
- On **Yes** → checks the user has joined the channel → posts their profile
  (name, ID, username, vote count) in the channel with **Vote** + **Participate** buttons
- **Voting**
  - Only counts if the voter has joined the channel (else a popup tells them to join)
  - Double-voting blocked ("You have already voted")
  - **Multi-Vote setting** (per giveaway, toggle in Manage)
    - `OFF` (default): a user can cast only **one vote total** in the giveaway
    - `ON`: a user can vote for **multiple different participants**, but still not
      twice for the same one
- **Manage** — Add Vote / Remove Vote (logged on the participant's channel message) /
  Toggle Multi-Vote / End Giveaway (posts Top 10 scoreboard, unpins)
- `/score` in bot DM — Top 10 leaderboard with votes and user details
- **Owner-only commands** (set `OWNER_ID` in `.env`):
  - `/stats` — total users, connected chats, total/live/completed giveaways,
    total participants, total votes cast, uptime
  - `/broadcast <text>` or reply to any message with `/broadcast` — sends it to
    every user who has started the bot
  - `/id` — quick lookup of your ID / current chat ID / replied user's ID

## Setup

```bash
cd vote-bot
pip install -r requirements.txt --break-system-packages   # Termux/managed envs
# or: pip install -r requirements.txt

cp .env.example .env
nano .env   # fill BOT_TOKEN, MONGO_URI, DB_NAME, OWNER_ID
```

Get `BOT_TOKEN` from [@BotFather](https://t.me/BotFather).
Get your `OWNER_ID` from [@userinfobot](https://t.me/userinfobot).

Run:

```bash
python3 bot.py
```

## Deploy on AWS EC2 (systemd)

```bash
cd ~/Vote-bot
sudo tee /etc/systemd/system/votebot.service > /dev/null << 'EOF'
[Unit]
Description=Vote Bot (Telegram)
After=network.target mongod.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/Vote-bot
ExecStart=/home/ubuntu/.pyenv/versions/3.12.7/bin/python /home/ubuntu/Vote-bot/bot.py
Restart=always
RestartSec=5
EnvironmentFile=/home/ubuntu/Vote-bot/.env

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable votebot
sudo systemctl start votebot
sudo systemctl status votebot
journalctl -u votebot -f     # live logs
```

Adjust the `ExecStart` python path to whatever interpreter you're using
(pyenv path, `venv/bin/python3`, or system `python3` — whichever works on your box).

## Design notes

1. **Connect list scoping** — a channel/group shows up under a user's
   "View Connected Chats" only if *that user* added the bot there
   (`added_by == user_id`).
2. **Giveaway ownership** — only the creator can manage a giveaway.
3. Bot must be **admin** in the target channel/group with post + pin rights —
   checked before a giveaway is created.
4. **Multi-Vote** toggle lives per-giveaway in Manage.
5. Admin vote adjustments are logged (last 5 shown) directly on the participant's
   channel profile message.
6. `/score` checks (a) your own active giveaway as creator, then (b) a giveaway
   you're participating in.
