"""Minimal markdown -> safe HTML renderer, for staff free-text notes fields
(e.g. CaseTrackedForm.notes_markdown, app/crm_models.py) that need a bit of
structure (headings, bold/italic, lists) without pulling in a real markdown
library. Same convention already used in this project for a different
document (scripts/generate_cartas_i539.py::_markdown_ish_to_story, which
converts a similar limited subset into ReportLab markup instead of HTML).

Deliberately escapes all HTML first -- input is staff-authored free text,
never trusted as markup.
"""
from __future__ import annotations

import re
from html import escape as _escape

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*]+?)\*(?!\*)")
_CODE_RE = re.compile(r"`([^`]+?)`")


def _inline(text: str) -> str:
    text = _BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = _ITALIC_RE.sub(r"<em>\1</em>", text)
    text = _CODE_RE.sub(r"<code>\1</code>", text)
    return text


def markdown_lite_to_html(raw: str | None) -> str:
    """Supports: # / ## / ### headings, "- "/"* " bullet lists, **bold**,
    *italic*, `code`, and blank-line-separated paragraphs. Anything else is
    passed through as plain text (escaped)."""
    if not raw or not raw.strip():
        return ""

    escaped = _escape(raw.strip())
    lines = escaped.splitlines()

    html_parts: list[str] = []
    paragraph_lines: list[str] = []
    list_items: list[str] = []

    def flush_paragraph() -> None:
        if paragraph_lines:
            html_parts.append("<p>" + "<br>".join(_inline(l) for l in paragraph_lines) + "</p>")
            paragraph_lines.clear()

    def flush_list() -> None:
        if list_items:
            html_parts.append("<ul>" + "".join(f"<li>{_inline(li)}</li>" for li in list_items) + "</ul>")
            list_items.clear()

    for line in lines:
        stripped = line.strip()
        heading_match = re.match(r"^(#{1,3})\s+(.*)$", stripped)
        list_match = re.match(r"^[-*]\s+(.*)$", stripped)

        if not stripped:
            flush_paragraph()
            flush_list()
        elif heading_match:
            flush_paragraph()
            flush_list()
            level = len(heading_match.group(1)) + 3  # h4/h5/h6 -- stays small inside a card
            html_parts.append(f"<h{level}>{_inline(heading_match.group(2))}</h{level}>")
        elif list_match:
            flush_paragraph()
            list_items.append(list_match.group(1))
        else:
            flush_list()
            paragraph_lines.append(stripped)

    flush_paragraph()
    flush_list()
    return "".join(html_parts)
