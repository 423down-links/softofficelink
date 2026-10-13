#!/usr/bin/env bash
# 维护收尾（改技能包/服务器配置后必跑）：归档 → 三处 sha256 校验 → PASS/FAIL。
# 用法：bash .../persist/maintain-close.sh
set -uo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TOKENS_ENV="/data/user/skills/gh-cf-tokens/tokens.env"
GH_URL="https://api.github.com/repos/423down-links/skillpack/contents/ssh-site-maintain-latest.tar.gz"
CANON="/www/backup/skill-packages/ssh-site-maintain-latest.tar.gz"
RECOV="/www/skill-recovery/skillpack.tar.gz"

echo "=== [1/2] 归档技能包（推 GitHub + 服务器双镜像）==="
bash "$SKILL_DIR/persist/archive-skill.sh" || { echo "[close] ✗ 归档失败，终止"; exit 1; }

echo
echo "=== [2/2] 三处 sha256 一致性校验 ==="
[ -f "$TOKENS_ENV" ] && { set -a; . "$TOKENS_ENV"; set +a; }
GH_SHA="$(curl -fsSL --proxy http://127.0.0.1:18080 -m 120 \
  -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github.raw" \
  "$GH_URL?ref=main" -o /tmp/close-gh.tgz 2>/dev/null && sha256sum /tmp/close-gh.tgz | awk '{print $1}')"
SRV="$(ssh 423down "sha256sum $CANON $RECOV" 2>/dev/null)"
CANON_SHA="$(echo "$SRV" | awk '/skill-packages/{print $1}')"
RECOV_SHA="$(echo "$SRV" | awk '/skill-recovery/{print $1}')"

echo "  GitHub          : ${GH_SHA:-<拉取失败>}"
echo "  server canonical: ${CANON_SHA:-<读取失败>}"
echo "  https recovery  : ${RECOV_SHA:-<读取失败>}"

if [ -n "$GH_SHA" ] && [ "$GH_SHA" = "$CANON_SHA" ] && [ "$GH_SHA" = "$RECOV_SHA" ]; then
  echo "[close] ✓ PASS：三处逐字节一致（sha256 $GH_SHA）"
  exit 0
else
  echo "[close] ✗ FAIL：三处不一致 → 未同步，需重跑归档"
  exit 1
fi