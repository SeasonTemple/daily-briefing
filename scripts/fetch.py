#!/usr/bin/env python3
"""
Daily fetch: 只抓数据 + 写 raw JSON,不做 LLM 摘要。
Mavis M3 session 接管,做中文摘要 + 评价。
"""
import argparse
import os
import re
import sys
import json
import logging
from datetime import datetime, timezone, timedelta

import feedparser
import yaml

SH = timezone(timedelta(hours=8))
NOW = datetime.now(SH)

AI_KW = re.compile(
    r'\b(ai|llm|gpt|claude|gemini|mistral|llama|deepseek|qwen|openai|anthropic|deepmind|hugging|'
    r'transformer|diffusion|rag|agent|embedding|finetune|prompt|cuda|ml|model|neural|train|'
    r'dataset|inference|tokeniz|sora|midjourney|stable diffusion|人工智能|大模型|深度学习|'
    r'机器学习|神经网络|训练|推理|微调|智能体|多模态|生成式|robot|autonomous|nlp|speech|语音|视觉)',
    re.IGNORECASE
)
NON_AI = re.compile(
    r'\b(database|graphql|kubernetes|docker|rust\b|golang|typescript|linux\b|kernel\b|'
    r'compiler|debugger|ide\b|vim|emacs|crypto|bitcoin|ethereum|nft|web3|defi|blockchain|'
    r'storage|cache|queue|nosql|sql\b|orm|frontend|backend)',
    re.IGNORECASE
)


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


def parse_pub(entry):
    from email.utils import parsedate_to_datetime
    for k in ['published', 'updated', 'created', 'pubDate']:
        v = entry.get(k)
        if not v:
            continue
        try:
            return parsedate_to_datetime(v).astimezone(SH)
        except Exception:
            pass
    return None


def fetch_source(url, src_key, timeout=15):
    try:
        d = feedparser.parse(url, agent='daily-briefing/1.0 (+https://github.com/SeasonTemple/daily-briefing)')
        out = []
        for e in d.entries:
            t = (e.get('title') or '').strip()
            l = (e.get('link') or '').strip()
            if not t or not l:
                continue
            pub = parse_pub(e)
            out.append({
                'title': t, 'link': l, 'pub': pub.isoformat() if pub else None,
                'src': src_key
            })
        return out
    except Exception as ex:
        logging.warning(f"  fetch fail {src_key}: {ex}")
        return []


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--profile', required=True)
    p.add_argument('--out', required=True)
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

    with open(args.profile) as f:
        profile = yaml.safe_load(f)
    logging.info(f"Profile: {profile.get('profile', '?')}, {len(profile.get('sources', []))} sources")

    items_by_src = {}
    for src in profile.get('sources', []):
        url = src.get('rss_url') or src.get('url')
        if not url:
            continue
        key = src.get('label') or src.get('name') or src.get('handle') or 'unknown'
        if src.get('type') in ['x_user', 'github_org'] and not src.get('rss_url'):
            continue
        items = fetch_source(url, key)
        items_by_src[key] = items
        logging.info(f"  {key}: fetched {len(items)} items (tier {src.get('tier', '?')})")

    # 时间窗 24h → 36h → 72h
    def in_win(items, cut):
        out = []
        for i in items:
            if not i['pub']:
                continue
            try:
                dt = datetime.fromisoformat(i['pub']).astimezone(SH)
                if dt >= cut:
                    out.append(i)
            except Exception:
                pass
        return sorted(out, key=lambda x: x['pub'], reverse=True)

    pools = {k: in_win(v, NOW - timedelta(hours=24)) for k, v in items_by_src.items()}
    total_24 = sum(len(v) for v in pools.values())
    logging.info(f"24h total: {total_24}")

    if total_24 < 15:
        pools = {k: in_win(v, NOW - timedelta(hours=36)) for k, v in items_by_src.items()}
        logging.info("Expanded to 36h")
    if sum(len(v) for v in pools.values()) < 15:
        pools = {k: in_win(v, NOW - timedelta(hours=72)) for k, v in items_by_src.items()}
        logging.info("Expanded to 72h")

    # AI 过滤
    for k in list(pools.keys()):
        pools[k] = [i for i in pools[k] if is_ai(i['title'], k)]

    # per-source cap (tier-based)
    SRC_LIMITS = {}
    for src in profile.get('sources', []):
        key = src.get('label') or src.get('name') or src.get('handle')
        tier = src.get('tier', 'T2')
        SRC_LIMITS[key] = {'T1.5': 3, 'T1': 3, 'T2': 3, 'T3': 3, 'T4': 3, 'T5': 3}.get(tier, 3)

    final = []
    for k, items in pools.items():
        lim = SRC_LIMITS.get(k, 3)
        final.extend(items[:lim])
    final.sort(key=lambda x: x['pub'] or '', reverse=True)
    # dedup
    seen, deduped = set(), []
    for it in final:
        k = re.sub(r'\s+', ' ', it['title'].lower())[:60]
        if k in seen:
            continue
        seen.add(k)
        deduped.append(it)
    final = deduped[:25]
    logging.info(f"Final: {len(final)} items")

    # 写 raw
    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    payload = {
        'date': NOW.isoformat(),
        'profile': profile.get('profile'),
        'window': '24h+fallback',
        'items': final,
        'sources_count': len(items_by_src),
        'per_source': {k: len(v) for k, v in items_by_src.items()},
        'note': 'raw data for Mavis M3 to summarize',
    }
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logging.info(f"Wrote {args.out}")


if __name__ == '__main__':
    main()
