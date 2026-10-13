#!/usr/bin/env bash
# 零密码回滚自愈（幂等）：确保 ~/.ssh 可用 + 423down 免密连通。
# 任何 ssh/rsync/scp/MCP 操作前先跑；分层：现成 key → GitHub → 423down HTTPS → 密码引导。
# 用法：bash .../persist/ensure-ssh-key.sh [别名，默认 423down]
set -uo pipefail

ALIAS="${1:-423down}"
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PROXY="http://127.0.0.1:18080"
TOKENS_ENV="/data/user/skills/gh-cf-tokens/tokens.env"
GH_URL="https://api.github.com/repos/423down-links/skillpack/contents/ssh-site-maintain-latest.tar.gz"
RP_URL="https://www.423down.com/sk-8ed7cd677edb0fb9e4ff0b1e640c2a453a14e09ffa625fd4/skillpack.tar.gz"
RP_TOKEN_FILE="$SKILL_DIR/etc/recover-token"
RP_TOKEN_FALLBACK="f7fa765c546c9f238cbfb2a66bc9f265"

log() { echo "[ensure] $*"; }

# 免密自检：BatchMode=yes 禁止一切交互，能过即纯密钥链路 OK
check() {
  ssh -o BatchMode=yes -o ConnectTimeout=8 "$ALIAS" 'echo SSH_OK' 2>/dev/null | grep -q SSH_OK
}

unpack() {  # $1 = tarball
  mkdir -p "$HOME/.ssh" /workspace && chmod 700 "$HOME/.ssh"
  # 技能包本体：仅在缺失时解包，避免用旧归档覆盖本地未归档的改动
  if [ ! -f "$SKILL_DIR/SKILL.md" ]; then
    tar -xzf "$1" -C /workspace .trae 2>/dev/null || true
  fi
  tar -xzf "$1" -C "$HOME/.ssh" --strip-components=1 .ssh 2>/dev/null || true
  chmod 600 "$HOME/.ssh/id_ed25519" "$HOME/.ssh/config" 2>/dev/null || true
}

# ① 现成 ~/.ssh
if check; then
  log "OK：$ALIAS 免密正常（~/.ssh 现成），无需恢复"
  exit 0
fi
log "① 本地 ~/.ssh 不可用或未连通，进入恢复流程…"

# ② GitHub 恢复点（零密码，需 GH_TOKEN）
if [ -z "${GH_TOKEN:-}" ] && [ -f "$TOKENS_ENV" ]; then
  set -a; . "$TOKENS_ENV"; set +a
fi
if [ -n "${GH_TOKEN:-}" ]; then
  if curl -fsSL --proxy "$PROXY" -m 120 \
       -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github.raw" \
       "$GH_URL" -o /tmp/sp.tgz 2>/dev/null && tar -tzf /tmp/sp.tgz >/dev/null 2>&1; then
    unpack /tmp/sp.tgz
    if check; then log "OK：$ALIAS 免密恢复成功（GitHub 恢复点）"; exit 0; fi
    log "② GitHub 恢复点已解包，但自检未过，继续…"
  else
    log "② GitHub 恢复点拉取失败（GH_TOKEN 缺失/网络），继续…"
  fi
else
  log "② 无 GH_TOKEN，跳过 GitHub 恢复点…"
fi

# ③ 423down HTTPS 恢复点（双因子：路径 token + X-Recover-Token 头）
RT="$RP_TOKEN_FALLBACK"; [ -f "$RP_TOKEN_FILE" ] && RT="$(tr -d '[:space:]' < "$RP_TOKEN_FILE")"
if curl -fSL --proxy "$PROXY" -m 120 -H "X-Recover-Token: $RT" "$RP_URL" -o /tmp/sp.tgz 2>/dev/null \
     && tar -tzf /tmp/sp.tgz >/dev/null 2>&1; then
  unpack /tmp/sp.tgz
  if check; then log "OK：$ALIAS 免密恢复成功（423down HTTPS 恢复点）"; exit 0; fi
  log "③ 423down 恢复点已解包，但自检未过，继续…"
else
  log "③ 423down HTTPS 恢复点拉取失败，继续…"
fi

# ④ 兜底：需人工/密码引导
log "✗ 自动恢复失败：服务器 authorized_keys 疑被清空 → 等 agent-key-guard 自动补回，或密码引导："
log "  printf '%s' '<密码>' | python3 $SKILL_DIR/bootstrap-key.py --host 45.151.132.50 --port 22 --user root"
exit 1