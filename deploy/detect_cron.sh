#!/bin/bash
# softofficelink 版本检测定时任务（替代被 GitHub 账单门禁卡死的 Actions）
#
# 用法: detect_cron.sh [hourly|full]
#   hourly = 快检 + 资源站（对应 CI 的 '0 * * * *'）
#   full   = 全量非资源站（对应 CI 的 '15,45 * * * *'）
#
# 行为与 .github/workflows/detect.yml 对齐：
#   检测 → 有变化则 embed + commit + push；无变化则只刷缓存并 push
#   push 到 main 会触发 Cloudflare Pages 自动部署，即「改完即上线」
set -uo pipefail

MODE="${1:-hourly}"
REPO_DIR=/opt/softofficelink
PY=/www/server/panel/pyenv/bin/python3.7
LOG_DIR=/var/log/softofficelink
LOCK=/var/lock/softofficelink-detect.lock

export PATH=/usr/bin:/usr/local/bin:/bin:/usr/sbin:/sbin:$PATH
export PYTHONIOENCODING=utf-8

mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/detect-${MODE}-$(date +%Y%m%d).log"

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

cd "$REPO_DIR" || { log "❌ 仓库目录不存在"; exit 1; }

# 同一时刻只跑一个任务（对齐 CI 的 concurrency: group main-push）
exec 9>"$LOCK"
if ! flock -n 9; then
  log "⏭️ 已有检测任务在跑，跳过本轮"
  exit 0
fi

# GitHub API 需要 token，否则 github_release 类探测会被限流降级成通用链接
if [ -z "${GITHUB_TOKEN:-}" ] && [ -f "$HOME/.git-credentials" ]; then
  GITHUB_TOKEN=$(grep -o 'https://[^:]*:' "$HOME/.git-credentials" | head -1 | sed 's|https://||; s|:$||')
  export GITHUB_TOKEN
fi

if [ "${GITHUB_TOKEN:-}" = "" ]; then
  log "❌ 没有 GITHUB_TOKEN，github_release 类探测会降级"
fi

log "===== 开始 $MODE 检测 ====="

# 拉取最新代码
git fetch origin main --quiet 2>>"$LOG" || log "⚠️ git fetch 失败，用本地版本继续"
git reset --hard origin/main --quiet 2>>"$LOG" || log "⚠️ git reset 失败"

# 按模式选择检测优先级
case "$MODE" in
  hourly) PRIORITY="fast,normal,resource" ;;
  full)   PRIORITY="fast,normal,slow" ;;
  *)      PRIORITY="fast,normal,resource" ;;
esac

rc=0
$PY check_versions.py --priority "$PRIORITY" --parallel 8 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}

if [ "$rc" = "3" ]; then
  log "❌ 产品数量守卫拦截：本轮结果比线上少，data.json 未改写，请检查 PRODUCTS 配置"
  exit 1
fi
if [ "$rc" != "0" ]; then
  log "❌ 检测脚本异常退出（rc=$rc），data.json 未改写"
  exit 1
fi

changed=false
if grep -q 'CHANGED=true' "$LOG"; then
  changed=true
fi

log "CHANGED=$changed"

# 嵌入 index.html（内含产品数量守卫，rc=3 时不改写）
rc=0
$PY embed_data.py 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}
if [ "$rc" = "3" ]; then
  log "❌ 产品数量守卫拦截：index.html 未改写，线上产品数保持原样"
  exit 1
fi
if [ "$rc" != "0" ]; then
  log "❌ embed_data.py 异常退出（rc=$rc）"
  exit 1
fi

git config user.email "bot@softofficelink.pages.dev"
git config user.name "softofficelink-bot"

if [ "$changed" = "true" ]; then
  git add -A
  if git diff --staged --quiet; then
    log "无变化，跳过提交"
  else
    msg=$(grep '🔄 版本变化' "$LOG" | tail -1 | sed 's/🔄 版本变化: //' | cut -c1-200)
    git commit -q -m "detect(${MODE}): ${msg:-版本更新}"
    if git push origin HEAD:main 2>>"$LOG"; then
      log "✅ 已推送 main，Cloudflare Pages 将自动部署"
    else
      log "❌ push 失败"
      exit 1
    fi
  fi
else
  # 无版本变化：只刷新探测缓存（缓存过期会让下轮重复下载大文件重算 MD5）
  git add md5_cache.json pe_version_cache.json startallback_dll_cache.json data.json 2>/dev/null
  if git diff --staged --quiet; then
    log "无变化，跳过"
  else
    git commit -q -m "chore: refresh probe caches"
    git push origin HEAD:main 2>>"$LOG" && log "✅ 缓存已推送"
  fi
fi

log "===== $MODE 检测结束 ====="
