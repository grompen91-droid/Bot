"""Per-job minigame configuration: what each trade's minigame is
called, the flavour text, and the round-count/timing knobs. Reward,
difficulty-tier, and cooldown math lives in formulas.py
(roll_minigame_reward, DIFFICULTIES/difficulty_length,
minigame_cooldown); this file is content, the same split as jobs.py
(yields) vs formulas.py (yield math).

min_len/max_len are no longer a level-scaling curve -- they're the
Easy (=min_len) and Hard (=max_len) bounds of the Easy/Medium/Hard
difficulty picker every command shows first (see formulas.DIFFICULTIES).

Flavour keys (success_text, fail_text, and the fisherman's early/late
pair) hold a LIST of hand-written variants, one picked at random per
run via pick_flavor() below, so back-to-back attempts don't read like
the same form letter. A plain string still works everywhere a list
does, for any one-off override a cog passes in.

kind:
    "match"     bot names a target among a few decoys, tap the right
                one before the timer runs out (harvest, dig, fell,
                hunt, tend)
    "reflex"    wait for the bite, then reel before the window closes;
                too early or too late both fail the whole cast (fish)
    "pressluck" keep adding ingredients toward a hidden target; one
                too many ruins the batch outright, or bank early for a
                smaller, safer reward (bake)
    "spotdiff"  a grid of near-identical tiles hides one that looks
                subtly different; no named target like "match", you
                have to actually spot it yourself before time's up
                (stretch)
    "pairs"     a face-down grid of gems, flip two at a time; a match
                stays revealed and banks progress, a mismatch ends the
                attempt on the spot (facet)
"""

import random


def pick_flavor(value) -> str:
    """One line from a flavour pool -- or the value itself when a cog
    passes a plain string override."""
    if isinstance(value, (list, tuple)):
        return random.choice(value)
    return value


MINIGAMES = {
    "farmer": {
        "command": "harvest", "job_name": "Farmer", "title": "🌾 The Harvest",
        "kind": "match",
        "options": {
            "wheat": "🌾", "carrot": "🥕", "apple": "🍎",
            "pumpkin": "🎃", "berry": "🫐", "cabbage": "🥬",
        },
        "decoys": 3, "round_timeout": 7,
        "min_len": 4, "max_len": 10,
        "prompt": "is ripe, pick it before it spoils!",
        "fail_text": [
            "You reach for the wrong row and trample the seedlings.",
            "A basket tips, and half the morning's picking rolls into the mud.",
            "You grab a green one by mistake and the foreman winces.",
        ],
        "success_text": [
            "Every basket filled before the sun set.",
            "Not a single crop left to spoil on the vine.",
            "The wagon creaks under the weight of a perfect picking.",
        ],
    },
    "miner": {
        "command": "dig", "job_name": "Miner", "title": "⛏️ The Deep Vein",
        "kind": "match",
        "options": {"north": "⬆️", "south": "⬇️", "east": "➡️", "west": "⬅️"},
        "decoys": 3, "round_timeout": 6,
        "min_len": 5, "max_len": 12,
        "prompt": "the vein pulls that way, follow it!",
        "fail_text": [
            "Your pick strikes solid rock, the vein is lost.",
            "Dust and rubble, nothing more. The seam pinched out behind you.",
            "The tunnel forks wrong and your lamp finds only dead stone.",
        ],
        "success_text": [
            "You break through into a glittering seam.",
            "The vein opens wide, ore enough to fill every cart you've got.",
            "Your pick rings true one last time and the wall comes away in sheets of ore.",
        ],
    },
    "lumberjack": {
        "command": "fell", "job_name": "Lumberjack", "title": "🪓 The Felling",
        "kind": "match",
        "options": {"left": "⬅️", "right": "➡️"},
        "decoys": 1, "round_timeout": 5,
        "min_len": 5, "max_len": 14,
        "prompt": "the trunk leans, swing that side!",
        "fail_text": [
            "You swing wide and the axe bites into empty air.",
            "The trunk kicks back the wrong way and you dive clear, axe abandoned.",
            "A bad cut, the tree twists on its stump and hangs up in its neighbour.",
        ],
        "success_text": [
            "The great tree finally groans and falls.",
            "It comes down exactly where you called it, to the inch.",
            "One last swing, a crack like thunder, and clear sky where the crown stood.",
        ],
    },
    "hunter": {
        "command": "hunt", "job_name": "Hunter", "title": "🏹 The Chase",
        "kind": "match",
        "options": {
            "rabbit": "🐇", "boar": "🐗", "stag": "🦌",
            "fox": "🦊", "wolf": "🐺",
        },
        "decoys": 3, "round_timeout": 6,
        "min_len": 4, "max_len": 10,
        "prompt": "breaks from the treeline, loose your arrow!",
        "fail_text": [
            "You loose an arrow at the wrong shape in the brush.",
            "The bowstring snaps taut a heartbeat late, and the woods go quiet.",
            "Your arrow thuds into a stump. Whatever it was, it's long gone.",
        ],
        "success_text": [
            "A clean shot, the hunt is yours.",
            "The quarry drops where it stood. Not a scrap will go to waste.",
            "You track it, wait it out, and take it with a single arrow.",
        ],
    },
    "brewer": {
        "command": "tend", "job_name": "Brewer", "title": "🍺 The Cellar Vats",
        "kind": "match",
        "options": {"oak": "🛢️", "clay": "🫙", "iron": "🪣", "stone": "🪨"},
        "decoys": 3, "round_timeout": 6,
        "min_len": 4, "max_len": 10,
        "prompt": "is ready to tap, quick, before it spoils!",
        "fail_text": [
            "You tap the wrong vat and sour ale floods the floor.",
            "The bung pops early and a week's brew hisses away to vinegar.",
            "Wrong vat, and the smell alone tells you it's ruined.",
        ],
        "success_text": [
            "Every barrel tapped at its perfect moment.",
            "The cellar rings with the sound of well-timed taps. Not a drop lost.",
            "Each vat caught at its peak, the landlord will pay double for this batch.",
        ],
    },
    "fisherman": {
        "command": "fish", "job_name": "Fisherman", "title": "🎣 The Bite",
        "kind": "reflex",
        "min_len": 3, "max_len": 8,
        "wait_min": 1.5, "wait_max": 3.5, "reel_window": 2.5,
        "fail_early_text": [
            "You yank the line before anything's there. It swims off.",
            "Too eager, the splash of your own line spooks everything for a mile.",
            "You strike at a ripple that was only the wind.",
        ],
        "fail_late_text": [
            "Too slow, the fish spits the hook and vanishes.",
            "The rod tip dips, then goes still. It took the bait and left the hook.",
            "You feel the weight a moment too late, and the line goes slack.",
        ],
        "fail_text": "The moment slips away.",
        "success_text": [
            "A fine catch, reeled in clean.",
            "The net comes up heavy. A good day on the water.",
            "You swing the last one aboard still fighting. The basket's full.",
        ],
    },
    "baker": {
        "command": "bake", "job_name": "Baker", "title": "🍞 The Batch",
        "kind": "pressluck",
        "min_len": 4, "max_len": 12,
        "step_timeout": 8,
        "fail_text": [
            "One scoop too many, the batch is ruined.",
            "The dough collapses under its own weight. Into the pig bucket it goes.",
            "Overworked and overloaded, it bakes into a brick even the crows refuse.",
        ],
        "success_text": [
            "A perfect batch, risen just right.",
            "Golden crust, soft crumb. The queue at the counter starts before it's cool.",
            "It comes out of the oven singing. This is the loaf people will ask for by name.",
        ],
    },
    "tanner": {
        "command": "stretch", "job_name": "Tanner", "title": "🥾 Stretch the Hide",
        "kind": "spotdiff",
        "common_emoji": "🟤", "odd_emoji": "🟫",
        "grid_size": 9, "round_timeout": 6,
        "min_len": 4, "max_len": 11,
        "fail_text": [
            "You press the wrong spot and the seam splits wide open.",
            "The hide tears along a flaw you never saw coming.",
            "One careless stretch and a week of curing rips right down the middle.",
        ],
        "success_text": [
            "Every weak spot caught and reinforced before it tore.",
            "The hide pulls drum-tight and flawless, ready for the finest boots in town.",
            "Not a blemish left. Leather like this sells itself.",
        ],
    },
    "jeweler": {
        "command": "facet", "job_name": "Jeweler", "title": "🔍 The Facet Match",
        "kind": "pairs",
        "gems": {
            "ruby": "🔴", "sapphire": "🔵", "emerald": "🟢", "topaz": "🟡",
            "amethyst": "🟣", "onyx": "⚫", "pearl": "⚪",
        },
        "hidden_emoji": "🔳", "round_timeout": 15,
        "min_len": 3, "max_len": 7,
        "fail_text": [
            "Wrong pair, the mismatched facets shatter under the loupe.",
            "The stones grind instead of seating, and a hairline crack races through both.",
            "A mismatch. The setting springs and scatters gems across the floor.",
        ],
        "success_text": [
            "Every facet paired and polished to a brilliant shine.",
            "The finished piece throws light across the whole workshop.",
            "Each stone finds its twin, the commission is worthy of a crown.",
        ],
    },
    # The Criminal trade's own minigame. Unlike the eight above, this one
    # requires an "are you sure?" confirmation before it starts (getting
    # caught is a real, painful cost, not just a wasted attempt), doesn't
    # grant or draw on fame, and pays out on the infamy scale instead --
    # see cogs/minigames.py's BaseMinigameSession._finish for the branch.
    # reward_tier_level overrides the usual "pay scales with how hard the
    # trade was to unlock" rule: Criminal itself unlocks free, but a bank
    # job is the single biggest score in the game, priced like the
    # hardest trade there is.
    "criminal": {
        "command": "rob", "job_name": "Criminal", "title": "🏦 The Bank Job",
        "kind": "match", "requires_confirm": True, "reward_tier_level": 50,
        "cooldown": 12 * 60 * 60,  # flat 12h, not the usual unlock-tier formula
        "options": {
            "north": "⬆️", "south": "⬇️", "east": "➡️", "west": "⬅️", "vault": "🔓",
        },
        "decoys": 3, "round_timeout": 5,
        "min_len": 5, "max_len": 10,
        "prompt": "the guard patrol shifts that way, move now!",
        "fail_text": [
            "A guard turns and spots you mid-step. The alarm wails.",
            "Your boot finds the one loose flagstone in the whole bank. Heads turn.",
            "A lantern swings your way at exactly the wrong moment.",
        ],
        "success_text": [
            "The vault door swings open. You're rich, and utterly infamous.",
            "You walk out the front door with the take, tipping your hat to the guards.",
            "By the time the alarm sounds, you and the gold are three streets away.",
        ],
    },
}
