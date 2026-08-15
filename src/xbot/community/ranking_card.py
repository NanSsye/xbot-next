from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

_WIDTH = 1024
_HEIGHT = 1536
_INK = "#352C2A"
_MUTED = "#8B7C75"
_POINTS = "#D65D45"
_SECTION_COLORS = ("#E76047", "#258E7E", "#C38A20", "#3E79AA")
_MEDAL_COLORS = ("#F2B735", "#AEB8C3", "#C77B4B", "#F7F0E8", "#F7F0E8")


def _font(path: Path, size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(path), size=size)
    try:
        font.set_variation_by_axes([weight])
    except (AttributeError, OSError, ValueError):
        pass
    return font


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> str:
    value = " ".join(str(text or "群成员").split()) or "群成员"
    if draw.textlength(value, font=font) <= max_width:
        return value
    while value and draw.textlength(value + "…", font=font) > max_width:
        value = value[:-1]
    return value + "…"


def _draw_rank_badge(
    draw: ImageDraw.ImageDraw,
    rank: int,
    center: tuple[int, int],
    number_font: ImageFont.FreeTypeFont,
) -> None:
    x, y = center
    fill = _MEDAL_COLORS[rank - 1]
    outline = "#C7A25C" if rank <= 3 else "#CFC4B8"
    draw.ellipse((x - 15, y - 15, x + 15, y + 15), fill=fill, outline=outline, width=2)
    number_fill = "#FFFFFF" if rank <= 3 else "#74665F"
    draw.text((x, y - 1), str(rank), font=number_font, fill=number_fill, anchor="mm")
    if rank <= 3:
        draw.polygon(
            ((x - 10, y + 12), (x - 3, y + 25), (x + 1, y + 14)),
            fill=fill,
        )
        draw.polygon(
            ((x + 10, y + 12), (x + 3, y + 25), (x - 1, y + 14)),
            fill=fill,
        )


def _draw_section_icon(
    draw: ImageDraw.ImageDraw,
    index: int,
    center: tuple[int, int],
    color: str,
) -> None:
    x, y = center
    if index == 0:
        draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=color)
        for dx, dy in ((0, -15), (0, 15), (-15, 0), (15, 0), (-11, -11), (11, 11), (-11, 11), (11, -11)):
            draw.line((x + dx * 0.7, y + dy * 0.7, x + dx, y + dy), fill=color, width=3)
    elif index in {1, 2}:
        draw.rounded_rectangle((x - 13, y - 12, x + 13, y + 13), radius=4, outline=color, width=3)
        draw.line((x - 13, y - 4, x + 13, y - 4), fill=color, width=3)
        draw.line((x - 7, y - 16, x - 7, y - 9), fill=color, width=3)
        draw.line((x + 7, y - 16, x + 7, y - 9), fill=color, width=3)
        if index == 2:
            draw.ellipse((x + 3, y + 1, x + 8, y + 6), fill=color)
    else:
        draw.arc((x - 12, y - 13, x + 12, y + 8), 0, 180, fill=color, width=4)
        draw.line((x - 12, y - 2, x - 5, y + 12), fill=color, width=4)
        draw.line((x + 12, y - 2, x + 5, y + 12), fill=color, width=4)
        draw.line((x, y + 8, x, y + 15), fill=color, width=4)
        draw.line((x - 8, y + 15, x + 8, y + 15), fill=color, width=4)


def render_points_ranking_card(
    payload: dict[str, list[dict[str, Any]]],
    *,
    assets_dir: Path,
    output_dir: Path,
    conversation_id: str,
) -> Path:
    background = assets_dir / "points-ranking-bg.png"
    font_path = assets_dir / "fonts" / "NotoSansSC-Variable.ttf"
    if not background.is_file() or not font_path.is_file():
        raise FileNotFoundError("积分排行榜底图或字体不存在")

    image = Image.open(background).convert("RGB")
    if image.size != (_WIDTH, _HEIGHT):
        image = image.resize((_WIDTH, _HEIGHT), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(image)
    title_font = _font(font_path, 51, 750)
    subtitle_font = _font(font_path, 21, 450)
    pill_font = _font(font_path, 19, 650)
    section_font = _font(font_path, 27, 700)
    name_font = _font(font_path, 24, 580)
    points_font = _font(font_path, 24, 700)
    number_font = _font(font_path, 17, 750)
    empty_font = _font(font_path, 22, 450)
    footer_font = _font(font_path, 19, 500)

    draw.text((350, 116), "群积分风云榜", font=title_font, fill=_INK)
    draw.text((352, 178), "签到 · 群互动 · 游戏奖励 · 积分兑换", font=subtitle_font, fill="#75665F")
    draw.rounded_rectangle((744, 111, 905, 154), radius=21, fill="#FFF2EC", outline="#F3B7A7", width=2)
    draw.ellipse((762, 126, 774, 138), fill="#53B79C")
    draw.text((787, 132), "实时更新", font=pill_font, fill="#D96049", anchor="lm")

    sections = (
        ("day", "今日 TOP 5", "今日净增"),
        ("week", "本周 TOP 5", "本周净增"),
        ("month", "本月 TOP 5", "本月净增"),
        ("total", "总榜 TOP 5", "当前余额"),
    )
    header_y = (360, 642, 925, 1210)
    row_y = (
        (411, 452, 493, 534, 575),
        (695, 736, 777, 818, 859),
        (979, 1020, 1061, 1102, 1143),
        (1264, 1305, 1346, 1387, 1428),
    )
    for section_index, ((key, label, points_label), color) in enumerate(zip(sections, _SECTION_COLORS, strict=True)):
        _draw_section_icon(draw, section_index, (137, header_y[section_index]), color)
        draw.text((161, header_y[section_index]), label, font=section_font, fill=_INK, anchor="lm")
        draw.text((894, header_y[section_index]), points_label, font=pill_font, fill=color, anchor="rm")
        rows = [row for row in (payload.get(key) or [])[:5] if isinstance(row, dict)]
        for rank, y in enumerate(row_y[section_index], start=1):
            _draw_rank_badge(draw, rank, (145, y), number_font)
            if rank <= len(rows):
                row = rows[rank - 1]
                nickname = _fit_text(draw, str(row.get("nickname") or "群成员"), name_font, 520)
                points = int(row.get("points") or 0)
                points_text = f"{points:+,}" if key != "total" else f"{points:,} 分"
                draw.text((188, y), nickname, font=name_font, fill=_INK, anchor="lm")
                draw.text((890, y), points_text, font=points_font, fill=_POINTS, anchor="rm")
            else:
                draw.text((188, y), "虚位以待", font=empty_font, fill=_MUTED, anchor="lm")
                draw.text((890, y), "—", font=points_font, fill="#B9ADA6", anchor="rm")

    draw.text((512, 1476), "✦ 数据实时变化，继续互动赢取更多积分 ✦", font=footer_font, fill="#397F70", anchor="mm")
    output_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(conversation_id.encode("utf-8")).hexdigest()[:20]
    output = output_dir / f"points-ranking-{digest}.png"
    temporary = output.with_suffix(".tmp")
    image.save(temporary, format="PNG", optimize=True)
    temporary.replace(output)
    return output
