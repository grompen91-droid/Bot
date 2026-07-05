"""Per-building `.gather` minigame configuration, plus `.scavenge`'s
own config -- the active-play counterparts to a production building's
passive trickle (`.collect`) and to `.work`'s rare material-drop
chance, respectively. Same content/math split as econ/data/minigames.py:
this file is flavour and round-shape, econ/formulas.py's "the town"
section owns the reward math (gather_reward, scavenge_reward, ...).

Every production building used to share one identical mechanic ("Read
the Seam": guess which material continues a hidden, unlabelled
sequence -- undoable without memorising an arbitrary internal list
order). Each building now gets its OWN mechanic, no two buildings
alike: five reuse the proven kinds cogs/minigames.py built out for the
job minigames (see that file's own kind docstring), re-themed and
paying out a construction material instead of gold/XP, and three are
unique to the town (implemented in cogs/town.py's Gather*Session
classes):

kind:
    "match"     bot names a target among a few decoys, tap the right
                one before the timer runs out (sawmill)
    "spotdiff"  a grid of near-identical tiles hides one that looks
                subtly different, spot it yourself (quarry, and
                .scavenge itself)
    "pressluck" keep adding loads toward a hidden limit; one too many
                ruins the attempt, or bank early for less (brickworks)
    "reflex"    wait for the right instant, then act before the window
                closes; too early or late both fail it (foundry)
    "pairs"     a face-down grid, flip two at a time to find matches
                (herb_garden)
    "sequence"  a pattern flashes by one symbol at a time; repeat it
                back from memory, in order (weavers_yard)
    "count"     a pallet of mixed tiles is laid out; tally how many of
                the named one are in it and tap the right number
                before time runs out (masons_workshop)
    "verify"    items cross the bench one at a time under a claimed
                label; call each Genuine or Fake, one wrong call ends
                it (gem_cutters_den)

`how_to` is the one or two sentences the difficulty picker shows before
an attempt starts -- the fix for the old mechanic's "very unclear what
to do": every kind now says exactly what a round wants from you.

success_text/fail_text (and the foundry's early/late pair, the
brickworks' empty-kiln line) hold a LIST of hand-written variants; one
is picked at random per run (econ/data/minigames.py's pick_flavor), so
grinding the same building doesn't read like the same form letter.
"""

GATHER_MINIGAMES = {
    "quarry": {
        "kind": "spotdiff", "title": "🪨 Strike the Vein",
        "how_to": "A grid of stone tiles hides one soft spot that looks just a little "
                   "different. Spot it and tap it before time runs out.",
        "common_emoji": "🪨", "odd_emoji": "⛏️",
        "grid_size": 9, "round_timeout": 7,
        "fail_header": "The Rock Holds",
        "fail_text": [
            "You strike solid stone and the vein slips away, unbroken.",
            "The pick rings off bedrock and the shock numbs your arms.",
            "Wrong spot. The face shrugs off the blow and gives you nothing.",
        ],
        "success_text": [
            "Every soft spot found, and the whole face comes free in one clean pull.",
            "The stone splits along the seam like it wanted to come loose.",
            "Clean blocks, square edges, barely a chip wasted.",
        ],
    },
    "sawmill": {
        "kind": "match", "title": "🪵 Mark the Grain",
        "how_to": "The bot calls out which ring to mark -- tap the matching ring "
                   "among the decoys before the saw moves past it.",
        "options": {"heartwood": "🔴", "sapwood": "🟡", "burl": "🟤", "knot": "⚫"},
        "decoys": 2, "round_timeout": 6,
        "prompt": "is ready to buck, mark it before the saw moves on!",
        "fail_header": "The Saw Moves On",
        "fail_text": [
            "You mark the wrong ring and the log's already past the blade.",
            "The chalk line lands a hand's width off, and the cut is firewood now.",
            "You hesitate, the blade doesn't. That plank's ruined.",
        ],
        "success_text": [
            "Every length marked true, clean planks stacked and ready.",
            "The saw sings through mark after perfect mark.",
            "Not a board wasted, the stack grows straight and true.",
        ],
    },
    "brickworks": {
        "kind": "pressluck", "title": "🧱 Stoke the Kiln",
        "how_to": "Shovel fuel into the kiln, one load at a time. Stop whenever you "
                   "like to bank it safely, but one shovel too many cracks the batch.",
        "step_timeout": 7,
        "unit_label": "shovelful", "add_label": "Shovel In", "add_emoji": "🔥",
        "stop_label": "Seal the Kiln", "stop_emoji": "🧱",
        "hint_empty": "The kiln sits cold. Start shovelling in fuel.",
        "hint_default": "Still lukewarm, needs more fuel.",
        "hint_mid": "The coals are catching nicely.",
        "hint_near": "The kiln's roaring now, almost too hot...",
        "fail_header": "The Kiln Cracks",
        "fail_text": [
            "One shovelful too many and the whole batch cracks in the heat.",
            "The kiln howls, then splits down the mortar line. Too hot, too fast.",
            "You hear the first brick pop and know the whole firing's gone.",
        ],
        "empty_fail_text": [
            "You seal a cold, empty kiln. There's nothing to fire.",
            "A sealed kiln with no fuel in it. The yard crew tries not to laugh.",
        ],
        "success_text": [
            "Fired to the perfect hardness, not a single brick lost.",
            "The kiln cools to reveal row after row of flawless brick.",
            "Struck at exactly the right heat, the batch rings like pottery.",
        ],
    },
    "foundry": {
        "kind": "reflex", "title": "⛏️ Strike the Heat",
        "how_to": "Watch the forge. The instant the metal hits its perfect glow, "
                   "strike -- too early or too late and the shape is lost.",
        "wait_min": 1.5, "wait_max": 3.5, "reel_window": 2.2,
        "waiting_text": "🔥 *The forge glows dull. Watch close...*",
        "ready_text": "# 🔥 STRIKE NOW!",
        "action_label": "Strike!", "action_emoji": "🔨",
        "watch_label": "Watch", "watch_emoji": "🔨",
        "fail_early_text": [
            "You swing before the metal's ready and the hammer just glances off.",
            "Too eager. The hammer bounces and the half-cold metal barely dents.",
        ],
        "fail_late_text": [
            "Too slow, the ingot cools and the shape is lost.",
            "The glow fades under your raised hammer. Back into the fire it goes.",
        ],
        "fail_header": "The Ingot Cools",
        "success_text": [
            "Struck at the perfect glow, a flawless ingot.",
            "One blow at the exact right heat, the metal takes its shape and holds it.",
            "Sparks fly, the shape sets true. The foundry master nods once.",
        ],
    },
    "herb_garden": {
        "kind": "pairs", "title": "🌿 Match the Cuttings",
        "how_to": "A row of cuttings lies face-down. Flip two at a time to find a "
                   "matching pair -- a mismatch ends the harvest on the spot.",
        "gems": {"root": "🌱", "petal": "🌼", "leaf": "🍃", "thorn": "🌵", "bloom": "🌺", "frost": "❄️"},
        "hidden_emoji": "🟩", "round_timeout": 13,
        "fail_header": "Wilted",
        "fail_text": [
            "A mismatched cutting bruises and the whole bundle wilts.",
            "Wrong pair. By the time you notice, the leaves have already curled.",
            "The two cuttings were never a match, and now neither will take root.",
        ],
        "success_text": [
            "Every cutting paired and bundled before it could wilt.",
            "The beds are planted in perfect matched rows, green to the fence line.",
            "Each pair takes root within the hour. A gardener's day to remember.",
        ],
    },
    "weavers_yard": {
        "kind": "sequence", "title": "🧵 Memorize the Pattern",
        "how_to": "The master weaver's pattern flashes by one thread at a time. "
                   "Watch closely, then weave it back in the exact same order -- "
                   "one thread out of place ruins the bolt.",
        "options": {"crimson": "🟥", "gold": "🟨", "indigo": "🟦", "moss": "🟩", "plum": "🟪"},
        "reveal_delay": 1.1, "answer_timeout": 18,
        "fail_header": "The Pattern's Lost",
        "fail_text": [
            "You thread the wrong colour and the pattern unravels before your eyes.",
            "One thread out of order, and the shuttle carries the mistake through the whole bolt.",
            "The motif slips from memory halfway across the loom.",
        ],
        "success_text": [
            "Every thread in order, the pattern flows flawless across the bolt.",
            "You weave the motif back from memory without a single slip.",
            "The finished cloth matches the master's pattern thread for thread.",
        ],
    },
    "masons_workshop": {
        "kind": "count", "title": "🏺 Tally the Pallet",
        "how_to": "A pallet of mixed stone rolls in. Count how many of the named "
                   "block are on it and tap the right tally before the cart moves "
                   "on -- one bad count ends the shift.",
        "emojis": {"brick": "🧱", "block": "🪨", "urn": "🏺", "slab": "⬜"},
        "grid_size": 15, "round_timeout": 10,
        "fail_header": "The Count Is Off",
        "fail_text": [
            "Your tally comes up wrong and the wall runs a course short.",
            "You call the count too fast, and the mismeasured pallet jams the whole yard.",
            "Two short. The foreman recounts it in front of everyone.",
        ],
        "success_text": [
            "Every pallet counted true, the wall rises without a single gap.",
            "Your tallies match the ledger to the last block.",
            "Counted, stacked, and mortared. The workshop runs on your numbers today.",
        ],
    },
    "gem_cutters_den": {
        "kind": "verify", "title": "💎 Appraise the Stones",
        "how_to": "Stones cross your bench one at a time, each under a merchant's "
                   "label. Look at the stone, judge whether the label is honest, and "
                   "call it Genuine or Fake -- one bad appraisal ends the sitting.",
        "gems": {
            "ruby": "🔴", "sapphire": "🔵", "emerald": "🟢",
            "topaz": "🟡", "amethyst": "🟣", "pearl": "⚪",
        },
        "round_timeout": 6,
        "fail_header": "A Bad Appraisal",
        "fail_text": [
            "You vouch for a fake, and word gets around the den before sundown.",
            "The 'ruby' you passed turns out to be dyed glass. Your eye is doubted for weeks.",
            "You wave a forgery through, and the buyer comes back shouting.",
        ],
        "success_text": [
            "Every stone called true, the merchants pay full price without a murmur.",
            "Genuine from glass at a glance. Your word is gospel in the den today.",
            "Not one fake slips past your loupe.",
        ],
    },
}

# `.scavenge`'s own config: one grid-scan minigame (see "spotdiff" above),
# not tied to any one production building -- it's the active-play route
# to the "universal" group materials Town Hall's own ladder and every
# utility/bonus building spend (see formulas.py's .scavenge section for
# why that group needed one).
SCAVENGE_MINIGAME = {
    "kind": "spotdiff", "title": "🧰 Sort the Storeroom",
    "how_to": "A grid of crates hides one that's mislabeled and looks just a little "
              "different. Spot it and tap it before the quartermaster notices.",
    "common_emoji": "📦", "odd_emoji": "🗃️",
    "grid_size": 9, "round_timeout": 7,
    "fail_header": "Wrong Crate",
    "fail_text": [
        "You crack open the wrong crate and the quartermaster comes running.",
        "The lid comes off a crate of someone's personal effects. Awkward questions follow.",
        "Sawdust and packing straw everywhere, and none of it what you were after.",
    ],
    "success_text": [
        "Every crate sorted and tagged, exactly what the town needs.",
        "The storeroom's never looked so orderly. The quartermaster is almost suspicious.",
        "Found it, tagged it, shelved the rest. Textbook work.",
    ],
}
