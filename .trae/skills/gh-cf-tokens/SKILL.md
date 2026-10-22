---
name: "gh-cf-tokens"
description: "沙盒预置的 GitHub CLI(gh) 与 Cloudflare Workers & Pages API 令牌，免重登；并含 softofficelink 检测的外部定时兜底 Worker 部署脚本。当任务需要鉴权 GitHub Actions/触发 workflow/推仓，或调用 Cloudflare Workers & Pages API、或排查/重建 detect.yml 外部定时器时调用。"
---

# GitHub / Cloudflare 令牌（沙盒持久化）

沙盒预置的两枚长期令牌。凭据本体在同目录 `tokens.env`（权限 600），本文件不内联密文。

## 加载

```bash
set -a; . /data/user/skills/gh-cf-tokens/tokens.env; set +a
```

| 变量 | 用途 | 说明 |
|---|---|---|
| `GH_TOKEN` | GitHub CLI：`gh run list` / `gh workflow run` / 仓库读写 / Actions dispatch | OAuth，scopes: `gist, read:org, repo, workflow`；账号 `423down` |
| `CLOUDFLARE_API_TOKEN` | Cloudflare Workers & Pages API（GitHub 关联登录账户） | API Token |

## 常用用法

```bash
# 手动触发 / 查看 Actions
gh workflow run detect.yml --ref main -f mode=hourly
gh run list --limit 5
gh run view <run-id> --log-failed

# Cloudflare：校验令牌 + 列 Pages/Workers
curl -sS https://api.cloudflare.com/client/v4/user/tokens/verify \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN"
```

## 固定信息

| 项 | 值 |
|---|---|
| Cloudflare Account ID | `1f5e2d11ee6dfb31343229a8e5c819b3` |
| workers.dev 子域 | `172201424` |
| 目标仓库 | `423down-links/softofficelink`（默认分支 `main`） |

## 外部定时兜底 Worker（soft-detect-cron）

GitHub 自带调度器会丢点，故用 Cloudflare Worker Cron 补触发 detect.yml。

- 源码：本目录 `worker/soft-detect-cron.js`（含部署脚本 `worker/deploy.sh`）
- 触发器：`5 * * * *`（兜整点 hourly）、`20,50 * * * *`（兜 :15/:45 full）
- 逻辑：先查 15 分钟内是否已有 detect.yml 运行 → 有则跳过，无则 `workflow_dispatch` 带 `mode` 补触发
- 绑定：`GH_PAT`（=GH_TOKEN）、`TRIGGER_KEY`（手动测试口令，存 `worker/.trigger_key`）
- 重新部署：`bash worker/deploy.sh`（读取 tokens.env）

```bash
# 手动验证（沙箱出口访问不了 workers.dev，需在能出网的机器上跑）
curl "https://soft-detect-cron.172201424.workers.dev/?key=$(cat worker/.trigger_key)&min=5"
```

## 备份与恢复

沙箱回滚会丢 `/data/user/skills/` 下的自建技能。冗余副本：

- `/workspace/.trae/skills/gh-cf-tokens/`（workspace 内，`.gitignore` 的 `.trae*` 已屏蔽，不会被 CI 的 `git add -A` 提交）

```bash
# 恢复
cp -r /workspace/.trae/skills/gh-cf-tokens /data/user/skills/ && chmod 600 /data/user/skills/gh-cf-tokens/tokens.env
```

## 注意

- 令牌是长期凭据：**禁止**让它们进入任何被提交的路径（尤其 `/workspace` 根目录，CI 会 `git add -A` 并推送到远端）
- `gh workflow run` 报 403 时，先看 `x-oauth-scopes`：dispatch 需要 `workflow` scope
- 令牌轮换后只改 `tokens.env`（两处副本都要改）