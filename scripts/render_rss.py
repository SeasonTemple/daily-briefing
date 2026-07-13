"""
render_rss.py — Atom 1.0 feed writer.

Output: an Atom 1.0 XML file with one <entry> per item, in declared order.
The <summary> uses type="html" with CDATA-wrapped HTML markup so feed
readers like Feedly / Inoreader / NetNewsWire render it nicely.

Each entry contains:
  - title    : Chinese (or original) title
  - link     : original article URL
  - id       : stable tag URI derived from feed id + url + date
  - updated  : item's published time (RFC 3339)
  - summary  : HTML (CDATA) with 中文标题 + 一句话摘要 + 关键信息 + 来源
"""
from __future__ import annotations

import html
import os
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any
from xml.sax.saxutils import escape


def _esc(s: str) -> str:
    return escape(s or "", {'"': "&quot;", "'": "&apos;"})


def _rfc3339(dt: datetime | None) -> str:
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return format_datetime(dt.astimezone(timezone.utc), usegmt=True)


def _entry_id(feed_id: str, url: str, dt: datetime | None) -> str:
    # Stable tag URI per item
    base = url or (dt.isoformat() if dt else "x")
    slug = "".join(ch if ch.isalnum() else "-" for ch in base)[:120]
    date_part = dt.strftime("%Y-%m-%d") if dt else "undated"
    return f"{feed_id}:{date_part}:{slug}"


def render(
    *,
    feed_title: str,
    feed_subtitle: str,
    feed_id: str,
    profile: str,
    items: list[dict],
    out_path: str,
) -> dict:
    """
    items: list of dicts from digest_items(...). Each item has:
      - url, title, source, source_type, published (datetime|iso), author
      - digest.headline, digest.summary, digest.key, digest.relevance
    """
    now = datetime.now(timezone.utc)

    lines: list[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="zh-CN">')
    lines.append(f"  <title>{_esc(feed_title)}</title>")
    lines.append(f"  <subtitle>{_esc(feed_subtitle)}</subtitle>")
    lines.append(f"  <id>{_esc(feed_id)}</id>")
    lines.append(f"  <updated>{_rfc3339(now)}</updated>")
    lines.append(f"  <generator>daily-briefing/0.1</generator>")
    lines.append(f'  <link rel="self" type="application/atom+xml" href="file://{_esc(out_path)}"/>')

    # Author block at feed level
    lines.append("  <author><name>Daily Briefing</name></author>")

    # Entries
    for it in items:
        d = it.get("digest") or {}
        title = d.get("headline") or it.get("title") or "(无标题)"
        url = it.get("url") or ""
        src = it.get("source") or "unknown"
        author = it.get("author") or src
        pub = it.get("published")
        if isinstance(pub, str):
            try:
                pub = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            except Exception:
                pub = None
        eid = _entry_id(feed_id, url, pub if isinstance(pub, datetime) else None)

        summary_html = (
            "<p><b>中文标题</b>: "
            + _esc(d.get("headline") or title)
            + "</p>"
            + "<p><b>摘要</b>: "
            + _esc(d.get("summary") or "")
            + "</p>"
            + "<p><b>关键信息</b>: "
            + _esc(d.get("key") or "")
            + "</p>"
            + "<p><b>来源</b>: "
            + _esc(src)
            + (f" · {_esc(author)}" if author and author != src else "")
            + "</p>"
            + (f'<p><a href="{_esc(url)}">阅读原文</a></p>' if url else "")
        )

        lines.append("  <entry>")
        lines.append(f"    <title>{_esc(title)}</title>")
        if url:
            lines.append(f'    <link href="{_esc(url)}"/>')
        lines.append(f"    <id>{_esc(eid)}</id>")
        lines.append(f"    <updated>{_rfc3339(pub if isinstance(pub, datetime) else now)}</updated>")
        lines.append(f"    <author><name>{_esc(author)}</name></author>")
        lines.append(f'    <category term="{_esc(profile)}"/>')
        lines.append(f"    <summary type=\"html\"><![CDATA[{summary_html}]]></summary>")
        lines.append("  </entry>")

    lines.append("</feed>")

    xml = "\n".join(lines) + "\n"
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(xml)
    return {"path": out_path, "entries": len(items), "bytes": len(xml.encode("utf-8"))}


def render_markdown_report(
    *,
    profile: str,
    feed_title: str,
    items: list[dict],
    stats: dict,
    out_path: str,
) -> dict:
    """Optional Markdown archive for the day."""
    lines: list[str] = []
    lines.append(f"# {feed_title} · {datetime.now(timezone.utc).strftime('%Y-%m-%d')}")
    lines.append("")
    lines.append(f"- Profile: `{profile}`")
    lines.append(f"- 抓取条目: {stats.get('total', 0)}")
    pe = stats.get("per_source", {})
    if pe:
        lines.append("- 抓取明细:")
        for k, v in pe.items():
            err = ""
            if k in stats.get("errors", {}):
                err = f" ⚠️ {stats['errors'][k]}"
            lines.append(f"  - {k}: {v}{err}")
    lines.append("")
    lines.append("---")
    lines.append("")
    for i, it in enumerate(items, 1):
        d = it.get("digest") or {}
        title = d.get("headline") or it.get("title") or "(无标题)"
        url = it.get("url") or ""
        src = it.get("source", "")
        lines.append(f"## {i}. {title}")
        lines.append("")
        lines.append(f"- **摘要**: {d.get('summary','')}")
        lines.append(f"- **关键信息**: {d.get('key','')}")
        lines.append(f"- **来源**: {src}")
        if url:
            lines.append(f"- **原文**: {url}")
        lines.append(f"- **相关度**: {d.get('relevance', 0)}")
        lines.append("")

    md = "\n".join(lines) + "\n"
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    return {"path": out_path, "bytes": len(md.encode("utf-8"))}
