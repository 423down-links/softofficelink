#!/usr/bin/env bash
# 幂等启动本地 CONNECT 中继：127.0.0.1:22022 → (HTTP 代理 18080) → 45.151.132.50:22
# 供 @lhtdeg/ssh-mcp-server 等不支持 HTTP 代理的连接器使用
set -e
RELAY_PORT="${RELAY_PORT:-22022}"
TARGET_HOST="${TARGET_HOST:-45.151.132.50}"
TARGET_PORT="${TARGET_PORT:-22}"
PROXY_HOST="${PROXY_HOST:-127.0.0.1}"
PROXY_PORT="${PROXY_PORT:-18080}"

if ss -tln "sport = :$RELAY_PORT" 2>/dev/null | grep -q LISTEN; then
  exit 0
fi
setsid nohup socat "TCP-LISTEN:$RELAY_PORT,bind=127.0.0.1,fork,reuseaddr" \
  "PROXY:$PROXY_HOST:$TARGET_HOST:$TARGET_PORT,proxyport=$PROXY_PORT" \
  >"/tmp/socat-relay-$RELAY_PORT.log" 2>&1 < /dev/null &
sleep 0.5
if ss -tln "sport = :$RELAY_PORT" 2>/dev/null | grep -q LISTEN; then
  echo "relay up on 127.0.0.1:$RELAY_PORT -> $TARGET_HOST:$TARGET_PORT (via $PROXY_HOST:$PROXY_PORT)"
else
  echo "relay FAILED, see /tmp/socat-relay-$RELAY_PORT.log" >&2
  exit 1
fi
