# 部署指南 · 5 分钟上线 Feedly 可订阅

> 目标:把 `daily-briefing` 部署到 **GitHub Pages**,产生 `https://SeasonTemple.github.io/daily-briefing/rss/<profile>.xml`,
> 在 Feedly / Inoreader / NetNewsWire 添加该 URL 就能每天自动收到新条目。

## 方案对比

| 方案 | 自动驱动 | LLM 来源 | 需要你配的 secret | 难度 |
|------|---------|----------|-------------------|------|
| **A. GitHub Actions(推荐)** | GitHub cron | 你自己的 LLM key | 3 个(LLM_API_KEY 等) | ⭐ |
| **B. mavis cron** | mavis cron | mavis M3(我) | 1 个(GitHub PAT, 给我) | ⭐⭐ |
| **C. 本地 + mavis 一次性** | 手动 | mavis M3 | 0 | ⭐(但不自动) |

**默认推荐方案 A**——零依赖,GitHub 自己跑,你只要配 3 个 secret 就行。
方案 B 也行,告诉我你的 GitHub PAT(只给 repo:write 权限),我帮你全程跑通。

---

## 方案 A · GitHub Actions 全自动(推荐)

### Step 1 · 建仓(2 分钟)

在 GitHub 上建一个**空仓** `daily-briefing`,然后本地:

```bash
# 克隆(替换成你的仓库)
git clone https://github.com/SeasonTemple/daily-briefing.git
cd daily-briefing

# 把 M1 代码复制过来(我会给你 tarball)
tar -xzf daily-briefing.tar.gz --strip-components=1

git add .
git commit -m "feat: M1 MVP + GitHub Actions cron"
git push origin main
```

### Step 2 · 配 Secret(1 分钟)

进 GitHub repo → Settings → Secrets and variables → Actions → New repository secret:

| Secret 名 | 值(示例) | 备注 |
|-----------|-----------|------|
| `LLM_API_KEY` | `sk-xxxxxxxx` | 你 LLM 服务的 API key |
| `LLM_BASE_URL` | `https://open.bigmodel.cn/api/paas/v4` | 不填默认 GLM-4-Flash endpoint |
| `LLM_MODEL` | `glm-4-flash` | 留空也行,默认这个 |

**LLM 选项**:
- 智谱 GLM-4-Flash(免费,中文友好)—— 申请:https://open.bigmodel.cn
- DeepSeek-V3(便宜)—— 申请:https://platform.deepseek.com
- OpenAI / Anthropic —— 用你自己的 key
- **不配也跑得动**,但 LLM 摘要会降级为标题 + 原文前 80 字模板

### Step 3 · 启 Pages(30 秒)

Settings → Pages → Source: **Deploy from a branch** → Branch: `main` / `(root)` → Save

### Step 4 · 第一次手动跑(测试)

Actions 标签 → Daily Briefing → Run workflow → 选 profile 跑一次

等 1-2 分钟,看 `rss/ai-daily.xml` 是否生成。

### Step 5 · 订阅 Feedly(1 分钟)

URL:
```
https://SeasonTemple.github.io/daily-briefing/rss/ai-daily.xml
```

Feedly → Add source → 粘贴 → 完成。

**注意**:第一次 push 后,GitHub Pages 大概 1-2 分钟部署,URL 立刻能访问。

---

## 方案 B · mavis cron(我帮你全自动)

适合"我什么都不想做"的用户。

### Step 1 · 你给我一个 GitHub PAT

进 https://github.com/settings/tokens/new 创建:
- Note: `mavis-daily-briefing`
- Expiration: 你定(建议 90 天)
- Scopes: ✅ **Contents: Read and write**

把 token 字符串贴给我(token 一次性,我会配到 mavis cron session 的环境变量)。

### Step 2 · 我来做

- 我用 token 创建仓库 + 推送代码 + 启 Pages
- 配 mavis cron 每天 7 点(Asia/Shanghai)跑
- session 用 Mavis(M3)做 LLM 摘要,无需你配 LLM key
- 产出 RSS → git push(用你的 PAT)
- GitHub Pages 自动 rebuild

### Step 3 · 订阅 Feedly

URL 同上:`https://SeasonTemple.github.io/daily-briefing/rss/ai-daily.xml`

---

## 时区 & cron 说明

- GitHub Actions cron 用 **UTC**: `0 23 * * *` = 北京时间每天 07:00
- mavis cron 用 **Asia/Shanghai**,默认 07:00
- 想要 8:00 跑?改 workflow 的 cron 即可(或者告诉我)

---

## 加新领域

不需要重新部署!在 repo 里加一个 `profiles/<新名字>.yaml`,然后:
- Actions:手动 Run workflow 时选新 profile,或者在 workflow 里改成 matrix 跑多个
- mavis cron:告诉我加一个 profile,我配一个新的 cron

---

## 常见问题

**Q: Actions 失败怎么办?**
A: 进 Actions 标签看日志,80% 是 LLM key 错了或者信源全挂(digest.py 不会因为信源挂而退出)。

**Q: 想跑多个 profile 怎么办?**
A: 加 matrix 策略,或者每天跑 N 个 profile 各一次。

**Q: 想看历史归档?**
A: `reports/<profile>-{date}.md` 都 commit 到 repo 里,GitHub 直接浏览。

**Q: Pages 部署要多久?**
A: 一般 1-2 分钟,推完后立刻访问(可能短暂 404)。

**Q: 不用 GitHub,想用自己的服务器?**
A: 在你自己的服务器 cron 跑 `python scripts/digest.py --profile ai-daily`,把 `rss/` 目录 nginx 出静态文件即可。
