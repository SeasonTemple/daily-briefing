# Daily Briefing v2 · Cron Runbook

## 流程 (M3 cron session 每 07:00 Asia/Shanghai 执行)

1. **拉取最新代码**
   ```bash
   cd /tmp/daily-briefing
   git pull origin main   # 或 git clone ... 如果目录不在
   ```

2. **抓 8 个一手信源 + 选 10 条 + 写 M3 中文摘要**
   - 抓取逻辑:`scripts/daily_briefing.py` (Python 3 stdlib only,无 pip 依赖)
   - 跑法:`python3 scripts/daily_briefing.py` 会输出 10 条候选 + 写原始 RSS/HTML
   - **M3 必须做**:
     - 读候选里的每条 (title + desc + url)
     - **改写为中文标题 (≤ 60 字) + 中文摘要 (≤ 60 字)**
     - 把结果写到 `ai-daily-YYYY-MM-DD.items.json` (按本仓库 `ai-daily-2026-07-13.items.json` 模板)

3. **生成最终 RSS + HTML**
   ```bash
   python3 scripts/_build_today.py --items ai-daily-YYYY-MM-DD.items.json
   ```
   产物:
   - `rss/ai-daily.xml`    — 严格 RSS 2.0 (无 CDATA, 转义 &, HTTPS self link, RFC 2822 pubDate, ttl 5, 每条 media:thumbnail)
   - `digests/ai-daily.html` — 暗色 #0b0e14 / zh-CN / CSP / skip-link / focus-visible / prefers-reduced-motion / 40x40 SVG logo 卡牌网格

4. **用 xml.etree 校验 RSS**
   ```python
   import xml.etree.ElementTree as ET
   ET.parse('rss/ai-daily.xml')  # 不能抛 ParseError
   ```
   自动校验:`python3 scripts/_build_today.py` 之后会打印 "ALL CHECKS PASSED ✓"

5. **推到 GitHub** (用环境变量 GITHUB_PAT)
   ```bash
   git add rss/ digests/ scripts/ ai-daily-*.items.json
   git commit -m "chore: ai-daily RSS YYYY-MM-DD (SHA) — M3 cron"
   git push https://x-access-token:${GITHUB_PAT}@github.com/SeasonTemple/daily-briefing.git main
   ```

   注意:GitHub 提示仓库已迁移到 **`SeasonTemple/daily-briefing`** (大写 S),原来的 `seasontemple/` 仍能 push 但会重定向。

6. **回执**
   - 产出几条 entry
   - 几个信源
   - push 成功/失败
   - 任何异常

## 失败处理

- 单源失败:不阻塞,继续 (daily_briefing.py 自带 3 次重试)
- LLM/M3 总结失败:走 fallback (英文标题截 60 字),继续
- git push 失败:重试 1 次,失败就 echo 错误信息

## 环境

- Python 3.11 stdlib only (无 feedparser / requests)
- `GITHUB_PAT` 环境变量,作用域:`push` 即可
- 时区:所有 pubDate 用 GMT;HTML 头部时间用 Asia/Shanghai
