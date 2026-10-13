#!/usr/bin/env bash
# 归档 = 打包技能包+~/.ssh，推 GitHub（权威源）→ 回拉 → 落服务器双镜像（逐字节一致）。
# 每次改技能包后执行一次；canonical 与 HTTPS 恢复点见 SKILL.md §6。
set -e
SKILL_NAME="ssh-site-maintain"
TOKENS_ENV="/data/user/skills/gh-cf-tokens/tokens.env"
GH_REPO="423down-links/skillpack"
GH_PATH="ssh-site-maintain-latest.tar.gz"
API="https://api.github.com/repos/$GH_REPO/contents/$GH_PATH"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

if [ -z "${GH_TOKEN:-}" ] && [ -f "$TOKENS_ENV" ]; then set -a; . "$TOKENS_ENV"; set +a; fi
[ -n "${GH_TOKEN:-}" ] || { echo "ERROR: 无 GH_TOKEN（环境变量 / gh 登录态 / $TOKENS_ENV 均缺失）" >&2; exit 1; }

# 1) 组装包：.trae/skills/<skill>（排除缓存）+ .trae/mcp.json + .ssh/{id_ed25519,config,hosts.json(如有)}
mkdir -p "$STAGE/root/.trae/skills" "$STAGE/root/.ssh"
cp -a "/workspace/.trae/skills/$SKILL_NAME" "$STAGE/root/.trae/skills/"
find "$STAGE/root/.trae/skills/$SKILL_NAME" -name '__pycache__' -type d -prune -exec rm -rf {} +
cp -a /workspace/.trae/mcp.json "$STAGE/root/.trae/"
cp -a "$HOME/.ssh/id_ed25519" "$HOME/.ssh/config" "$STAGE/root/.ssh/"
if [ -f "$HOME/.ssh/hosts.json" ]; then cp -a "$HOME/.ssh/hosts.json" "$STAGE/root/.ssh/"; fi
chmod 700 "$STAGE/root/.ssh"
chmod 600 "$STAGE/root/.ssh/"* "$STAGE/root/.trae/mcp.json"
tar -czf "$STAGE/pkg.tgz" -C "$STAGE/root" .trae .ssh
chmod 600 "$STAGE/pkg.tgz"
echo "本地构建 sha256: $(sha256sum "$STAGE/pkg.tgz" | awk '{print $1}')"

# 2) 推 GitHub（权威源）
[ -f "$TOKENS_ENV" ] && { set -a; . "$TOKENS_ENV"; set +a; }
SHA="$(curl -fsS -m 30 "$API?ref=main" -H "Authorization: Bearer $GH_TOKEN" \
      | python3 -c 'import sys,json;print(json.load(sys.stdin).get("sha",""))' 2>/dev/null || true)"
python3 - "$SHA" "$STAGE/pkg.tgz" <<'PY' > "$STAGE/gh.json"
import base64, json, sys
sha, pkg = sys.argv[1], sys.argv[2]
d = {"message": "archive: skill pack (GitHub is source of truth; server mirrors this)",
     "content": base64.b64encode(open(pkg, "rb").read()).decode(), "branch": "main"}
if sha:
    d["sha"] = sha
print(json.dumps(d))
PY
CODE="$(curl -sS -m 300 -o /dev/null -w '%{http_code}' -X PUT "$API" \
  -H "Authorization: Bearer $GH_TOKEN" -H 'Accept: application/vnd.github+json' \
  -H 'Content-Type: application/json' --data-binary @"$STAGE/gh.json" || echo 000)"

# 3) 服务器镜像：GitHub 成功则从 GitHub 回拉（= 与 GitHub 逐字节一致）；失败退用本地构建
MIRROR="$STAGE/mirror.tgz"
if [ "$CODE" = "200" ] || [ "$CODE" = "201" ]; then
  echo "已推 GitHub: $GH_REPO/$GH_PATH"
  if curl -fsSL -m 120 -H "Authorization: Bearer $GH_TOKEN" \
       -H "Accept: application/vnd.github.raw" "$API?ref=main" -o "$MIRROR"; then
    echo "已从 GitHub 回拉镜像（权威源）"
  else
    echo "⚠️ GitHub 回拉失败，退用本地构建镜像" >&2; cp "$STAGE/pkg.tgz" "$MIRROR"
  fi
else
  echo "⚠️ GitHub 推送失败 (HTTP $CODE)：服务器暂用本地构建，GitHub 权威源待重推" >&2
  cp "$STAGE/pkg.tgz" "$MIRROR"
fi

# 4) 落服务器两处（同源同内容）：唯一 canonical + HTTPS 恢复点
scp -q "$MIRROR" "423down:/www/backup/skill-packages/ssh-site-maintain-latest.tar.gz"
scp -q "$MIRROR" "423down:/www/skill-recovery/skillpack.tar.gz"
ssh 423down 'chown root:root /www/backup/skill-packages/ssh-site-maintain-latest.tar.gz; chmod 600 /www/backup/skill-packages/ssh-site-maintain-latest.tar.gz; chgrp www /www/skill-recovery/skillpack.tar.gz; chmod 640 /www/skill-recovery/skillpack.tar.gz'
scp -q "$(dirname "$0")/restore-skill.sh" "423down:/www/backup/skill-packages/"

echo "服务器已镜像（GitHub 为准）："
ssh 423down 'echo "  -- /www/backup/skill-packages --"; ls -l /www/backup/skill-packages/; echo "  -- /www/skill-recovery --"; ls -l /www/skill-recovery/; echo "  -- sha256 --"; sha256sum /www/backup/skill-packages/ssh-site-maintain-latest.tar.gz /www/skill-recovery/skillpack.tar.gz'