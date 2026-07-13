# 每日前沿信息聚合 + Agent 评价 + RSS 订阅

> 状态: 规划中 v0.1 · 作者: Mavis · 日期: 2026-07-13

---

## 1. 一句话定位

> **通用的每日信息聚合工具**。管线固定(`fetch → normalize → dedupe → score → LLM digest → RSS`),
> 差异全在配置——给一组信源 + 关键词 + LLM prompt,就得到一个该领域的 RSS 早报。
> AI 日报只是其中一种 profile。

**核心设计哲学**: **管线是框架(代码),领域是数据(profile yaml)**。

| 维度 | 实现方式 |
|------|---------|
| 通用管线 | `scripts/fetch.py` / `normalize.py` / `digest.py` / `render_rss.py` — 与领域无关 |
| 领域差异 | `profiles/<name>.yaml` — 信源列表 + 关键词 + LLM prompt + 输出路径 |
| 加新领域 | **零代码改动**:`cp profiles/EXAMPLE.yaml profiles/my-domain.yaml`,改 sources 即可 |
| 加新信源类型 | `scripts/fetch.py` 加 1 个 fetcher 函数,其他都不动 |

**为什么是 RSS 输出**: 市面已有项目(cclank/news-aggregator、last30days、ai-daily-digest)
大多是「输出 Markdown 报告给 Agent 读」,本工具把早报本身做成 RSS feed,
让用户像订阅播客一样订阅「每日 X 圈」(X 是任何你关心的领域),
每天自动收 3-10 条精炼的精华流,而不是每次主动拉取。

---

## 2. Profile = 领域 = 一组信源 + 一段 prompt

```yaml
# profiles/my-domain.yaml
profile: my-domain              # 唯一标识
title: "我的领域每日精华"
description: "为什么需要这个 profile"

# ⚡ 核心:信源列表
sources:
  - { type: rss, name: "...", url: "..." }
  - { type: x_user, handle: "..." }
  - { type: github_org, org: "..." }
  - { type: opml, path: "user_sources.opml" }    # 也可整个 OPML 喂进来

# 关键词(影响评分 + LLM prompt 上下文)
keywords: [...]

# 领域专属 LLM prompt(M1 用代码里的默认,M2 移到配置)
# prompts: { summarize: "你是<领域>资深编辑..." }

# 输出
output: { rss: "rss/my-domain.xml", markdown: "reports/my-domain-{date}.md" }

# 评分
scoring: { recency_weight: 0.25, relevance_weight: 0.45, engagement_weight: 0.30 }
```

**已提供 3 个示例 profile**(在 `profiles/` 下):

| Profile | 信源 | 用例 |
|---------|------|------|
| `ai-daily.yaml` | X 官号 / 关键人物 / 官网 / GitHub / arXiv | AI 工程圈 |
| `example-finance-daily.yaml` | SEC / 财经媒体 / 经济日历 | 美股 + 宏观 |
| `example-dev-daily.yaml` | GitHub Trending / HN / dev.to / Lobsters | 通用开发者动态 |

**用别的领域**: 复制任意 example,改 `sources` + `keywords` + 标题即可。代码一行不动。

---

## 3. 关键参考与启发

| 项目 | 借鉴点 | 不借鉴点 |
|------|-------|---------|
| [cclank/news-aggregator-skill](https://github.com/cclank/news-aggregator-skill) | 44+ 源 + OPML 自定义 + Deep Fetch + 统一报告模板 | 它输出 Markdown,不做 RSS |
| [mvanhorn/last30days-skill](https://github.com/mvanhorn/last30days-skill) (35.7K★) | 跨平台、AI 评价系统(fun+relevance judge)、Shareable HTML brief | 它按 topic 临时查,不做定时领域订阅 |
| [vigorX777/ai-daily-digest](https://github.com/vigorX777/ai-daily-digest) | Gemini 三维评分(相关性/质量/时效性)、Top-N 筛选 | 输出单条报告,不做领域分流 |
| [Jesseovo/last30days-skill-cn](https://github.com/Jesseovo/last30days-skill-cn) | 中文平台支持(微博/知乎/小红书) | 偏爬虫路线,合规风险高 |
| [LearnPrompt/ai-news-radar (懂王)](https://github.com/LearnPrompt/ai-news-radar) | 多源聚合 + 结构化 JSON + GitHub Pages 静态站 | 它做整站,不做 RSS feed |
| [quotedance-rss-digest](https://clawhub.ai/yoocky/quotedance-rss-digest) | RSSHub + 按源过滤 + 本地缓存 | 依赖外部 service,部署门槛高 |

**我的核心提炼**:
1. **领域可配置**,不要写死信源列表
2. **RSS 作为一等公民输出**(不是 markdown 之后)
3. **多视角评价**: 不是单一"摘要",而是「价值/风险/启发/数据」四维
4. **静态站 + RSS**: 走 GitHub Pages / Vercel,运维成本几乎为零

---

## 4. 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                  每天 07:00 cron 触发                        │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  [1] 收集层 fetch                                           │
│  ┌──────────────┬──────────────┬──────────────────────────┐ │
│  │ RSS/Atom 源  │ OPML 自定义  │ Web 搜索(可选)           │ │
│  │ feedparser   │ 见 user_*.opml│ Tavily/Perplexity/SearXNG│ │
│  └──────────────┴──────────────┴──────────────────────────┘ │
│  支持 --deep(Playwright 穿 Cloudflare 拿正文)                │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  [2] 标准化 + 去重 normalize + dedupe                        │
│  Schema: {id, title, url, source, time, content, heat, lang}│
│  去重: URL 规范化 + 标题相似度(rapidfuzz)                    │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  [3] 评分层 score                                           │
│  相关性(45%) × 时效性(25%) × 互动度(30%)                    │
│  相关性: 与「目标领域关键词」向量/字面匹配                    │
│  互动度: HN points / GitHub stars / 微博热度 等归一化         │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  [4] 脱水 + 多视角评价 (LLM Agent)                          │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Step 1 摘要: 一句话中文概括(< 30 字)                  │ │
│  │  Step 2 深度解读: 背景/影响/技术价值(60-120 字)        │ │
│  │  Step 3 多视角评价:                                   │ │
│  │    🎯 价值(给读者带来什么)                            │ │
│  │    ⚠️  风险/争议点                                    │ │
│  │    💡 启发/可行动点                                   │ │
│  │    📊 关键数据                                        │ │
│  │  Step 4 翻译(英文 → 中文)                              │ │
│  └────────────────────────────────────────────────────────┘ │
│  降级: LLM 失败时返回基础摘要,不阻塞流水线                   │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  [5] 输出层 outputs                                         │
│  ├── digest.html         完整 HTML 简报(可分享/打印)         │
│  ├── rss/ai-daily.xml    按领域的 RSS feed(主交付物)         │
│  ├── rss/finance-daily.xml                                  │
│  └── reports/YYYY-MM-DD.md  每日归档 Markdown              │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  [6] 部署层 publish                                         │
│  默认: GitHub Pages(免费/自动)                              │
│  可选: Vercel / Cloudflare Pages / 自托管                   │
│  订阅: 用户在 Feedly 加 https://<user>.github.io/rss/ai.xml  │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. 模块设计

### 4.1 配置: profiles.yaml

```yaml
profiles:
  ai-daily:
    title: "AI 圈每日精华"
    description: "跟踪 AI 工程、模型、行业事件"
    keywords: ["LLM", "Agent", "GPT", "Claude", "RAG", "DeepSeek", ...]
    sources:
      - type: rss
        url: https://hnrss.org/frontpage
      - type: rss
        url: https://www.aibase.com/daily/feed
      - type: opml
        path: user_sources_ai.opml
    schedule: "0 7 * * *"   # 每天 7:00
    max_items: 15
    llm:
      model: "glm-4-flash"  # 或 deepseek-chat
    output:
      rss: rss/ai-daily.xml
      html: digest/ai-daily.html
```

支持多个 profile 并行运行,每个 profile 独立 RSS feed。

### 4.2 核心脚本

```
scripts/
├── fetch.py          # 多源抓取(RSS/OPML/Web 搜索/Playwright)
├── normalize.py      # 标准化 + 去重
├── score.py          # 三维评分
├── digest.py         # LLM 脱水 + 多视角评价(主入口)
├── render_rss.py     # 生成 RSS XML
├── render_html.py    # 生成 HTML 简报
└── publish.py        # git push / 部署
```

调用方式:
```bash
# 单 profile
python scripts/digest.py --profile ai-daily

# 全 profile
python scripts/digest.py --all

# 本地预览
python scripts/digest.py --profile ai-daily --no-publish
```

### 4.3 LLM Prompt 设计(关键)

```text
你是一名资深[领域]编辑,负责为每日早报写一条「精炼条目」。

输入: 标题 + 原文摘要 + 来源 + 互动度
输出(JSON 严格):
{
  "headline": "中文标题(若原英文则翻译, ≤ 25 字)",
  "summary": "一句话核心信息(≤ 40 字)",
  "deep_dive": "深度解读, 包含背景/影响/价值(60-120 字)",
  "perspectives": {
    "value": "这条对读者的价值是什么",
    "risk": "潜在风险或争议点(无则写 '无显著风险')",
    "insight": "可行动/可借鉴的点",
    "data": "关键数据(若有)"
  }
}

约束:
- 严守原文事实, 不编造数据/因果
- 主观评价有依据, 不空泛
- 若文章主题与领域弱相关, 在 relevance 字段打 < 0.3
```

### 4.4 RSS 输出 schema(Atom 1.0)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>AI 圈每日精华</title>
  <updated>2026-07-13T07:00:00+08:00</updated>
  <id>tag:user,2026:ai-daily</id>
  <entry>
    <title>Anthropic 发布 Claude Code 2.0</title>
    <link href="https://..."/>
    <id>tag:user,2026:ai-daily:2026-07-13:001</id>
    <updated>2026-07-13T08:30:00+08:00</updated>
    <summary type="html"><![CDATA[
      <p><b>摘要</b>: ...</p>
      <p><b>深度解读</b>: ...</p>
      <p><b>价值</b>: 🎯 ...</p>
      <p><b>风险</b>: ⚠️ ...</p>
      <p><b>启发</b>: 💡 ...</p>
      <p><b>数据</b>: 📊 ...</p>
      <p><a href="...">原文</a></p>
    ]]></summary>
    <category term="ai-daily"/>
  </entry>
  ...
</feed>
```

---

## 6. 技术选型

| 层 | 选择 | 理由 |
|----|------|-----|
| 语言 | **Python 3.11+** | 与 cclank/last30days 一致,生态最全 |
| RSS 解析 | `feedparser` | 行业标准 |
| 评分 | `rapidfuzz` + `numpy` | 标题相似度快 |
| Web 搜索 | `tavily-python` / SearXNG | Tavily AI 友好,免费 1000/月;SearXNG 自托管 |
| 反爬 | `playwright` (可选) | 穿 Cloudflare |
| LLM | **可配置**: GLM-4-Flash / DeepSeek / OpenAI / Anthropic | 默认用 GLM-4-Flash(便宜) |
| HTML 渲染 | **Jinja2** + 内联 CSS | last30days 风格,单文件可分享 |
| RSS 输出 | 手写 Atom 1.0 | 不引第三方,简单可控 |
| 部署 | **GitHub Pages**(默认) / Vercel | 免费、自动、RSS 友好 |
| 调度 | `mavis` cron / GitHub Actions cron | 二选一,前者本地,后者云端 |

---

## 7. 实施路线(三个 Milestone)

### M1 · MVP(2-3 天)

- 单 profile(`ai-daily`)
- 5-8 个硬编码信源(HN/GitHub Trending/36Kr/微博热搜/少数派/InfoQ/AI Newsletters)
- RSS/Atom 抓取 + URL 去重
- 单 profile LLM 摘要 + 翻译
- 输出 RSS feed + Markdown 报告
- 本地 cron + 手动 publish

**验证**: 用户能在 Feedly 订阅到 RSS,点开 3-5 条都是有质量的中文条目。

### M2 · 多 profile + OPML(3-4 天)

- profiles.yaml 多 profile 配置
- OPML 导入/导出
- Web 搜索兜底(Tavily/SearXNG)
- Deep Fetch(Playwright)可选
- 三维评分(相关/时效/互动)
- 多视角评价 prompt
- HTML 简报

**验证**: 切到 `finance-daily` profile,新出独立 RSS feed,内容与 ai-daily 互不污染。

### M3 · 自动化 + 公网部署(2-3 天)

- 接入 mavis cron / GitHub Actions
- 部署到 GitHub Pages / Vercel
- 一键初始化新 profile
- 健康检查(源失效提醒)
- 历史归档 + 搜索

**验证**: 关掉电脑,每天 7 点自动产出,Feedly 自动收到新条目。

---

## 8. 关键决策点(请用户拍板)

| # | 问题 | 我的推荐 |
|---|------|---------|
| Q1 | 第一个 profile 选什么领域? | **AI 工程圈**(信源成熟、中文友好) |
| Q2 | RSS 是单 feed(所有 profile 合并)还是多 feed(每 profile 一条)? | **多 feed**(用户可按需订阅) |
| Q3 | 部署走哪条路? | **GitHub Pages**(零运维,直接 RSS 友好) |
| Q4 | LLM 默认用什么? | **GLM-4-Flash**(便宜、够用),可换 DeepSeek |
| Q5 | 是否要支持 OPML 自定义源? | **M2 加**,M1 先用硬编码 |
| Q6 | 是否要 Web 搜索兜底(Tavily)? | **M2 加**,M1 仅 RSS |
| Q7 | 是否要 Deep Fetch(Playwright 穿 Cloudflare)? | **M2 加**,M1 先用 RSS summary |
| Q8 | 实施节奏: 一次性做满 M1+M2+M3,还是分批确认? | **分批**:先 M1 跑通,M2/M3 看效果再决定 |

---

## 9. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 信源失效/反爬 | 每个源独立 try/except,失败标记但不阻塞;给运营提供「源健康」指标 |
| LLM 不稳定/编造 | 严守 prompt 反幻觉约束 + JSON schema 校验;失败时回退基础摘要 |
| RSS 源被内容农场刷 | 互动度维度 + 重复域名去重 |
| 部署平台对 RSS 缓存 | GitHub Pages 直出 XML,加 `<updated>` 头避免缓存 |
| cron 跨时区 | profile 内显式 timezone;默认 Asia/Shanghai |
| 隐私/合规 | 仅抓公开 RSS,不做登录态爬取 |

---

## 10. 不做的事(明确边界)

- ❌ 不做微信公众号抓取(合规风险大)
- ❌ 不做小红书/抖音爬虫(同上)
- ❌ 不做实时推送(只做每日定时,这是 RSS 哲学)
- ❌ 不做交互式 Web UI(Feedly 就是 UI)
- ❌ 不做付费源(Reuters Connect 之类)

---

## 11. 仓库结构(目标)

```
daily-briefing/
├── PLAN.md                 # 本文件
├── README.md
├── pyproject.toml
├── profiles.yaml           # 用户配置
├── user_sources/           # OPML 自定义源
│   └── ai-daily.opml
├── scripts/
│   ├── fetch.py
│   ├── normalize.py
│   ├── score.py
│   ├── digest.py           # 主入口
│   ├── render_rss.py
│   ├── render_html.py
│   └── publish.py
├── prompts/
│   ├── summarize.md        # LLM prompt 模板
│   └── perspectives.md
├── src/
│   └── digest/             # 可复用 Python 包
├── reports/                # 每日归档
├── rss/                    # 生成的 RSS feed
├── digest/                 # HTML 简报
└── .github/workflows/
    └── daily.yml           # GitHub Actions cron
```

---

## 12. 下一步

- 收到 Q1-Q8 的答复后, 我会先 M1 落地一个能跑通的 ai-daily
- 跑一周看真实效果(信源质量、prompt 是否合理、RSS 阅读器体验)
- 再决定 M2/M3 的具体范围

*End of Plan v0.1*
