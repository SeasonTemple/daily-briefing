"""
digest.py — Daily Briefing orchestrator (M1 main entry).

Pipeline (M1):
  load profile  →  fetch all sources  →  normalize/dedupe
                  →  LLM digest (with fallback)  →  rank + limit
                  →  render Atom RSS  →  render Markdown archive

CLI:
  python scripts/digest.py --profile ai-daily
  python scripts/digest.py --profile ai-daily --dry-run
  python scripts/digest.py --profile ai-daily --no-publish
  python scripts/digest.py --profile ai-daily --limit 5
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Make sibling modules importable when invoked as `python scripts/digest.py`
THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from fetch import fetch_all
from normalize import normalize
from llm_digest import digest_items
from render_rss import render, render_markdown_report

LOG = logging.getLogger("digest")

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Offline fixture (for sandboxed / no-network runs)
# ---------------------------------------------------------------------------

def _offline_items() -> list[dict]:
    """Realistic-looking fixture items, mix of 一手 + 二手. Used when --offline."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    def dt(hours: float) -> str:
        return (now - timedelta(hours=hours)).isoformat()
    return [
        # 一手:Anthropic newsroom
        {
            "id": "anthropic-news-001",
            "title": "Anthropic 发布 Claude Code 2.0,主打多文件重构与 Agent 模式",
            "url": "https://www.anthropic.com/news/claude-code-2",
            "source": "Anthropic News",
            "source_type": "rss",
            "author": "Anthropic",
            "published": dt(2.5),
            "content": "Claude Code 2.0 introduces multi-file coordinated refactoring and persistent agent context, "
                       "significantly improving efficiency when editing large codebases.",
            "lang": "en",
        },
        # 一手:OpenAI blog
        {
            "id": "openai-blog-001",
            "title": "OpenAI 公布 GPT 系列新模型的多模态能力升级",
            "url": "https://openai.com/blog/gpt-multimodal-upgrade",
            "source": "OpenAI Blog",
            "source_type": "rss",
            "author": "OpenAI",
            "published": dt(5.0),
            "content": "Latest GPT model upgrades video understanding, on-screen action and real-time voice capabilities.",
            "lang": "en",
        },
        # 一手:DeepMind blog
        {
            "id": "deepmind-blog-001",
            "title": "Google DeepMind 开源新一代 Gemma 长上下文模型",
            "url": "https://deepmind.google/discover/blog/gemma-long-context",
            "source": "Google DeepMind Blog",
            "source_type": "rss",
            "author": "DeepMind",
            "published": dt(7.0),
            "content": "New Gemma extends context window to 1M tokens, optimized for long-document RAG scenarios.",
            "lang": "en",
        },
        # 一手:HF blog
        {
            "id": "hf-blog-001",
            "title": "Hugging Face 推出新版 Daily Papers 自动排行",
            "url": "https://huggingface.co/blog/daily-papers-2026",
            "source": "Hugging Face Blog",
            "source_type": "rss",
            "author": "HF Team",
            "published": dt(8.0),
            "content": "HF Daily Papers adds topic-based auto leaderboards (code, math, multimodal) and community voting.",
            "lang": "en",
        },
        # 一手:GitHub org (DeepSeek)
        {
            "id": "gh-deepseek-001",
            "title": "DeepSeek-V3.2 推理优化版本开源",
            "url": "https://github.com/deepseek-ai/DeepSeek-V3.2",
            "source": "DeepSeek GitHub",
            "source_type": "github_org",
            "author": "deepseek-ai",
            "published": dt(3.0),
            "content": "DeepSeek-V3.2 inference-optimized release: 2x throughput, 30% less VRAM.",
            "lang": "en",
        },
        # 一手:GitHub org (Qwen)
        {
            "id": "gh-qwen-001",
            "title": "Qwen3 推出长上下文 Agent 工具链",
            "url": "https://github.com/QwenLM/Qwen3-Agent",
            "source": "Qwen GitHub",
            "source_type": "github_org",
            "author": "QwenLM",
            "published": dt(11.0),
            "content": "Qwen3 long-context Agent toolchain open-sourced under Apache 2.0.",
            "lang": "en",
        },
        # 一手:arXiv
        {
            "id": "arxiv-001",
            "title": "用稀疏注意力把 7B 模型训练提速 3.2 倍",
            "url": "https://arxiv.org/abs/2607.12345",
            "source": "arXiv cs.CL",
            "source_type": "rss",
            "author": "Anonymous",
            "published": dt(6.0),
            "content": "Adaptive sparse attention trains 7B models 3.2x faster with <0.3% quality loss.",
            "lang": "en",
        },
        # 一手:HF Daily Papers
        {
            "id": "hf-papers-001",
            "title": "HF Daily Papers 今日榜首:Mixture-of-Depths 在 70B 模型上验证有效",
            "url": "https://huggingface.co/papers/2607.99999",
            "source": "HF Daily Papers",
            "source_type": "rss",
            "author": "Community",
            "published": dt(10.0),
            "content": "Mixture-of-Depths validated on 70B models: 1.6x inference speedup at iso-quality.",
            "lang": "en",
        },
        # 一手:X 官号(@sama, simulated — represents what a Nitter-mirror pull would yield)
        {
            "id": "x-sama-001",
            "title": "Sam Altman: GPT-5 将更深度整合工具调用与代码执行",
            "url": "https://x.com/sama/status/1234567890",
            "source": "Sam Altman (@sama)",
            "source_type": "x_user",
            "author": "@sama",
            "published": dt(1.5),
            "content": "GPT-5 will more deeply integrate tool calling, code execution, and long-term memory.",
            "lang": "en",
        },
        # 一手:X 官号(@deepseek_ai)
        {
            "id": "x-deepseek-001",
            "title": "DeepSeek 官方:开源 V3.2 推理引擎,显存降低 30%",
            "url": "https://x.com/deepseek_ai/status/1234567891",
            "source": "DeepSeek (@deepseek_ai)",
            "source_type": "x_user",
            "author": "@deepseek_ai",
            "published": dt(4.0),
            "content": "Open-sourced V3.2 inference engine with 30% lower VRAM footprint.",
            "lang": "en",
        },
        # 二手:HN
        {
            "id": "hn-001",
            "title": "Hacker News 热议:Mistral Large 3 在企业私域场景落地",
            "url": "https://news.ycombinator.com/item?id=42345678",
            "source": "Hacker News",
            "source_type": "rss",
            "author": "HN",
            "published": dt(9.0),
            "content": "HN discussion on Mistral Large 3 deployment cost and throughput advantages in finance/customer-service private deployments.",
            "lang": "en",
        },
        # 二手:36Kr
        {
            "id": "36kr-001",
            "title": "36Kr:国产开源大模型 2026 上半年格局重塑",
            "url": "https://36kr.com/p/12345",
            "source": "36Kr AI",
            "source_type": "rss",
            "author": "36Kr",
            "published": dt(12.0),
            "content": "国产开源大模型 2026 上半年格局重塑:DeepSeek、Qwen、智谱、月之暗面多方混战。",
            "lang": "zh",
        },
    ]


# ---------------------------------------------------------------------------
# Profile loading
# ---------------------------------------------------------------------------

def load_profile(name: str) -> dict:
    path = REPO_ROOT / "profiles" / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"profile not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Scoring + sorting
# ---------------------------------------------------------------------------

def relevance_score(item: dict) -> float:
    """M1 simple scoring: keyword match + recency + source-type weight."""
    d = item.get("digest") or {}
    base = float(d.get("relevance") or 0.5)
    recency = 0.0
    pub = item.get("published")
    if isinstance(pub, str):
        try:
            pub = datetime.fromisoformat(pub.replace("Z", "+00:00"))
        except Exception:
            pub = None
    if isinstance(pub, datetime):
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        hours_old = (datetime.now(timezone.utc) - pub.astimezone(timezone.utc)).total_seconds() / 3600
        recency = max(0.0, 1.0 - hours_old / 96.0)  # linear decay over 4 days
    type_weight = {
        "x_user": 1.0,
        "github_org": 0.95,
        "rss": 0.7,
    }.get(item.get("source_type", "rss"), 0.6)
    return round(0.55 * base + 0.25 * recency + 0.20 * type_weight, 4)


def filter_and_rank(items: list[dict], *, limit: int) -> list[dict]:
    for it in items:
        it["_score"] = relevance_score(it)
    items.sort(key=lambda x: x.get("_score", 0.0), reverse=True)
    return items[:limit]


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run(
    profile_name: str,
    *,
    limit: int,
    hours_lookback: int,
    dry_run: bool,
    no_publish: bool,
    offline: bool = False,
) -> dict:
    profile = load_profile(profile_name)
    keywords = profile.get("keywords") or ["AI", "LLM"]
    if hours_lookback is None:
        hours_lookback = int(profile.get("hours_lookback", 72))
    sources = profile.get("sources", [])

    LOG.info("=" * 60)
    LOG.info("Profile: %s", profile_name)
    LOG.info("Sources: %d", len(sources))
    LOG.info("Hours lookback: %d", hours_lookback)
    LOG.info("Limit: %d", limit)
    if offline:
        LOG.info("Mode: OFFLINE (using built-in fixture items; network skipped)")
    LOG.info("=" * 60)

    # Stage 1: fetch
    t0 = time.time()
    if offline:
        items_raw = _offline_items()
        stats = {
            "total": len(items_raw),
            "per_source": {it["source"]: 0 for it in items_raw},
            "errors": {},
            "started_at": datetime.now(timezone.utc).isoformat(),
            "mode": "offline",
        }
        # Count per source
        from collections import Counter
        c = Counter(it["source"] for it in items_raw)
        stats["per_source"] = dict(c)
    else:
        items_raw, stats = fetch_all(sources)
    LOG.info("Fetched %d raw items in %.1fs", len(items_raw), time.time() - t0)

    # Stage 2: normalize + dedupe
    t0 = time.time()
    items_norm = normalize(items_raw, hours_lookback=hours_lookback)
    LOG.info("After normalize/dedupe: %d items in %.1fs", len(items_norm), time.time() - t0)

    # Stage 3: digest
    t0 = time.time()
    digested = digest_items(items_norm, keywords=keywords)
    LOG.info("Digested %d items in %.1fs", len(digested), time.time() - t0)

    # Stage 4: rank + limit
    ranked = filter_and_rank(digested, limit=limit)
    LOG.info("Final: %d items", len(ranked))

    if dry_run:
        LOG.info("--dry-run set; not writing RSS or report.")
        return {
            "profile": profile_name,
            "stats": stats,
            "items": ranked,
        }

    # Stage 5: render
    out_cfg = profile.get("output", {}) or {}
    rss_path = REPO_ROOT / out_cfg.get("rss", f"rss/{profile_name}.xml")
    md_path_tpl = out_cfg.get("markdown", f"reports/{profile_name}-{{date}}.md")
    md_path = REPO_ROOT / md_path_tpl.format(date=datetime.now().strftime("%Y-%m-%d"))

    feed_id = f"tag:daily-briefing,2026:{profile_name}"
    rss_info = render(
        feed_title=profile.get("title", profile_name),
        feed_subtitle=profile.get("subtitle", profile.get("description", "")),
        feed_id=feed_id,
        profile=profile_name,
        items=ranked,
        out_path=str(rss_path),
    )
    LOG.info("RSS: %s (%d bytes, %d entries)", rss_info["path"], rss_info["bytes"], rss_info["entries"])

    md_info = render_markdown_report(
        profile=profile_name,
        feed_title=profile.get("title", profile_name),
        items=ranked,
        stats=stats,
        out_path=str(md_path),
    )
    LOG.info("MD : %s (%d bytes)", md_info["path"], md_info["bytes"])

    if no_publish:
        LOG.info("--no-publish set; not pushing.")
    else:
        LOG.info("(Local-only mode; no remote publish in M1.)")

    return {
        "profile": profile_name,
        "stats": stats,
        "rss": rss_info,
        "markdown": md_info,
        "items": ranked,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    p = argparse.ArgumentParser(description="Daily Briefing — M1 orchestrator")
    p.add_argument("--profile", default="ai-daily", help="profile name (profiles/<name>.yaml)")
    p.add_argument("--limit", type=int, default=None, help="max items in feed")
    p.add_argument("--hours-lookback", type=int, default=None, help="time window in hours")
    p.add_argument("--dry-run", action="store_true", help="do everything but write outputs")
    p.add_argument("--no-publish", action="store_true", help="skip publish step (M1: no-op)")
    p.add_argument("--out-json", default=None, help="write full result JSON to this path")
    p.add_argument("--offline", action="store_true",
                   help="use built-in fixture items (no network). For sandboxes / smoke tests.")
    args = p.parse_args()

    profile = load_profile(args.profile)
    limit = args.limit if args.limit is not None else int(profile.get("daily_limit", 20))

    try:
        result = run(
            profile_name=args.profile,
            limit=limit,
            hours_lookback=args.hours_lookback,
            dry_run=args.dry_run,
            no_publish=args.no_publish,
            offline=args.offline,
        )
    except Exception:
        LOG.exception("run failed")
        return 1

    if args.out_json:
        with open(args.out_json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        LOG.info("Wrote %s", args.out_json)

    # Top-line summary
    print("=" * 60)
    print(f"Profile: {result['profile']}")
    s = result["stats"]
    print(f"Raw fetched: {s.get('total', 0)} items across {len(s.get('per_source', {}))} sources")
    errs = s.get("errors", {})
    if errs:
        print(f"Source errors: {len(errs)}")
        for k, v in list(errs.items())[:5]:
            print(f"  - {k}: {v}")
    if "rss" in result:
        print(f"RSS: {result['rss']['path']}  ({result['rss']['entries']} entries, {result['rss']['bytes']} bytes)")
        print(f"MD : {result['markdown']['path']}")
    elif "items" in result:
        print(f"Items: {len(result['items'])}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
