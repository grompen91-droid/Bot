"""Venture path registry. Add a route here and `.venture` picks it up.

success = win chance (0-1)
reward  = (min, max) gold on success, before rank/streak multipliers
loss    = (min, max) gold lost on failure (0, 0) for a safe miss
"""

VENTURE_PATHS = {
    "road": {
        "name": "Old Trade Road", "emoji": "🌾", "risk": "Low risk",
        "success": 0.90, "reward": (400, 900), "loss": (0, 120),
        "success_flavour": [
            "A merchant caravan pays well for your escort.",
            "You find a coin purse dropped along the roadside.",
            "A grateful traveller rewards you for the company.",
        ],
        "fail_flavour": [
            "Bandits rough you up and lift a few coins before fleeing.",
            "A wrong turn costs you half a day and some coin in tolls.",
        ],
    },
    "forest": {
        "name": "Shadowed Forest", "emoji": "🌲", "risk": "Medium risk",
        "success": 0.68, "reward": (950, 2_100), "loss": (160, 400),
        "success_flavour": [
            "You stumble upon an abandoned smuggler's cache.",
            "A woodland shrine rewards your courage with old coin.",
            "You track down a fleeing thief and reclaim his loot.",
        ],
        "fail_flavour": [
            "Wolves chase you out empty-handed and lighter of purse.",
            "You're lost for hours and robbed by highwaymen.",
        ],
    },
    "ruins": {
        "name": "Ancient Ruins", "emoji": "🏚️", "risk": "High risk",
        "success": 0.45, "reward": (2_200, 4_800), "loss": (320, 720),
        "success_flavour": [
            "Beneath collapsed stone you find a forgotten hoard.",
            "An ancient vault finally yields to your persistence.",
            "You strike a fair split with a wandering relic-hunter.",
        ],
        "fail_flavour": [
            "A passage collapses behind you, you flee with nothing.",
            "Restless spirits chase you out, coin lost along the way.",
        ],
    },
}
