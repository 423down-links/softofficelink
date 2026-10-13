#!/usr/bin/env bash
# 增强 SSH 连接器：@lhtdeg/ssh-mcp-server v1.3.3（异步长任务 / 会话复用 / 远程目录快照）
# 不支持 HTTP 代理 → 先幂等启动 socat 中继(22022)，再连 127.0.0.1:22022
DIR="$(cd "$(dirname "$0")/.." && pwd)"
"$DIR/bin/ensure-relay.sh"
exec node "$DIR/node_modules/@lhtdeg/ssh-mcp-server/build/index.js" \
  --host 127.0.0.1 --port 22022 --username root \
  --privateKey "$HOME/.ssh/id_ed25519" \
  --pty false \
  --allowed-local-paths /workspace,/tmp \
  --allowed-remote-paths /www,/tmp,/etc,/root \
  --blacklist 'rm\s+-rf\s+/,mkfs,dd\s+if=/dev/,shutdown,reboot,halt,poweroff,init\s+[06],systemctl\s+(stop|disable)\s+(sshd|nginx|mysqld|mariadb|php-fpm|fail2ban),(service|/etc/init\.d/)\s+(sshd|nginx|mysqld|mariadb|mysql|php-fpm\S*|fail2ban|bt)\s+(stop|kill),mysqladmin\s+(shutdown|stop)'
