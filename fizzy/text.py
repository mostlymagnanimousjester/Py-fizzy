"""Rich text stored the way Action Text does: a sanitized HTML fragment."""

from __future__ import annotations

import re

import bleach

ALLOWED_TAGS = [
    "a", "blockquote", "br", "code", "div", "em", "h1", "h2", "h3",
    "li", "ol", "p", "pre", "span", "strong", "ul",
]
ALLOWED_ATTRIBUTES = {
    "a": ["href", "title"],
    "span": ["class", "data-user-id"],
    "div": ["class"],
}

_TAG_RE = re.compile(r"<[a-z][\s\S]*>", re.I)
_WS_RE = re.compile(r"\s+")


def plain_text(html: str | None) -> str:
    if not html:
        return ""
    text = bleach.clean(html, tags=[], strip=True)
    return _WS_RE.sub(" ", text).strip()


def sanitize(html: str | None) -> str:
    if not html:
        return ""
    cleaned = bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=["http", "https", "mailto"],
        strip=True,
    )
    return cleaned.strip()


def to_html(value: str | None) -> str:
    """Accept plain text or HTML and store an Action Text style fragment."""
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    if _TAG_RE.search(raw):
        body = sanitize(raw)
    else:
        parts = []
        for block in re.split(r"\n\s*\n", raw):
            lines = "<br>".join(bleach.clean(line, tags=[], strip=True) for line in block.splitlines())
            if lines:
                parts.append(f"<p>{lines}</p>")
        body = "".join(parts)
    if not body:
        return ""
    if body.startswith('<div class="action-text-content"'):
        return body
    return f'<div class="action-text-content">{body}</div>'


def mention_ids_from_html(html: str | None) -> list[str]:
    if not html:
        return []
    return re.findall(r'data-user-id="([0-9a-z]{25})"', html)
