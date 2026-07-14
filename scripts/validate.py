#!/usr/bin/env python3
"""Validate RSS 2.0 + HTML digest files."""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

def validate_rss(path: str) -> bool:
    p = Path(path)
    if not p.exists():
        print(f"[validate] FAIL: {path} does not exist")
        return False
    try:
        tree = ET.parse(p)
        items = tree.getroot().findall('.//item')
        n = len(items)
        if n == 0:
            print(f"[validate] FAIL: 0 items in {path}")
            return False
        # Check for required tags
        first = items[0]
        title = first.find('title')
        link = first.find('link')
        if title is None or link is None:
            print(f"[validate] FAIL: missing title/link in first item")
            return False
        # Check for media:thumbnail
        has_thumb = any('thumbnail' in child.tag for child in first)
        # Check for lastBuildDate
        lbd = tree.getroot().find('.//lastBuildDate')
        print(f"[validate] RSS OK: {n} items, lastBuildDate={'yes' if lbd is not None else 'no'}, media:thumbnail={'yes' if has_thumb else 'no'}")
        return True
    except ET.ParseError as e:
        print(f"[validate] FAIL: XML parse error: {e}")
        return False


def validate_html(path: str) -> bool:
    p = Path(path)
    if not p.exists():
        print(f"[validate] FAIL: {path} does not exist")
        return False
    content = p.read_text(encoding='utf-8')
    size = len(content)
    if size < 5000:
        print(f"[validate] FAIL: {path} only {size} bytes (expected > 5KB)")
        return False
    n_articles = content.count('<article')
    n_logos = content.count('assets/logos/')
    has_csp = 'Content-Security-Policy' in content
    has_skip = 'skip-link' in content
    has_lang = 'lang="zh-CN"' in content
    if n_articles < 1:
        print(f"[validate] FAIL: 0 <article> tags in {path}")
        return False
    print(f"[validate] HTML OK: {size} bytes, {n_articles} articles, {n_logos} logo refs, CSP={has_csp}, skip-link={has_skip}, lang=zh-CN={has_lang}")
    return True


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: validate.py <rss_or_html_path>")
        sys.exit(1)
    path = sys.argv[1]
    if path.endswith('.xml'):
        ok = validate_rss(path)
    elif path.endswith('.html'):
        ok = validate_html(path)
    else:
        print(f"[validate] unknown type: {path}")
        sys.exit(1)
    sys.exit(0 if ok else 1)
