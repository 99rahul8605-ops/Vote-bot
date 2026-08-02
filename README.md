# Vote Bot

Telegram vote-giveaway bot — aiogram v3 + MongoDB.

## Features

- `/start` → Connect / Create Giveaway / Manage (inline menu)
- **Connect** — lists channels/groups the bot has been added to (as admin)
- **Create Giveaway** — verify channel/username → post + pin announcement with a
  deep-link "Participate" button
- **Deep link join** → bot DM asks "Participate? Yes/No"
- On **Yes** → checks the user has joined the channel → posts their profile
  (name, ID, username, vote count) in the channel with **Vote** + **Participate** buttons
- **Voting**
  - Only counts if the voter has joined the channel (else a popup tells them to join)
  - Double-voting blocked ("You have already voted")
  - **Multi-Vote setting (per giveaway, toggle in Manage)**
    - `OFF` (default): a user can cast only **one vote total** in the giveaway
    - `ON`: a user can vote for **multiple different participants**, but still not
      twice for the same one
- **Manage** — Add Vote / Remove Vote (admin adjustment, logged on the participant's
  channel message) / Toggle Multi-Vote / End Giveaway (posts Top 10 scoreboard, unpins)
- `/score` in bot DM — Top 10 leaderboard with votes and user details

## Project structure

```
vote-bot/
├── main.py            # entrypoint
├── config.py           # env config
├── database.py          # MongoDB (motor) — all DB logic
├── states.py            # FSM states
├── keyboards.py          # inline keyboards
├── handlers/
│   ├── start.py          # /start + deep link routing
│   ├── chat_member.py     # tracks chats bot is added/removed from
│   ├── connect.py         # Connect menu
│   ├── giveaway.py        # Create Giveaway flow
│   ├── participate.py     # join confirm, profile post, vote button
│   ├── manage.py          # add/remove vote, multi-vote toggle, end giveaway
│   └── score.py           # /score command
├── requirements.txt
└── .env.example
```

## Setup (Termux / local)

```bash
cd vote-bot
pip install -r requirements.txt --break-system-packages   # Termux
# or: pip install -r requirements.txt                      # normal Linux venv

cp .env.example .env
nano .env   # fill BOT_TOKEN, MONGO_URI, DB_NAME
```

Get `BOT_TOKEN` from [@BotFather](https://t.me/BotFather). Also run `/setprivacy` →
`Disable` on BotFather if you want the bot to still respond correctly to callbacks
inside groups (not strictly needed for this bot, but good practice for
group-connected bots).

Run locally:

```bash
python3 main.py
```

## Deploy on AWS EC2 (systemd, matches your existing setup)

```bash
# on EC2
cd ~
git clone <your-repo-or-scp-the-folder> vote-bot
cd vote-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
```

Create the systemd service:

```bash
sudo tee /etc/systemd/system/votebot.service > /dev/null << 'EOF'
[Unit]
Description=Vote Bot (Telegram)
After=network.target mongod.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/vote-bot
ExecStart=/home/ubuntu/vote-bot/venv/bin/python3 main.py
Restart=always
RestartSec=5
EnvironmentFile=/home/ubuntu/vote-bot/.env

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable votebot
sudo systemctl start votebot
sudo systemctl status votebot
journalctl -u votebot -f     # live logs
```

If MongoDB is on the same EC2 instance, make sure `mongod` is running
(`sudo systemctl enable --now mongod`) before starting `votebot`.

## Important design notes / assumptions

1. **Connect list scoping** — a channel/group shows up under a user's Connect
   list only if *that user* was the one who added the bot there
   (`added_by == user_id`, captured from the `my_chat_member` update). This keeps
   one user from seeing/managing channels added by someone else.
2. **Giveaway ownership** — only the creator (`creator_id`) can see/manage a
   giveaway in the Manage menu.
3. **Bot must be admin** in the target channel/group with **post message** and
   **pin message** rights — this is checked before a giveaway is created.
4. **Multi-Vote** is a per-giveaway toggle, changeable anytime from Manage →
   select giveaway → 🔁 Multi-Vote button. See the OFF/ON behavior above.
5. **Admin add/remove vote** — every manual adjustment is appended as a log line
   under the participant's profile message in the channel (last 5 shown), and the
   vote count updates immediately on that message.
6. **`/score`** — checks (a) the caller's most recent active giveaway as creator,
   then (b) a giveaway the caller is participating in. If you'd rather scope this
   by giveaway ID or channel explicitly, that's an easy follow-up change.
7. **Channel membership checks** use Telegram's `getChatMember` — this works for
   any user ID as long as the bot is admin in that channel, no separate
   permission needed from the voter.

## Possible next steps (not built yet, tell me if you want these)

- Multiple concurrent active giveaways per creator with a picker in `/score`
- Broadcast/notify all participants when a giveaway ends
- Rate limiting / captcha on vote button to deter vote-bots
- Web dashboard for giveaway stats
