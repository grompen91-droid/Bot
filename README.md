# 🏰 Medieval Town Economy Bot

A pure economy Discord bot with a medieval flavour. Townsfolk pick a trade,
work it to gather goods, level up their skills, sell at a market whose prices
shift daily, and save up for better tools. **No Discord roles are used or
required** — everything lives in the bot's own economy.

## Features

- **8 trades** anyone can take up (and switch between — skill per trade is
  never lost): 🌾 Farmer, ⛏️ Miner, 🎣 Fisherman, 🪓 Lumberjack, 🏹 Hunter,
  🍞 Baker, 🍺 Brewer, 🧪 Alchemist
- **Work & skills** — `/work` on a short cooldown gathers trade goods
  (wheat, ore, fish, logs…) plus a small coin tip, and grants XP.
  Each skill level adds +3% to your yields.
- **Town market** — goods prices swing ±15–20% every day. Sell one item,
  a chosen amount, or your whole satchel.
- **Tool shop** — three purchasable tool tiers per trade (up to ×1.50 yield),
  the main gold sink.
- **Daily stipend** with a streak bonus, player-to-player payments, and
  gold & skill leaderboards.
- Per-server economy stored in a local SQLite database.

## Commands

| Command | What it does |
| --- | --- |
| `/job list` | Browse all trades on the town job board |
| `/job choose` | Take up a trade |
| `/job quit` | Quit your trade (skill is kept) |
| `/work` | Labour at your trade for goods, coin, and XP |
| `/skills [member]` | Skill levels in every trade practised |
| `/inventory` | See your satchel and what it's worth today |
| `/sell [item] [amount]` | Sell goods (no item = sell everything) |
| `/market` | Today's market prices for every good |
| `/shop` | Browse tool tiers for your trade |
| `/buy` | Buy the next tool tier |
| `/balance [member]` | Gold in a purse |
| `/daily` | Daily stipend (streak bonus up to +100) |
| `/pay <member> <amount>` | Give gold to another player |
| `/profile [member]` | Full profile: purse, trade, tool, progress |
| `/leaderboard [board]` | Richest or most skilled townsfolk |

## Setup

1. Create an application at the
   [Discord Developer Portal](https://discord.com/developers/applications),
   add a **Bot**, and copy its token. No privileged intents are needed.
2. Invite the bot to your server with the `bot` and `applications.commands`
   scopes (Send Messages + Embed Links permissions are enough).
3. Install and run:

   ```bash
   pip install -r requirements.txt
   cp .env.example .env   # then paste your token into .env
   python bot.py
   ```

Set `GUILD_ID` in `.env` to your server's ID for instant slash-command sync
while testing; without it, global sync can take up to an hour to appear.
