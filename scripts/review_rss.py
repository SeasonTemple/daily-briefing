#!/usr/bin/env python3
"""
Review RSS via GH Models: 找出"套话"评价, 用 gpt-4o 改写为具体观点
(用作 GHA review workflow)
"""
import argparse
import os
import re
import sys
import json
import logging
import xml.etree.ElementTree as ET
import requests

CLICHE_PATTERNS = [
    r'提供了理论基础', r'值得关注', r'具有.{0,5}价值', r'重要.{0,5}意义',
    r'具有.{0,5}应用前景', r'值得研究', r'值得深入', r'具有.{0,5}潜力',
    r'产生深远影响', r'具有重要意义', r'为.{0,5}提供.{0,5}支持',
    r'值得关注和学习', r'具有借鉴意义',
]


def has_cliche(text):
    return any(re.search(p, text) for p in CLICHE_PATTERNS)


def review_one(take_old, title, src, token, model='gpt-4o'):
    """调 gpt-4o 改写套话评价为具体观点"""
    prompt = f"""你是 AI 行业分析师。把下面这条 AI 新闻的"评价"改写为更具体、有观点的版本(30-50字)。

要求: 必须给**具体观点**——可以是'X 跟 Y 的区别'、'对 Z 行业的影响'、'具体数字 N%'、'跟某某公司路线对比'等。**禁止**使用"提供了理论基础/值得关注/具有价值"等套话。

源: {src}
标题: {title}
原评价(套话版): {take_old}

只输出新评价字符串(无 markdown, 无引号, 无其他内容):"""
    for m in [model, 'gpt-4o-mini', 'Mistral-large']:
        try:
            r = requests.post(
                'https://models.inference.ai.azure.com/chat/completions',
                headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
                json={
                    'model': m,
                    'messages': [
                        {'role': 'system', 'content': '你是中文 AI 行业分析师,严格直接输出。'},
                        {'role': 'user', 'content': prompt},
                    ],
                    'temperature': 0.4,
                    'max_tokens': 200,
                },
                timeout=25,
            )
            if r.status_code == 200:
                data = r.json()
                content = data['choices'][0]['message']['content'].strip()
                # 去掉可能的引号
                content = content.strip('"\' ')
                if 10 <= len(content) <= 200 and not has_cliche(content):
                    return content
        except Exception as ex:
            logging.debug(f"  {m} fail: {ex}")
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--rss', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--model', default='gpt-4o')
    p.add_argument('--log', default=None)
    p.add_argument('--max-review', type=int, default=5)
    args = p.parse_args()

    if args.log:
        log_dir = os.path.dirname(args.log)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
            handlers=[logging.FileHandler(args.log), logging.StreamHandler(sys.stdout)])
    else:
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        logging.error("No GITHUB_TOKEN")
        return

    # 备份
    if os.path.exists(args.rss):
        with open(args.rss, 'rb') as f:
            raw = f.read()
    else:
        logging.error(f"RSS not found: {args.rss}")
        return

    # 解析 XML (lxml 容错)
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        text = raw.decode('utf-8', errors='ignore')

    # 用 ET.parse 容错
    tree = ET.ElementTree(ET.fromstring(text))
    root = tree.getroot()
    items = root.findall('.//item')

    reviewed = 0
    for it in items:
        if reviewed >= args.max_review: break
        desc_el = it.find('description')
        if desc_el is None or not desc_el.text: continue
        desc = desc_el.text

        # 找 评价:... 部分
        m = re.search(r'评价:(.+?)\s*\[来源:', desc)
        if not m: continue
        take_old = m.group(1).strip()

        # 检查是否是套话
        if not has_cliche(take_old): continue

        # 找 title / link (for LLM context)
        title = (it.findtext('title') or '').strip()
        cat = (it.findtext('category') or '')
        src = cat.split(' ', 1)[1] if ' ' in cat else ''

        logging.info(f"  Reviewing: {title[:50]}")
        take_new = review_one(take_old, title, src, token, args.model)
        if take_new and take_new != take_old:
            new_desc = desc.replace(f'评价:{take_old}', f'评价:{take_new}', 1)
            desc_el.text = new_desc
            reviewed += 1
            logging.info(f"    -> {take_new[:60]}")

    if reviewed == 0:
        logging.info("No cliche takes found, no changes made")
        return

    # 写回
    logging.info(f"Reviewed {reviewed} takes, writing {args.out}")
    tree.write(args.out, encoding='utf-8', xml_declaration=True)


if __name__ == '__main__':
    main()
