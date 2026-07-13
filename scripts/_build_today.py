#!/usr/bin/env python3
"""
_build_today.py — v2 finalizer.

This is run by the M3 cron session AFTER fetching with daily_briefing.py.
The 10 picked items + M3-curated Chinese summaries are passed in as JSON.

Outputs:
  - rss/ai-daily.xml        (strict RSS 2.0 with media:thumbnail)
  - digests/ai-daily.html   (dark, zh-CN, a11y, card grid)
"""
from __future__ import annotations

import json
import sys
import hashlib
import argparse
import html
import re
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

REPO = Path("/tmp/daily-briefing")
RSS_OUT = REPO / "rss" / "ai-daily.xml"
HTML_OUT = REPO / "digests" / "ai-daily.html"
GITHUB_PAGES_BASE = "https://seasontemple.github.io/daily-briefing"
LOGOS_BASE = f"{GITHUB_PAGES_BASE}/assets/logos"

LOGO = {
    "openai":    "openai.svg",
    "anthropic": "anthropic.svg",
    "deepmind":  "deepmind.svg",
    "hn":        "hackernews.svg",
    "arxiv":     "arxiv.svg",
}

# Source label slug used in HTML section ids
SLUG = {
    "OpenAI Blog":              "openai",
    "Anthropic News":           "anthropic",
    "DeepMind Blog":            "deepmind",
    "Hacker News":              "hn",
    "arXiv cs.AI":              "arxiv",
    "GitHub openai":            "gh-openai",
    "GitHub anthropics":        "gh-anthropics",
    "GitHub google-deepmind":   "gh-deepmind",
}


def parse_iso(s: str) -> datetime:
    s = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def write_rss(items: list[dict], now: datetime) -> str:
    self_href = f"{LOGOS_BASE.replace('assets/logos', 'rss/ai-daily.xml')}"
    # Correct self link:
    self_href = f"{GITHUB_PAGES_BASE}/rss/ai-daily.xml"
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append(
        '<rss version="2.0" '
        'xmlns:atom="http://www.w3.org/2005/Atom" '
        'xmlns:media="http://search.yahoo.com/mrss/">'
    )
    lines.append("  <channel>")
    lines.append("    <title>AI 圈每日精华</title>")
    sources_repr = " / ".join(
        sorted({it["source_label"] for it in items})
    )
    lines.append(
        f"    <description>每日 07:00 (Asia/Shanghai) 自动抓取 8 个一手信源 "
        f"({sources_repr}),M3 中文摘要 60 字以内。本次共 {len(items)} 条。</description>"
    )
    lines.append(f"    <link>{GITHUB_PAGES_BASE}/</link>")
    lines.append(
        f'    <atom:link rel="self" type="application/rss+xml" '
        f'href="{xml_escape(self_href)}"/>'
    )
    lines.append("    <language>zh-CN</language>")
    lines.append(f"    <lastBuildDate>{format_datetime(now, usegmt=True)}</lastBuildDate>")
    lines.append("    <generator>daily-briefing/0.4 (M3 cron)</generator>")
    lines.append("    <ttl>5</ttl>")

    for it in items:
        title  = it["m3_title"]
        if not title:
            title = it["title"]
        if len(title) > 60:
            title = title[:60]
        title_esc = xml_escape(title).replace('"', "&quot;")
        url_esc   = xml_escape(it["url"])
        desc      = it.get("m3_summary") or it.get("desc") or title
        if len(desc) > 240:
            desc = desc[:237] + "..."
        desc_esc  = xml_escape(desc)
        pd        = parse_iso(it["pubdate"])
        pd_rfc    = format_datetime(pd, usegmt=True)
        cat       = xml_escape(it["source_label"])
        guid      = "ai-daily-" + hashlib.sha1(it["url"].encode()).hexdigest()[:12]
        logo      = LOGO.get(it["source_key"], "openai.svg")
        thumb     = f"{LOGOS_BASE}/{logo}"

        lines.append("    <item>")
        lines.append(f"      <title>{title_esc}</title>")
        lines.append(f"      <description>{desc_esc}</description>")
        lines.append(f"      <link>{url_esc}</link>")
        lines.append(f'      <guid isPermaLink="false">{guid}</guid>')
        lines.append(f"      <pubDate>{pd_rfc}</pubDate>")
        lines.append(f"      <category>{cat}</category>")
        lines.append(f'      <media:thumbnail url="{xml_escape(thumb)}"/>')
        lines.append("    </item>")
    lines.append("  </channel>")
    lines.append("</rss>")
    return "\n".join(lines) + "\n"


def write_html(items: list[dict], now: datetime, gen_seconds: int) -> str:
    sh = timezone(timedelta(hours=8))
    now_sha = now.astimezone(sh)
    date_iso = now_sha.strftime("%Y-%m-%d")
    wd = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now_sha.weekday()]
    date_label = f"{date_iso} · {wd}"

    by_label: dict[str, list[dict]] = {}
    for it in items:
        by_label.setdefault(it["source_label"], []).append(it)

    preferred = ["OpenAI Blog", "Anthropic News", "DeepMind Blog",
                 "Hacker News", "arXiv cs.AI",
                 "GitHub openai", "GitHub anthropics", "GitHub google-deepmind"]
    ordered = [k for k in preferred if k in by_label] + [k for k in by_label if k not in preferred]

    nav_links = "\n".join(
        f'      <li><a href="#{SLUG.get(lab, lab.lower().replace(" ", "-"))}">{lab} ({len(by_label[lab])})</a></li>'
        for lab in ordered
    )

    # Top topic
    word_count: dict[str, int] = {}
    for it in items:
        text = (it["m3_title"] + " " + it.get("m3_summary", "")).lower()
        for kw in ("GPT-5", "Claude", "Gemini", "Agent", "OpenAI", "Anthropic",
                   "DeepMind", "RAG", "LLM", "arXiv"):
            if kw.lower() in text:
                word_count[kw] = word_count.get(kw, 0) + 1
    top_topic = max(word_count, key=word_count.get) if word_count else "AI"

    css = CSS  # see below
    out = []
    out.append('<!DOCTYPE html>')
    out.append('<html lang="zh-CN">')
    out.append('<head>')
    out.append('<meta charset="UTF-8">')
    out.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
    out.append(
        '<meta http-equiv="Content-Security-Policy" '
        'content="default-src \'self\'; img-src \'self\' data: https://seasontemple.github.io; '
        'style-src \'unsafe-inline\'; script-src \'none\'; font-src \'self\'; '
        'base-uri \'none\'; form-action \'none\';">'
    )
    out.append(f'<title>AI 圈每日精华 · {date_label} · Daily Briefing</title>')
    out.append('<style>')
    out.append(css)
    out.append('</style>')
    out.append('</head>')
    out.append('<body>')
    out.append('<a href="#main" class="skip-link">跳到主要内容</a>')

    out.append('<header class="hero" role="banner">')
    out.append('  <div class="container">')
    out.append('    <h1>AI 圈每日精华</h1>')
    out.append('    <p class="subtitle">M3 自动化汇总 8 个一手信源,中文摘要 60 字以内,8-12 条要点</p>')
    out.append('    <div class="meta">')
    out.append(f'      <time datetime="{date_iso}">{date_label}</time>')
    out.append('      <span class="dot" aria-hidden="true"></span>')
    out.append(f'      <span>{len(items)} 条新闻 · {len(by_label)} 个信源</span>')
    out.append('      <span class="dot" aria-hidden="true"></span>')
    out.append('      <span>由 <a href="https://github.com/SeasonTemple/daily-briefing">daily-briefing</a> 自动生成</span>')
    out.append('    </div>')
    out.append('  </div>')
    out.append('</header>')

    out.append('<nav class="section-nav" aria-label="信源导航">')
    out.append('  <div class="container">')
    out.append('    <ul>')
    out.append(nav_links)
    out.append('      <li><a href="#subscribe">订阅</a></li>')
    out.append('    </ul>')
    out.append('  </div>')
    out.append('</nav>')

    out.append('<main id="main" class="container" tabindex="-1">')
    out.append('<section class="stats" aria-label="数据概览">')
    out.append(f'  <div class="stat"><div class="label">总条目</div><div class="value">{len(items)}</div><div class="delta">今日筛选后</div></div>')
    out.append(f'  <div class="stat"><div class="label">信源覆盖</div><div class="value">{len(by_label)}</div><div class="delta">从 8 个目标中成功</div></div>')
    out.append(f'  <div class="stat"><div class="label">Top 话题</div><div class="value">{html.escape(top_topic)}</div><div class="delta">本批最热</div></div>')
    out.append(f'  <div class="stat"><div class="label">生成耗时</div><div class="value">~{gen_seconds}s</div><div class="delta">cron 跑通</div></div>')
    out.append('</section>')

    for lab in ordered:
        group = by_label[lab]
        sec_id = SLUG.get(lab, lab.lower().replace(" ", "-"))
        key = group[0]["source_key"]
        logo = LOGO.get(key, "openai.svg")
        out.append(f'<section class="source-group" id="{sec_id}" aria-labelledby="{sec_id}-h">')
        out.append(f'  <h2 id="{sec_id}-h"><img src="../assets/logos/{logo}" alt="">{html.escape(lab)} <span class="count">{len(group)}</span></h2>')
        out.append('  <div class="cards">')
        for it in group:
            title  = it["m3_title"] or it["title"]
            if len(title) > 60:
                title = title[:60]
            desc   = it.get("m3_summary") or it.get("desc") or title
            if len(desc) > 220:
                desc = desc[:217] + "…"
            pd     = parse_iso(it["pubdate"])
            pd_iso = pd.strftime("%Y-%m-%d")
            link_text = "查看讨论 →" if it["source_key"] == "hn" else "阅读原文 →"
            out.append(f'    <article class="card">')
            out.append(f'      <div class="card-header">')
            out.append(f'        <img class="source-logo" src="../assets/logos/{logo}" alt="" aria-hidden="true">')
            out.append(f'        <h3><a href="{html.escape(it["url"])}" target="_blank" rel="noopener">{html.escape(title)}</a></h3>')
            out.append(f'      </div>')
            out.append(f'      <p class="desc">{html.escape(desc)}</p>')
            out.append(f'      <div class="card-footer"><time datetime="{pd_iso}">{pd_iso}</time><a href="{html.escape(it["url"])}" target="_blank" rel="noopener">{link_text}</a></div>')
            out.append(f'    </article>')
        out.append('  </div>')
        out.append('</section>')
        out.append('')

    out.append('</main>')

    out.append('<footer class="site-footer" id="subscribe" role="contentinfo">')
    out.append('  <div class="container">')
    out.append('    <h2>订阅 · 让日报自动送到你那里</h2>')
    out.append('    <div class="footer-grid">')
    out.append('      <div>')
    out.append('        <h2>RSS 订阅</h2>')
    out.append('        <ul>')
    out.append('          <li>AI 每日精华 → <a href="../rss/ai-daily.xml">rss/ai-daily.xml</a></li>')
    out.append('          <li>直接复制到 Feedly / Inoreader / NetNewsWire</li>')
    out.append('        </ul>')
    out.append('      </div>')
    out.append('      <div>')
    out.append('        <h2>本站说明</h2>')
    out.append('        <ul>')
    out.append('          <li>每日 07:00 (Asia/Shanghai) 自动抓取</li>')
    out.append('          <li>8 个一手信源:M3 中文摘要</li>')
    out.append('          <li>代码开源 · 仅供学习与参考</li>')
    out.append('        </ul>')
    out.append('      </div>')
    out.append('    </div>')
    out.append('    <div class="copy">© Daily Briefing · 自动生成,不代表任何机构观点</div>')
    out.append('  </div>')
    out.append('</footer>')
    out.append('</body>')
    out.append('</html>')
    return "\n".join(out) + "\n"


# CSS verbatim from existing digests/ai-daily.html (so visual continuity is preserved)
CSS = """:root{
  --bg:#0b0e14;--surface:#131720;--surface2:#1a1f2c;--border:#262c3d;--text:#e6e8f0;--text2:#8a90a8;--text3:#5d6378;
  --accent:#6ea8fe;--accent2:#b197fc;--blue:#4285F4;--green:#34A853;--red:#EA4335;--yellow:#FBBC05;--orange:#FF6600;--teal:#10A37F;
  --radius:12px;--radius-sm:6px;--shadow:0 1px 0 rgba(255,255,255,.04) inset,0 1px 3px rgba(0,0,0,.2);
  --font-sans:"PingFang SC","Hiragino Sans GB","Microsoft YaHei","Source Han Sans CN","Noto Sans CJK SC",system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  --font-serif:"Source Han Serif SC","Noto Serif CJK SC","Songti SC","STSong",Georgia,serif;
  --font-mono:"JetBrains Mono","SF Mono","Cascadia Code",Consolas,monospace;
}
*{box-sizing:border-box;margin:0;padding:0}
html{-webkit-text-size-adjust:100%;text-size-adjust:100%}
body{background:var(--bg);color:var(--text);font-family:var(--font-sans);font-size:16px;line-height:1.8;font-feature-settings:"kern","tnum","palt","calt";-webkit-font-smoothing:antialiased;letter-spacing:.01em}
a{color:var(--accent);text-decoration:none;transition:color .15s}a:hover{color:var(--accent2);text-decoration:underline;text-underline-offset:3px;text-decoration-thickness:1px}
img,svg{display:block;max-width:100%;height:auto}
:focus-visible{outline:2px solid var(--accent);outline-offset:3px;border-radius:4px}
.skip-link{position:absolute;top:-40px;left:8px;background:var(--accent);color:#000;padding:8px 16px;border-radius:6px;z-index:100;font-weight:600;transition:top .2s}.skip-link:focus{top:8px}
.container{max-width:1100px;margin:0 auto;padding:0 24px}
.hero{position:relative;padding:64px 0 48px;background:radial-gradient(ellipse at top,rgba(110,168,254,.08),transparent 60%),var(--bg);border-bottom:1px solid var(--border);overflow:hidden}
.hero::before{content:"";position:absolute;width:300px;height:300px;background:radial-gradient(circle,rgba(177,151,252,.12),transparent 70%);top:-100px;right:-50px;pointer-events:none}
.hero h1{font-size:clamp(28px,4.5vw,48px);font-weight:800;line-height:1.2;letter-spacing:-.02em;margin-bottom:12px;background:linear-gradient(135deg,var(--text) 0%,var(--accent) 60%,var(--accent2) 100%);-webkit-background-clip:text;background-clip:text;color:transparent}
.hero .subtitle{font-size:clamp(15px,1.6vw,18px);color:var(--text2);font-weight:400;margin-bottom:24px;font-family:var(--font-serif);font-style:italic}
.hero .meta{display:flex;flex-wrap:wrap;gap:16px;align-items:center;font-size:14px;color:var(--text2)}
.hero .meta time{font-family:var(--font-mono);color:var(--text)}
.hero .meta .dot{width:4px;height:4px;background:var(--text3);border-radius:50%}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;padding:32px 0;border-bottom:1px solid var(--border)}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:20px 24px;transition:transform .2s,border-color .2s}.stat:hover{transform:translateY(-2px);border-color:var(--accent)}
.stat .label{font-size:12px;color:var(--text2);text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px;font-weight:500}
.stat .value{font-size:clamp(28px,3.5vw,36px);font-weight:800;line-height:1;background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;background-clip:text;color:transparent;font-feature-settings:"tnum"}
.stat .delta{font-size:13px;color:var(--text2);margin-top:6px}
.section-nav{position:sticky;top:0;background:rgba(11,14,20,.85);backdrop-filter:saturate(180%) blur(20px);-webkit-backdrop-filter:saturate(180%) blur(20px);border-bottom:1px solid var(--border);z-index:50;padding:12px 0;margin-bottom:32px}
.section-nav ul{list-style:none;display:flex;flex-wrap:wrap;gap:4px}
.section-nav a{display:block;padding:8px 14px;border-radius:8px;font-size:14px;color:var(--text2);transition:background .15s,color .15s}.section-nav a:hover{background:var(--surface2);color:var(--text);text-decoration:none}
main{padding-bottom:64px}
.source-group{margin-bottom:56px}
.source-group h2{font-size:22px;font-weight:700;margin-bottom:20px;display:flex;align-items:center;gap:12px;padding-bottom:12px;border-bottom:1px solid var(--border);letter-spacing:-.01em}
.source-group h2 img{width:32px;height:32px;border-radius:8px;flex-shrink:0}
.source-group h2 .count{font-size:13px;font-weight:500;color:var(--text2);background:var(--surface);padding:2px 10px;border-radius:12px;font-family:var(--font-mono)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,460px),1fr));gap:16px}
article.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:20px 24px;transition:transform .2s,border-color .2s,box-shadow .2s;display:flex;flex-direction:column;gap:8px}
article.card:hover{transform:translateY(-2px);border-color:var(--accent);box-shadow:0 8px 24px rgba(0,0,0,.3)}
.card .card-header{display:flex;align-items:flex-start;gap:12px}
.card .source-logo{width:40px;height:40px;border-radius:10px;flex-shrink:0;background:var(--surface2);padding:4px}
.card h3{font-size:17px;font-weight:600;line-height:1.45;letter-spacing:-.01em;flex:1}
.card h3 a{color:var(--text)}.card h3 a:hover{color:var(--accent);text-decoration:none}
.card .desc{color:var(--text2);font-size:14.5px;line-height:1.7;margin-top:4px}
.card .card-footer{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:12px;padding-top:12px;border-top:1px solid var(--border);font-size:13px;color:var(--text3)}
.card .card-footer time{font-family:var(--font-mono)}
.card .card-footer a{color:var(--text2);font-weight:500}.card .card-footer a:hover{color:var(--accent)}
footer.site-footer{padding:48px 0 64px;border-top:1px solid var(--border);background:var(--surface);color:var(--text2);font-size:14px}
footer h2{color:var(--text);font-size:18px;margin-bottom:16px;font-weight:600}
footer .footer-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:32px;margin-bottom:32px}
footer ul{list-style:none}
footer li{padding:6px 0;border-bottom:1px dashed var(--border)}
footer li:last-child{border:none}
footer .copy{text-align:center;padding-top:24px;border-top:1px solid var(--border);color:var(--text3);font-size:13px}
@media (max-width:640px){
  .hero{padding:40px 0 32px}
  .stats{grid-template-columns:repeat(2,1fr);gap:12px;padding:20px 0}
  .stat{padding:16px}
  .section-nav{position:static}
  .cards{grid-template-columns:1fr}
  article.card{padding:16px}
}
@media (prefers-reduced-motion:reduce){*{transition:none !important;animation:none !important}}
"""


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--items", required=True, help="JSON file with 10 picked items + m3_title/m3_summary")
    p.add_argument("--gen-seconds", type=int, default=90)
    args = p.parse_args()

    with open(args.items, "r", encoding="utf-8") as f:
        items = json.load(f)
    assert 8 <= len(items) <= 12, f"need 8-12 items, got {len(items)}"

    now = datetime.now(timezone.utc)
    rss = write_rss(items, now)
    HTML_OUT.parent.mkdir(parents=True, exist_ok=True)
    HTML_OUT.write_text(write_html(items, now, args.gen_seconds), encoding="utf-8")
    RSS_OUT.parent.mkdir(parents=True, exist_ok=True)
    RSS_OUT.write_text(rss, encoding="utf-8")

    print(f"Wrote {RSS_OUT} ({len(rss)} bytes)")
    print(f"Wrote {HTML_OUT} ({HTML_OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
