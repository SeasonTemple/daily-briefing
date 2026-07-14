#!/usr/bin/env python3
"""Create a daily GitHub Discussion with the day's briefing summary.

Usage:
  GITHUB_PAT=xxx python3 scripts/notify_discussions.py
  # or with explicit profile
  python3 scripts/notify_discussions.py --profile ai-daily

Writes 1 discussion per profile per day. Idempotent on a given date
(it skips if a discussion with the same title exists today).
"""
import os
import sys
import json
import datetime
import argparse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path

API = 'https://api.github.com'
REPO_OWNER = 'SeasonTemple'
REPO_NAME = 'daily-briefing'

PROFILES = [
    ('ai-daily', 'AI 圈每日精华'),
    ('developer-daily', '开发者每日信号'),
    ('finance-daily', '财经每日精华'),
]


def gh_request(path, data=None, method='GET'):
    token = os.environ.get('GITHUB_PAT')
    if not token:
        sys.exit('[notify] GITHUB_PAT env var required')
    url = f"{API}{path}"
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'daily-briefing-cron/1.0',
    }
    body = None
    if data is not None:
        headers['Content-Type'] = 'application/json'
        body = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def graphql(query, variables):
    result = gh_request('/graphql', {'query': query, 'variables': variables})
    if 'errors' in result:
        raise RuntimeError(f"GraphQL errors: {result['errors']}")
    return result['data']


def get_repo_meta():
    """Get repo node ID + discussion categories."""
    data = graphql("""
        query($owner: String!, $name: String!) {
          repository(owner: $owner, name: $name) {
            id
            discussionCategories(first: 25) {
              nodes { id name }
            }
          }
        }
    """, {'owner': REPO_OWNER, 'name': REPO_NAME})
    return data['repository']['id'], data['repository']['discussionCategories']['nodes']


def find_category(categories, name='Daily Briefing'):
    """Find category by name, fallback to General, fallback to first."""
    for c in categories:
        if c['name'] == name:
            return c['id']
    for c in categories:
        if c['name'].lower() in ('general', 'announcements'):
            return c['id']
    return categories[0]['id'] if categories else None


def today_discussion_exists(category_id, title_prefix):
    """Check if a discussion with same title prefix already exists today."""
    data = graphql("""
        query($id: ID!, $first: Int!) {
          node(id: $id) {
            ... on DiscussionCategory {
              discussions(first: $first, orderBy: {field: CREATED_AT, direction: DESC}) {
                nodes { title createdAt url }
              }
            }
          }
        }
    """, {'id': category_id, 'first': 30})
    today = datetime.date.today().isoformat()
    for d in data['node']['discussions']['nodes']:
        if d['title'].startswith(title_prefix) and d['createdAt'].startswith(today):
            return d
    return None


def create_discussion(repo_id, category_id, title, body):
    data = graphql("""
        mutation($repoId: ID!, $catId: ID!, $title: String!, $body: String!) {
          createDiscussion(input: {
            repositoryId: $repoId,
            categoryId: $catId,
            title: $title,
            body: $body
          }) {
            discussion { id number url title }
          }
        }
    """, {
        'repoId': repo_id,
        'catId': category_id,
        'title': title,
        'body': body,
    })
    return data['createDiscussion']['discussion']


def parse_rss(path):
    """Extract titles + links from RSS 2.0."""
    try:
        tree = ET.parse(path)
        items = tree.getroot().findall('.//item')
        out = []
        for item in items:
            title = (item.find('title').text or '').strip()
            link = (item.find('link').text or '').strip()
            desc = (item.find('description').text or '').strip()
            cat = item.find('category')
            cat = (cat.text or '').strip() if cat is not None else ''
            out.append({'title': title, 'link': link, 'desc': desc, 'cat': cat})
        return out
    except Exception as e:
        print(f"[notify] parse error on {path}: {e}", file=sys.stderr)
        return []


def build_body(items, html_url, rss_url, date_str, profile_name):
    """Build discussion body markdown."""
    lines = [
        f'## 📊 {date_str} · {len(items)} 条精选',
        '',
        f'**{profile_name}** · 自动生成于 {datetime.datetime.now().strftime("%Y-%m-%d %H:%M %Z")}',
        '',
        f'- 📄 完整 HTML 阅读 → {html_url}',
        f'- 📡 RSS 订阅 → {rss_url}',
        '',
        '---',
        '',
    ]
    for i, item in enumerate(items, 1):
        cat_badge = f' `{item["cat"]}`' if item['cat'] else ''
        lines.append(f'{i}. [{item["title"]}]({item["link"]}){cat_badge}')
    lines.extend([
        '',
        '---',
        '',
        f'由 [daily-briefing](https://github.com/SeasonTemple/daily-briefing) cron 自动生成 · 有问题请回复本贴',
    ])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', choices=[p[0] for p in PROFILES], help='Only run for one profile')
    parser.add_argument('--base', default='/tmp/daily-briefing', help='Base dir (default cron sandbox)')
    parser.add_argument('--category', default='Daily Briefing', help='Discussion category name')
    parser.add_argument('--date', help='Override date (YYYY-MM-DD), default today')
    args = parser.parse_args()

    date_str = args.date or datetime.date.today().isoformat()
    base = Path(args.base)
    profiles = [p for p in PROFILES if args.profile is None or p[0] == args.profile]

    try:
        repo_id, categories = get_repo_meta()
    except Exception as e:
        sys.exit(f"[notify] cannot fetch repo meta (Discussions enabled? PAT has write:discussion?): {e}")

    cat_id = find_category(categories, args.category)
    if not cat_id:
        sys.exit(f"[notify] no suitable category in {[c['name'] for c in categories]}")
    print(f"[notify] repo={REPO_OWNER}/{REPO_NAME} category_id={cat_id} date={date_str}", file=sys.stderr)

    ok = 0
    skip = 0
    fail = 0
    for profile_id, profile_name in profiles:
        rss_path = base / 'rss' / f'{profile_id}.xml'
        if not rss_path.exists():
            print(f"[notify] {profile_id}: skip (no RSS at {rss_path})")
            skip += 1
            continue
        items = parse_rss(rss_path)
        if not items:
            print(f"[notify] {profile_id}: skip (empty)")
            skip += 1
            continue
        title_prefix = f'📡 {profile_name} · {date_str}'
        existing = today_discussion_exists(cat_id, title_prefix)
        if existing:
            print(f"[notify] {profile_id}: skip (today exists, #{existing['number']})")
            skip += 1
            continue
        title = f'{title_prefix} · {len(items)} 条'
        html_url = f'https://seasontemple.github.io/daily-briefing/digests/{profile_id}.html'
        rss_url = f'https://seasontemple.github.io/daily-briefing/rss/{profile_id}.xml'
        body = build_body(items, html_url, rss_url, date_str, profile_name)
        try:
            d = create_discussion(repo_id, cat_id, title, body)
            print(f"[notify] ✓ {profile_id}: discussion #{d['number']} - {d['url']}")
            ok += 1
        except Exception as e:
            print(f"[notify] ✗ {profile_id}: {e}")
            fail += 1

    print(f"[notify] done: ok={ok} skip={skip} fail={fail}")
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
