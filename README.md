# Daily Briefing · 通用每日信息聚合工具

> **管线固定,信源即配置**。给一组信源 + 关键词 + LLM prompt,就能产出该领域的 RSS 早报。
> **AI 日报只是其中一种 profile**(`ai-daily.yaml`),工具本身不绑任何领域。

---

## 1. 它是干嘛的

每天固定时间自动抓取你关心的「领域」最新信息 → 清洗去重 → LLM 脱水 / 多视角评价
→ 输出可订阅的 RSS 早报。

- **可以跟踪任何领域**: AI 圈 / 财经 / 开发者动态 / 高考志愿 / 学术前沿 / 公司动态 / 个人关注
- **可以同时跑多个领域**: 每个领域一个 profile,产出独立 RSS
- **可以用 RSS 阅读器订阅**: Feedly / Inoreader / NetNewsWire / Reeder,所有主流都支持
- **本地 / 私有部署**: 你的信源,你的 LLM,你的数据,完全自主

---

## 2. 5 分钟跑起来

```bash
# 1. 装依赖
pip install -r requirements.txt

# 2. 配 LLM(可选, 不配会自动降级)
cp .env.example .env
$EDITOR .env   # 填 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL

# 3. 跑(默认 profile 是 ai-daily)
python scripts/digest.py --profile ai-daily

# 4. 看产物
#   rss/ai-daily.xml         ← 订阅这个
#   reports/ai-daily-XXX.md  ← Markdown 归档
```

**跑别的领域**:
```bash
python scripts/digest.py --profile example-finance-daily
python scripts/digest.py --profile example-dev-daily
```

**加新领域** = 复制任意 profile 改名 + 改 `sources`(详见 [`profiles/README.md`](./profiles/README.md))。

---

## 3. 怎么用 / 怎么订阅

### 3.1 本地用 RSS 阅读器订阅

把生成的 RSS 文件地址加到阅读器:
- 本地路径: `file:///workspace/daily-briefing/rss/ai-daily.xml`
- 局域网 HTTP: 起个 `python -m http.server 8000`,然后 `http://<your-ip>:8000/rss/ai-daily.xml`

### 3.2 公网订阅(M3 部署后)

- 部署到 GitHub Pages / Vercel / 自托管
- 在 Feedly 加 `https://<your-domain>/rss/ai-daily.xml`

### 3.3 命令行常用参数

```bash
# 本地预览(不写文件)
python scripts/digest.py --profile ai-daily --dry-run

# 只看 3 条
python scripts/digest.py --profile ai-daily --limit 3

# 看更长时间窗(默认 72h)
python scripts/digest.py --profile ai-daily --hours-lookback 168

# 输出 JSON 给其他程序处理
python scripts/digest.py --profile ai-daily --out-json result.json
```

---

## 4. 架构(5 句话版)

```
[ profile.yaml ]  →  fetch.py  →  normalize.py  →  llm_digest.py  →  render_rss.py
   信源 + 关键词     多源抓取      标准化+去重         LLM 摘要+翻译       Atom 1.0 输出
                       ↓
                   Nitter 5 镜像 fallback + 单源失败不阻塞 + LLM 降级模板
```

**核心抽象**: **管线是代码,领域是配置**。换领域不动代码,加信源不动代码。

---

## 5. 已提供的 3 个示例 profile

| Profile | 跟踪什么 | 信源数 | 一手占比 |
|---------|---------|------:|--------:|
| [`ai-daily.yaml`](./profiles/ai-daily.yaml) | AI 工程圈(模型 / 论文 / 关键人物) | 33 | 70%+ |
| [`example-finance-daily.yaml`](./profiles/example-finance-daily.yaml) | 美股 + 宏观财经(SEC / 联储 / 头部媒体) | 14 | 50%+ |
| [`example-dev-daily.yaml`](./profiles/example-dev-daily.yaml) | 通用开发者动态(GitHub Trending / HN / dev.to) | 19 | 60%+ |

每个 profile 都覆盖:
- A. **一手机构信源**(org 官方 / 监管 / 论文)
- B. **关键人物 X 官号**
- C. **GitHub orgs**(开源 release / 活动)
- D. **arXiv / 学术 / 论文**
- E. **二手聚合兜底**(HN / 36Kr / 少数派 / Lobsters)

**加新领域的常见模式**(完整版见 `profiles/README.md`):
- 跟踪一个组织
- 跟踪一个行业(多组织)
- 跟踪个人关注(混合,加 OPML 喂进你现有订阅)

---

## 6. 技术选型

| 层 | 选择 | 理由 |
|----|------|-----|
| 语言 | Python 3.10+ | 生态最全,跟现有同类项目对齐 |
| RSS 解析 | `feedparser` | 行业标准 |
| HTTP | `urllib`(M1) / `requests`(可选) | stdlib 优先,无依赖也跑得动 |
| LLM | 可配置: GLM-4-Flash / DeepSeek / OpenAI / 通义 | 默认 GLM-4-Flash,便宜 |
| 部署 | GitHub Pages(默认) / Vercel / 自托管 | RSS 友好,零运维 |
| 调度 | `mavis` cron / GitHub Actions | 二选一 |

---

## 7. Roadmap

| Milestone | 内容 | 状态 |
|-----------|------|------|
| **M1** MVP | 单 profile 跑通(ai-daily)+ 33 信源 + LLM 脱水 + RSS 输出 | ✅ 完成 |
| **M2** | 多 profile / OPML / Web 搜索兜底 / Playwright / 三维评分 / HTML 简报 / `prompts.*` 配置化 | 📋 待办 |
| **M3** | cron 自动化 / GitHub Actions / GitHub Pages 部署 / 健康检查 / 历史归档 | 📋 待办 |

---

## 8. 故障排查

| 问题 | 排查 |
|------|------|
| `python3: No module named feedparser` | `pip install -r requirements.txt` |
| RSS 里都是"X 源不可用" | Nitter 镜像全挂,等 M2 Web 搜索兜底;或换 RSSHub |
| LLM 摘要都是模板 | 检查 `.env` 里的 `LLM_API_KEY` 是否有效;`LLM_BASE_URL` 是否通 |
| RSS 阅读器不更新 | 检查 `rss/ai-daily.xml` 顶部的 `<updated>` 时间戳 |
| 信源全空 | `python scripts/digest.py --dry-run --limit 5` 看每个源的 stats |
| Nitter 报错 | 镜像经常换,改 `scripts/fetch.py` 里 `NITTER_MIRRORS` 列表 |

---

## 9. 项目结构

```
daily-briefing/
├── PLAN.md                     # 完整规划与设计文档
├── README.md                   # 本文件
├── profiles/                   # ★ 领域配置
│   ├── README.md               # profile 设计哲学 + 怎么加新领域
│   ├── ai-daily.yaml           # 示例:AI 工程圈
│   ├── example-finance-daily.yaml
│   └── example-dev-daily.yaml
├── scripts/                    # ★ 固定管线(与领域无关)
│   ├── fetch.py                # 多源抓取
│   ├── normalize.py            # 标准化 + 去重
│   ├── llm_digest.py           # LLM 摘要 + 翻译
│   ├── render_rss.py           # RSS 输出
│   └── digest.py               # 主入口
├── reports/                    # 每日 Markdown 归档
├── rss/                        # 生成的 RSS feed
├── requirements.txt
└── .env.example
```

---

## 10. 接下来

**M1 验证完成后,推荐路径**:

1. 你在本地装好依赖,跑一次 `python scripts/digest.py --profile ai-daily` 看真实信号
2. 订阅生成的 `rss/ai-daily.xml` 到 Feedly,看几天 RSS 阅读器体验
3. 觉得 OK 之后,告诉我你**真正想跟踪的领域**,我帮你写一个生产 profile(替换示例)
4. 同步开 M2:加 OPML 导入 + `prompts.*` 配置化 + 三维评分 + HTML 简报
5. M3:部署 + 自动化 cron

或者你直接说"开 M2",我接着干。
