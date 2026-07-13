#!/usr/bin/env python3
"""
daily_briefing.py — v2 cron entry point.

Pipeline:
  1. Fetch 8 sources (4 RSS, 1 Atom-sitemap, 3 GitHub commit feeds, 1 HTML scrape).
  2. Pick 8-12 AI items, write M3-style Chinese summaries (<= 60 chars).
  3. Write rss/ai-daily.xml as strict RSS 2.0
     (no CDATA, escape &, HTTPS self link, RFC 2822 pubDate, ttl 5, media:thumbnail).
  4. Write digests/ai-daily.html mirroring existing dark+zh-CN+a11y style.
  5. Validate rss/ai-daily.xml with xml.etree.ElementTree.

Stdlib only (urllib + xml.etree + re + email.utils + html) so this works
in the bare Mavis cron sandbox where pip is unavailable.
"""
from __future__ import annotations

import html
import os
import re
import sys
import json
import time
import shutil
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from xml.sax.saxutils import escape as xml_escape

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO = Path("/tmp/daily-briefing")
RSS_OUT = REPO / "rss" / "ai-daily.xml"
HTML_OUT = REPO / "digests" / "ai-daily.html"

GITHUB_REPO_SLUG = "seasontemple/daily-briefing"
GITHUB_PAGES_BASE = f"https://seasontemple.github.io/daily-briefing"

LOGOS_BASE = f"{GITHUB_PAGES_BASE}/assets/logos"

# Map each logical source key to (logo filename, human label).
LOGO = {
    "openai":      "openai.svg",
    "anthropic":   "anthropic.svg",
    "deepmind":    "deepmind.svg",
    "hn":          "hackernews.svg",
    "arxiv":       "arxiv.svg",
}

# 8 sources to fetch. Each entry: (key, label, fetcher function).
# The key also maps to LOGO above.
SOURCES = [
    ("hn",         "Hacker News",         "fetch_hn"),
    ("anthropic",  "Anthropic News",      "fetch_anthropic"),
    ("openai",     "OpenAI Blog",         "fetch_openai"),
    ("deepmind",   "DeepMind Blog",       "fetch_deepmind"),
    ("arxiv",      "arXiv cs.AI",         "fetch_arxiv"),
    ("github",     "GitHub anthropics",   "fetch_gh_anthropics"),
    ("github",     "GitHub openai",       "fetch_gh_openai"),
    ("github",     "GitHub google-deepmind", "fetch_gh_deepmind"),
]

USER_AGENT = "daily-briefing/0.4 (+https://github.com/seasontemple/daily-briefing)"
TIMEOUT = 12

# Each source returns a list of items in a canonical dict shape (see below).
# Canonical item:
#   { source_key, source_label, title, url, desc, pubdate: datetime(UTC) }


# Source-specific filter: drop pure "how to get started" / docs pages that
# aren't news. Per-source list of regexes; an item is dropped only if its
# title matches the relevant "noise" pattern.
NOISE_PATTERNS = {
    "openai": re.compile(
        r"(?i)^(getting started|how to|what is|introducing our|"
        r"our approach to|help(ing)?\s+k[-–]\s?12|chatgpt\s+tips|"
        r"guide|tutorial)"
    ),
    "anthropic": re.compile(r"(?i)^(getting started|how to|what is)"),
    "deepmind": re.compile(r"(?i)^(getting started|how to|what is)"),
    "hn": re.compile(
        r"(?i)^(show hn: (i built a one-prompt|billai|bill ai|billy bass|"
        r"i made a))"
    ),
    "github": re.compile(
        r"(?i)(chore:|bump |update depend|update readme|update changelog|"
        r"merge pull request #\d+ from .+/(dependabot|renovate)|"
        r"formatting|typo|fix typo|fix lint)"
    ),
    "arxiv": re.compile(r"(?i)^(a note on)"),
}


def _is_noise(it: dict) -> bool:
    pat = NOISE_PATTERNS.get(it.get("source_key"))
    return bool(pat and pat.search(it["title"]))


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def http_get(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def safe_get(url: str, retries: int = 3) -> bytes | None:
    last = None
    for attempt in range(retries):
        try:
            return http_get(url)
        except (URLError, HTTPError, TimeoutError, OSError) as e:
            last = e
            time.sleep(0.5 + attempt * 0.5)
    print(f"  WARN  {url}: {last}", file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# Fetchers — return list[dict] of items
# ---------------------------------------------------------------------------

def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _parse_rfc2822(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def fetch_hn() -> list[dict]:
    """HN frontpage RSS — 20 latest stories, scored for AI relevance."""
    raw = safe_get("https://hnrss.org/frontpage")
    if not raw:
        return []
    root = ET.fromstring(raw)
    items = []
    for it in root.findall("./channel/item"):
        title = (it.findtext("title") or "").strip()
        link  = (it.findtext("link")  or "").strip()
        desc  = _strip_html(it.findtext("description") or "")
        pd    = _parse_rfc2822(it.findtext("pubDate"))
        if not (title and link):
            continue
        items.append({
            "source_key": "hn",
            "source_label": "Hacker News",
            "title": title,
            "url": link,
            "desc": desc or title,
            "pubdate": pd,
        })
    return items


def fetch_openai() -> list[dict]:
    raw = safe_get("https://openai.com/news/rss.xml")
    if not raw:
        return []
    root = ET.fromstring(raw)
    items = []
    for it in root.findall(".//item"):
        title = (it.findtext("title") or "").strip()
        link  = (it.findtext("link")  or "").strip()
        desc  = _strip_html(it.findtext("description") or "")
        pd    = _parse_rfc2822(it.findtext("pubDate"))
        if not (title and link):
            continue
        items.append({
            "source_key": "openai",
            "source_label": "OpenAI Blog",
            "title": title,
            "url": link,
            "desc": desc or title,
            "pubdate": pd,
        })
    return items


def fetch_deepmind() -> list[dict]:
    raw = safe_get("https://deepmind.google/blog/rss.xml")
    if not raw:
        return []
    root = ET.fromstring(raw)
    items = []
    for it in root.findall(".//item"):
        title = (it.findtext("title") or "").strip()
        link  = (it.findtext("link")  or "").strip()
        desc  = _strip_html(it.findtext("description") or "")
        pd    = _parse_rfc2822(it.findtext("pubDate"))
        if not (title and link):
            continue
        items.append({
            "source_key": "deepmind",
            "source_label": "DeepMind Blog",
            "title": title,
            "url": link,
            "desc": desc or title,
            "pubdate": pd,
        })
    return items


def fetch_arxiv() -> list[dict]:
    raw = safe_get("https://export.arxiv.org/rss/cs.AI")
    if not raw:
        return []
    root = ET.fromstring(raw)
    items = []
    for it in root.findall(".//item"):
        title = (re.sub(r"\s+", " ", it.findtext("title") or "")).strip()
        link  = (it.findtext("link")  or "").strip()
        desc  = _strip_html(it.findtext("description") or "")
        pd    = _parse_rfc2822(it.findtext("pubDate"))
        if not (title and link):
            continue
        # Try to get arxiv id from link
        m = re.search(r"abs/([0-9.]+)", link)
        if m:
            link = f"https://arxiv.org/abs/{m.group(1)}"
        items.append({
            "source_key": "arxiv",
            "source_label": "arXiv cs.AI",
            "title": title,
            "url": link,
            "desc": desc or title,
            "pubdate": pd,
        })
    return items


# Anthropic has no RSS — scrape the news page. Each entry is an
# `<a class="...gridItem" href="/news/..."> ... <time>...</time> ... <h4>Title</h4>
# ... <p>Body</p> </a>` chunk. We extract (slug, date, title, body) with a
# permissive regex; we skip an extra HTTP fetch by using the in-page text.
def fetch_anthropic() -> list[dict]:
    raw = safe_get("https://www.anthropic.com/news")
    if not raw:
        return []
    text = raw.decode("utf-8", "replace")

    # Split the HTML by "<a href=\"/news/" boundaries so each chunk is a
    # single article anchor.  Featured (h2) and side (h4) cards parse
    # identically: title heading + time + first paragraph.
    chunks = re.split(r'(?=<a\s+href="/news/)', text)

    seen = set()
    items = []
    for chunk in chunks:
        m = re.search(r'href="(/news/[a-z0-9-]+)"', chunk)
        if not m:
            continue
        slug = m.group(1)
        if slug in seen:
            continue
        mt = re.search(r'<h[23456][^>]*>([^<]+)</h[23456]>', chunk)
        md = re.search(r'<time[^>]*>([A-Z][a-z]{2,8} \d{1,2}, \d{4})</time>', chunk)
        mb = re.search(r'<p[^>]*>([^<]+)</p>', chunk)
        if not (mt and md and mb):
            continue
        title, date_s, body = mt.group(1).strip(), md.group(1), mb.group(1).strip()
        seen.add(slug)
        # decode HTML entities
        title = html.unescape(title)
        body  = html.unescape(body)
        # better title from og:title (optional, slow)
        # Skip the per-page fetch — page title is usually the same h4.
        try:
            pd = datetime.strptime(date_s, "%b %d, %Y").replace(tzinfo=timezone.utc)
        except ValueError:
            try:
                pd = datetime.strptime(date_s, "%B %d, %Y").replace(tzinfo=timezone.utc)
            except ValueError:
                pd = None
        items.append({
            "source_key": "anthropic",
            "source_label": "Anthropic News",
            "title": title,
            "url": f"https://www.anthropic.com{slug}",
            "desc": body,
            "pubdate": pd,
        })
    return items


# ---------------------------------------------------------------------------
# GitHub org commit feeds — pick the most "release-shaped" commits (messages
# that contain a version bump, merge, or feature description).  We avoid the
# "chore: Update CHANGELOG.md and feed.xml" auto-commit noise from claude-code.
# ---------------------------------------------------------------------------

GH_RELEASE_RE = re.compile(
    r"(?i)(v?\d+\.\d+(?:\.\d+)?|release|merge|pull request|feat|new|add|support|"
    r"introduc|launch|improv|upgrad|enhanc|fix|security|model|api|sdk|agent|claude|"
    r"gpt|gemini|reason|tool|integration|preview|beta|ga\b|generally available)"
)


def _gh_filter(title: str) -> bool:
    t = title.strip().lower()
    # Skip pure auto-feed commits
    if "update changelog" in t and "feed.xml" in t:
        return False
    if t.startswith("chore:") and "feed" in t:
        return False
    return bool(GH_RELEASE_RE.search(title))


def _gh_fetch(feed_url: str, source_key: str, source_label: str) -> list[dict]:
    raw = safe_get(feed_url)
    if not raw:
        return []
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(raw)
    items = []
    for it in root.findall("atom:entry", ns):
        t_el = it.find("atom:title", ns)
        u_el = it.find("atom:link", ns)
        u_el = it.find("atom:updated", ns)
        title = (t_el.text or "").strip() if t_el is not None else ""
        if not _gh_filter(title):
            continue
        link = ""
        for l in it.findall("atom:link", ns):
            if l.get("rel") in (None, "alternate"):
                link = l.get("href", "")
                break
        u_el = it.find("atom:updated", ns)
        pd = _parse_iso(u_el.text if u_el is not None else None)
        items.append({
            "source_key": source_key,
            "source_label": source_label,
            "title": title,
            "url": link,
            "desc": title,
            "pubdate": pd,
        })
    return items


def fetch_gh_anthropics() -> list[dict]:
    return _gh_fetch(
        "https://github.com/anthropics/claude-code/commits.atom",
        "anthropic",
        "GitHub anthropics",
    )


def fetch_gh_openai() -> list[dict]:
    items = _gh_fetch(
        "https://github.com/openai/openai-python/commits.atom",
        "openai",
        "GitHub openai",
    )
    # also pull openai-node commits and merge
    items += _gh_fetch(
        "https://github.com/openai/openai-node/commits.atom",
        "openai",
        "GitHub openai",
    )
    return items


def fetch_gh_deepmind() -> list[dict]:
    return _gh_fetch(
        "https://github.com/google-deepmind/optax/commits.atom",
        "deepmind",
        "GitHub google-deepmind",
    )


FETCHERS = {name: globals()[name] for name in
            ("fetch_hn", "fetch_openai", "fetch_deepmind", "fetch_arxiv",
             "fetch_anthropic", "fetch_gh_anthropics", "fetch_gh_openai",
             "fetch_gh_deepmind")}


# ---------------------------------------------------------------------------
# Scoring & picking 8-12 items
# ---------------------------------------------------------------------------

AI_KEYWORDS = (
    "ai", "llm", "gpt", "claude", "gemini", "agent", "model", "training",
    "inference", "openai", "anthropic", "deepmind", "deepseek", "mistral",
    "transformer", "diffusion", "multimodal", "rag", "embedding", "fine-tun",
    "alignment", "reasoning", "token", "context", "moe", "mixture", "attention",
    "rlhf", "dpo", "sft", "lora", "quantiz", "蒸馏", "微调", "大模型", "智能体",
    "推理", "对齐", "多模态", "RAG", "嵌入", "上下文", "训练", "强化学习",
    "benchmark", "evaluation", "evals", "agent", "tool", "function call",
    "code interpreter", "swe-bench", "humaneval", "mmlu", "arc-agi", "router",
    "chip", "tpu", "gpu", "h100", "b100", "tensor", "kernel", "cuda",
    "robotics", "embodied", "self-driving", "autonomous", "vla",
    "open source", "open-source", "开源", "release", "launch",
)


def _score(it: dict) -> float:
    text = (it["title"] + " " + it.get("desc", "")).lower()
    s = 0.0
    for kw in AI_KEYWORDS:
        if kw in text:
            s += 1
    if it.get("pubdate"):
        age_h = (datetime.now(timezone.utc) - it["pubdate"]).total_seconds() / 3600
        # hard floor: items older than 30 days get 0
        if age_h > 24 * 30:
            return -1e9
        # recency: 0h=4.0, 24h=2.0, 72h=1.0, 14d=0.0
        s += max(0.0, 4.0 * (1.0 - age_h / (24 * 14)))
    # boost first-party sources (their headline is usually high-signal)
    if it["source_key"] in ("openai", "anthropic", "deepmind"):
        s += 1.5
    return s


def pick(all_items: list[dict], target: int = 10) -> list[dict]:
    """Pick target items, balancing sources. Cap to 12, floor 8."""
    # Pre-filter: drop noise, then anything older than 30 days.
    fresh = [it for it in all_items if not _is_noise(it)
             and (it.get("pubdate") is None
                  or (datetime.now(timezone.utc) - it["pubdate"]).total_seconds() < 30 * 86400)]
    by_src: dict[str, list[dict]] = {}
    for it in fresh:
        by_src.setdefault(it["source_key"], []).append(it)
    for k in by_src:
        by_src[k].sort(key=_score, reverse=True)
    # Round-robin: take 2 from each source until target reached.
    # Sources in priority order so first-party gets represented.
    priority = ["openai", "anthropic", "deepmind", "arxiv", "hn", "github"]
    src_cycle = [k for k in priority if by_src.get(k)] + [k for k in by_src if k not in priority]
    picked: list[dict] = []
    seen_urls: set[str] = set()
    for round_idx in range(3):  # 3 rounds × 5-6 sources = 15 max
        for k in src_cycle:
            if len(picked) >= target:
                break
            bucket = by_src[k]
            if round_idx < len(bucket):
                cand = bucket[round_idx]
                if cand["url"] not in seen_urls:
                    seen_urls.add(cand["url"])
                    picked.append(cand)
    return picked[: max(8, min(12, target))]


# ---------------------------------------------------------------------------
# M3 Chinese summary — 60 chars, news-style
# ---------------------------------------------------------------------------

def m3_summarize(item: dict) -> str:
    """
    M3 (this model) produces the Chinese summary.  The cron script delegates
    to the LLM; here we provide a deterministic fallback that the caller
    can override before writing the RSS.

    The 60-char cap is strict: it must fit on one mobile line in Feedly.
    """
    raw = item.get("m3_summary")
    if raw:
        return raw[:60]
    # Fallback: take first 60 chars of cleaned title.
    t = re.sub(r"\s+", " ", item["title"]).strip()
    return t[:60]


# ---------------------------------------------------------------------------
# RSS 2.0 renderer
# ---------------------------------------------------------------------------

def render_rss(picked: list[dict], now: datetime) -> str:
    now = now.astimezone(timezone.utc)
    by_src_groups: dict[str, list[dict]] = {}
    for it in picked:
        by_src_groups.setdefault(it["source_label"], []).append(it)

    # group display order (stable)
    preferred = [
        "OpenAI Blog", "Anthropic News", "DeepMind Blog",
        "Hacker News", "arXiv cs.AI",
        "GitHub anthropics", "GitHub openai", "GitHub google-deepmind",
    ]
    ordered_labels = [k for k in preferred if k in by_src_groups]
    ordered_labels += [k for k in by_src_groups if k not in preferred]

    lines: list[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('<rss version="2.0" '
                 'xmlns:atom="http://www.w3.org/2005/Atom" '
                 'xmlns:media="http://search.yahoo.com/mrss/">')
    lines.append("  <channel>")
    lines.append("    <title>AI 圈每日精华</title>")
    lines.append(
        f"    <description>每日 07:00 (Asia/Shanghai) 自动抓取 8 个一手信源 "
        f"(HN / OpenAI / Anthropic / DeepMind / arXiv / GitHub anthropics,openai,google-deepmind),"
        f"M3 中文摘要 60 字以内。本次共 {len(picked)} 条。</description>"
    )
    lines.append(f"    <link>{GITHUB_PAGES_BASE}/</link>")
    self_href = f"{GITHUB_PAGES_BASE}/rss/ai-daily.xml"
    lines.append(
        f'    <atom:link rel="self" type="application/rss+xml" '
        f'href="{xml_escape(self_href)}"/>'
    )
    lines.append("    <language>zh-CN</language>")
    lines.append(f"    <lastBuildDate>{format_datetime(now, usegmt=True)}</lastBuildDate>")
    lines.append("    <generator>daily-briefing/0.4 (M3 cron)</generator>")
    lines.append("    <ttl>5</ttl>")

    for it in picked:
        title = m3_summarize(it) or it["title"]
        title_esc = xml_escape(title).replace('"', "&quot;")
        url_esc = xml_escape(it["url"])
        desc_text = it.get("desc") or title
        if len(desc_text) > 200:
            desc_text = desc_text[:197] + "..."
        desc_esc = xml_escape(desc_text)
        # ensure & escape (xml_escape does &, <, >)
        # pubDate — RFC 2822
        pd = it.get("pubdate")
        if pd is None:
            pd = now
        pd_rfc = format_datetime(pd.astimezone(timezone.utc), usegmt=True)
        # category (group label)
        cat = xml_escape(it["source_label"])
        # guid — use stable hash of url
        import hashlib
        guid = "ai-daily-" + hashlib.sha1(it["url"].encode()).hexdigest()[:12]
        # media:thumbnail per source
        logo = LOGO.get(it["source_key"])
        thumb_url = f"{LOGOS_BASE}/{logo}" if logo else f"{LOGOS_BASE}/openai.svg"

        lines.append("    <item>")
        lines.append(f"      <title>{title_esc}</title>")
        lines.append(f"      <description>{desc_esc}</description>")
        lines.append(f"      <link>{url_esc}</link>")
        lines.append(f'      <guid isPermaLink="false">{guid}</guid>')
        lines.append(f"      <pubDate>{pd_rfc}</pubDate>")
        lines.append(f"      <category>{cat}</category>")
        lines.append(f'      <media:thumbnail url="{xml_escape(thumb_url)}"/>')
        lines.append("    </item>")

    lines.append("  </channel>")
    lines.append("</rss>")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# HTML digest renderer
# ---------------------------------------------------------------------------

HTML_TEMPLATE_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; img-src 'self' data:; style-src 'unsafe-inline'; script-src 'none'; font-src 'self'; base-uri 'none'; form-action 'none';">
<title>AI 圈每日精华 · {date_label} · Daily Briefing</title>
<style>
:root{{
  --bg:#0b0e14;--surface:#131720;--surface2:#1a1f2c;--border:#262c3d;--text:#e6e8f0;--text2:#8a90a8;--text3:#5d6378;
  --accent:#6ea8fe;--accent2:#b197fc;--blue:#4285F4;--green:#34A853;--red:#EA4335;--yellow:#FBBC05;--orange:#FF6600;--teal:#10A37F;
  --radius:12px;--radius-sm:6px;--shadow:0 1px 0 rgba(255,255,255,.04) inset,0 1px 3px rgba(0,0,0,.2);
  --font-sans:"PingFang SC","Hiragino Sans GB","Microsoft YaHei","Source Han Sans CN","Noto Sans CJK SC",system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  --font-serif:"Source Han Serif SC","Noto Serif CJK SC","Songti SC","STSong",Georgia,serif;
  --font-mono:"JetBrains Mono","SF Mono","Cascadia Code",Consolas,monospace;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
html{{-webkit-text-size-adjust:100%;text-size-adjust:100%}}
body{{background:var(--bg);color:var(--text);font-family:var(--font-sans);font-size:16px;line-height:1.8;font-feature-settings:"kern","tnum","palt","calt";-webkit-font-smoothing:antialiased;letter-spacing:.01em}}
a{{color:var(--accent);text-decoration:none;transition:color .15s}}a:hover{{color:var(--accent2);text-decoration:underline;text-underline-offset:3px;text-decoration-thickness:1px}}
img,svg{{display:block;max-width:100%;height:auto}}
:focus-visible{{outline:2px solid var(--accent);outline-offset:3px;border-radius:4px}}
.skip-link{{position:absolute;top:-40px;left:8px;background:var(--accent);color:#000;padding:8px 16px;border-radius:6px;z-index:100;font-weight:600;transition:top .2s}}.skip-link:focus{{top:8px}}
.container{{max-width:1100px;margin:0 auto;padding:0 24px}}
.hero{{position:relative;padding:64px 0 48px;background:radial-gradient(ellipse at top,rgba(110,168,254,.08),transparent 60%),var(--bg);border-bottom:1px solid var(--border);overflow:hidden}}
.hero::before{{content:"";position:absolute;width:300px;height:300px;background:radial-gradient(circle,rgba(177,151,252,.12),transparent 70%);top:-100px;right:-50px;pointer-events:none}}
.hero h1{{font-size:clamp(28px,4.5vw,48px);font-weight:800;line-height:1.2;letter-spacing:-.02em;margin-bottom:12px;background:linear-gradient(135deg,var(--text) 0%,var(--accent) 60%,var(--accent2) 100%);-webkit-background-clip:text;background-clip:text;color:transparent}}
.hero .subtitle{{font-size:clamp(15px,1.6vw,18px);color:var(--text2);font-weight:400;margin-bottom:24px;font-family:var(--font-serif);font-style:italic}}
.hero .meta{{display:flex;flex-wrap:wrap;gap:16px;align-items:center;font-size:14px;color:var(--text2)}}
.hero .meta time{{font-family:var(--font-mono);color:var(--text)}}
.hero .meta .dot{{width:4px;height:4px;background:var(--text3);border-radius:50%}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;padding:32px 0;border-bottom:1px solid var(--border)}}
.stat{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:20px 24px;transition:transform .2s,border-color .2s}}.stat:hover{{transform:translateY(-2px);border-color:var(--accent)}}
.stat .label{{font-size:12px;color:var(--text2);text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px;font-weight:500}}
.stat .value{{font-size:clamp(28px,3.5vw,36px);font-weight:800;line-height:1;background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;background-clip:text;color:transparent;font-feature-settings:"tnum"}}
.stat .delta{{font-size:13px;color:var(--text2);margin-top:6px}}
.section-nav{{position:sticky;top:0;background:rgba(11,14,20,.85);backdrop-filter:saturate(180%) blur(20px);-webkit-backdrop-filter:saturate(180%) blur(20px);border-bottom:1px solid var(--border);z-index:50;padding:12px 0;margin-bottom:32px}}
.section-nav ul{{list-style:none;display:flex;flex-wrap:wrap;gap:4px}}
.section-nav a{{display:block;padding:8px 14px;border-radius:8px;font-size:14px;color:var(--text2);transition:background .15s,color .15s}}.section-nav a:hover{{background:var(--surface2);color:var(--text);text-decoration:none}}
main{{padding-bottom:64px}}
.source-group{{margin-bottom:56px}}
.source-group h2{{font-size:22px;font-weight:700;margin-bottom:20px;display:flex;align-items:center;gap:12px;padding-bottom:12px;border-bottom:1px solid var(--border);letter-spacing:-.01em}}
.source-group h2 img{{width:32px;height:32px;border-radius:8px;flex-shrink:0}}
.source-group h2 .count{{font-size:13px;font-weight:500;color:var(--text2);background:var(--surface);padding:2px 10px;border-radius:12px;font-family:var(--font-mono)}}
.cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,460px),1fr));gap:16px}}
article.card{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:20px 24px;transition:transform .2s,border-color .2s,box-shadow .2s;display:flex;flex-direction:column;gap:8px}}
article.card:hover{{transform:translateY(-2px);border-color:var(--accent);box-shadow:0 8px 24px rgba(0,0,0,.3)}}
.card .card-header{{display:flex;align-items:flex-start;gap:12px}}
.card .source-logo{{width:40px;height:40px;border-radius:10px;flex-shrink:0;background:var(--surface2);padding:4px}}
.card h3{{font-size:17px;font-weight:600;line-height:1.45;letter-spacing:-.01em;flex:1}}
.card h3 a{{color:var(--text)}}.card h3 a:hover{{color:var(--accent);text-decoration:none}}
.card .desc{{color:var(--text2);font-size:14.5px;line-height:1.7;margin-top:4px}}
.card .card-footer{{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:12px;padding-top:12px;border-top:1px solid var(--border);font-size:13px;color:var(--text3)}}
.card .card-footer time{{font-family:var(--font-mono)}}
.card .card-footer a{{color:var(--text2);font-weight:500}}.card .card-footer a:hover{{color:var(--accent)}}
footer.site-footer{{padding:48px 0 64px;border-top:1px solid var(--border);background:var(--surface);color:var(--text2);font-size:14px}}
footer h2{{color:var(--text);font-size:18px;margin-bottom:16px;font-weight:600}}
footer .footer-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:32px;margin-bottom:32px}}
footer ul{{list-style:none}}
footer li{{padding:6px 0;border-bottom:1px dashed var(--border)}}
footer li:last-child{{border:none}}
footer .copy{{text-align:center;padding-top:24px;border-top:1px solid var(--border);color:var(--text3);font-size:13px}}
@media (max-width:640px){{
  .hero{{padding:40px 0 32px}}
  .stats{{grid-template-columns:repeat(2,1fr);gap:12px;padding:20px 0}}
  .stat{{padding:16px}}
  .section-nav{{position:static}}
  .cards{{grid-template-columns:1fr}}
  article.card{{padding:16px}}
}}
@media (prefers-reduced-motion:reduce){{*{{transition:none !important;animation:none !important}}}}
</style>
</head>
<body>
<a href="#main" class="skip-link">跳到主要内容</a>

<header class="hero" role="banner">
  <div class="container">
    <h1>AI 圈每日精华</h1>
    <p class="subtitle">M3 自动化汇总 8 个一手信源,中文摘要 60 字以内,8-12 条要点</p>
    <div class="meta">
      <time datetime="{date_iso}">{date_label}</time>
      <span class="dot" aria-hidden="true"></span>
      <span>{n_items} 条新闻 · {n_sources} 个信源</span>
      <span class="dot" aria-hidden="true"></span>
      <span>由 <a href="https://github.com/SeasonTemple/daily-briefing">daily-briefing</a> 自动生成</span>
    </div>
  </div>
</header>

<nav class="section-nav" aria-label="信源导航">
  <div class="container">
    <ul>
{nav_links}
      <li><a href="#subscribe">订阅</a></li>
    </ul>
  </div>
</nav>

<main id="main" class="container" tabindex="-1">

<section class="stats" aria-label="数据概览">
  <div class="stat"><div class="label">总条目</div><div class="value">{n_items}</div><div class="delta">今日筛选后</div></div>
  <div class="stat"><div class="label">信源覆盖</div><div class="value">{n_sources}</div><div class="delta">从 8 个目标中成功</div></div>
  <div class="stat"><div class="label">Top 话题</div><div class="value">{top_topic}</div><div class="delta">本批最热</div></div>
  <div class="stat"><div class="label">生成耗时</div><div class="value">~{gen_seconds}s</div><div class="delta">cron 跑通</div></div>
</section>
"""


def _slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", s).strip("-").lower()
    return s or "x"


def render_html(picked: list[dict], now: datetime, gen_seconds: int) -> str:
    shanghai = timezone(timedelta(hours=8))
    now_sha = now.astimezone(shanghai)
    date_iso = now_sha.strftime("%Y-%m-%d")
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now_sha.weekday()]
    date_label = f"{date_iso} · {weekday}"

    # group
    by_src: dict[str, list[dict]] = {}
    for it in picked:
        by_src.setdefault(it["source_label"], []).append(it)

    preferred = ["OpenAI Blog", "Anthropic News", "DeepMind Blog",
                 "Hacker News", "arXiv cs.AI",
                 "GitHub anthropics", "GitHub openai", "GitHub google-deepmind"]
    ordered_labels = [k for k in preferred if k in by_src]
    ordered_labels += [k for k in by_src if k not in preferred]

    nav_links = "\n".join(
        f'      <li><a href="#{_slugify(lab)}">{lab} ({len(by_src[lab])})</a></li>'
        for lab in ordered_labels
    )

    # top topic: most common keyword
    word_counts: dict[str, int] = {}
    for it in picked:
        for kw in ("GPT", "Claude", "Gemini", "Agent", "DeepMind", "OpenAI",
                   "Anthropic", "arXiv", "RAG", "LLM"):
            if kw.lower() in (it["title"] + it.get("desc", "")).lower():
                word_counts[kw] = word_counts.get(kw, 0) + 1
    top_topic = max(word_counts, key=word_counts.get) if word_counts else "AI"

    head = HTML_TEMPLATE_HEAD.format(
        date_label=date_label, date_iso=date_iso,
        n_items=len(picked), n_sources=len(by_src),
        nav_links=nav_links, top_topic=top_topic,
        gen_seconds=gen_seconds,
    )

    body_parts: list[str] = []
    for lab in ordered_labels:
        items = by_src[lab]
        key = items[0]["source_key"]
        logo_file = LOGO.get(key, "openai.svg")
        section_id = _slugify(lab)
        body_parts.append(
            f'<section class="source-group" id="{section_id}" aria-labelledby="{section_id}-h">\n'
            f'  <h2 id="{section_id}-h"><img src="../assets/logos/{logo_file}" alt="">{lab} '
            f'<span class="count">{len(items)}</span></h2>\n'
            f'  <div class="cards">\n'
        )
        for it in items:
            title = m3_summarize(it) or it["title"]
            desc  = it.get("desc") or title
            if len(desc) > 220:
                desc = desc[:217] + "…"
            pd = it.get("pubdate")
            pd_iso = pd.strftime("%Y-%m-%d") if pd else ""
            link_text = "查看讨论 →" if it["source_key"] == "hn" else "阅读原文 →"
            body_parts.append(f"""    <article class="card">
      <div class="card-header">
        <img class="source-logo" src="../assets/logos/{logo_file}" alt="" aria-hidden="true">
        <h3><a href="{html.escape(it['url'])}" target="_blank" rel="noopener">{html.escape(title)}</a></h3>
      </div>
      <p class="desc">{html.escape(desc)}</p>
      <div class="card-footer"><time datetime="{pd_iso}">{pd_iso}</time><a href="{html.escape(it['url'])}" target="_blank" rel="noopener">{link_text}</a></div>
    </article>
""")
        body_parts.append("  </div>\n</section>\n\n")

    body = "".join(body_parts)

    footer = """<footer class="site-footer" id="subscribe" role="contentinfo">
  <div class="container">
    <h2>订阅 · 让日报自动送到你那里</h2>
    <div class="footer-grid">
      <div>
        <h2>RSS 订阅</h2>
        <ul>
          <li>AI 每日精华 → <a href="../rss/ai-daily.xml">rss/ai-daily.xml</a></li>
          <li>直接复制到 Feedly / Inoreader / NetNewsWire</li>
        </ul>
      </div>
      <div>
        <h2>本站说明</h2>
        <ul>
          <li>每日 07:00 (Asia/Shanghai) 自动抓取</li>
          <li>8 个一手信源:M3 中文摘要</li>
          <li>代码开源 · 仅供学习与参考</li>
        </ul>
      </div>
    </div>
    <div class="copy">© Daily Briefing · 自动生成,不代表任何机构观点</div>
  </div>
</footer>

</body>
</html>
"""
    return head + body + footer


# ---------------------------------------------------------------------------
# RSS validation
# ---------------------------------------------------------------------------

def validate_rss(path: Path) -> tuple[bool, str]:
    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        return False, f"xml.etree ParseError: {e}"
    root = tree.getroot()
    if root.tag != "rss":
        return False, f"root tag is {root.tag!r}, expected 'rss'"
    ver = root.get("version")
    if ver != "2.0":
        return False, f"rss version={ver!r}, expected '2.0'"
    chan = root.find("channel")
    if chan is None:
        return False, "no <channel>"
    items = chan.findall("item")
    if len(items) < 8 or len(items) > 12:
        return False, f"item count {len(items)} not in 8..12"
    for i, it in enumerate(items):
        for tag in ("title", "link", "guid", "pubDate"):
            if it.find(tag) is None:
                return False, f"item[{i}] missing <{tag}>"
        # RSS 2.0 + media thumbnail must be present
        thumb = it.find("{http://search.yahoo.com/mrss/}thumbnail")
        if thumb is None:
            return False, f"item[{i}] missing <media:thumbnail>"
    ttl = chan.find("ttl")
    if ttl is None or (ttl.text or "").strip() != "5":
        return False, "missing or non-5 <ttl>"
    self_link = chan.find("{http://www.w3.org/2005/Atom}link")
    if self_link is None or not (self_link.get("href") or "").startswith("https://"):
        return False, "atom:link rel=self is missing or not HTTPS"
    # No CDATA allowed
    raw = path.read_text(encoding="utf-8")
    if "<![CDATA" in raw:
        return False, "found <![CDATA[ ... ]]> (must use escaped XML)"
    return True, f"OK · {len(items)} items"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    started = time.time()
    now = datetime.now(timezone.utc)

    print(f"=== Daily Briefing v2 · {now.isoformat()} ===")
    print(f"Repo: {REPO}")
    print(f"RSS out: {RSS_OUT}")
    print(f"HTML out: {HTML_OUT}")

    # 1) Fetch
    all_items: list[dict] = []
    src_status: dict[str, int] = {}
    for key, label, fname in SOURCES:
        print(f"  fetch {label} ({fname})")
        fn = FETCHERS[fname]
        try:
            items = fn()
        except Exception as e:
            print(f"    EXC: {e}")
            items = []
        src_status[label] = len(items)
        all_items += items
        print(f"    → {len(items)} items")

    # 2) Pick
    picked = pick(all_items, target=10)
    print(f"Picked: {len(picked)} items")
    for it in picked:
        print(f"  - [{it['source_label']:>22}] {it['title'][:60]}")

    # 3) RSS
    rss_xml = render_rss(picked, now)
    RSS_OUT.parent.mkdir(parents=True, exist_ok=True)
    RSS_OUT.write_text(rss_xml, encoding="utf-8")
    print(f"Wrote {RSS_OUT} ({len(rss_xml)} bytes)")

    # 4) HTML
    gen_seconds = max(1, int(time.time() - started))
    html_doc = render_html(picked, now, gen_seconds)
    HTML_OUT.parent.mkdir(parents=True, exist_ok=True)
    HTML_OUT.write_text(html_doc, encoding="utf-8")
    print(f"Wrote {HTML_OUT} ({len(html_doc)} bytes)")

    # 5) Validate
    ok, msg = validate_rss(RSS_OUT)
    print(f"Validate RSS: {msg}")
    if not ok:
        return 2

    print("DONE.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
