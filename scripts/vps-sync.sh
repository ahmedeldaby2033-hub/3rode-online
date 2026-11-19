#!/bin/bash
# Hourly sync for 3rde.online on the Coolify VPS (Oracle free tier).
#   1) git pull latest
#   2) run scripts/sync.py (refresh from Sheet via the Apps Script export
#      endpoint, rebuild site/, watermark new images)
#   3) if site/ or data actually changed, commit + push — Coolify
#      auto-deploys on push. No change = no commit, no deploy.
#
# Requires on the VPS: git, python3, Pillow (pip install pillow),
# and a git identity:  git config --global user.name "3rde-sync"
#                      git config --global user.email "3rdeonline@gmail.com"
# Install as a cron job (crontab -e):
#   0 * * * *  /opt/3rode-online/scripts/vps-sync.sh
set -e
cd "$(dirname "$0")/.."
BRANCH=$(git rev-parse --abbrev-ref HEAD)
git pull --ff-only origin "$BRANCH"
python3 scripts/sync.py >> data/sync-cron.log 2>&1 || true
git add site data
# logs change every run — never commit them
git reset -q -- data/sync-log.json data/sync-cron.log 2>/dev/null || true
if ! git diff --cached --quiet; then
  git commit -m "sync: $(date -u +%Y-%m-%dT%H:%M:%SZ) prices/images refresh"
  git push origin "$BRANCH"
  echo "pushed — Coolify will redeploy"
else
  echo "no changes — nothing to push"
fi
