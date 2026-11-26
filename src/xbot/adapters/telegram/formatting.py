from __future__ import annotations

import html
import re
from urllib.parse import urlparse

_FENCE_RE = re.compile(r"^```([^\n`]*)\n([\s\S]*?)\n?```$", re.MULTILINE)
_LINK_RE = re.compile(r"\[([^\]\n]+)]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_AUTOLINK_RE = re.compile(r"<(https?://[^<>\s]+)>")
_CODE_RE = re.compile(r"`([^`\n]+)`")
_TABLE_DIVIDER_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")


def telegram_markdown_chunks(text: str, limit: int = 4096) -> list[tuple[str, str]]:
    """Return safe Telegram HTML plus readable plain fallbacks for each chunk."""
    return [(markdown_to_telegram_html(chunk), chunk) for chunk in split_markdown(text, limit)]


def split_markdown(text: str, limit: int = 4096) -> list[str]:
    """Split CommonMark-like text without leaving fenced code blocks open."""
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not value:
        return [" "]
    limit = max(1, int(limit))
    blocks = _markdown_blocks(value)
    pieces: list[str] = []
    for block in blocks:
        if len(block) <= limit:
            pieces.append(block)
            continue
        fence = _FENCE_RE.fullmatch(block)
        if fence:
            language = fence.group(1).strip()
            prefix = f"```{language}\n"
            suffix = "\n```"
            content_limit = max(1, limit - len(prefix) - len(suffix))
            pieces.extend(
                f"{prefix}{part}{suffix}"
                for part in _split_natural(fence.group(2), content_limit)
            )
        else:
            pieces.extend(_split_natural(block, limit))

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = piece if not current else f"{current}\n\n{piece}"
        if current and len(candidate) > limit:
            chunks.append(current)
            current = piece
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [" "]


def markdown_to_telegram_html(text: str) -> str:
    """Render the useful CommonMark subset supported by Telegram's HTML mode."""
    blocks = _markdown_blocks(str(text or ""))
    rendered: list[str] = []
    index = 0
    while index < len(blocks):
        block = blocks[index]
        fence = _FENCE_RE.fullmatch(block)
        if fence:
            language = re.sub(r"[^A-Za-z0-9_+.#-]", "", fence.group(1).strip())
            class_name = f' class="language-{html.escape(language, quote=True)}"' if language else ""
            rendered.append(f"<pre><code{class_name}>{html.escape(fence.group(2))}</code></pre>")
            index += 1
            continue

        lines = block.splitlines()
        if len(lines) >= 2 and _TABLE_DIVIDER_RE.fullmatch(lines[1]):
            rendered.append(_render_table(lines))
            index += 1
            continue
        if all(line.lstrip().startswith(">") for line in lines if line.strip()):
            quote = "\n".join(line.lstrip()[1:].lstrip() for line in lines)
            rendered.append(f"<blockquote>{_inline(quote)}</blockquote>")
            index += 1
            continue

        output_lines: list[str] = []
        for line in lines:
            heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
            if heading:
                output_lines.append(f"<b>{_inline(heading.group(1))}</b>")
                continue
            unordered = re.match(r"^\s*[-+*]\s+(.+)$", line)
            if unordered:
                output_lines.append(f"• {_inline(unordered.group(1))}")
                continue
            ordered = re.match(r"^\s*(\d+)[.)]\s+(.+)$", line)
            if ordered:
                output_lines.append(f"{ordered.group(1)}. {_inline(ordered.group(2))}")
                continue
            if re.fullmatch(r"\s*(?:-{3,}|_{3,}|\*{3,})\s*", line):
                output_lines.append("────────")
                continue
            output_lines.append(_inline(line))
        rendered.append("\n".join(output_lines))
        index += 1
    return "\n\n".join(item for item in rendered if item) or " "


def _markdown_blocks(text: str) -> list[str]:
    lines = text.splitlines()
    blocks: list[str] = []
    current: list[str] = []
    in_fence = False
    for line in lines:
        if line.lstrip().startswith("```"):
            if not in_fence and current:
                blocks.append("\n".join(current).strip("\n"))
                current = []
            current.append(line)
            in_fence = not in_fence
            if not in_fence:
                blocks.append("\n".join(current).strip("\n"))
                current = []
            continue
        if not in_fence and not line.strip():
            if current:
                blocks.append("\n".join(current).strip("\n"))
                current = []
            continue
        current.append(line)
    if current:
        if in_fence:
            current.append("```")
        blocks.append("\n".join(current).strip("\n"))
    return [block for block in blocks if block]


def _split_natural(text: str, limit: int) -> list[str]:
    remaining = text
    chunks: list[str] = []
    while len(remaining) > limit:
        window = remaining[: limit + 1]
        positions = [
            window.rfind("\n"),
            window.rfind("。"),
            window.rfind("！"),
            window.rfind("？"),
            window.rfind(" "),
        ]
        split_at = max(positions)
        if split_at < max(1, limit // 2):
            split_at = limit
        elif window[split_at:split_at + 1] in "。！？":
            split_at += 1
        part = remaining[:split_at].rstrip()
        chunks.append(part or remaining[:limit])
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks or [" "]


def _inline(text: str) -> str:
    tokens: dict[str, str] = {}

    def token(value: str) -> str:
        key = f"\ue000{len(tokens)}\ue001"
        tokens[key] = value
        return key

    value = _CODE_RE.sub(lambda match: token(f"<code>{html.escape(match.group(1))}</code>"), text)

    def link(match: re.Match[str]) -> str:
        url = match.group(2)
        parsed = urlparse(url)
        if parsed.scheme.lower() not in {"http", "https", "tg", "mailto"}:
            return match.group(0)
        label = _inline(match.group(1))
        return token(f'<a href="{html.escape(url, quote=True)}">{label}</a>')

    value = _LINK_RE.sub(link, value)
    value = _AUTOLINK_RE.sub(
        lambda match: token(
            f'<a href="{html.escape(match.group(1), quote=True)}">'
            f"{html.escape(match.group(1))}</a>"
        ),
        value,
    )
    value = html.escape(value)
    value = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"__(.+?)__", r"<b>\1</b>", value)
    value = re.sub(r"~~(.+?)~~", r"<s>\1</s>", value)
    value = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", value)
    value = re.sub(r"(?<![\w_])_([^_\n]+)_(?![\w_])", r"<i>\1</i>", value)
    for key, replacement in tokens.items():
        value = value.replace(key, replacement)
    return value


def _render_table(lines: list[str]) -> str:
    rows = [_table_cells(line) for line in [lines[0], *lines[2:]]]
    if not rows or not rows[0]:
        return "\n".join(_inline(line) for line in lines)
    headers = rows[0]
    output: list[str] = []
    for row_index, row in enumerate(rows[1:], start=1):
        values = [
            f"<b>{_inline(header)}</b>：{_inline(row[index])}"
            for index, header in enumerate(headers)
            if index < len(row) and row[index]
        ]
        if values:
            output.append(f"{row_index}. " + " · ".join(values))
    return "\n".join(output) or " · ".join(f"<b>{_inline(item)}</b>" for item in headers)


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]
