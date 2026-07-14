#!/bin/bash
# Daily Briefing cron pipeline
# Run from mavis cron session: bash /tmp/daily-briefing/scripts/cron.sh
# Outputs: rss/ai-daily.xml (RSS 2.0 + media:thumbnail) + digests/ai-daily.html

set -e

REPO_DIR="${REPO_DIR:-/tmp/daily-briefing}"
GITHUB_PAT="${GITHUB_PAT:-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}"
LOG_PREFIX="[cron]"

echo "$LOG_PREFIX === DAILY BRIEFING START ==="
echo "$LOG_PREFIX $(date)"

# === Step 1: clone or pull ===
mkdir -p "$REPO_DIR"
cd "$REPO_DIR"

if [ -d ".git" ]; then
  echo "$LOG_PREFIX git pull (rebase)"
  git pull origin main --rebase 2>&1 | tail -3
else
  echo "$LOG_PREFIX git clone"
  git clone "https://x-access-token:${GITHUB_PAT}@github.com/SeasonTemple/daily-briefing.git" . 2>&1 | tail -3
fi

# === Step 2: fetch sources via web_fetch (delegated to caller — mavis M3) ===
# This script handles everything EXCEPT the LLM summarization step.
# The mavis cron session (M3) will:
#   1. web_fetch 8 RSS sources
#   2. Pick 8-12 AI items
#   3. M3 Chinese summarize each
#   4. Pass the data into build_rss.py and build_html.py (steps 3-4 below)

# === Step 3: M3 writes rss/ai-daily.xml and digests/ai-daily.html (LLM summarization happens here) ===
# After M3 finishes writing, the cron session will:
#   - call: python3 "$REPO_DIR/scripts/validate.py" "$REPO_DIR/rss/ai-daily.xml"
#   - call: python3 "$REPO_DIR/scripts/validate.py" "$REPO_DIR/digests/ai-daily.html"

# === Step 4: commit + push ===
echo "$LOG_PREFIX git add + commit + push"
git -c user.name=mavis-bot -c user.email=mavis@users.noreply.github.com add rss/ digests/ reports/ 2>&1
git -c user.name=mavis-bot -c user.email=mavis@users.noreply.github.com commit -m "chore: ai-daily RSS + HTML $(date -u +%Y-%m-%d)" 2>&1 || echo "$LOG_PREFIX no changes to commit"
git push "https://x-access-token:${GITHUB_PAT}@github.com/SeasonTemple/daily-briefing.git" main 2>&1 | tail -5

echo "$LOG_PREFIX === DONE ==="
ls -la rss/ digests/ reports/ 2>&1
echo "$LOG_PREFIX RSS: https://seasontemple.github.io/daily-briefing/rss/ai-daily.xml"
echo "$LOG_PREFIX HTML: https://seasontemple.github.io/daily-briefing/digests/ai-daily.html"
