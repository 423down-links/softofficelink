#!/usr/bin/env bash
# 部署/更新 soft-detect-cron Worker + Cron 触发器到 Cloudflare
# 用法：bash deploy.sh   （会自动加载 tokens.env）
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
set -a; . "$SKILL_DIR/tokens.env"; set +a

A="1f5e2d11ee6dfb31343229a8e5c819b3"      # Cloudflare Account ID
NAME="soft-detect-cron"
SRC="$SKILL_DIR/worker/soft-detect-cron.js"
KEYFILE="$SKILL_DIR/worker/.trigger_key"

[ -f "$KEYFILE" ] || openssl rand -hex 16 > "$KEYFILE"
KEY="$(cat "$KEYFILE")"

META=$(printf '{"main_module":"soft-detect-cron.js","compatibility_date":"2024-11-01","bindings":[{"type":"secret_text","name":"GH_PAT","text":"%s"},{"type":"secret_text","name":"TRIGGER_KEY","text":"%s"}]}' "$GH_TOKEN" "$KEY")

echo "== 上传脚本 =="
curl -sS -X PUT "https://api.cloudflare.com/client/v4/accounts/$A/workers/scripts/$NAME" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -F "metadata=$META;type=application/json" \
  -F "soft-detect-cron.js=@$SRC;type=application/javascript+module" | head -c 800
echo

echo "== 设置 Cron =="
curl -sS -X PUT "https://api.cloudflare.com/client/v4/accounts/$A/workers/scripts/$NAME/schedules" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" -H "Content-Type: application/json" \
  --data '[{"cron":"5 * * * *"},{"cron":"20,50 * * * *"}]' | head -c 600
echo

echo "== 开启 workers.dev =="
curl -sS -X POST "https://api.cloudflare.com/client/v4/accounts/$A/workers/scripts/$NAME/subdomain" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" -H "Content-Type: application/json" \
  --data '{"enabled":true,"previews_enabled":false}' | head -c 300
echo
echo "完成。手动验证：curl \"https://$NAME.172201424.workers.dev/?key=$KEY&min=5\""