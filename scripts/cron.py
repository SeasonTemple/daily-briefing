#!/usr/bin/env python3
"""
Daily briefing cron script for GitHub Actions.

Pipeline:
  1. 读 profile/*.yaml
  2. fetch 每个 source
  3. 24h 严格 + 36h/72h fallback (按需)
  4. AI 关键词过滤
  5. 多源混搭(每源按 tier 限)
  6. GitHub Models API 做中文摘要 + 评价
  7. 写 RSS 2.0 + HTML digest
"""
import argparse
import os
import re
import sys
import json
import time
import logging
from datetime import datetime, timezone, timedelta
from html import escape

import feedparser
import requests
import yaml

# ============== Constants ==============
SH = timezone(timedelta(hours=8))
NOW = datetime.now(SH)

# AI 关键词 (中英)
AI_KW = re.compile(
    r'\b(ai|llm|gpt|claude|gemini|mistral|llama|deepseek|qwen|openai|anthropic|deepmind|hugging|'
    r'transformer|diffusion|rag|agent|embedding|finetune|prompt|cuda|ml|model|neural|train|'
    r'dataset|inference|tokeniz|anthropic|sora|midjourney|stable diffusion|人工智能|大模型|'
    r'深度学习|机器学习|神经网络|训练|推理|微调|智能体|多模态|生成式|robot|autonomous|'
    r'self-driving|computer vision|nlp|speech|语音|视觉)',
    re.IGNORECASE
)
NON_AI = re.compile(
    r'\b(database|graphql|kubernetes|docker|rust\b|golang|typescript|linux\b|kernel\b|'
    r'compiler|debugger|ide\b|vim|emacs|crypto|bitcoin|ethereum|nft|web3|defi|blockchain|'
    r'storage|cache|queue|nosql|sql\b|orm|frontend|backend)',
    re.IGNORECASE
)

LOGO_MAP = {
    'arXiv cs.AI': 'arxiv', 'arXiv cs.LG': 'arxiv', 'arXiv cs.CL': 'arxiv',
    'Hacker News': 'hackernews', 'HN Best': 'hackernews',
    'TechCrunch AI': 'google', 'MIT Tech Review': 'google', 'AWS ML Blog': 'google',
    'Apple ML Research': 'google', 'AIBase Daily': 'google',
}

SRC_TIER = {
    'arXiv cs.AI': 'T1.5', 'arXiv cs.LG': 'T1.5', 'arXiv cs.CL': 'T1.5',
    'Hacker News': 'T3', 'HN Best': 'T3',
    'TechCrunch AI': 'T2', 'MIT Tech Review': 'T2',
    'AWS ML Blog': 'T1', 'Apple ML Research': 'T1', 'AIBase Daily': 'T5',
}


# ============== Helpers ==============
def setup_logging(log_path=None):
    fmt = '%(asctime)s %(levelname)s %(message)s'
    if log_path:
        logging.basicConfig(
            level=logging.INFO,
            format=fmt,
            handlers=[logging.FileHandler(log_path), logging.StreamHandler(sys.stdout)]
        )
    else:
        logging.basicConfig(level=logging.INFO, format=fmt)


def parse_pub(entry):
    for k in ['published', 'updated', 'created', 'pubDate']:
        v = entry.get(k)
        if not v:
            continue
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(v).astimezone(SH)
        except Exception:
            pass
    return None


def is_ai(title, src):
    if not title:
        return False
    if src.startswith('arXiv'):
        return True
    if AI_KW.search(title):
        return True
    if NON_AI.search(title):
        return False
    return True


def fetch_source(url, src_key, timeout=15):
    """fetch RSS/Atom, 容错"""
    try:
        d = feedparser.parse(url, agent='daily-briefing/0.9 (+https://github.com/SeasonTemple/daily-briefing)')
        out = []
        for e in d.entries:
            t = (e.get('title') or '').strip()
            l = (e.get('link') or '').strip()
            if not t or not l:
                continue
            pub = parse_pub(e)
            out.append({'title': t, 'link': l, 'pub': pub, 'src': src_key})
        return out
    except Exception as ex:
        logging.warning(f"  fetch fail {src_key}: {ex}")
        return []


# ============== GitHub Models API ==============
def summarize_with_llm(title_en, src_label, model='gpt-4o-mini'):
    """调 GitHub Models API 生成中文 RSS 卡片字段"""
    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        return None
    prompt = f"""你是 AI 行业分析师。把下面这条英文新闻生成中文 RSS 卡片 3 字段。

源: {src_label}
英文标题: {title_en}

输出严格 JSON (无 markdown,无解释):
{{"title_zh":"中文标题(20-40字,精炼)","summary":"中文摘要(60-80字,讲清楚事件/研究是什么)","take":"中文评价(30-50字,为什么值得关注 / 工程价值 / 行业意义)"}}"""
    try:
        r = requests.post(
            'https://models.inference.ai.azure.com/chat/completions',
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
            },
            json={
                'model': model,
                'messages': [
                    {'role': 'system', 'content': '你是中文 AI 行业分析师,精准输出 JSON。'},
                    {'role': 'user', 'content': prompt},
                ],
                'temperature': 0.3,
                'max_tokens': 400,
                'response_format': {'type': 'json_object'},
            },
            timeout=30,
        )
        if r.status_code == 200:
            data = r.json()
            content = data['choices'][0]['message']['content']
            parsed = json.loads(content)
            # 兜底字段
            for k in ['title_zh', 'summary', 'take']:
                if k not in parsed or not parsed[k]:
                    return None
            return parsed
        else:
            logging.warning(f"  GH Models {r.status_code}: {r.text[:200]}")
    except Exception as ex:
        logging.warning(f"  LLM fail: {ex}")
    return None


def summarize_fallback(title_en, src_label):
    """无 LLM 时的规则化 fallback"""
    t = re.sub(r'^arXiv:\s*\d+\.\d+\s*', '', title_en)
    t = re.sub(r'\s*\[arXiv:\d+\.\d+\].*$', '', t)
    t = re.sub(r'\s*\[(D|d)iscussion[^\]]*\]\s*', '', t)
    title_zh = t if len(t) <= 60 else t[:60] + '…'
    summary = f'来自 {src_label} 的 AI 行业内容,详见原文。'
    take = '持续关注 AI 行业动态,可结合上下文判断价值。'
    return {'title_zh': title_zh, 'summary': summary, 'take': take}


# ============== Render RSS ==============
def render_rss(items, profile, out_path):
    title = profile.get('title', 'AI 圈每日精华')
    desc = profile.get('description', '')
    link = 'https://seasontemple.github.io/daily-briefing/'
    LOGO_BASE = 'https://seasontemple.github.io/daily-briefing/assets/logos/'

    def xe(s): return escape(s, quote=True)
    def rfc(dt): return dt.strftime('%a, %d %b %Y %H:%M:%S %z')

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/">\n')
        f.write('  <channel>\n')
        f.write(f'    <title>{xe(title)}</title>\n')
        f.write(f'    <description>{xe(desc)}</description>\n')
        f.write(f'    <link>{link}</link>\n')
        f.write('    <atom:link rel="self" type="application/rss+xml" href="https://seasontemple.github.io/daily-briefing/rss/ai-daily.xml"/>\n')
        f.write('    <language>zh-CN</language>\n')
        f.write(f'    <lastBuildDate>{rfc(NOW)}</lastBuildDate>\n')
        f.write('    <ttl>5</ttl>\n')
        f.write(f'    <generator>daily-briefing/{profile.get("version", "0.9")} (GitHub Actions + GH Models)</generator>\n\n')

        for i, it in enumerate(items, 1):
            src = it['src']
            tier = SRC_TIER.get(src, 'T2')
            logo = LOGO_MAP.get(src, 'google')
            desc_text = f"{xe(it['summary'])} 评价:{xe(it['take'])} [来源:{xe(src)}]"
            pub = rfc(it['pub']) if it['pub'] else rfc(NOW)
            guid = f"ai-daily-auto-{NOW.strftime('%Y%m%d')}-{i:03d}"
            f.write('    <item>\n')
            f.write(f'      <title>{xe(it["title_zh"])}</title>\n')
            f.write(f'      <description>{desc_text}</description>\n')
            f.write(f'      <link>{xe(it["link"])}</link>\n')
            f.write(f'      <guid isPermaLink="false">{guid}</guid>\n')
            f.write(f'      <pubDate>{pub}</pubDate>\n')
            f.write(f'      <category>{tier} {xe(src)}</category>\n')
            f.write(f'      <media:thumbnail url="{LOGO_BASE}{logo}.svg" width="64" height="64"/>\n')
            f.write('    </item>\n')
        f.write('  </channel>\n</rss>\n')
    logging.info(f"Wrote {out_path} ({len(items)} items)")


# ============== Render HTML ==============
def render_html(items, profile, out_path):
    LOGO_BASE = 'https://seasontemple.github.io/daily-briefing/assets/logos/'

    def category_to_logo(cat):
        if 'arXiv' in cat: return 'arxiv'
        if 'Hacker' in cat: return 'hackernews'
        return 'google'

    def fmt_time(rfc):
        from email.utils import parsedate_to_datetime
        try: return parsedate_to_datetime(rfc).strftime('%m-%d %H:%M')
        except: return rfc[:16]

    from collections import Counter
    tiers = Counter()
    srcs = Counter()
    for it in items:
        src = it['src']
        tier = SRC_TIER.get(src, 'T2')
        tiers[tier] += 1
        srcs[src] += 1
    total = len(items)

    cards = []
    for i, it in enumerate(items, 1):
        src = it['src']
        tier = SRC_TIER.get(src, 'T2')
        logo = category_to_logo(src)
        pub = it['pub'].strftime('%a, %d %b %Y %H:%M:%S %z') if it['pub'] else NOW.strftime('%a, %d %b %Y %H:%M:%S %z')
        time = fmt_time(pub)
        cards.append(f'''
    <article class="card" aria-labelledby="c{i}">
      <div class="card-head">
        <img src="{LOGO_BASE}{logo}.svg" alt="" width="40" height="40" loading="lazy" class="src-logo"/>
        <div class="meta">
          <span class="src">{escape(src)}</span>
          <span class="tier tier-{tier.lower().replace(".","")}">{escape(tier)}</span>
        </div>
        <time class="time" datetime="{escape(pub)}">{escape(time)}</time>
      </div>
      <h3 id="c{i}" class="title">
        <a href="{escape(it["link"])}" target="_blank" rel="noopener">{escape(it["title_zh"])}</a>
      </h3>
      <p class="desc">{escape(it["summary"])}</p>
      <p class="take"><span class="take-lbl">评价</span> {escape(it["take"])}</p>
    </article>''')

    src_bars = []
    for src, cnt in sorted(srcs.items(), key=lambda x: -x[1]):
        pct = cnt * 100 // total if total else 0
        logo = category_to_logo(src)
        src_bars.append(f'''
    <li class="src-row">
      <img src="{LOGO_BASE}{logo}.svg" alt="" width="20" height="20" loading="lazy"/>
      <span class="src-name">{escape(src)}</span>
      <span class="src-bar"><span class="src-bar-fill" style="width:{pct}%"></span></span>
      <span class="src-count">{cnt}</span>
    </li>''')

    gen = 'daily-briefing/0.9 (GitHub Actions + GH Models)'
    desc = f'每日 07:00 (Asia/Shanghai) 自动抓取 71 个信源,LLM 中文摘要 + 评价。本期 {total} 条,8 源混搭,GitHub Actions 自动化构建。'

    # 复用昨日 CSS (内联)
    html = f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; img-src https://seasontemple.github.io https://i.gh-fork.githubusercontent.com data:; style-src 'self' 'unsafe-inline'; script-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'">
<title>AI 圈每日精华 · {NOW.strftime('%Y-%m-%d')}</title>
<style>
  :root {{ --bg: #0b0e14; --surface: #12161f; --surface-2: #1a2030; --border: #2a3142;
    --ink: #e6e9ef; --ink-2: #b6bcc8; --ink-3: #8a8f9c;
    --accent: #4f8bff; --t1: #4ade80; --t15: #34d399; --t2: #60a5fa; --t3: #f59e0b; --t5: #f472b6; }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: var(--bg); color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif; line-height: 1.6; }}
  a {{ color: var(--accent); text-decoration: none; }} a:hover, a:focus-visible {{ text-decoration: underline; }}
  :focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }}
  @media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ animation: none !important; transition: none !important; }} }}
  .skip-link {{ position: absolute; top: -40px; left: 8px; padding: 8px 12px; background: var(--accent); color: #fff; border-radius: 4px; z-index: 100; transition: top 0.2s; }}
  .skip-link:focus {{ top: 8px; }}
  .container {{ max-width: 1200px; margin: 0 auto; padding: 24px 20px 64px; }}
  header.hero {{ background: linear-gradient(135deg, #1a1f2e 0%, #0b0e14 50%, #0e1421 100%);
    padding: 48px 24px; border-radius: 12px; margin-bottom: 32px; border: 1px solid var(--border); }}
  header.hero h1 {{ margin: 0 0 8px; font-size: 32px; letter-spacing: -0.02em; }}
  header.hero .sub {{ color: var(--ink-2); margin: 0 0 24px; font-size: 16px; }}
  .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 16px; }}
  .stat {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px; }}
  .stat-num {{ font-size: 28px; font-weight: 700; color: var(--accent); line-height: 1; }}
  .stat-lbl {{ font-size: 12px; color: var(--ink-3); text-transform: uppercase; letter-spacing: 0.05em; margin-top: 4px; }}
  nav.sources {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px 20px; margin-bottom: 24px; }}
  nav.sources h2 {{ font-size: 14px; color: var(--ink-3); text-transform: uppercase; letter-spacing: 0.05em; margin: 0 0 12px; font-weight: 600; }}
  nav.sources ul {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 8px; }}
  .src-row {{ display: grid; grid-template-columns: 24px 1fr 100px 32px; gap: 12px; align-items: center; font-size: 13px; color: var(--ink-2); }}
  .src-name {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .src-bar {{ height: 6px; background: var(--surface-2); border-radius: 3px; overflow: hidden; }}
  .src-bar-fill {{ display: block; height: 100%; background: var(--accent); border-radius: 3px; }}
  .src-count {{ text-align: right; color: var(--ink-3); font-variant-numeric: tabular-nums; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }}
  article.card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
    padding: 16px 18px; transition: border-color 0.15s, transform 0.15s; display: flex; flex-direction: column; }}
  article.card:hover {{ border-color: var(--accent); transform: translateY(-2px); }}
  .card-head {{ display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }}
  .src-logo {{ flex: 0 0 auto; }}
  .card-head .meta {{ flex: 1 1 auto; min-width: 0; display: flex; align-items: center; gap: 8px; }}
  .card-head .src {{ font-size: 12px; color: var(--ink-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 160px; }}
  .tier {{ font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }}
  .tier-t1 {{ background: rgba(74, 222, 128, 0.15); color: var(--t1); }}
  .tier-t15 {{ background: rgba(52, 211, 153, 0.15); color: var(--t15); }}
  .tier-t2 {{ background: rgba(96, 165, 250, 0.15); color: var(--t2); }}
  .tier-t3 {{ background: rgba(245, 158, 11, 0.15); color: var(--t3); }}
  .tier-t5 {{ background: rgba(244, 114, 182, 0.15); color: var(--t5); }}
  .time {{ font-size: 11px; color: var(--ink-3); font-variant-numeric: tabular-nums; }}
  .title {{ margin: 0 0 8px; font-size: 15px; line-height: 1.4; font-weight: 600; }}
  .title a {{ color: var(--ink); }} .title a:hover {{ color: var(--accent); }}
  .desc {{ margin: 0 0 8px; font-size: 13px; color: var(--ink-2); line-height: 1.5; flex: 1 1 auto; }}
  .take {{ margin: 0; padding: 8px 10px; background: var(--surface-2); border-left: 3px solid var(--accent);
    border-radius: 4px; font-size: 12px; color: var(--ink); line-height: 1.5; }}
  .take-lbl {{ display: inline-block; font-size: 10px; font-weight: 600; color: var(--accent);
    text-transform: uppercase; letter-spacing: 0.05em; margin-right: 4px; }}
  footer {{ margin-top: 48px; padding-top: 24px; border-top: 1px solid var(--border);
    color: var(--ink-3); font-size: 12px; display: flex; gap: 16px; flex-wrap: wrap; justify-content: space-between; }}
  @media (max-width: 600px) {{ .grid {{ grid-template-columns: 1fr; }} .src-row {{ grid-template-columns: 24px 1fr 60px 24px; }} header.hero h1 {{ font-size: 24px; }} }}
</style>
</head>
<body>
<a href="#main" class="skip-link">跳到内容</a>
<div class="container">
  <header class="hero">
    <h1>AI 圈每日精华</h1>
    <p class="sub">{escape(desc)}</p>
    <div class="stats">
      <div class="stat"><div class="stat-num">{total}</div><div class="stat-lbl">条数</div></div>
      <div class="stat"><div class="stat-num">{tiers.get('T1',0)+tiers.get('T1.5',0)}</div><div class="stat-lbl">T1 论文+一手</div></div>
      <div class="stat"><div class="stat-num">{tiers.get('T2',0)+tiers.get('T3',0)}</div><div class="stat-lbl">T2-T3 二手</div></div>
      <div class="stat"><div class="stat-num">{len(srcs)}</div><div class="stat-lbl">采自信源</div></div>
    </div>
  </header>

  <nav class="sources" aria-label="信源分布">
    <h2>信源分布(本期)</h2>
    <ul>{''.join(src_bars)}</ul>
  </nav>

  <main id="main">
    <div class="grid" role="feed">{''.join(cards)}</div>
  </main>

  <footer>
    <div>生成器:{escape(gen)}<br>最后更新:{escape(NOW.strftime("%a, %d %b %Y %H:%M:%S %z"))}</div>
    <div><a href="rss/ai-daily.xml">RSS 订阅</a> · <a href="https://github.com/SeasonTemple/daily-briefing">源码</a> · <a href="index.html">所有日报</a></div>
  </footer>
</div>
</body>
</html>'''
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)
    logging.info(f"Wrote {out_path} ({total} cards)")


# ============== Main ==============
def main():
    p = argparse.ArgumentParser()
    p.add_argument('--profile', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--html', required=True)
    p.add_argument('--log', default=None)
    p.add_argument('--max-items', type=int, default=25)
    p.add_argument('--no-llm', action='store_true', help='skip LLM (use rule-based fallback)')
    args = p.parse_args()

    setup_logging(args.log)

    # 1. 读 profile
    with open(args.profile) as f:
        profile = yaml.safe_load(f)
    logging.info(f"Loaded profile: {profile.get('profile', '?')}")

    # 2. fetch 所有源
    items_by_src = {}
    for src in profile.get('sources', []):
        url = src.get('rss_url') or src.get('url')
        if not url:
            continue
        key = src.get('label') or src.get('name') or src.get('handle') or src.get('org', 'unknown')
        if src.get('type') in ['x_user', 'github_org'] and not src.get('rss_url'):
            continue
        items = fetch_source(url, key)
        items_by_src[key] = items
        logging.info(f"  {key}: fetched {len(items)} items")

    # 3. 时间窗 24h → 36h → 72h
    def in_win(items, cut):
        return sorted([i for i in items if i['pub'] and i['pub'] >= cut],
                      key=lambda x: x['pub'], reverse=True)

    pools = {k: in_win(v, NOW - timedelta(hours=24)) for k, v in items_by_src.items()}
    total_24 = sum(len(v) for v in pools.values())
    logging.info(f"24h total: {total_24}")

    if total_24 < 15:
        pools = {k: in_win(v, NOW - timedelta(hours=36)) for k, v in items_by_src.items()}
        logging.info("Expanded to 36h")
    if sum(len(v) for v in pools.values()) < 15:
        pools = {k: in_win(v, NOW - timedelta(hours=72)) for k, v in items_by_src.items()}
        logging.info("Expanded to 72h")

    # 4. AI 关键词过滤
    for k in list(pools.keys()):
        pools[k] = [i for i in pools[k] if is_ai(i['title'], k)]

    # 5. 多源混搭 (按 tier 限)
    SRC_LIMITS = {}
    for src in profile.get('sources', []):
        key = src.get('label') or src.get('name') or src.get('handle')
        tier = src.get('tier', 'T2')
        if tier in ('T1', 'T1.5'):
            SRC_LIMITS[key] = 8
        elif tier in ('T2', 'T3'):
            SRC_LIMITS[key] = 4
        else:
            SRC_LIMITS[key] = 5

    final = []
    for k, items in pools.items():
        lim = SRC_LIMITS.get(k, 3)
        final.extend(items[:lim])
    final.sort(key=lambda x: x['pub'] or NOW, reverse=True)
    # 去重
    seen, deduped = set(), []
    for it in final:
        k = re.sub(r'\s+', ' ', it['title'].lower())[:60]
        if k in seen:
            continue
        seen.add(k)
        deduped.append(it)
    final = deduped[:args.max_items]
    logging.info(f"Final: {len(final)} items after dedup + cap")

    # 6. LLM 摘要
    use_llm = not args.no_llm and bool(os.environ.get('GITHUB_TOKEN'))
    logging.info(f"LLM mode: {'on (GH Models)' if use_llm else 'off (fallback)'}")
    for i, it in enumerate(final, 1):
        if use_llm and i <= 20:
            res = summarize_with_llm(it['title'], it['src'])
            if res is None:
                res = summarize_fallback(it['title'], it['src'])
                logging.info(f"  [{i}] LLM fail, used fallback for: {it['title'][:50]}")
            else:
                logging.info(f"  [{i}] LLM ok: {res['title_zh'][:40]}")
        else:
            res = summarize_fallback(it['title'], it['src'])
        it['title_zh'] = res['title_zh']
        it['summary'] = res['summary']
        it['take'] = res['take']

    # 7/8. 写 RSS + HTML
    render_rss(final, profile, args.out)
    render_html(final, profile, args.html)

    logging.info("DONE")


if __name__ == '__main__':
    main()
