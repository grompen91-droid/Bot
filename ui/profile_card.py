"""Renders `.profile` as a PNG card via Pillow -- avatar, coin count,
best trade, and leaderboard standing, styled in whatever cosmetic
theme (see econ/data/themes.py) the player has equipped.

Text uses Pillow's own bundled default font (ImageFont.load_default),
not a system font path or an emoji font -- the bot's deployment host
isn't guaranteed to have any particular font package installed, and
this one ships inside Pillow itself, so the card renders identically
everywhere. That does mean no colour emoji in the image; stats are
plain typographic labels instead.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

CARD_W, CARD_H = 1000, 400
PAD = 36
AVATAR_SIZE = 200
ACCENT_BAR_W = 10
CORNER_RADIUS = 28
PILL_RADIUS = 16
PILL_GAP = 18

BG_BASE = (17, 17, 24)          # near-black card background
TEXT_PRIMARY = (240, 240, 245)
TEXT_DIM = (165, 165, 178)
PILL_BG = (28, 28, 38)
MIN_TEXT_LUMINANCE = 0.45       # floor so a dark theme's accent stays legible as text


@dataclass
class ProfileCardData:
    display_name: str
    avatar_bytes: bytes | None
    accent_rgb: tuple[int, int, int]
    rank_title: str
    flair: str | None
    pocket_gold: int
    bank_gold: int
    best_trade_label: str      # e.g. "Miner - Level 32" or "No trade yet"
    gold_rank: int
    skill_rank: int


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius, fill=255)
    return mask


def _circle_mask(diameter: int) -> Image.Image:
    mask = Image.new("L", (diameter, diameter), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter - 1, diameter - 1), fill=255)
    return mask


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (c / 255 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _readable(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """The true accent colour is used for the background glow and the
    avatar ring, where a dark theme like Obsidian Crown is the whole
    point. But that same colour used as TEXT on this card's near-black
    background would be unreadable, so anything drawn as text or a
    pill outline goes through this: lighten towards white just enough
    to clear a minimum contrast floor, leaving bright themes untouched."""
    result = rgb
    while _luminance(result) < MIN_TEXT_LUMINANCE:
        result = _lerp(result, (255, 255, 255), 0.12)
    return result


def _background(accent: tuple[int, int, int]) -> Image.Image:
    """A dark card with a soft diagonal glow of the accent colour
    bleeding in from the top-left, behind the avatar."""
    bg = Image.new("RGB", (CARD_W, CARD_H), BG_BASE)
    glow_colour = _lerp(BG_BASE, accent, 0.35)
    glow = Image.new("RGB", (CARD_W, CARD_H), BG_BASE)
    draw = ImageDraw.Draw(glow)
    cx, cy, max_r = PAD + AVATAR_SIZE // 2, CARD_H // 2 - 10, CARD_W // 2
    for r in range(max_r, 0, -6):
        t = 1 - (r / max_r)
        colour = _lerp(BG_BASE, glow_colour, t ** 2)
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=colour)
    return glow


def _draw_text(
    draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
    size: int, colour: tuple[int, int, int], *, bold: bool = False,
) -> tuple[int, int]:
    """Draws text and returns its (width, height). `bold` fakes weight
    with a thin stroke, since the bundled default font has no bold cut."""
    font = _font(size)
    kwargs = {"stroke_width": max(1, size // 22)} if bold else {}
    draw.text(xy, text, font=font, fill=colour, **kwargs)
    bbox = draw.textbbox(xy, text, font=font, **kwargs)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _fit_value(
    draw: ImageDraw.ImageDraw, value: str, max_w: int
) -> tuple[str, ImageFont.FreeTypeFont]:
    """Shrinks the value font a step, then truncates with an ellipsis,
    until it fits the pill -- a long trade name ("Reinforced Bowyer")
    must never spill past the pill's edge or into the next one."""
    for size in (30, 26, 22, 19):
        font = _font(size)
        if draw.textlength(value, font=font) <= max_w:
            return value, font
    font = _font(19)
    text = value
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return (text + "…" if text != value else value), font


def _stat_pill(
    canvas: Image.Image, xy: tuple[int, int], size: tuple[int, int],
    label: str, value: str, accent: tuple[int, int, int],
) -> None:
    pill = Image.new("RGB", size, PILL_BG)
    pill.putalpha(_rounded_mask(size, PILL_RADIUS))
    canvas.paste(pill, xy, pill)
    draw = ImageDraw.Draw(canvas)
    x, y = xy
    draw.rounded_rectangle(
        (x, y, x + size[0] - 1, y + size[1] - 1), PILL_RADIUS, outline=_readable(accent), width=2
    )
    draw.text((x + 18, y + 16), label.upper(), font=_font(17), fill=TEXT_DIM)
    text, value_font = _fit_value(draw, value, size[0] - 36)
    draw.text((x + 18, y + 44), text, font=value_font, fill=TEXT_PRIMARY, stroke_width=1)


def render_profile_card(data: ProfileCardData) -> io.BytesIO:
    canvas = _background(data.accent_rgb).convert("RGB")
    draw = ImageDraw.Draw(canvas)

    # accent flag down the left edge, matching the game's usual Panel look
    draw.rectangle((0, 0, ACCENT_BAR_W, CARD_H), fill=data.accent_rgb)

    # outer rounded-corner frame
    frame_mask = _rounded_mask((CARD_W, CARD_H), CORNER_RADIUS)
    framed = Image.new("RGB", (CARD_W, CARD_H), BG_BASE)
    framed.paste(canvas, (0, 0))
    framed.putalpha(frame_mask)
    canvas = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    canvas.paste(framed, (0, 0), framed)
    draw = ImageDraw.Draw(canvas)

    # avatar, circular with an accent ring
    ax, ay = PAD + 12, PAD
    ring_pad = 6
    ring = Image.new(
        "RGBA", (AVATAR_SIZE + ring_pad * 2, AVATAR_SIZE + ring_pad * 2), (0, 0, 0, 0)
    )
    ImageDraw.Draw(ring).ellipse(
        (0, 0, ring.width - 1, ring.height - 1), fill=(*_readable(data.accent_rgb), 255)
    )
    canvas.paste(ring, (ax - ring_pad, ay - ring_pad), ring)

    if data.avatar_bytes:
        try:
            avatar = Image.open(io.BytesIO(data.avatar_bytes)).convert("RGBA")
        except Exception:
            avatar = None
    else:
        avatar = None
    if avatar is None:
        avatar = Image.new("RGBA", (AVATAR_SIZE, AVATAR_SIZE), (*data.accent_rgb, 255))
    avatar = avatar.resize((AVATAR_SIZE, AVATAR_SIZE))
    avatar.putalpha(_circle_mask(AVATAR_SIZE))
    canvas.paste(avatar, (ax, ay), avatar)

    # name / rank / flair, to the right of the avatar
    text_x = ax + AVATAR_SIZE + 40
    text_y = PAD - 4
    name = data.display_name if len(data.display_name) <= 22 else data.display_name[:21] + "…"
    _draw_text(draw, (text_x, text_y), name, 46, TEXT_PRIMARY, bold=True)
    text_y += 58
    _draw_text(draw, (text_x, text_y), data.rank_title, 26, _readable(data.accent_rgb), bold=True)
    text_y += 40
    if data.flair:
        _draw_text(draw, (text_x, text_y), data.flair, 20, TEXT_DIM)

    # stat pills along the bottom. Best Trade gets a bigger share of the
    # row than the others -- "Miner Lv 40" runs noticeably longer than
    # a rank number ever will, and the level is the part that matters,
    # not something to truncate away.
    pill_y = PAD + AVATAR_SIZE + 24
    pill_h = CARD_H - pill_y - PAD
    weights = [1, 2, 1, 1]
    unit_w = (CARD_W - PAD * 2 - PILL_GAP * (len(weights) - 1)) / sum(weights)
    total_gold = data.pocket_gold + data.bank_gold
    stats = [
        ("Gold", f"{total_gold:,}"),
        ("Best Trade", data.best_trade_label),
        ("Wealth Rank", f"#{data.gold_rank}"),
        ("Skill Rank", f"#{data.skill_rank}"),
    ]
    x = PAD
    for (label, value), weight in zip(stats, weights):
        pill_w = round(unit_w * weight)
        _stat_pill(canvas, (x, pill_y), (pill_w, pill_h), label, value, data.accent_rgb)
        x += pill_w + PILL_GAP

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf
