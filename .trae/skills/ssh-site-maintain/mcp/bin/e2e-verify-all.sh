#!/usr/bin/env bash
# 一键端到端验证全部 4 个 MCP 连接器（fangjunjie / lhtdeg / aiondadotcom / fail2ban）
# = 4 个 e2e 全链路用例 + 3 个生产启动脚本 smoke（验证 launch 脚本本身可起、可连）
# 用法：bash bin/e2e-verify-all.sh
set -u
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"
# lhtdeg 那组直连 127.0.0.1:22022（不走 launch 脚本），需先幂等拉起 socat 中继
bash bin/ensure-relay.sh || echo "WARN: relay 未起，e2e-lhtdeg 会失败（见 /tmp/socat-relay-22022.log）"
echo -n "mcp-e2e-verify-$(date +%Y%m%d-%H%M%S)" > /tmp/mcp-e2e-src.txt
rm -f /tmp/mcp-e2e-down.txt /tmp/mcp-e2e-down-aion.txt /tmp/mcp-e2e-down-lhtdeg.txt
rm -rf /tmp/mcp-snapshot-test

declare -A RESULT
SPECS="specs/e2e-fangjunjie.json specs/e2e-aiondadotcom.json specs/e2e-lhtdeg.json specs/e2e-fail2ban.json specs/smoke-launch-primary.json specs/smoke-launch-async.json specs/smoke-launch-f2b.json"
for spec in $SPECS; do
  name="$(basename "$spec" .json)"
  echo "===== $name ====="
  if node bin/mcp-e2e-client.mjs "$spec" --timeout 60; then
    RESULT[$name]=PASS
  else
    RESULT[$name]=FAIL
  fi
  echo
done

echo "===== 汇总 ====="
rc=0
for k in e2e-fangjunjie e2e-aiondadotcom e2e-lhtdeg e2e-fail2ban smoke-launch-primary smoke-launch-async smoke-launch-f2b; do
  echo "  ${RESULT[$k]:-FAIL}  $k"
  [ "${RESULT[$k]}" = PASS ] || rc=1
done
echo "本地/远端 md5 对照:"
md5sum /tmp/mcp-e2e-src.txt /tmp/mcp-e2e-down.txt /tmp/mcp-e2e-down-aion.txt /tmp/mcp-e2e-down-lhtdeg.txt 2>/dev/null
exit $rc
