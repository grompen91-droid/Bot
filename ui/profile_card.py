"""Renders `.profile` as a PNG card via Pillow -- avatar, coin count,
best trade, and leaderboard standing. Each cosmetic theme (see
econ/data/themes.py) picks both a colour AND a structural layout, so
equipping a different theme doesn't just recolour the same card, it
rearranges it -- flat, solid colour blocks, no glow/gradient effects.

Text uses Pillow's own bundled default font (ImageFont.load_default),
not a system font path or an emoji font -- the bot's deployment host
isn't guaranteed to have either installed, and this one ships inside
Pillow itself, so the card renders identically everywhere. That does
mean no colour emoji in the image; stats are plain typographic labels
instead.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

TEXT_PRIMARY = (240, 240, 245)
TEXT_DIM = (185, 185, 196)
MIN_TEXT_LUMINANCE = 0.45   # floor so a dark theme's accent stays legible as text


@dataclass
class ProfileCardData:
    display_name: str
    avatar_bytes: bytes | None
    accent_rgb: tuple[int, int, int]
    layout: str                # which _LAYOUTS render function to use
    rank_title: str
    flair: str | None
    level: int                 # total skill level, summed across every trade
    pocket_gold: int
    bank_gold: int
    best_trade_label: str      # e.g. "Miner Lv 32" or "No trade yet"
    gold_rank: int
    skill_rank: int


# ── shared drawing helpers ───────────────────────────────────────────────

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


def _readable(rgb: tuple[int, int, int], *, floor: float = MIN_TEXT_LUMINANCE) -> tuple[int, int, int]:
    """A dark theme like Obsidian Crown is the whole point of its flat
    fill and ring -- but that same colour used as TEXT would be
    unreadable, so anything drawn as text or a thin outline goes
    through this: lighten towards white just enough to clear a minimum
    contrast floor, leaving already-bright themes untouched."""
    result = rgb
    while _luminance(result) < floor:
        result = _lerp(result, (255, 255, 255), 0.12)
    return result


def _darkable(rgb: tuple[int, int, int], *, ceiling: float = 0.8) -> tuple[int, int, int]:
    """The inverse of _readable, for a light theme's flat fill (e.g. a
    pale lavender) used as a big background wash -- darken towards
    black just enough that white text stays legible on top of it."""
    result = rgb
    while _luminance(result) > ceiling:
        result = _lerp(result, (0, 0, 0), 0.10)
    return result


def _draw_text(
    draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
    size: int, colour: tuple[int, int, int], *, bold: bool = False,
) -> None:
    """`bold` fakes weight with a thin stroke, since the bundled
    default font has no separate bold cut."""
    font = _font(size)
    kwargs = {"stroke_width": max(1, size // 22)} if bold else {}
    draw.text(xy, text, font=font, fill=colour, **kwargs)


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> str:
    if draw.textlength(text, font=font) <= max_w:
        return text
    trimmed = text
    while trimmed and draw.textlength(trimmed + "…", font=font) > max_w:
        trimmed = trimmed[:-1]
    return trimmed + "…" if trimmed != text else text


def _fit_value(
    draw: ImageDraw.ImageDraw, value: str, max_w: int
) -> tuple[str, ImageFont.FreeTypeFont]:
    """Shrinks the value font a step, then truncates with an ellipsis,
    until it fits -- a long trade name ("Reinforced Bowyer") must
    never spill past its box."""
    for size in (30, 26, 22, 19):
        font = _font(size)
        if draw.textlength(value, font=font) <= max_w:
            return value, font
    font = _font(19)
    return _ellipsize(draw, value, font, max_w), font


def _load_avatar(data: ProfileCardData, size: int, accent: tuple[int, int, int]) -> Image.Image:
    avatar = None
    if data.avatar_bytes:
        try:
            avatar = Image.open(io.BytesIO(data.avatar_bytes)).convert("RGBA")
        except Exception:
            avatar = None
    if avatar is None:
        avatar = Image.new("RGBA", (size, size), (*accent, 255))
    else:
        avatar = avatar.resize((size, size))
    avatar.putalpha(_circle_mask(size))
    return avatar


def _round_frame(canvas: Image.Image, radius: int, bg: tuple[int, int, int]) -> Image.Image:
    """Clips a flat RGB canvas to rounded corners, returning an RGBA
    image ready to compose further elements on top of."""
    framed = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.putalpha(_rounded_mask(canvas.size, radius))
    framed.paste(canvas_rgba, (0, 0), canvas_rgba)
    return framed


def _stat_box(
    canvas: Image.Image, xy: tuple[int, int], size: tuple[int, int],
    label: str, value: str, accent: tuple[int, int, int], box_bg: tuple[int, int, int],
    *, radius: int = 14,
) -> None:
    box = Image.new("RGB", size, box_bg)
    box.putalpha(_rounded_mask(size, radius))
    canvas.paste(box, xy, box)
    draw = ImageDraw.Draw(canvas)
    x, y = xy
    draw.rounded_rectangle(
        (x, y, x + size[0] - 1, y + size[1] - 1), radius, outline=_readable(accent), width=2
    )
    draw.text((x + 16, y + 12), label.upper(), font=_font(16), fill=TEXT_DIM)
    text, value_font = _fit_value(draw, value, size[0] - 32)
    draw.text((x + 16, y + 38), text, font=value_font, fill=TEXT_PRIMARY, stroke_width=1)


# ── layout: banner -- flat, minimal, avatar-left (the default look) ──────

def _layout_banner(data: ProfileCardData) -> Image.Image:
    w, h = 1000, 360
    pad, avatar_size = 36, 190
    bg_flat = _darkable(_lerp((16, 16, 22), data.accent_rgb, 0.16))

    canvas = Image.new("RGB", (w, h), bg_flat)
    canvas = _round_frame(canvas, 26, bg_flat)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 8, h), fill=data.accent_rgb)

    ax, ay = pad + 10, pad
    ring_pad = 6
    ring = Image.new("RGBA", (avatar_size + ring_pad * 2,) * 2, (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((0, 0, ring.width - 1, ring.height - 1), fill=(*_readable(data.accent_rgb), 255))
    canvas.paste(ring, (ax - ring_pad, ay - ring_pad), ring)
    avatar = _load_avatar(data, avatar_size, data.accent_rgb)
    canvas.paste(avatar, (ax, ay), avatar)

    tx, ty = ax + avatar_size + 40, pad - 2
    name = _ellipsize(draw, data.display_name, _font(44), w - tx - pad)
    _draw_text(draw, (tx, ty), name, 44, TEXT_PRIMARY, bold=True)
    ty += 56
    _draw_text(draw, (tx, ty), data.rank_title, 25, _readable(data.accent_rgb), bold=True)
    ty += 38
    if data.flair:
        _draw_text(draw, (tx, ty), data.flair, 19, TEXT_DIM)

    box_y = pad + avatar_size + 22
    box_h = h - box_y - pad
    weights = [1, 2, 1, 1]
    gap = 16
    unit_w = (w - pad * 2 - gap * (len(weights) - 1)) / sum(weights)
    total_gold = data.pocket_gold + data.bank_gold
    stats = [
        ("Gold", f"{total_gold:,}"),
        ("Best Trade", data.best_trade_label),
        ("Wealth Rank", f"#{data.gold_rank}"),
        ("Skill Rank", f"#{data.skill_rank}"),
    ]
    box_bg = _darkable(_lerp(bg_flat, (0, 0, 0), 0.35))
    x = pad
    for (label, value), weight in zip(stats, weights):
        bw = round(unit_w * weight)
        _stat_box(canvas, (x, box_y), (bw, box_h), label, value, data.accent_rgb, box_bg)
        x += bw + gap
    return canvas


# ── layout: dashboard -- header strip, centre LEVEL|RANK block, two ──────
# side columns of stat rows either side of a vertical divider (inspired
# by the reference "champion" rank card: trophy/level/rank up top, a
# hard divider down the middle, icon + value rows either side).

def _layout_dashboard(data: ProfileCardData) -> Image.Image:
    w = 1000
    pad, avatar_size = 34, 96
    bg_flat = _darkable(_lerp((14, 14, 20), data.accent_rgb, 0.22))
    border = _readable(data.accent_rgb)

    # Every block stacks top-to-bottom with its own clearance, height
    # computed from that instead of a guessed constant -- a long flair
    # string (varies per theme) must never collide with the badge below
    # it, and a long trade name must never overflow its row.
    ax, ay = pad, pad
    header_bottom = ay + avatar_size + 24
    badge_w, badge_h = 260, 84
    badge_top = header_bottom + 18
    badge_bottom = badge_top + badge_h
    body_top = badge_bottom + 18
    row_h, row_gap = 80, 16
    body_bottom = body_top + row_h * 2 + row_gap
    h = body_bottom + pad

    canvas = Image.new("RGB", (w, h), bg_flat)
    canvas = _round_frame(canvas, 22, bg_flat)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((0, 0, w - 1, h - 1), 22, outline=border, width=4)

    # header: avatar + name/trade/flair block
    ring_pad = 4
    ring = Image.new("RGBA", (avatar_size + ring_pad * 2,) * 2, (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((0, 0, ring.width - 1, ring.height - 1), fill=(*border, 255))
    canvas.paste(ring, (ax - ring_pad, ay - ring_pad), ring)
    avatar = _load_avatar(data, avatar_size, data.accent_rgb)
    canvas.paste(avatar, (ax, ay), avatar)

    tx = ax + avatar_size + 28
    name = _ellipsize(draw, data.display_name, _font(32), w - tx - pad)
    _draw_text(draw, (tx, ay - 4), name, 32, TEXT_PRIMARY, bold=True)
    _draw_text(draw, (tx, ay + 34), data.best_trade_label, 19, border, bold=True)
    if data.flair:
        flair = _ellipsize(draw, data.flair, _font(17), w - tx - pad)
        _draw_text(draw, (tx, ay + 62), flair, 17, TEXT_DIM)

    draw.line((pad, header_bottom, w - pad, header_bottom), fill=border, width=3)

    # centre LEVEL | RANK badge, entirely below the header (never
    # overlapping it, however long the header's text runs)
    bx, by = (w - badge_w) // 2, badge_top
    badge_bg = (12, 12, 16)
    draw.rounded_rectangle((bx, by, bx + badge_w, by + badge_h), 12, fill=badge_bg, outline=border, width=3)
    draw.line((bx + badge_w // 2, by + 6, bx + badge_w // 2, by + badge_h - 6), fill=border, width=2)
    _draw_text(draw, (bx + 24, by + 10), "LEVEL", 14, TEXT_DIM)
    draw.text((bx + 24, by + 30), str(data.level), font=_font(30), fill=TEXT_PRIMARY, stroke_width=1)
    _draw_text(draw, (bx + badge_w // 2 + 24, by + 10), "RANK", 14, TEXT_DIM)
    draw.text((bx + badge_w // 2 + 24, by + 30), f"#{data.skill_rank}", font=_font(30), fill=TEXT_PRIMARY, stroke_width=1)

    # vertical divider splitting the body into two stat columns
    mid_x = w // 2
    draw.line((mid_x, body_top, mid_x, body_bottom), fill=border, width=3)

    col_w = mid_x - pad * 2
    total_gold = data.pocket_gold + data.bank_gold
    left_rows = [("Gold", f"{total_gold:,}"), ("Wealth Rank", f"#{data.gold_rank}")]
    right_rows = [("Best Trade", data.best_trade_label), ("Rank Title", data.rank_title)]
    row_bg = _darkable(_lerp(bg_flat, (0, 0, 0), 0.3))
    y = body_top
    for label, value in left_rows:
        _stat_box(canvas, (pad, y), (col_w, row_h), label, value, data.accent_rgb, row_bg, radius=10)
        y += row_h + row_gap
    y = body_top
    for label, value in right_rows:
        _stat_box(canvas, (mid_x + pad, y), (col_w, row_h), label, value, data.accent_rgb, row_bg, radius=10)
        y += row_h + row_gap
    return canvas


# ── layout: ticket -- portrait ID card, avatar centred top, a 2x2 ────────
# stat grid below (a distinctly different silhouette from the other
# two, which are both landscape)

def _layout_ticket(data: ProfileCardData) -> Image.Image:
    w, h = 620, 620
    pad, avatar_size = 32, 168
    bg_flat = _darkable(_lerp((16, 16, 22), data.accent_rgb, 0.18))
    border = _readable(data.accent_rgb)

    canvas = Image.new("RGB", (w, h), bg_flat)
    canvas = _round_frame(canvas, 24, bg_flat)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((0, 0, w - 1, h - 1), 24, outline=border, width=4)

    cx = w // 2
    ay = pad
    ring_pad = 6
    ring = Image.new("RGBA", (avatar_size + ring_pad * 2,) * 2, (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((0, 0, ring.width - 1, ring.height - 1), fill=(*border, 255))
    canvas.paste(ring, (cx - ring.width // 2, ay - ring_pad), ring)
    avatar = _load_avatar(data, avatar_size, data.accent_rgb)
    canvas.paste(avatar, (cx - avatar_size // 2, ay), avatar)

    ty = ay + avatar_size + 22
    name = _ellipsize(draw, data.display_name, _font(34), w - pad * 2)
    name_w = draw.textlength(name, font=_font(34))
    _draw_text(draw, (cx - int(name_w) // 2, ty), name, 34, TEXT_PRIMARY, bold=True)
    ty += 46
    rank_w = draw.textlength(data.rank_title, font=_font(22))
    _draw_text(draw, (cx - int(rank_w) // 2, ty), data.rank_title, 22, border, bold=True)
    ty += 34
    if data.flair:
        flair = _ellipsize(draw, data.flair, _font(17), w - pad * 2)
        flair_w = draw.textlength(flair, font=_font(17))
        _draw_text(draw, (cx - int(flair_w) // 2, ty), flair, 17, TEXT_DIM)
        ty += 26

    divider_y = ty + 14
    draw.line((pad, divider_y, w - pad, divider_y), fill=border, width=3)

    grid_top = divider_y + 20
    cell_w = (w - pad * 2 - 16) // 2
    cell_h = (h - grid_top - pad - 16) // 2
    total_gold = data.pocket_gold + data.bank_gold
    cells = [
        ("Gold", f"{total_gold:,}"), ("Best Trade", data.best_trade_label),
        ("Wealth Rank", f"#{data.gold_rank}"), ("Skill Rank", f"#{data.skill_rank}"),
    ]
    box_bg = _darkable(_lerp(bg_flat, (0, 0, 0), 0.32))
    for i, (label, value) in enumerate(cells):
        col, row = i % 2, i // 2
        x = pad + col * (cell_w + 16)
        y = grid_top + row * (cell_h + 16)
        _stat_box(canvas, (x, y), (cell_w, cell_h), label, value, data.accent_rgb, box_bg)
    return canvas


# ── layout: scroll -- a wide accent "spine" down the left edge instead
# of a thin flag, avatar set into it, stats as one flowing tag row
# separated by thin rules rather than individual boxes.

def _layout_scroll(data: ProfileCardData) -> Image.Image:
    w, h = 1000, 340
    pad, avatar_size = 30, 160
    spine_w = 70
    bg_flat = _darkable(_lerp((16, 16, 22), data.accent_rgb, 0.14))
    border = _readable(data.accent_rgb)

    canvas = Image.new("RGB", (w, h), bg_flat)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, spine_w, h), fill=_darkable(data.accent_rgb, ceiling=0.55))
    canvas = _round_frame(canvas, 20, bg_flat)
    draw = ImageDraw.Draw(canvas)

    ax = spine_w - avatar_size // 2
    ay = (h - 150) // 2 - avatar_size // 2 + 10
    ring_pad = 5
    ring = Image.new("RGBA", (avatar_size + ring_pad * 2,) * 2, (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((0, 0, ring.width - 1, ring.height - 1), fill=(*border, 255))
    canvas.paste(ring, (ax - ring_pad, ay - ring_pad), ring)
    avatar = _load_avatar(data, avatar_size, data.accent_rgb)
    canvas.paste(avatar, (ax, ay), avatar)

    tx = ax + avatar_size + 36
    ty = pad
    name = _ellipsize(draw, data.display_name, _font(42), w - tx - pad)
    _draw_text(draw, (tx, ty), name, 42, TEXT_PRIMARY, bold=True)
    ty += 54
    _draw_text(draw, (tx, ty), data.rank_title, 24, border, bold=True)
    ty += 34
    if data.flair:
        _draw_text(draw, (tx, ty), data.flair, 18, TEXT_DIM)

    rule_y = h - 108
    draw.line((tx, rule_y, w - pad, rule_y), fill=border, width=2)

    total_gold = data.pocket_gold + data.bank_gold
    tags = [
        ("Gold", f"{total_gold:,}"),
        ("Best Trade", data.best_trade_label),
        ("Wealth Rank", f"#{data.gold_rank}"),
        ("Skill Rank", f"#{data.skill_rank}"),
    ]
    tag_w = (w - tx - pad - 3 * 24) // 4
    x = tx
    y = rule_y + 20
    for i, (label, value) in enumerate(tags):
        draw.text((x, y), label.upper(), font=_font(15), fill=TEXT_DIM)
        text, value_font = _fit_value(draw, value, tag_w)
        draw.text((x, y + 22), text, font=value_font, fill=TEXT_PRIMARY, stroke_width=1)
        if i < len(tags) - 1:
            line_x = x + tag_w + 12
            draw.line((line_x, y, line_x, y + 56), fill=border, width=1)
        x += tag_w + 24
    return canvas


_LAYOUTS = {
    "banner": _layout_banner,
    "dashboard": _layout_dashboard,
    "ticket": _layout_ticket,
    "scroll": _layout_scroll,
}


def render_profile_card(data: ProfileCardData) -> io.BytesIO:
    render = _LAYOUTS.get(data.layout, _layout_banner)
    canvas = render(data)
    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf
