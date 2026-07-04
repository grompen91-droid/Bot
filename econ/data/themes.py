"""Profile theme registry: purely cosmetic. A theme picks both
.profile card's accent colour AND its layout (see ui/profile_card.py)
-- equipping a different theme rearranges the card, not just
recolours it. No gold price, no gameplay effect. Everyone starts with
"parchment"; every other theme is unlocked only by an admin's
`.granttheme`, so they work as a reward (bug bounties, events,
whatever a mod wants to hand out) rather than something bought or
farmed.

`flair` is plain text, no emoji: it's only ever drawn onto the
.profile PNG, which uses Pillow's bundled default font -- no colour
emoji glyphs, so an emoji there would just render as a missing-glyph
box. `emoji` is for the emoji-native Components V2 `.theme` picker, a
separate, un-rendered-to-pixels list.
"""

import discord

DEFAULT_THEME = "parchment"

THEMES = {
    "parchment": {
        "name": "Parchment & Gold", "emoji": "📜", "layout": "banner",
        "accent": discord.Colour(0xC9A227),
        "flair": None,
        "description": "The town's everyday look. Everyone starts here.",
    },
    "bug_finder": {
        "name": "Bug Finder", "emoji": "🐛", "layout": "dashboard",
        "accent": discord.Colour(0x9FE2BF),
        "flair": "credited by the town for hunting down a genuine bug",
        "description": "Awarded for reporting a real bug. Admin-granted only.",
    },
}


def resolve_theme(query: str) -> str | None:
    """Fuzzy-match a typed theme name ('crimson', 'azure crest')."""
    q = query.strip().lower()
    key_form = q.replace(" ", "_")
    if key_form in THEMES:
        return key_form
    for key, t in THEMES.items():
        if t["name"].lower() == q:
            return key
    for key, t in THEMES.items():
        if t["name"].lower().startswith(q) or key.startswith(key_form):
            return key
    return None
