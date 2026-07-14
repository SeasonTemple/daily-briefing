# Profiles · 领域即配置

> **核心设计哲学**: 管线是框架(代码),领域是数据(yaml)。
> 加新领域 = 复制 yaml + 改 sources,**零代码改动**。

---

## 5 分钟创建你的第一个 profile

```bash
# 1. 复制一个示例
cp profiles/ai-daily.yaml profiles/my-domain.yaml

# 2. 编辑它
$EDITOR profiles/my-domain.yaml
#   改: profile / title / description / sources / keywords

# 3. 跑起来
python scripts/digest.py --profile my-domain

# 4. 订阅
# 生成的 rss/my-domain.xml 直接加到 Feedly / Inoreader / NetNewsWire
```

---

## Profile Schema 速查

```yaml
# ===== 必须 =====
profile: <唯一标识,小写+短横线>           # 命令行 --profile 用这个
title: "..."                              # RSS feed 的标题
sources:                                  # 信源列表(核心)
  - { type: rss, name: "...", url: "..." }
  - { type: x_user, handle: "..." }
  - { type: github_org, org: "..." }
  - { type: opml, path: "user_sources.opml" }

# ===== 推荐 =====
description: "..."                        # 一句话说明这个 profile 跟踪什么
keywords: [词1, 词2, ...]                 # 用于相关度评分 + LLM 上下文
author: "..."                              # RSS feed 的 author 字段
language: zh-CN
timezone: Asia/Shanghai
hours_lookback: 72                         # 抓多久内的内容
daily_limit: 20                            # 最多出多少条

# ===== 输出路径(可选) =====
output:
  rss: rss/<profile>.xml
  markdown: reports/<profile>-{date}.md

# ===== 评分权重(可选,有默认) =====
scoring:
  recency_weight: 0.25
  relevance_weight: 0.45
  engagement_weight: 0.30
```

---

## 支持的 source type

| Type | 配置 | 抓取方式 | 适用 |
|------|------|---------|------|
| `rss` | `name`, `url` | 任意 RSS/Atom | 几乎所有有 feed 的网站 |
| `x_user` | `handle` (无 @) | Nitter 多镜像轮询 | 跟踪 X 官号、关键人物 |
| `github_org` | `org` | GitHub org events Atom | 跟踪 org 下的所有 release/活动 |
| `github_repo` | `repo` (M2) | GitHub releases | 跟踪单 repo |
| `opml` | `path` (M2) | 整个 OPML 文件 | 一次性导入用户订阅列表 |
| `web_search` | `query` (M2) | Tavily / SearXNG | 兜底,搜不到信源的内容 |

**扩展新 type**: 在 `scripts/fetch.py` 里加一个 `fetch_<type>()` 函数,其他都不动。

---

## 现成的 3 个示例

| 文件 | 领域 | 信源数 | 怎么用 |
|------|------|-------:|--------|
| `ai-daily.yaml` | AI 工程圈(默认) | 33 | `python scripts/digest.py --profile ai-daily` |
| `finance-daily.yaml` | 美股 + 宏观财经 | 12 | 复制改名跑 |
| `developer-daily.yaml` | 通用开发者动态 | 10 | 复制改名跑 |

---

## 加新领域的常见模式

### 模式 A: 跟踪一个组织
```yaml
profile: anthropic-internal
sources:
  - { type: x_user, handle: "AnthropicAI" }
  - { type: x_user, handle: "sama" }  # 也想跟 Sam Altman
  - { type: rss, name: "Anthropic News", url: "https://www.anthropic.com/news/rss.xml" }
  - { type: github_org, org: "anthropics" }
keywords: [Anthropic, Claude, Agent, ...]
```

### 模式 B: 跟踪一个行业(多组织)
```yaml
profile: ai-llm-industry
sources:
  # 6 个模型厂家
  - { type: x_user, handle: "AnthropicAI" }
  - { type: x_user, handle: "OpenAI" }
  - { type: x_user, handle: "GoogleDeepMind" }
  - { type: x_user, handle: "AIatMeta" }
  - { type: x_user, handle: "xai" }
  - { type: x_user, handle: "deepseek_ai" }
  # 关键人物
  - { type: x_user, handle: "sama" }
  - { type: x_user, handle: "ylecun" }
  # 论文
  - { type: rss, name: "arXiv cs.AI", url: "http://export.arxiv.org/rss/cs.AI" }
  - { type: rss, name: "HF Papers", url: "https://huggingface.co/papers" }
  # 社区
  - { type: rss, name: "HN", url: "https://hnrss.org/frontpage" }
```

### 模式 C: 跟踪个人关注(混合)
```yaml
profile: my-morning-brief
sources:
  - { type: rss, name: "HN", url: "https://hnrss.org/frontpage" }
  - { type: rss, name: "TechCrunch", url: "https://techcrunch.com/feed/" }
  - { type: x_user, handle: "dabor1234" }     # 你关注的大 V
  - { type: github_org, org: "vercel" }       # 你用的框架的官方
  - { type: opml, path: "user_opml/feeds.opml" }  # 你现有的订阅列表
keywords: [frontend, devtools, AI, ...]
```

---

## Tips

- **想抓的内容不出现?** 加 `keywords` 提高相关度,或调 `scoring.relevance_weight` 更高
- **X (Twitter) 抓不到?** Nitter 镜像经常挂,M2 会加 Web 搜索兜底
- **同一个事件多源重复?** 已默认 URL 规范化 + 标题相似度去重(rapidfuzz 88%)
- **想跨多个领域?** 一个 RSS reader 订阅多个 profile 的 RSS 即可,完全独立
- **想本地调试?** 加 `--dry-run` 只跑不写文件,加 `--limit 3` 只看 3 条

---

## 后续计划(M2/M3)

- M2: `prompts.summarize` / `prompts.perspectives` 字段,prompt 也配置化
- M2: `web_search` source type(Tavily / SearXNG 兜底)
- M2: `opml` source type(整个 OPML 喂进来)
- M2: GitHub repo / 单 repo release 跟踪
- M3: `cron` / GitHub Actions 自动化
- M3: GitHub Pages 部署,profile 路径直接是公开 URL
