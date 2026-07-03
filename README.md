# 🏰 Medieval Town Economy Bot

A pure economy Discord bot with a medieval soul. Townsfolk take a trade,
work it to gather goods, level their skills, sell at a market whose prices
drift every day, and save for better tools. **No Discord roles are used or
required**, rank in town is measured in gold and skill alone.

Built on [Components V2](https://message.style/docs/features/components-v2/):
every reply is a styled container panel with headers, separators, and
interactive controls (a trade-picker menu on the job board, a ⚒️ Work Again
button, one-click tool buying at the smithy).

Every command is **hybrid**, `.work` and `/work` both do the same thing.

## The game

- **10 trades**: 🌾 Farmer, ⛏️ Miner, 🎣 Fisherman start open; 🪓 Lumberjack,
  🏹 Hunter, 🍞 Baker, 🍺 Brewer, 🥾 Tanner, 🔍 Jeweler, 🧪 Alchemist unlock at
  an evenly-spaced 7 / 14 / 21 / 29 / 36 / 43 / 50 total skill levels (every
  ~7 levels, no sudden jumps). Skill per trade is never lost; switching has
  a 5-minute cooldown.
- **Anti-bot guard**: each work has a 1-in-20 chance of a letter
  challenge; commands and buttons stay locked (and the challenge
  repeats) until the player types the letters back in chat.
- **Town ranks**: a 9-tier title ladder from total skill level
  (Newcomer through Legendary Sovereign) that grants a real, permanent
  +2%/tier bonus to all gold and yields, town-wide, not just flavour.
- **`.venture`**: a second, job-independent way to earn. Pick one of
  three routes (low/medium/high risk) on a 2-hour cooldown, real
  choice, real risk. Payout scales with town rank and an ongoing win
  streak (+4%/win, capped).
- **Working** (`.work`) rolls a weighted haul of trade goods plus a coin tip
  and XP. Skill and tools compound:
  - yields: **+3%/level** (soft-capped at 25, then +1%), tools up to **×1.85**
  - cooldown: **-0.6%/level**, down to -30%
  - crit chance (double haul): up to **25%**, fed by tools and levels
  - bonus finds (second haul): up to **30%**
  - rare+ goods get **luckier with level** (up to double drop weight)
- **The market** (`.market`, `.sell`): deterministic daily prices, a 7-day
  sine wave per good (each on its own phase) times daily noise, so goods
  peak on different days and every player sees the same market. Selling
  a single named item is instant; `.sell` with no item (or `all`) asks
  "sell everything?" with Yes/No buttons first, since it's a one-shot,
  irreversible action.
- **`.shop`**: one paginated, dropdown-driven browser (same shape as
  `.market`/`.inventory`). A fresh **18 goods** rotate in daily out of
  a pool of every potion/buff food plus a broad set of rare-or-better
  raw goods (never crafted goods, never common/uncommon) -- shown
  **9 to a page**, same for every player, changes at UTC midnight, so
  the lineup is never a guaranteed way to buy any one item. Prices are
  a flat markup over base value (4x for potions/foods, 12x for rare
  goods), not the daily-drifting `.market` price. Every item also
  shows an "(N in stock)" cap next to its name -- not a flat number, a
  fresh 1-2 for potions/foods and 1-3 for rare goods, rolled per
  player per item per day, so your stock on any given item is never
  the same as the next player's, or the same as yesterday's. Buying is
  a single click from the "🛒 Buy an item…" dropdown.
- **⚒️ Upgrade Tool** (the button on `.shop`, or run `.buy` directly):
  the trade-specific gear, five tool tiers per trade (300 → 30,000
  gold), the main gold sink. Always asks you to confirm first --
  current tool, next tool, price, and the yield you'd get for it --
  before spending anything.
- **Crafting** (`.recipes`, `.craft`): a standalone skill, not tied to
  any trade, anyone can craft regardless of their current job. Combine
  gathered goods from across multiple trades into one higher-value
  crafted item, gated by Crafting skill level (13 recipes across 5
  tiers, and its own much steeper-than-a-trade XP curve -- recipes
  unlock early but further Crafting levels are the hardest grind in
  the game). Every recipe mints the item itself, not gold, priced tens
  to well over a hundred times the combined market value of its
  ingredients -- steepest for the XP-buff recipes, since an XP buff is
  a direct shortcut on every trade's own grind and is gated and priced
  accordingly (the market still lists what it's worth if you'd rather
  sell it). Crafting itself levels the skill and counts toward total
  skill level like any trade.
- **Consumables** (`.use`, `.buffs`): potions and foods that grant a
  temporary buff, either -cooldown, +XP, or +gold, for a set duration.
  All of them are priced as a real gold sink, not pocket change --
  cooldown/gold potions run into the thousands, and every XP potion
  costs noticeably more than a cooldown/gold one of the same rarity,
  from a quick +10% sip up to a top-tier +60% tonic worth tens of
  thousands. A small chance drops from ordinary `.work` regardless of trade,
  Alchemists can also brew potions with `.brew` (guaranteed on a
  flawless brew), and 9 of the 13 crafting recipes yield a buff food
  instead of a sellable good. `.use <item>` drinks/eats it; using the
  *same* item again extends the remaining time rather than resetting it
  (capped at 3x its base duration, so chaining a cheap item can't buy a
  near-permanent buff), while two *different* items of the same kind
  stack additively, up to a balance cap (+75% gold, +100% XP, -75%
  cooldown) so five gold potions at once can't multiply your income
  several times over. Every command that grants gold, XP, or has a
  cooldown reads these buffs, not just `.work`/`.craft`, everything from
  `.daily` and `.beg` to `.pickpocket`, `.smuggle`, `.venture`, `.brew`,
  and every per-job minigame. `.inventory` has a category dropdown
  (like `.market`) so it's obvious at a glance what's usable and what it
  does.
- **`.cd` / `.cooldown`**: every timer you're currently carrying in one
  place, gold and skill trades, crime, brewing, minigames, all of it,
  with a live `<t:...:R>` countdown or a plain "ready now." Only shows
  what you actually have access to (e.g. `.brew` stays hidden until
  you're an Alchemist or Alchemist level 5+), so it doesn't turn into a
  wall of things you can't do yet.
- **Daily stipend** (`.daily`): base + streak bonus + a bonus for total
  skill level across every trade, capped at 1,000 gold a day. `.pay`,
  `.profile` (with lifetime deed stats), `.leaderboard` for gold and
  skills (ranked by pocket + bank combined).
- **The bank** (`.bank`, `.deposit`, `.withdraw`): banked gold is safe
  from pickpocketing. Starts with a 5,000 gold capacity, upgradeable
  through 5 tiers up to 750,000. Amounts accept plain numbers, `10k` /
  `1.5m` shorthand, `half`, and `all`.
- **`.pickpocket`**: lift a chunk of another player's *pocket* gold
  only, never their bank. 20-minute cooldown per attacker, and a
  successful victim is shielded from further attempts for 10 minutes.
  Failing costs a small fine. Needs the Criminal trade (or Criminal
  skill 5+); odds and steal size both scale with that skill level.
- **`.smuggle`**: a solo crime sitting between pickpocket (petty,
  frequent) and `.rob` (huge, rare, one mistake wipes your
  reputation) -- a real payday on an hour cooldown, with a real chance
  the shipment gets seized and you pay a fine, but never the full
  reputation wipe a botched bank job carries.
- **`.surrender`**: the voluntary, paid version of that same wipe --
  anyone carrying infamy can turn themselves in for a flat 10,000 gold
  fine (confirm-gated) and walk out with reputation reset to 0, giving
  up the payout bonus that infamy was earning in exchange for a clean
  slate on their own terms.
- **`.beg`**: needs no job, no skill, no unlock -- just an 8-minute
  cooldown and a tiny, reliable trickle of gold. Costs a little fame
  if you have any (never pushes you into infamy), and does nothing at
  all if you're already neutral or infamous.
- **Job minigames**: every trade has its own quick, timed challenge,
  the real hands-on way to earn beyond `.work`. Running the command
  first shows a 🟢 Easy / 🟡 Medium / 🔴 Hard picker instead of just
  starting: Easy is always open, Medium unlocks at **level 15** in
  that trade's own skill, Hard at **level 35** -- so a higher skill
  level buys access to a longer, tougher, better-paying version of the
  *same* minigame. Hard runs more rounds (up to the trade's own tuned
  ceiling), tightens whichever timer that minigame uses by up to 38%,
  throws in extra decoys/tiles to track, and pays up to **×1.85** on
  top of the normal reward. All ten still share one underlying reward
  curve too: pay scales with skill level (low at level 1, up to 6x
  that at max level) and with how late-game the trade was to unlock in
  the first place (Alchemist pays far more per round than Farmer from
  square one), and a flawless run earns a 50% bonus on top of
  everything else. Every one has a genuine fail state, one mistake or
  a blown timer ends the attempt right there, and every one has an
  admin-only `*test` twin (e.g. `.harvesttest`) to try any difficulty
  with no job, cooldown, or real reward. Access follows the same rule
  everywhere: your current job always qualifies, or skill level 5+ in
  that trade even without holding the job.
  - 🌾 `.harvest` (Farmer): a crop is named among decoys, tap the right one
  - ⛏️ `.dig` (Miner): a direction flashes, follow the vein before it's lost
  - 🎣 `.fish` (Fisherman): pure reflex, reel in the instant it bites,
    too early or too late both fail the cast
  - 🪓 `.fell` (Lumberjack): the trunk leans one way, swing that side, fast
  - 🏹 `.hunt` (Hunter): the right prey breaks from decoys, loose an arrow
  - 🍞 `.bake` (Baker): press-your-luck, keep adding ingredients toward a
    hidden target or bank early, one scoop too many ruins the batch
  - 🍺 `.tend` (Brewer): the vat that's ready flashes among decoys, tap it
  - 🥾 `.stretch` (Tanner): a grid of near-identical tiles hides one weak
    spot that looks *just* subtly different, nothing is named for you,
    you have to actually spot it yourself before the seam splits
  - 🔍 `.facet` (Jeweler): a face-down grid of gems, flip two at a time,
    a match stays revealed and banks progress, a mismatched pair
    shatters the whole attempt right there
  - 🧪 `.brew` (Alchemist): watch a reagent sequence, then repeat it back
    in order; the longest cooldown, and the single biggest payout in the
    game since there's no risk of loss, only how far your memory takes you

## Commands

| Command | What it does |
| --- | --- |
| `.job` | Job board with a trade-picker menu |
| `.job choose <trade>` / `.job quit` / `.job info <trade>` | Manage your trade |
| `.work` | Labour for goods, coin, and XP (⚒️ Work Again button) |
| `.skills [member]` | Skill levels in every trade |
| `.resetskill <member> <skill>` | Admin-only: reset a townsfolk's level/XP in one trade (or Crafting) back to level 1 |
| `.deduct <member> <amount>` | Admin-only: remove gold from a townsfolk's pocket purse (can push it negative, e.g. as a debt) |
| `.inventory [member]` | A satchel with a category dropdown (All / Consumables / per-trade) |
| `.market` | Today's prices with ▲▼ trends, one category at a time via dropdown |
| `.sell [item] [amount]` | Sell goods (`.sell` alone sells everything) |
| `.shop` | Today's 18 goods, 9/page, with an Upgrade Tool button (confirm-gated) |
| `.buy` | Straight to the tool-upgrade confirm popup, skipping `.shop`'s item list |
| `.recipes [member]` / `.craft <recipe>` | Crafting: browse and craft, no trade required |
| `.use <item>` / `.buffs [member]` | Drink/eat a consumable for its buff, or check what's active |
| `.venture` | Risk a journey beyond the walls, no trade needed |
| `.balance` / `.daily` / `.pay` / `.profile` / `.leaderboard` | Gold |
| `.bank` / `.deposit [amount\|half\|all]` / `.withdraw [amount\|half\|all]` | Bank (`10k`/`1.5m` shorthand works) |
| `.pickpocket <member>` | Try to lift coin from their pocket |
| `.smuggle` | Move contraband for a real payday, real risk of losing it |
| `.surrender` | Turn yourself in, pay a 10,000 gold fine, wipe your infamy to 0 (confirm-gated) |
| `.beg` | A tiny, reliable trickle of gold, no job or skill needed |
| `.harvest` / `.dig` / `.fish` / `.fell` / `.hunt` / `.bake` / `.tend` / `.stretch` / `.facet` / `.brew` | Job minigames (current job, or lvl 5+ in it) |
| `.harvesttest` / `.digtest` / `.fishtest` / `.felltest` / `.hunttest` / `.baketest` / `.tendtest` / `.stretchtest` / `.facettest` / `.brewtest [level]` | Admin-only: try any minigame with no job/cooldown/rewards |
| `.cd [member]` / `.cooldown` | Every cooldown someone is currently carrying, at a glance |
| `.help` / `.about` | Guidance |

## Architecture (how to expand it)

```
bot.py               entry point, prefix + intents, error handling, sync
econ/
  formulas.py        EVERY tunable number & curve, balance the game here
  database.py        SQLite/Postgres with versioned migrations (append to
                     MIGRATIONS to evolve the schema safely)
  captcha.py         anti-bot letter-challenge state
  buffs.py           reads active_buffs and turns them into ready-to-use
                     cooldown/XP/gold multipliers for .work/.craft/etc.
  data/
    items.py         item registry (name, emoji, value, rarity)
    jobs.py          job registry (yields, cooldown, unlock, flavour)
    tools.py         tool ladders per trade (names + prices)
    ventures.py      venture route registry (odds, rewards, flavour)
    bank.py          bank tier capacities and upgrade costs
    minigames.py     per-job minigame content (options, flavour, timing)
    recipes.py       crafting recipe registry (ingredients, output, unlock)
    consumables.py   which items are usable, their buff + duration, and
                     the work-drop / brew-potion pool odds
    store.py         .shop's stock pool + markup (rare-goods pool
                     derived from items.py + jobs.py at import)
ui/
  panels.py          Components V2 medieval panel builder (fluent API)
cogs/
  jobs.py            job board, work engine, skills
  market.py          inventory, market, sell, the shop (goods + tool
                     upgrade)
  economy.py         balance, daily, pay, profile, leaderboards, bank
  venture.py         the .venture minigame
  crime.py           pickpocketing, smuggling
  brew.py            the .brew cauldron memory minigame
  minigames.py       the other 9 per-job minigames (harvest/dig/fish/
                     fell/hunt/bake/tend/stretch/facet) + their *test
                     admin twins
  craft.py           .recipes / .craft, the standalone Crafting skill
  consumables.py     .use / .buffs
  info.py            help, about
```

- **Add an item**: one line in `econ/data/items.py`.
- **Add a trade**: an entry in `jobs.py` + a tool ladder in `tools.py` -
  the job board, work, market, shop, and autocomplete all pick it up.
  Registries self-validate at import time.
- **Rebalance**: everything from XP pacing to market volatility is a named
  constant or pure function in `econ/formulas.py`.
- **New features**: the `stats` table already tracks lifetime counters
  (works, goods gathered/sold, gold flows), ready for achievements,
  quests, or taxes. Add tables via a new entry in `MIGRATIONS`.

## Setup

1. Create an application at the
   [Discord Developer Portal](https://discord.com/developers/applications),
   add a **Bot**, copy its token, and enable the **Message Content** intent
   (Bot → Privileged Gateway Intents), needed for `.` prefix commands.
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

## Deploying on Railway

The repo ships with `railway.json`, a `Procfile`, and `.python-version`,
so Railway needs no extra configuration:

1. Go to [railway.app](https://railway.app) → **New Project** →
   **Deploy from GitHub repo** → pick this repo (choose the branch you
   want under the service's *Settings → Source* if it isn't the default).
2. **Add persistent storage:** in the project, tap **+ Create →
   Database → Add PostgreSQL**. This keeps the economy safe across
   deploys; without it, SQLite lives on the container filesystem and is
   wiped on every redeploy.
3. In the bot service's **Variables** tab add:
   - `DISCORD_TOKEN`: your bot token
   - `GUILD_ID`: your server ID (instant slash-command sync)
   - `DATABASE_URL`: use *Add Variable Reference* and pick the
     Postgres service's `DATABASE_URL`
4. Deploy. The logs should end with
   `Logged in as <your bot>` and `Synced N commands to guild …`.

The free trial credit is enough to test; after that a small always-on
worker like this costs roughly $5/month.
