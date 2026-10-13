#!/usr/bin/env bash
# Fail2ban 专用 MCP：零依赖自定义服务，经 ssh 别名 423down 操作远端 fail2ban
DIR="$(cd "$(dirname "$0")/.." && pwd)"
exec node "$DIR/mcp-fail2ban/server.mjs"
