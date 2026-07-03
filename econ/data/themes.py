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
    "crimson_seal": {
        "name": "Crimson Seal", "emoji": "🩸", "layout": "dashboard",
        "accent": discord.Colour(0xB4232F),
        "flair": "bears the Crimson Seal of the town's gratitude",
        "description": "A deep red dashboard card, level & rank front and centre.",
    },
    "azure_crest": {
        "name": "Azure Crest", "emoji": "🔷", "layout": "ticket",
        "accent": discord.Colour(0x2E86DE),
        "flair": "flies the Azure Crest of a trusted friend of the crown",
        "description": "A vivid blue portrait-style ID card.",
    },
    "emerald_veil": {
        "name": "Emerald Veil", "emoji": "🌿", "layout": "scroll",
        "accent": discord.Colour(0x1FA97C),
        "flair": "wrapped in the Emerald Veil of the wildwood",
        "description": "A rich green scroll, avatar set into a wide spine.",
    },
    "obsidian_crown": {
        "name": "Obsidian Crown", "emoji": "👑", "layout": "dashboard",
        "accent": discord.Colour(0x1A1A2E),
        "flair": "crowned in Obsidian, a legend of the town",
        "description": "Near-black dashboard card, unmistakably rare.",
    },
    "starlight_mantle": {
        "name": "Starlight Mantle", "emoji": "✨", "layout": "ticket",
        "accent": discord.Colour(0xB8A9E0),
        "flair": "wears the Starlight Mantle, blessed by fortune",
        "description": "A pale lavender portrait-style ID card.",
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
