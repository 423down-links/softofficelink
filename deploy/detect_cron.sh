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
# ⚠️ 服务器 git 是 1.8.3.1，1.8 的 `git fetch origin main` 只写 FETCH_HEAD，
#    不会更新 refs/remotes/origin/main → reset 会回到旧代码。
#    必须用显式 refspec 强制更新远端跟踪分支。
git fetch origin '+refs/heads/main:refs/remotes/origin/main' --quiet 2>>"$LOG" || log "⚠️ git fetch 失败，用本地版本继续"
git reset --hard origin/main --quiet 2>>"$LOG" || log "⚠️ git reset 失败"

# 按模式选择检测优先级
case "$MODE" in
  hourly) PRIORITY="fast,normal,resource" ;;
  full)   PRIORITY="fast,normal,slow" ;;
  *)      PRIORITY="fast,normal,resource" ;;
esac

rc=0
# 2026-10-22 并行度 8→4：外层线程池 + 内层 _parallel_md5（8 分片 × 4MB）
# 叠加后单轮峰值 RSS 近 1GB，2026-10-22 12:53 打爆整机内存触发全局 OOM，
# 内核连带杀掉 php-fpm 工作进程。降到 4 后峰值约减半，检测耗时约翻倍
#（full 70s → 约 140s），对版本检测时效无影响。
$PY check_versions.py --priority "$PRIORITY" --parallel 4 2>&1 | tee -a "$LOG"
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

# 推送 main：失败时先拉远端再 rebase 重试一次（防并发提交被拒）
push_main() {
  if git push origin HEAD:main 2>>"$LOG"; then
    return 0
  fi
  log "⚠️ push 失败，拉取远端后 rebase 重试"
  git fetch origin '+refs/heads/main:refs/remotes/origin/main' --quiet 2>>"$LOG"
  if ! git rebase origin/main >>"$LOG" 2>&1; then
    log "❌ rebase 冲突，本轮放弃推送（远端已有提交不会丢）"
    return 1
  fi
  if git push origin HEAD:main 2>>"$LOG"; then
    log "✅ rebase 后推送成功"
    return 0
  fi
  log "❌ push 失败"
  return 1
}

if [ "$changed" = "true" ]; then
  git add -A
  if git diff --staged --quiet; then
    log "无变化，跳过提交"
  else
    msg=$(grep '🔄 版本变化' "$LOG" | tail -1 | sed 's/🔄 版本变化: //' | cut -c1-200)
    git commit -q -m "detect(${MODE}): ${msg:-版本更新}"
    if push_main; then
      log "✅ 已推送 main，Cloudflare Pages 将自动部署"
    else
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
    push_main && log "✅ 缓存已推送"
  fi
fi

log "===== $MODE 检测结束 ====="
