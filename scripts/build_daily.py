#!/usr/bin/env python3
"""
Self-contained daily build script for mavis cron session.
Usage: python3 scripts/build_daily.py
"""
import feedparser
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from html import escape
from email.utils import parsedate_to_datetime

SH = timezone(timedelta(hours=8))
NOW = datetime.now(SH)

# Logo / tier mapping
LOGOS = {
    'arXiv cs.AI': 'arxiv', 'arXiv cs.LG': 'arxiv', 'arXiv cs.CL': 'arxiv',
    'arXiv cs.CV': 'arxiv', 'arXiv cs.RO': 'arxiv',
    'Hacker News': 'hackernews', 'HN Best': 'hackernews', 'Lobsters AI': 'hackernews',
    'TechCrunch AI': 'google', 'MIT Tech Review': 'google', 'AWS ML Blog': 'google',
    'Apple ML Research': 'google', 'AIBase Daily': 'google', 'Latent Space': 'google',
    '量子位': 'google', '机器之心': 'google', '少数派': 'google', '36Kr': 'google',
    'V2EX AI': 'google',
}
TIERS = {
    'arXiv cs.AI': 'T1.5', 'arXiv cs.LG': 'T1.5', 'arXiv cs.CL': 'T1.5',
    'arXiv cs.CV': 'T1.5', 'arXiv cs.RO': 'T1.5',
    'Hacker News': 'T3', 'HN Best': 'T3', 'Lobsters AI': 'T3',
    'TechCrunch AI': 'T2', 'MIT Tech Review': 'T2',
    'AWS ML Blog': 'T1', 'Apple ML Research': 'T1',
    'AIBase Daily': 'T5', '量子位': 'T5', '机器之心': 'T5', '少数派': 'T5',
    'Latent Space': 'T4',
}

AI_KW = re.compile(
    r'\b(ai|llm|gpt|claude|gemini|mistral|llama|deepseek|qwen|openai|anthropic|deepmind|'
    r'transformer|diffusion|rag|agent|embedding|finetune|prompt|ml|model|neural|'
    r'train|dataset|inference|人工智能|大模型|深度学习|机器学习|训练|推理|智能体|多模态|生成式)\b',
    re.IGNORECASE
)
NON_AI = re.compile(
    r'\b(database|graphql|kubernetes|docker|rust\b|golang|typescript|linux\b|kernel\b|'
    r'compiler|crypto|bitcoin|ethereum|nft|web3|blockchain|frontend|backend)\b',
    re.IGNORECASE
)


def is_ai(title, src):
    if not title: return False
    if src.startswith('arXiv'): return True
    if AI_KW.search(title): return True
    if NON_AI.search(title): return False
    return True


def parse_pub(s):
    if not s: return None
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try: return datetime.strptime(s[:31], fmt).astimezone(SH)
        except: continue
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})', s)
    if m:
        try: return datetime(*map(int, m.groups()), tzinfo=timezone.utc).astimezone(SH)
        except: pass
    return None


SOURCES = [
    ('arXiv cs.AI', 'http://export.arxiv.org/rss/cs.AI'),
    ('arXiv cs.CL', 'http://export.arxiv.org/rss/cs.CL'),
    ('arXiv cs.LG', 'http://export.arxiv.org/rss/cs.LG'),
    ('arXiv cs.CV', 'http://export.arxiv.org/rss/cs.CV'),
    ('arXiv cs.RO', 'http://export.arxiv.org/rss/cs.RO'),
    ('AWS ML Blog', 'https://aws.amazon.com/blogs/machine-learning/feed/'),
    ('Apple ML Research', 'https://machinelearning.apple.com/rss.xml'),
    ('AIBase Daily', 'https://www.aibase.com/daily'),
    ('Hacker News', 'https://hnrss.org/frontpage'),
    ('HN Best', 'https://hnrss.org/best'),
    ('TechCrunch AI', 'https://techcrunch.com/category/artificial-intelligence/feed/'),
    ('MIT Tech Review', 'https://www.technologyreview.com/topic/artificial-intelligence/feed'),
    ('The Verge AI', 'https://www.theverge.com/ai-artificial-intelligence/rss/index.xml'),
    ('量子位', 'https://www.qbitai.com/feed'),
    ('机器之心', 'https://www.jiqizhixin.com/rss'),
    ('少数派', 'https://sspai.com/feed'),
]


def main():
    # 1. fetch
    items_by_src = {}
    for src, url in SOURCES:
        try:
            d = feedparser.parse(url, agent='daily-briefing/3.0')
            out = []
            for e in d.entries[:6]:
                t = (e.get('title') or '').strip()
                l = (e.get('link') or '').strip()
                if not t or not l: continue
                pub_raw = e.get('published') or e.get('updated') or ''
                pub = parse_pub(pub_raw)
                out.append({'title': t, 'link': l, 'pub': pub.isoformat() if pub else None, 'src': src, 'pub_raw': pub_raw})
            items_by_src[src] = out
            print(f'  {src}: {len(out)} items', flush=True)
        except Exception as ex:
            print(f'  {src}: FAIL {ex}', flush=True)

    # 2. 时间窗
    def in_win(items, cut_hours):
        cut = NOW - timedelta(hours=cut_hours)
        out = []
        for i in items:
            if not i['pub']: continue
            try:
                dt = datetime.fromisoformat(i['pub']).astimezone(SH)
                if dt >= cut: out.append(i)
            except: pass
        return sorted(out, key=lambda x: x['pub'], reverse=True)

    pools = {k: in_win(v, 24) for k, v in items_by_src.items()}
    total_24 = sum(len(v) for v in pools.values())
    if total_24 < 15:
        pools = {k: in_win(v, 36) for k, v in items_by_src.items()}
    if sum(len(v) for v in pools.values()) < 15:
        pools = {k: in_win(v, 72) for k, v in items_by_src.items()}

    # 3. AI 过滤
    for k in list(pools.keys()):
        pools[k] = [i for i in pools[k] if is_ai(i['title'], k)]

    # 4. 多源混搭 per-source cap = 3
    final = []
    for k, items in pools.items():
        final.extend(items[:3])
    final.sort(key=lambda x: x['pub'] or '', reverse=True)
    seen, deduped = set(), []
    for it in final:
        k = re.sub(r'\s+', ' ', it['title'].lower())[:60]
        if k in seen: continue
        seen.add(k); deduped.append(it)
    final = deduped[:25]
    print(f'\nFinal raw: {len(final)} items', flush=True)

    # 5. 写 raw JSON (给 M3 LLM 后面用)
    os.makedirs('data', exist_ok=True)
    raw_path = f'data/raw-ai-daily-{NOW.strftime("%Y%m%dT%H%M%S")}.json'
    with open(raw_path, 'w', encoding='utf-8') as f:
        json.dump({'date': NOW.isoformat(), 'items': final, 'sources_count': len(SOURCES)}, f, ensure_ascii=False)
    print(f'Wrote {raw_path}', flush=True)

    # 6. 输出 items to stdout (M3 LLM inline 写 RSS)
    print('\n=== RAW ITEMS FOR M3 ===')
    print(json.dumps(final, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
