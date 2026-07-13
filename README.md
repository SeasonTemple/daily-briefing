<div align="center">

# 📡 Daily Briefing

**通用每日信息聚合工具 · 管线固定,信源即配置 · LLM 摘要 + RSS 订阅**

![Hero Banner](assets/hero-banner.jpg)

<sub>给一组信源 + 关键词 + LLM prompt,就能产出该领域的 RSS 早报 · AI 日报只是其中一种 profile</sub>

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![RSS: Atom 1.0](https://img.shields.io/badge/output-Atom_1.0-orange.svg)](https://en.wikipedia.org/wiki/Atom_(web_standard))
![Sources: 44+](https://img.shields.io/badge/sources-44%2B-brightgreen.svg)
![LLM: Mavis M3](https://img.shields.io/badge/LLM-Mavis_M3-purple.svg)
![Schedule: Daily 07:00](https://img.shields.io/badge/schedule-daily_07:00-blue.svg)

[Why](#-why-daily-briefing) · [Try it](#-try-the-demo) · [How it works](#-how-it-works) · [Profiles](#-profile--领域即配置) · [Getting started](#-getting-started) · [Subscribe](#-subscribe-in-feedly) · [Roadmap](#-roadmap)

</div>

---

## 🤔 Why Daily Briefing

信息流 24h 都在爆炸,但**真正值得看的精华 = 2-3 条**。现在的痛点:

- **二手转载慢 6-24h** —— 36Kr 写"GPT-5 出了",原推早 8 小时就在 Sam Altman 那
- **模型厂家 Nitter 镜像全挂,你看不到一手** —— X 官号是真金矿,Anthropic/OpenAI/DeepMind 的 release 比任何媒体都快
- **英文信源读着累** —— 你想看到中文摘要 + 关键信息,但不想每条都自己翻译
- **一天刷十几个 source 太累** —— 不刷又怕错过

**Daily Briefing 的解法**: 每天 7:00 自动跑,33 个一手信源抓全,LLM 摘要翻译,扔到你的 RSS 阅读器(Feady / Inoreader / NetNewsWire 都行)。

---

## 🚀 Try the demo

**30 秒看到 RSS,零网络、零 LLM key**:

```bash
git clone https://github.com/SeasonTemple/daily-briefing.git
cd daily-briefing
pip install -r requirements.txt
python scripts/digest.py --profile ai-daily --offline --limit 10
```

打开 `rss/ai-daily.xml` 就是 10 条示例 entry,可以塞 Feedly 看格式。

**真信号模式**(需要网络):

```bash
# 配 LLM(可选)
cp .env.example .env
$EDITOR .env   # 填 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL

# 跑真抓取
python scripts/digest.py --profile ai-daily
```

---

## 🔧 How it works

```
[ profile.yaml ]  →  fetch.py  →  normalize.py  →  llm_digest.py  →  render_rss.py
   信源 + 关键词     多源抓取      标准化+去重         LLM 摘要+翻译       Atom 1.0 输出
                       ↓
                   Nitter 5 镜像 fallback + 单源失败不阻塞 + LLM 降级模板
```

**核心抽象**:**管线是代码(固定),领域是配置(yaml)**。换领域不动代码,加信源不动代码。

### 三层防御

| 层 | 防什么 | 怎么防 |
|----|-------|--------|
| **fetch** | 单源挂死全局 | 每个源独立 try/except,失败不阻塞;Nitter 5 镜像轮询 |
| **digest** | LLM API 限流 | 30s 超时 + ThreadPool 并发;失败降级用模板(标题 + 原文前 80 字) |
| **render** | RSS 阅读器不更新 | feed 头 `<updated>` 用当前时间;稳定的 tag URI id |

### 信源类型

| Type | 配置 | 抓取方式 | 适用 |
|------|------|---------|------|
| `rss` | `name`, `url` | 任意 RSS/Atom | 几乎所有有 feed 的网站 |
| `x_user` | `handle`(无 @) | Nitter 多镜像轮询 | 跟踪 X 官号、关键人物 |
| `github_org` | `org` | GitHub org events Atom | 跟踪 org 下的所有 release/活动 |
| `opml` | `path` (M2) | 整个 OPML 文件 | 一次性导入用户订阅列表 |
| `web_search` | `query` (M2) | Tavily / SearXNG | 兜底,搜不到信源的内容 |

---

## 📁 Profile = 领域即配置

> **加新领域 = 复制 yaml + 改 sources,代码零改动**。详见 [`profiles/README.md`](./profiles/README.md)

### 5 分钟创建你的 profile

```bash
cp profiles/ai-daily.yaml profiles/my-domain.yaml
$EDITOR profiles/my-domain.yaml   # 改 profile / title / sources / keywords
python scripts/digest.py --profile my-domain
```

### 已提供的 3 个示例

| Profile | 跟踪什么 | 信源数 | 一手占比 | 跑法 |
|---------|---------|------:|--------:|------|
| `ai-daily` | AI 工程圈(模型 / 论文 / 关键人物) | 33 | 70%+ | `python scripts/digest.py --profile ai-daily` |
| `example-finance-daily` | 美股 + 宏观财经(SEC / 联储 / 头部媒体) | 14 | 50%+ | `python scripts/digest.py --profile example-finance-daily` |
| `example-dev-daily` | 通用开发者动态(GitHub Trending / HN / dev.to) | 19 | 60%+ | `python scripts/digest.py --profile example-dev-daily` |

每个 profile 都覆盖:
- **A. 一手机构信源**(org 官方 / 监管 / 论文)
- **B. 关键人物 X 官号**
- **C. GitHub orgs**(开源 release / 活动)
- **D. arXiv / 学术 / 论文**
- **E. 二手聚合兜底**(HN / 36Kr / 少数派 / Lobsters)

### 加新领域的 3 种模式

```yaml
# 模式 A:跟踪一个组织
profile: anthropic-internal
sources:
  - { type: x_user, handle: "AnthropicAI" }
  - { type: x_user, handle: "sama" }
  - { type: rss, name: "Anthropic News", url: "https://www.anthropic.com/news/rss.xml" }
  - { type: github_org, org: "anthropics" }
keywords: [Anthropic, Claude, Agent, ...]
```

```yaml
# 模式 B:跟踪一个行业(多组织)
profile: ai-llm-industry
sources:
  - { type: x_user, handle: "AnthropicAI" }
  - { type: x_user, handle: "OpenAI" }
  - { type: x_user, handle: "GoogleDeepMind" }
  - { type: x_user, handle: "xai" }
  - { type: rss, name: "arXiv cs.AI", url: "http://export.arxiv.org/rss/cs.AI" }
  - { type: rss, name: "HN", url: "https://hnrss.org/frontpage" }
```

```yaml
# 模式 C:跟踪个人关注(混合,加 OPML)
profile: my-morning-brief
sources:
  - { type: rss, name: "HN", url: "https://hnrss.org/frontpage" }
  - { type: x_user, handle: "dabor1234" }
  - { type: github_org, org: "vercel" }
  - { type: opml, path: "user_opml/feeds.opml" }
```

---

## 🛠️ Getting started

### 本地跑

```bash
git clone https://github.com/SeasonTemple/daily-briefing.git
cd daily-briefing

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
$EDITOR .env   # 填 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL(可选)

python scripts/digest.py --profile ai-daily
```

产出 `rss/ai-daily.xml` + `reports/ai-daily-{date}.md`。

### 部署到 GitHub Pages + 自动跑(零运维)

详见 [`DEPLOY.md`](./DEPLOY.md)。两条路:

- **A. GitHub Actions**(推荐,标准 GitHub 流程)—— 配 3 个 secret(LLM key),GitHub 每天 7:00 自动跑
- **B. mavis cron**(我帮你全自动)—— 给我 GitHub PAT,LLM 用我(Mavis M3)免配 key

跑通后订阅 URL:
```
https://seasontemple.github.io/daily-briefing/rss/ai-daily.xml
```

### 命令行常用参数

```bash
# 本地预览(不写文件)
python scripts/digest.py --profile ai-daily --dry-run

# 只看 N 条
python scripts/digest.py --profile ai-daily --limit 5

# 看更长时间窗(默认 72h)
python scripts/digest.py --profile ai-daily --hours-lookback 168

# 输出 JSON 给其他程序处理
python scripts/digest.py --profile ai-daily --out-json result.json

# 沙箱/无网络模式(内置 fixture)
python scripts/digest.py --profile ai-daily --offline --limit 10
```

---

## 📡 Subscribe in Feedly

```
https://seasontemple.github.io/daily-briefing/rss/ai-daily.xml
```

1. 打开 Feedly
2. **Add source** → 粘贴上面 URL
3. 完成 — 每天 7:00 自动收到 8-15 条精选

> Inoreader / NetNewsWire / Reeder / RSS Reader 等任何标准 RSS 阅读器都支持。

---

## 🗺️ Roadmap

| Milestone | 内容 | 状态 |
|-----------|------|:----:|
| **M1** MVP | 单 profile 跑通(ai-daily)+ 33 信源 + LLM 脱水 + RSS 输出 + offline 模式 | ✅ |
| **M2** | 多 profile cron 自动化 / OPML 导入 / Web 搜索兜底 / Playwright / 三维评分 / `prompts.*` 配置化 / HTML 简报 | 📋 |
| **M3** | GitHub Pages 部署已完成 ✅ / GitHub Actions cron ✅ / mavis cron ✅ / 健康检查 / 历史归档搜索 | 🚧 |

---

## 🧱 Tech stack

| 层 | 选择 | 理由 |
|----|------|------|
| 语言 | Python 3.10+ | 生态最全,跟现有同类项目对齐 |
| RSS 解析 | `feedparser` | 行业标准 |
| HTTP | `urllib`(M1) / `requests`(可选) | stdlib 优先,无依赖也跑得动 |
| LLM | 可配置: GLM-4-Flash / DeepSeek / OpenAI / 通义 / **Mavis M3** | 默认 GLM-4-Flash,便宜;M3 零成本 |
| 部署 | GitHub Pages(默认) / Vercel / 自托管 | RSS 友好,零运维 |
| 调度 | `mavis` cron / GitHub Actions | 二选一,前者本地,后者云端 |

---

## 🤝 Contributing

加新信源类型(比如 `web_search` / `opml` / `github_repo`):
- 在 `scripts/fetch.py` 加一个 `fetch_<type>()` 函数
- 在 `profiles/README.md` 文档化
- 加 example profile 演示

加新领域示例 profile:
- `cp profiles/EXAMPLE-ai-daily.yaml profiles/example-<新名>.yaml`
- 改 sources
- PR

---

## 📋 故障排查

| 问题 | 排查 |
|------|------|
| `No module named feedparser` | `pip install -r requirements.txt` |
| RSS 里都是"X 源不可用" | Nitter 镜像全挂,等 M2 Web 搜索兜底;或换 RSSHub |
| LLM 摘要都是模板 | 检查 `.env` 里的 `LLM_API_KEY`;`LLM_BASE_URL` 是否通 |
| RSS 阅读器不更新 | 检查 `rss/ai-daily.xml` 顶部的 `<updated>` 时间戳 |
| 信源全空 | `python scripts/digest.py --dry-run --limit 5` 看每个源 stats |
| Nitter 报错 | 镜像经常换,改 `scripts/fetch.py` 里 `NITTER_MIRRORS` 列表 |

---

## 📂 Project structure

```
daily-briefing/
├── README.md                    # 本文件
├── PLAN.md                      # 完整规划与设计文档
├── DEPLOY.md                    # 部署手册
├── LICENSE                      # MIT
├── index.html                   # GitHub Pages 落地页
├── profiles/                    # ★ 领域配置(profile = 一组信源)
│   ├── README.md
│   ├── ai-daily.yaml
│   ├── example-finance-daily.yaml
│   └── example-dev-daily.yaml
├── scripts/                     # ★ 固定管线(与领域无关)
│   ├── fetch.py                 # 多源抓取
│   ├── normalize.py             # 标准化 + 去重
│   ├── llm_digest.py            # LLM 摘要 + 翻译
│   ├── render_rss.py            # RSS 输出
│   └── digest.py                # 主入口
├── assets/                      # README 资源
│   └── hero-banner.jpg
├── reports/                     # 每日 Markdown 归档
├── rss/                         # 生成的 RSS feed
├── .github/workflows/daily.yml  # GitHub Actions cron
├── mavis/cron.example.json      # mavis cron 配置示例
├── requirements.txt
└── .env.example
```

---

<div align="center">

**Made with ☕ by SeasonTemple · Powered by Mavis M3**

[⬆ Back to top](#-daily-briefing)

</div>
