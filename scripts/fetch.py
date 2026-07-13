"""
fetch.py — multi-source ingestion for Daily Briefing.

Each source type is implemented as an independent fetcher; failures are
isolated and recorded in the returned ``stats`` dict so one bad source
can never break the whole pipeline.

Supported source types:
  - rss        : any RSS / Atom feed (via feedparser)
  - x_user     : a Twitter/X user, pulled via a list of Nitter mirrors
                 with round-robin fallback. We try every mirror in order;
                 if all fail we mark the source as "x_unavailable" but
                 never raise.
  - github_org : a GitHub organization (events Atom feed)

Output schema (one record per item):
  {
    "id":         str,    # stable per-source ID (URL or guid)
    "title":      str,
    "url":        str,
    "source":     str,    # source name (label)
    "source_type": str,   # rss | x_user | github_org
    "author":     str,    # best-effort author display
    "published":  datetime | None,
    "content":    str,    # summary / body
    "lang":       "en" | "zh" | "und"
  }
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import feedparser
import requests

LOG = logging.getLogger("fetch")

DEFAULT_UA = os.getenv(
    "HTTP_USER_AGENT",
    "daily-briefing/0.1 (+https://github.com/local/daily-briefing)",
)
TIMEOUT = 15
# X via Nitter is famously flaky. Tight timeouts + no retry: the next
# mirror in the list is the retry. Single attempt = predictable runtime.
NITTER_TIMEOUT = 5
NITTER_MIRRORS = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.1d4.us",
    "https://nitter.woodland.cafe",
]

# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class Item:
    id: str
    title: str
    url: str
    source: str
    source_type: str
    author: str = ""
    published: datetime | None = None
    content: str = ""
    lang: str = "und"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.published is not None:
            d["published"] = self.published.isoformat()
        return d


# ---------------------------------------------------------------------------
# URL canonicalization helpers
# ---------------------------------------------------------------------------

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src", "ref_url",
    "igshid", "vero_id", "vero_conv", "trk", "trkCampaign",
}

def canonicalize_url(url: str) -> str:
    if not url:
        return url
    try:
        p = urlparse(url)
    except Exception:
        return url
    if not p.netloc:
        return url
    # Drop fragment
    frag = ""
    # Keep query but strip tracking params
    q = []
    for k, v in parse_qsl(p.query, keep_blank_values=True):
        if k.lower() in _TRACKING_PARAMS:
            continue
        q.append((k, v))
    new_query = urlencode(q, doseq=True)
    # Lower-case scheme + host
    new = urlunparse((
        (p.scheme or "https").lower(),
        p.netloc.lower(),
        p.path or "",
        p.params or "",
        new_query,
        frag,
    ))
    return new


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _to_dt(*candidates: Any) -> datetime | None:
    """Best-effort conversion from feedparser time tuples to datetime."""
    for c in candidates:
        if not c:
            continue
        try:
            t = feedparser._parse_date(c) if isinstance(c, str) else c
            if t is None:
                continue
            if isinstance(t, datetime):
                # feedparser returns naive UTC; assume UTC if no tz
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                return t.astimezone(timezone.utc)
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# HTTP helper with retry
# ---------------------------------------------------------------------------

def http_get(url: str, *, timeout: int = TIMEOUT, headers: dict | None = None) -> requests.Response | None:
    h = {"User-Agent": DEFAULT_UA, "Accept": "*/*"}
    if headers:
        h.update(headers)
    for attempt in range(2):
        try:
            r = requests.get(url, headers=h, timeout=timeout, allow_redirects=True)
            if r.status_code == 200 and r.content:
                return r
            LOG.warning("non-200 from %s: %s", url, r.status_code)
        except requests.RequestException as e:
            LOG.warning("GET %s failed (attempt %d): %s", url, attempt + 1, e)
        time.sleep(0.5 * (attempt + 1))
    return None


def http_get_once(url: str, *, timeout: int = TIMEOUT, headers: dict | None = None) -> requests.Response | None:
    """Single-attempt GET. Used for Nitter where the next mirror is the retry."""
    h = {"User-Agent": DEFAULT_UA, "Accept": "*/*"}
    if headers:
        h.update(headers)
    try:
        r = requests.get(url, headers=h, timeout=timeout, allow_redirects=True)
        if r.status_code == 200 and r.content:
            return r
        LOG.warning("non-200 from %s: %s", url, r.status_code)
    except requests.RequestException as e:
        LOG.debug("GET %s failed: %s", url, e)
    return None


# ---------------------------------------------------------------------------
# Source: generic RSS / Atom feed
# ---------------------------------------------------------------------------

def fetch_rss(source: dict) -> tuple[list[Item], str | None]:
    """Return (items, error_msg)."""
    url = source["url"]
    name = source.get("name") or url
    LOG.info("RSS fetch: %s", name)
    try:
        r = http_get(url, timeout=20)
        if not r:
            return [], f"http_failed: {url}"
        feed = feedparser.parse(r.content)
        items: list[Item] = []
        for entry in feed.entries[: int(os.getenv("FETCH_PER_SOURCE", "30"))]:
            link = entry.get("link") or entry.get("id") or ""
            link = canonicalize_url(link)
            title = (entry.get("title") or "").strip()
            if not title:
                # synthesize from link
                title = link
            author = (entry.get("author") or "").strip()
            content = ""
            if entry.get("summary"):
                content = entry.summary
            elif entry.get("content"):
                v = entry.content
                if isinstance(v, list) and v:
                    content = v[0].get("value", "")
            if entry.get("published_parsed"):
                pub = _to_dt(entry.published_parsed, entry.get("published"))
            else:
                pub = _to_dt(entry.get("published"), entry.get("updated"))
            lang = (entry.get("language") or "und").lower()[:2] or "und"
            items.append(Item(
                id=entry.get("id") or link or title,
                title=title,
                url=link,
                source=name,
                source_type="rss",
                author=author,
                published=pub,
                content=_strip_html(content),
                lang=lang,
            ))
        return items, None
    except Exception as e:
        return [], f"exception: {e!r}"


# ---------------------------------------------------------------------------
# Source: X (Twitter) user via Nitter mirrors
# ---------------------------------------------------------------------------

def fetch_x_user(source: dict) -> tuple[list[Item], str | None]:
    handle = source["handle"].lstrip("@")
    label = source.get("label") or f"@{handle}"
    per_source = int(os.getenv("FETCH_PER_SOURCE", "30"))
    items: list[Item] = []
    last_err: str | None = None
    for mirror in NITTER_MIRRORS:
        url = f"{mirror.rstrip('/')}/{handle}/rss"
        LOG.debug("X mirror try: %s for @%s", mirror, handle)
        # No retry on Nitter; the next mirror is the retry.
        r = http_get_once(url, timeout=NITTER_TIMEOUT)
        if not r:
            last_err = f"http_failed: {url}"
            continue
        try:
            feed = feedparser.parse(r.content)
        except Exception as e:
            last_err = f"parse_error: {e!r}"
            continue
        if not feed.entries:
            last_err = f"empty_feed: {url}"
            continue
        for entry in feed.entries[:per_source]:
            link = entry.get("link") or entry.get("id") or ""
            link = canonicalize_url(link)
            title = (entry.get("title") or "").strip()
            # Nitter often uses the tweet text as title; trim if huge
            if len(title) > 240:
                title = title[:237].rstrip() + "..."
            if not title:
                title = f"Tweet by @{handle}"
            content = ""
            if entry.get("summary"):
                content = entry.summary
            pub = _to_dt(entry.get("published_parsed"), entry.get("published"))
            items.append(Item(
                id=entry.get("id") or link or f"x:{handle}:{title[:40]}",
                title=title,
                url=link,
                source=f"{label} (@{handle})",
                source_type="x_user",
                author=f"@{handle}",
                published=pub,
                content=_strip_html(content),
                lang="en",
            ))
        LOG.info("X mirror OK: %s -> %d items", mirror, len(items))
        return items, None
    return [], last_err or "x_unavailable"


# ---------------------------------------------------------------------------
# Source: GitHub org events Atom feed
# ---------------------------------------------------------------------------

def fetch_github_org(source: dict) -> tuple[list[Item], str | None]:
    org = source["org"]
    label = source.get("label") or f"GitHub:{org}"
    url = f"https://github.com/orgs/{org}/events.atom"
    LOG.info("GitHub events fetch: %s", org)
    r = http_get(url, timeout=15, headers={"Accept": "application/atom+xml"})
    if not r:
        return [], f"http_failed: {url}"
    try:
        feed = feedparser.parse(r.content)
    except Exception as e:
        return [], f"parse_error: {e!r}"
    items: list[Item] = []
    for entry in feed.entries[: int(os.getenv("FETCH_PER_SOURCE", "30"))]:
        link = canonicalize_url(entry.get("link") or entry.get("id") or "")
        title = (entry.get("title") or "").strip()
        if not title:
            title = f"GitHub activity in {org}"
        content = entry.get("summary") or entry.get("content", "")
        if isinstance(content, list):
            content = " ".join(str(x) for x in content)
        pub = _to_dt(entry.get("published_parsed"), entry.get("published"))
        author = ""
        for a in entry.get("authors", []) or []:
            if a.get("name"):
                author = a["name"]
                break
        items.append(Item(
            id=entry.get("id") or link or f"github:{org}:{title[:40]}",
            title=title,
            url=link,
            source=label,
            source_type="github_org",
            author=author,
            published=pub,
            content=_strip_html(content),
            lang="en",
        ))
    return items, None


# ---------------------------------------------------------------------------
# HTML stripping
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

def _strip_html(s: str | None) -> str:
    if not s:
        return ""
    s = _TAG_RE.sub(" ", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", "\"").replace("&#39;", "'")
    s = _WS_RE.sub(" ", s).strip()
    return s


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def fetch_all(sources: list[dict]) -> tuple[list[Item], dict[str, Any]]:
    """Fetch every source. Returns (items, stats)."""
    items: list[Item] = []
    stats: dict[str, Any] = {
        "total": 0,
        "per_source": {},
        "errors": {},
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    for s in sources:
        st = s.get("type", "rss")
        name = (
            s.get("label")
            or s.get("name")
            or s.get("handle")
            or s.get("org")
            or s.get("url")
            or "unknown"
        )
        try:
            if st == "rss":
                its, err = fetch_rss(s)
            elif st == "x_user":
                its, err = fetch_x_user(s)
            elif st == "github_org":
                its, err = fetch_github_org(s)
            else:
                LOG.warning("unknown source type: %s", st)
                its, err = [], f"unknown_type:{st}"
        except Exception as e:  # hard guard
            LOG.exception("source %s crashed: %s", name, e)
            its, err = [], f"crash:{e!r}"

        stats["per_source"][name] = len(its)
        if err:
            stats["errors"][name] = err
        items.extend(its)
    stats["total"] = len(items)
    stats["ended_at"] = datetime.now(timezone.utc).isoformat()
    return items, stats


# ---------------------------------------------------------------------------
# CLI for debugging
# ---------------------------------------------------------------------------

def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    import argparse, yaml
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--out", default="-")
    args = p.parse_args()

    with open(f"profiles/{args.profile}.yaml", "r", encoding="utf-8") as f:
        prof = yaml.safe_load(f)
    sources = prof.get("sources", [])
    items, stats = fetch_all(sources)
    payload = {
        "stats": stats,
        "items": [it.to_dict() for it in items],
    }
    txt = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out == "-":
        print(txt)
    else:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
