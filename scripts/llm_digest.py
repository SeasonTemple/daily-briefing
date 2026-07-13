"""
llm_digest.py — LLM digest stage.

For each item, the LLM is asked to return a strict JSON:
  {
    "headline":   str  ≤ 25 中文字符 (translated if English)
    "summary":    str  ≤ 40 中文字符 (one-line gist)
    "relevance":  float 0-1  (how on-topic vs profile keywords)
    "key":        str  ≤ 40  (key data point, e.g. "模型: Claude 3.5")
  }

If LLM is unavailable (no key, network error, parse error, schema violation),
we fall back to a deterministic template:
  - title itself (or a truncated version),
  - first 80 chars of content as summary,
  - relevance computed from keyword match (0-1),
  - key derived from the source label.

A 30s timeout is enforced per call. The whole digest stage has its own
graceful degradation so a single bad item never breaks the pipeline.
"""
from __future__ import annotations

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

LOG = logging.getLogger("llm_digest")

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

PROMPT_TEMPLATE = """你是一名「AI 圈每日早报」资深编辑。请阅读下面的素材,产出 1 条精炼条目,严格返回 JSON。

【Profile 关键词】 {keywords}

【素材】
- 来源: {source}
- 作者: {author}
- 标题: {title}
- 摘要: {content}

【输出要求】仅返回 JSON,不要任何额外文字、Markdown 代码块、解释。Schema:
{{
  "headline":  "<中文标题, ≤ 25 字,英文标题请意译>",
  "summary":   "<一句话核心信息, ≤ 40 字,中文>",
  "relevance": <0-1 浮点, 与 AI/ML 主题相关度>,
  "key":       "<关键信息(模型名/数据点/事件), ≤ 40 字,中文>"
}}
"""

# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

_LEN_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")


def _char_len(s: str) -> int:
    return len(_LEN_RE.findall(s or ""))


def _clip(s: str, n: int) -> str:
    if not s:
        return ""
    if _char_len(s) <= n:
        return s.strip()
    out, count = [], 0
    for ch in s:
        out.append(ch)
        if _LEN_RE.match(ch):
            count += 1
        if count >= n:
            break
    return ("".join(out).rstrip() + "…") if count >= n else "".join(out)


def _validate_schema(obj: Any) -> dict | None:
    if not isinstance(obj, dict):
        return None
    headline = str(obj.get("headline", "")).strip()
    summary = str(obj.get("summary", "")).strip()
    key = str(obj.get("key", "")).strip()
    rel = obj.get("relevance", 0.5)
    try:
        rel = float(rel)
        rel = max(0.0, min(1.0, rel))
    except Exception:
        rel = 0.5
    if not headline:
        return None
    return {
        "headline": _clip(headline, 25),
        "summary": _clip(summary or headline, 40),
        "key": _clip(key or summary or headline, 40),
        "relevance": rel,
    }


# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------

class LLMClient:
    """OpenAI-compatible chat completion client (also works for GLM-4-Flash)."""

    def __init__(self) -> None:
        self.base = (os.getenv("LLM_BASE_URL") or "").rstrip("/")
        self.key = os.getenv("LLM_API_KEY") or ""
        self.model = os.getenv("LLM_MODEL", "glm-4-flash")
        self.timeout = int(os.getenv("LLM_TIMEOUT", "30"))
        self.enabled = bool(self.base and self.key)

    def chat(self, prompt: str) -> dict | None:
        if not self.enabled:
            return None
        url = f"{self.base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }
        use_json_mode = "glm" in self.model.lower() or "deepseek" in self.model.lower()
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a precise JSON-emitting assistant. Output valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 400,
        }
        if use_json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            r = requests.post(url, headers=headers, json=body, timeout=self.timeout)
        except requests.RequestException as e:
            LOG.warning("LLM request failed: %s", e)
            return None
        if r.status_code != 200:
            LOG.warning("LLM HTTP %s: %s", r.status_code, r.text[:200])
            return None
        try:
            data = r.json()
            content = data["choices"][0]["message"]["content"]
        except Exception as e:
            LOG.warning("LLM response parse error: %s", e)
            return None
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?", "", content).rstrip("`").strip()
        try:
            obj = json.loads(content)
        except json.JSONDecodeError as e:
            LOG.warning("LLM JSON decode error: %s; content=%r", e, content[:200])
            return None
        return _validate_schema(obj)


# ---------------------------------------------------------------------------
# Per-item digest
# ---------------------------------------------------------------------------

_ZH_RE = re.compile(r"[\u4e00-\u9fff]")


def _looks_chinese(s: str) -> bool:
    if not s:
        return False
    return len(_ZH_RE.findall(s)) / max(1, len(s)) > 0.3


def _keyword_relevance(text: str, keywords: list[str]) -> float:
    if not text or not keywords:
        return 0.5
    t = text.lower()
    hits = sum(1 for k in keywords if k.lower() in t)
    return min(1.0, round(0.3 + 0.7 * (hits / max(1, len(keywords) * 0.4)), 2))


def fallback_digest(item: dict, keywords: list[str]) -> dict:
    title = item.get("title", "")
    content = item.get("content", "")
    src = item.get("source", "unknown")
    combined = f"{title}\n{content[:400]}"
    rel = _keyword_relevance(combined, keywords)
    if _looks_chinese(title):
        headline = _clip(title, 25)
    else:
        headline = _clip(title, 25) or "(无标题)"
    summary_src = content or title
    summary = _clip(summary_src, 40)
    if not _looks_chinese(summary):
        first = re.split(r"[.。!?！？]\s", summary, maxsplit=1)[0]
        summary = _clip(first, 40)
    return {
        "headline": headline,
        "summary": summary,
        "key": src,
        "relevance": rel,
    }


def digest_item(item: dict, llm: LLMClient, keywords: list[str]) -> dict:
    prompt = PROMPT_TEMPLATE.format(
        keywords=", ".join(keywords[:20]) or "AI, LLM, Agent",
        source=item.get("source", "unknown"),
        author=item.get("author", ""),
        title=item.get("title", ""),
        content=(item.get("content") or "")[:1200],
    )
    parsed = llm.chat(prompt) if llm.enabled else None
    if parsed:
        return parsed
    return fallback_digest(item, keywords)


def digest_items(
    items: list[dict],
    *,
    keywords: list[str],
    concurrency: int = 4,
) -> list[dict]:
    llm = LLMClient()
    LOG.info("LLM enabled=%s, model=%s", llm.enabled, llm.model)
    if not llm.enabled:
        LOG.warning("LLM disabled (missing LLM_BASE_URL or LLM_API_KEY); using fallback only.")
    results: list[dict] = []
    if not llm.enabled or len(items) <= 4:
        for it in items:
            results.append({**it, "digest": digest_item(it, llm, keywords)})
        return results

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        fut_to_item = {ex.submit(digest_item, it, llm, keywords): it for it in items}
        for fut in as_completed(fut_to_item):
            it = fut_to_item[fut]
            try:
                d = fut.result(timeout=60)
            except Exception as e:
                LOG.warning("digest_item crash: %s", e)
                d = fallback_digest(it, keywords)
            results.append({**it, "digest": d})
    return results
