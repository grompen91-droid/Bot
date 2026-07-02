# 🏰 Medieval Town Economy Bot

A pure economy Discord bot with a medieval soul. Townsfolk take a trade,
work it to gather goods, level their skills, sell at a market whose prices
drift every day, and save for better tools. **No Discord roles are used or
required** — rank in town is measured in gold and skill alone.

Built on [Components V2](https://message.style/docs/features/components-v2/):
every reply is a styled container panel with headers, separators, and
interactive controls (a trade-picker menu on the job board, a ⚒️ Work Again
button, one-click tool buying at the smithy).

Every command is **hybrid** — `.work` and `/work` both do the same thing.

## The game

- **8 trades**: 🌾 Farmer, ⛏️ Miner, 🎣 Fisherman, 🪓 Lumberjack, 🏹 Hunter,
  plus 🍞 Baker, 🍺 Brewer, 🧪 Alchemist unlocked at 5 / 10 / 20 total skill
  levels. Switch freely — skill per trade is never lost.
- **Working** (`.work`) rolls a weighted haul of trade goods plus a coin tip
  and XP. Skill and tools compound:
  - yields: **+3%/level** (soft-capped at 25, then +1%), tools up to **×1.85**
  - cooldown: **-0.6%/level**, down to -30%
  - crit chance (double haul): up to **25%**, fed by tools and levels
  - bonus finds (second haul): up to **30%**
  - rare+ goods get **luckier with level** (up to double drop weight)
- **The market** (`.market`, `.sell`): deterministic daily prices — a 7-day
  sine wave per good (each on its own phase) times daily noise, so goods
  peak on different days and every player sees the same market.
- **The smithy** (`.shop`, `.buy`): five tool tiers per trade
  (300 → 30,000 gold), the main gold sink.
- **Daily stipend** (`.daily`): base + streak bonus + a bonus for total
  skill level. `.pay`, `.profile` (with lifetime deed stats),
  `.leaderboard` for gold and skills.

## Commands

| Command | What it does |
| --- | --- |
| `.job` | Job board with a trade-picker menu |
| `.job choose <trade>` / `.job quit` / `.job info <trade>` | Manage your trade |
| `.work` | Labour for goods, coin, and XP (⚒️ Work Again button) |
| `.skills [member]` | Skill levels in every trade |
| `.inventory` | Your satchel and today's worth |
| `.market` | Today's prices with ▲▼ trends |
| `.sell [item] [amount]` | Sell goods (`.sell` alone sells everything) |
| `.shop` / `.buy` | The smithy — tool tiers with a buy button |
| `.balance` / `.daily` / `.pay` / `.profile` / `.leaderboard` | Gold |
| `.help` / `.about` | Guidance |

## Architecture (how to expand it)

```
bot.py               entry point, prefix + intents, error handling, sync
econ/
  formulas.py        EVERY tunable number & curve — balance the game here
  database.py        async SQLite with versioned migrations (append to
                     MIGRATIONS to evolve the schema safely)
  data/
    items.py         item registry (name, emoji, value, rarity)
    jobs.py          job registry (yields, cooldown, unlock, flavour)
    tools.py         tool ladders per trade (names + prices)
ui/
  panels.py          Components V2 medieval panel builder (fluent API)
cogs/
  jobs.py            job board, work engine, skills
  market.py          inventory, market, sell, smithy
  economy.py         balance, daily, pay, profile, leaderboards
  info.py            help, about
```

- **Add an item**: one line in `econ/data/items.py`.
- **Add a trade**: an entry in `jobs.py` + a tool ladder in `tools.py` —
  the job board, work, market, shop, and autocomplete all pick it up.
  Registries self-validate at import time.
- **Rebalance**: everything from XP pacing to market volatility is a named
  constant or pure function in `econ/formulas.py`.
- **New features**: the `stats` table already tracks lifetime counters
  (works, goods gathered/sold, gold flows) — ready for achievements,
  quests, or taxes. Add tables via a new entry in `MIGRATIONS`.

## Setup

1. Create an application at the
   [Discord Developer Portal](https://discord.com/developers/applications),
   add a **Bot**, copy its token, and enable the **Message Content** intent
   (Bot → Privileged Gateway Intents) — needed for `.` prefix commands.
2. Invite the bot with the `bot` + `applications.commands` scopes
   (Send Messages permission is enough).
3. Install and run:

   ```bash
   pip install -r requirements.txt
   cp .env.example .env   # paste your token into .env
   python bot.py
   ```

Set `GUILD_ID` in `.env` for instant slash-command sync while testing;
global sync can take up to an hour. Requires Python 3.10+ and
discord.py 2.6+ (Components V2).
