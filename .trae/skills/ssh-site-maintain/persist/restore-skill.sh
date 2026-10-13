#!/usr/bin/env bash
# 冷启动恢复技能包（沙箱回滚/换新后）—— 走服务器通道兜底；首选 GitHub（见 SKILL.md §6）。
# 前提：~/.ssh 已免密，否则先走密码引导（§1）。
# 用法：bash .../persist/restore-skill.sh
set -e
ARCHIVE="ssh-site-maintain-latest.tar.gz"

echo "[1/4] 前置检查：ssh 423down 连通性"
if ! ssh -o BatchMode=yes 423down 'hostname' >/dev/null 2>&1; then
  echo "  ssh 423down 不可用。请先恢复 ~/.ssh，二选一："
  echo "  ① 首选 GitHub 私有仓（零密码）：见 SKILL.md §6 ①"
  echo "  ② 密码引导（仅一次）：SKILL.md §1"
  echo "    printf '%s' '<密码>' | python3 bootstrap-key.py --host 45.151.132.50 --port 22 --user root"
  echo "    python3 register-host.py 423down 45.151.132.50 22 root \"wordpress 生产站\""
  exit 1
fi
echo "  OK"

echo "[2/4] 拉取归档并解包到 /workspace/.trae/ 与 ~/.ssh/"
mkdir -p /workspace/.trae/skills "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
ssh 423down "cat /www/backup/skill-packages/$ARCHIVE" > /tmp/sp.tgz
tar -xzf /tmp/sp.tgz -C /workspace .trae
tar -xzf /tmp/sp.tgz -C "$HOME/.ssh" --strip-components=1 .ssh
chmod 600 "$HOME/.ssh/id_ed25519" "$HOME/.ssh/config"
echo "  OK"

echo "[3/4] 目录概况"
ls /workspace/.trae/skills/ssh-site-maintain/ | head
echo "  mcp.json: $(ls -l /workspace/.trae/mcp.json 2>/dev/null || echo 缺失)"

echo "[4/4] 全链路回归验证（4 个 MCP 连接器）"
bash /workspace/.trae/skills/ssh-site-maintain/mcp/bin/e2e-verify-all.sh