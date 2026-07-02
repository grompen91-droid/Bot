"""Per-job minigame configuration: what each trade's minigame is
called, the flavour text, and the round-count/timing knobs. Reward and
round-count math lives in formulas.py (roll_minigame_reward,
minigame_length, minigame_cooldown); this file is content, the same
split as jobs.py (yields) vs formulas.py (yield math).

kind:
    "match"     bot names a target among a few decoys, tap the right
                one before the timer runs out (harvest, dig, fell,
                hunt, tend)
    "reflex"    wait for the bite, then reel before the window closes;
                too early or too late both fail the whole cast (fish)
    "pressluck" keep adding ingredients toward a hidden target; one
                too many ruins the batch outright, or bank early for a
                smaller, safer reward (bake)
"""

MINIGAMES = {
    "farmer": {
        "command": "harvest", "job_name": "Farmer", "title": "🌾 The Harvest",
        "kind": "match",
        "options": {
            "wheat": "🌾", "carrot": "🥕", "apple": "🍎",
            "pumpkin": "🎃", "berry": "🫐", "cabbage": "🥬",
        },
        "decoys": 3, "round_timeout": 7,
        "min_len": 4, "max_len": 10, "level_per_step": 12,
        "prompt": "is ripe, pick it before it spoils!",
        "fail_text": "You reach for the wrong row and trample the seedlings.",
        "success_text": "Every basket filled before the sun set.",
    },
    "miner": {
        "command": "dig", "job_name": "Miner", "title": "⛏️ The Deep Vein",
        "kind": "match",
        "options": {"north": "⬆️", "south": "⬇️", "east": "➡️", "west": "⬅️"},
        "decoys": 3, "round_timeout": 6,
        "min_len": 5, "max_len": 12, "level_per_step": 10,
        "prompt": "the vein pulls that way, follow it!",
        "fail_text": "Your pick strikes solid rock, the vein is lost.",
        "success_text": "You break through into a glittering seam.",
    },
    "lumberjack": {
        "command": "fell", "job_name": "Lumberjack", "title": "🪓 The Felling",
        "kind": "match",
        "options": {"left": "⬅️", "right": "➡️"},
        "decoys": 1, "round_timeout": 5,
        "min_len": 5, "max_len": 14, "level_per_step": 8,
        "prompt": "the trunk leans, swing that side!",
        "fail_text": "You swing wide and the axe bites into empty air.",
        "success_text": "The great tree finally groans and falls.",
    },
    "hunter": {
        "command": "hunt", "job_name": "Hunter", "title": "🏹 The Chase",
        "kind": "match",
        "options": {
            "rabbit": "🐇", "boar": "🐗", "stag": "🦌",
            "fox": "🦊", "wolf": "🐺",
        },
        "decoys": 3, "round_timeout": 6,
        "min_len": 4, "max_len": 10, "level_per_step": 12,
        "prompt": "breaks from the treeline, loose your arrow!",
        "fail_text": "You loose an arrow at the wrong shape in the brush.",
        "success_text": "A clean shot, the hunt is yours.",
    },
    "brewer": {
        "command": "tend", "job_name": "Brewer", "title": "🍺 The Cellar Vats",
        "kind": "match",
        "options": {"oak": "🛢️", "clay": "🫙", "iron": "🪣", "stone": "🪨"},
        "decoys": 3, "round_timeout": 6,
        "min_len": 4, "max_len": 10, "level_per_step": 12,
        "prompt": "is ready to tap, quick, before it spoils!",
        "fail_text": "You tap the wrong vat and sour ale floods the floor.",
        "success_text": "Every barrel tapped at its perfect moment.",
    },
    "fisherman": {
        "command": "fish", "job_name": "Fisherman", "title": "🎣 The Bite",
        "kind": "reflex",
        "min_len": 3, "max_len": 8, "level_per_step": 14,
        "wait_min": 1.5, "wait_max": 3.5, "reel_window": 2.5,
        "fail_early_text": "You yank the line before anything's there. It swims off.",
        "fail_late_text": "Too slow, the fish spits the hook and vanishes.",
        "fail_text": "The moment slips away.",
        "success_text": "A fine catch, reeled in clean.",
    },
    "baker": {
        "command": "bake", "job_name": "Baker", "title": "🍞 The Batch",
        "kind": "pressluck",
        "min_len": 4, "max_len": 12, "level_per_step": 9,
        "step_timeout": 8,
        "fail_text": "One scoop too many, the batch is ruined.",
        "success_text": "A perfect batch, risen just right.",
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
        "options": {
            "north": "⬆️", "south": "⬇️", "east": "➡️", "west": "⬅️", "vault": "🔓",
        },
        "decoys": 3, "round_timeout": 5,
        "min_len": 5, "max_len": 10, "level_per_step": 10,
        "prompt": "the guard patrol shifts that way, move now!",
        "fail_text": "A guard turns and spots you mid-step. The alarm wails.",
        "success_text": "The vault door swings open. You're rich, and utterly infamous.",
    },
}
