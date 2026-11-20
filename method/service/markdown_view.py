"""Small, safe Markdown-to-HTML for protocol documents (stdlib only).

All text is HTML-escaped before anything else, and only a fixed set of tags is ever emitted. Links are limited to
http(s), mailto and in-page anchors, so a protocol that contains HTML or a `javascript:` link cannot inject anything.
Supported: headings, paragraphs, bullet and numbered lists (nested), fenced code, inline code, bold, italic,
blockquotes, horizontal rules, tables and links. HTML comments (such as the protocol header markers) are dropped.
"""
from __future__ import annotations

import re
from html import escape as e

_COMMENT = re.compile(r"<!--.*?-->", re.S)
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+|mailto:[^\s)]+|#[\w-]+)\)")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
_LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_HR = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")


def _inline(text: str) -> str:
    out = []
    for i, part in enumerate(re.split(r"`([^`\n]+)`", text)):
        if i % 2:  # code span: escape and never touch again
            out.append(f"<code>{e(part)}</code>")
            continue
        safe = e(part)
        links: list[str] = []

        def keep(m):
            href = m.group(2)
            attrs = "" if href.startswith("#") else " target='_blank' rel='noopener noreferrer'"
            links.append(f"<a href='{href}'{attrs}>{m.group(1)}</a>")
            return f"\x00{len(links) - 1}\x00"

        safe = _LINK.sub(keep, safe)
        safe = _ITALIC.sub(r"<em>\1</em>", _BOLD.sub(r"<strong>\1</strong>", safe))
        out.append(re.sub(r"\x00(\d+)\x00", lambda m: links[int(m.group(1))], safe))
    return "".join(out)


def _cells(row: str) -> list[str]:
    row = row.strip().strip("|")
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", row)]


def _list_html(items: list[tuple[int, bool, str]]) -> str:
    out: list[str] = []
    stack: list[tuple[int, str]] = []
    for indent, ordered, text in items:
        tag = "ol" if ordered else "ul"
        while stack and indent < stack[-1][0]:
            out.append(f"</li></{stack.pop()[1]}>")
        if stack and indent == stack[-1][0]:
            out.append("</li>")
        else:
            out.append(f"<{tag}>")
            stack.append((indent, tag))
        out.append(f"<li>{_inline(text)}")
    while stack:
        out.append(f"</li></{stack.pop()[1]}>")
    return "".join(out)


def render(markdown: str) -> str:
    lines = _COMMENT.sub("", markdown.replace("\r\n", "\n").replace("\r", "\n")).split("\n")
    html: list[str] = []
    paragraph: list[str] = []
    seen_ids: dict[str, int] = {}
    i = 0

    def flush() -> None:
        if paragraph:
            # Hard-wrapped prose is joined with spaces; a line that starts a bold label (**Key:** value) or follows a line
            # ending in two spaces keeps its own line, so status blocks stay readable.
            text = paragraph[0]
            for previous, line in zip(paragraph, paragraph[1:]):
                text += ("\n" if line.startswith("**") or previous.endswith("  ") else " ") + line
            html.append(f"<p>{_inline(text).replace(chr(10), '<br>')}</p>")
            paragraph.clear()

    while i < len(lines):
        line = lines[i]
        fence = re.match(r"^\s*(```|~~~)", line)
        if fence:
            flush()
            code: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].lstrip().startswith(fence.group(1)):
                code.append(lines[i])
                i += 1
            i += 1
            html.append(f"<pre><code>{e(chr(10).join(code))}</code></pre>")
            continue
        if not line.strip():
            flush()
            i += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if heading:
            flush()
            level = min(len(heading.group(1)) + 2, 6)
            base = re.sub(r"[^a-z0-9]+", "-", heading.group(2).lower()).strip("-") or "section"
            n = seen_ids.get(base, 0)
            seen_ids[base] = n + 1
            html.append(f"<h{level} id='{base}{'-' + str(n) if n else ''}'>{_inline(heading.group(2))}</h{level}>")
            i += 1
            continue
        if _HR.match(line):
            flush()
            html.append("<hr>")
            i += 1
            continue
        if line.lstrip().startswith(">"):
            flush()
            quote = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            html.append(f"<blockquote>{render(chr(10).join(quote))}</blockquote>")
            continue
        if "|" in line and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
            flush()
            head = _cells(line)
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                rows.append(_cells(lines[i]))
                i += 1
            body = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in rows)
            html.append("<div class='table-wrap'><table class='striped'><thead><tr>"
                        + "".join(f"<th>{_inline(c)}</th>" for c in head) + f"</tr></thead><tbody>{body}</tbody></table></div>")
            continue
        item = _LIST_ITEM.match(line)
        if item:
            flush()
            items: list[tuple[int, bool, str]] = []
            while i < len(lines):
                m = _LIST_ITEM.match(lines[i])
                if m:
                    items.append((len(m.group(1).expandtabs(4)), m.group(2)[0].isdigit(), m.group(3)))
                elif lines[i].strip() and lines[i].startswith((" ", "\t")) and items:
                    indent, ordered, text = items[-1]  # continuation line of the previous item
                    items[-1] = (indent, ordered, f"{text} {lines[i].strip()}")
                else:
                    break
                i += 1
            html.append(_list_html(items))
            continue
        paragraph.append(line.rstrip() if line.rstrip().endswith('  ') else line.strip())
        i += 1
    flush()
    return "".join(html)
