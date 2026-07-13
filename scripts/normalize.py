"""
normalize.py — schema normalization + deduplication.

Input: raw list[Item] (dataclass or dict) from fetch.py
Output: list[dict] ready for the LLM/digest stage.

Operations:
  1. Schema fix-up: coerce types, fill defaults.
  2. Time window filter: drop items older than `hours_lookback`.
  3. URL canonicalization (idempotent w/ fetch).
  4. Dedup:
     - by URL (exact, after canonicalize)
     - by title similarity (rapidfuzz token_set_ratio >= THRESHOLD)
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

try:
    from rapidfuzz import fuzz
    HAVE_RAPIDFUZZ = True
except Exception:  # pragma: no cover
    HAVE_RAPIDFUZZ = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TITLE_SIM_THRESHOLD = 88  # 0-100
DEFAULT_HOURS_LOOKBACK = 72

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_dt(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)
    if isinstance(v, str):
        s = v.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(s)
        except Exception:
            pass
    return None


def _ensure_dict(it: Any) -> dict:
    if hasattr(it, "to_dict") and callable(it.to_dict):
        return it.to_dict()
    if isinstance(it, dict):
        return dict(it)
    raise TypeError(f"cannot normalize item of type {type(it)}")


_WS_RE = re.compile(r"\s+")
_BRACKETS_RE = re.compile(r"[\[\(【].*?[\]\)】]")

def clean_title(t: str) -> str:
    t = (t or "").strip()
    t = _BRACKETS_RE.sub("", t)
    t = _WS_RE.sub(" ", t)
    return t.strip()


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def normalize(
    items: Iterable[Any],
    *,
    hours_lookback: int = DEFAULT_HOURS_LOOKBACK,
    now: datetime | None = None,
) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours_lookback)

    cleaned: list[dict] = []
    for raw in items:
        d = _ensure_dict(raw)
        # 1. Coerce types
        d["title"] = clean_title(d.get("title") or "")
        d["url"] = d.get("url") or ""
        d["source"] = d.get("source") or "unknown"
        d["source_type"] = d.get("source_type") or "rss"
        d["author"] = d.get("author") or ""
        d["content"] = (d.get("content") or "").strip()
        d["lang"] = (d.get("lang") or "und")[:2].lower()
        d["id"] = d.get("id") or d.get("url") or d["title"]
        pub = _to_dt(d.get("published"))
        d["published"] = pub
        # 2. Time filter (only if we have a timestamp; otherwise keep)
        if pub is not None and pub < cutoff:
            continue
        if not d["title"] and not d["url"]:
            continue
        cleaned.append(d)

    # 3. Dedupe — by URL first
    seen_url: set[str] = set()
    deduped: list[dict] = []
    for d in cleaned:
        u = d["url"]
        if u and u in seen_url:
            continue
        if u:
            seen_url.add(u)
        deduped.append(d)

    # 4. Dedupe — by title similarity (slow path; use rapidfuzz when present)
    if HAVE_RAPIDFUZZ:
        final: list[dict] = []
        kept_titles: list[str] = []
        for d in deduped:
            t = d["title"].lower()
            is_dup = False
            for kt in kept_titles:
                if fuzz.token_set_ratio(t, kt) >= TITLE_SIM_THRESHOLD:
                    is_dup = True
                    break
            if is_dup:
                continue
            final.append(d)
            kept_titles.append(t)
        return final

    # Stdlib fallback: SequenceMatcher (cheap, slightly less accurate)
    from difflib import SequenceMatcher
    final = []
    kept_titles = []
    for d in deduped:
        t = d["title"].lower()
        is_dup = False
        for kt in kept_titles:
            if SequenceMatcher(None, t, kt).ratio() >= 0.86:
                is_dup = True
                break
        if is_dup:
            continue
        final.append(d)
        kept_titles.append(t)
    return final
