#!/usr/bin/env bash
# 主 SSH 连接器：@fangjunjie/ssh-mcp-server v1.9.2
# 原生 --proxy http（CONNECT 隧道），无需本地中继；密钥认证；黑名单挡危险命令
DIR="$(cd "$(dirname "$0")/.." && pwd)"
exec node "$DIR/node_modules/@fangjunjie/ssh-mcp-server/build/index.js" \
  --host 45.151.132.50 --port 22 --username root \
  --privateKey "$HOME/.ssh/id_ed25519" \
  --proxy http://127.0.0.1:18080 \
  --pty false \
  --allowed-local-paths /workspace,/tmp \
  --allowed-remote-paths /www,/tmp,/etc,/root \
  --blacklist 'rm\s+-rf\s+/,mkfs,dd\s+if=/dev/,shutdown,reboot,halt,poweroff,init\s+[06],systemctl\s+(stop|disable)\s+(sshd|nginx|mysqld|mariadb|php-fpm|fail2ban),(service|/etc/init\.d/)\s+(sshd|nginx|mysqld|mariadb|mysql|php-fpm\S*|fail2ban|bt)\s+(stop|kill),mysqladmin\s+(shutdown|stop)'
