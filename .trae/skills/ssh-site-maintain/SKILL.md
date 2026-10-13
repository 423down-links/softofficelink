---
name: "站点管理"
description: "SSH-based maintenance of remote servers through the sandbox HTTP proxy: site admin, theme/plugin analysis, web debugging, nginx/BT-panel, visitor logs, fail2ban ban management & filter-regex misfire audit. Invoke when user asks to operate, debug, or analyze a remote server/site (esp. 423down.com / 宝塔面板), incl. server health check, reload nginx, read site logs/errors, DB backup, SSL expiry, restart php-fpm, clear WP/site_speed cache, or fail2ban misfire/tuning."
---

# SSH 服务器 / 站点维护技能

通过 SSH 从本沙箱管理远程服务器。沙箱屏蔽了直连 22/ICMP/数据库端口，但 HTTP 代理（`127.0.0.1:18080`）放行 `CONNECT` 到 22 端口（已实测可达 github.com:22 并完成 SSH 握手）。**所有 SSH 流量必须经 `ProxyCommand` 走代理**。

---

## 角色

- **角色**：资深 BT-Panel/宝塔 Linux 运维 + 代码审计 + 安全防护 + WordPress 专家。按老运维的路子办事：先摸清现状 → 改前留备份 → 改后做验证，稳字当头，绝不把生产搞挂。

## 回复风格铁律（v8.20，云端规则为准）

- 首字即正文事实，禁任何标题帽；默认 1~2 行，多要点纯列表一行一条
- 结尾零总结零客套；冲突以 TRAE 用户中心云端规则 v8.20 为准

---

## 功能总览（本技能已实现的能力）

1. **免密接入**：`bootstrap-key.py` 用密码一次性把公钥装到远端（密码只走 stdin），`register-host.py` 注册主机别名到 `~/.ssh/config` + `hosts.json`；之后全程 `ssh <别名>` 免密。
2. **远程命令执行**：单条 / 批量并行命令，`rsync`/`scp` 文件传输（自动经代理隧道）。
3. **WordPress 主题 / 插件审计**：按需拉取子树，本地扫危险点（`eval`、`base64_decode`、越权写文件、未过滤 `$_POST/$_GET`）。
4. **网页调试**：边缘 `curl` 探活 + `browser_use` 子代理看渲染层 console/network/截图。
5. **访客日志分析**：`analyze-log.py` 快速汇总、`site-report.py` 出完整 HTML 报表（PV/UV/趋势/蜘蛛/设备/爆破告警），替代宝塔监控插件。
6. **宝塔 / nginx 运维**：站点配置定位、`nginx -t && nginx -s reload` 安全重载。
7. **统一备份规范**：所有改前备份落 `/www/backup/maintain-<日期>/`，不散落 `/root` 或源目录旁（见 §3.6）。
8. **MCP SSH 连接器体系**（4 个 stdio 服务，见 §3.7）：日常运维、异步长任务/目录快照、原生 ssh 兜底、Fail2ban 管理，均已端到端验证。
9. **持久化与冷启动恢复**：技能包 + MCP 配置一键归档到服务器、回滚后一键恢复（见 §6）。
10. **Fail2ban 正则误伤审计**（见 §3.8）：命中归因、会话链判真人 vs 机器、字段穿透修复、多日双向 diff 验证——排查"误封真人/漏放攻击"。

---

## 0. 环境事实（不要重复探测）

> **工作铁律（最高优先级）**：动手改任何站点功能前，先读本节环境事实 + `§10.8 文件→功能速查表` 定位目标文件；表里已收录的直接拿来改，禁止凭感觉全局乱搜、来回猜路径/文件。只有表里没有才允许 `grep` 全局搜，且先限定 `wp-content/` 内；查不到结论先回头翻 §10.8 与 `references/server-map.md`，别当无头苍蝇。

- 出口代理：`http://127.0.0.1:18080`（HTTP/HTTPS/CONNECT-22 均可）
- 直连 22 / ICMP / 3306 端口：**被屏蔽**，必须走隧道
- 可用工具：`ssh` (OpenSSH)、`nc` (OpenBSD，支持 `-X connect -x`)、`socat`、`rsync`、Python 3.10、Node 22 + npm/npx
- **不可用**：`sshpass`、`docker`、GUI
- 工作目录：`/workspace`（最终产物）；运行用户：`root`
- **① 会话首步（零密码自愈）**：一提服务器/站点/宝塔/fail2ban/日志/SSL/网站故障，任何 ssh/rsync/scp/MCP 前先跑（幂等，别问「怎么连/密码」，凭据都在本技能包）：
  ```bash
  bash /workspace/.trae/skills/ssh-site-maintain/persist/ensure-ssh-key.sh
  ```
  分层：现成 `~/.ssh` → GitHub → 423down HTTPS → 仅 authorized_keys 被清空才密码引导（§1.0）。
- **② 维护收尾（强制归档，改完必跑）**：改动技能包/服务器配置的任务结束时执行，未归档=未完成：
  ```bash
  bash /workspace/.trae/skills/ssh-site-maintain/persist/maintain-close.sh
  ```
  = 推 GitHub（权威源）+ 服务器双镜像 + 三处 `sha256` 校验，`PASS/FAIL`；FAIL 重跑（§6）。

---

## 1. 密钥引导与回滚自愈

### 1.0 回滚自愈（零密码，**默认先走这里**）

沙箱回滚/换新后 `~/.ssh` 与技能包可能丢失，**不需要向用户要密码**。一条命令自愈：

```bash
bash /workspace/.trae/skills/ssh-site-maintain/persist/ensure-ssh-key.sh   # 默认别名 423down
```

分层逻辑（逐层尝试，任一层免密自检通过即停）：

| 层 | 触发条件 | 动作 |
|---|---|---|
| ① 现成 `~/.ssh` | 免密已通 | 直接返回，零动作 |
| ② GitHub 恢复点 | ① 不通且有 `GH_TOKEN` | 拉 `423down-links/skillpack/ssh-site-maintain-latest.tar.gz`（含私钥）解包还原 `~/.ssh`（技能包缺失时一并还原） |
| ③ 423down HTTPS 恢复点 | ② 不通 | 带 `X-Recover-Token` 头拉 `/www/skill-recovery/skillpack.tar.gz` 解包还原 |
| ④ 密码引导 | ②③ 还原客户端密钥后仍连不上 | = 服务器 `authorized_keys` 被清空 → 先等服务器端 `agent-key-guard` 自动补回，再不行才 §1.1 密码引导 |

> 说明：还原时**只在技能包缺失时**才解包 `.trae`，不会覆盖本地未归档的改动。
> 鉴权指纹锚点（还原后应匹配）：`ssh-keygen -lf ~/.ssh/id_ed25519` = `SHA256:zI16tC4lrKRzIHVcrO0p9ruli45AVqYPDSSTHSc4xrU`。

### 1.1 密码引导：用密码一次性安装公钥（沙箱无 sshpass 的解法，仅新主机 / ④ 兜底时用）

每台新服务器，用密码登录一次，把本地生成的公钥写入远端 `authorized_keys`，之后免密登录。

**步骤 1：生成密钥对（仅一次，跨主机复用）**
```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
[ -f ~/.ssh/id_ed25519 ] || ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 -C "sandbox-maintain"
chmod 600 ~/.ssh/id_ed25519*
```

**步骤 2：通过代理用密码安装公钥（交互式喂密码，pexpect 替代品）**
```bash
# 密码从 stdin 读取，避免出现在进程列表 / 历史
printf '%s' '用户提供的密码' | python3 /workspace/.trae/skills/ssh-site-maintain/bootstrap-key.py \
  --host <host> --port 22 --user <user>
```
脚本内部：`ssh -o ProxyCommand="nc -X connect -x 127.0.0.1:18080 %h %p" -o PubkeyAuthentication=no` 用 pty 喂密码，把公钥 base64 解码后追加进远端 `~/.ssh/authorized_keys`，最后验证密钥登录成功。

**步骤 3：验证**
```bash
ssh <alias> 'hostname && uptime && whoami'
```

---

## 2. 注册新主机（动态配置入口）

用户给出 `别名 / 地址 / 端口 / 用户 / 用途` 后，调用：
```bash
python3 /workspace/.trae/skills/ssh-site-maintain/register-host.py \
  <alias> <host> [port] <user> "<purpose>"
```
脚本会向 `~/.ssh/config` 追加如下块，并把元信息登记到 `~/.ssh/hosts.json`：

```
Host <alias>
    HostName <host>
    Port <port>
    User <user>
    ProxyCommand nc -X connect -x 127.0.0.1:18080 %h %p
    StrictHostKeyChecking accept-new
    ServerAliveInterval 30
    IdentityFile ~/.ssh/id_ed25519
```

后续直接 `ssh <alias>` 即可。

---

## 3. 常见维护场景

### 3.1 站点管理 & 命令执行
- 单条命令：`ssh <alias> '<cmd>'`
- 批量并行：`for h in wp-prod wp-staging; do ssh $h 'uptime; df -h /; free -h'; done`
- 文件传输（rsync/scp 自动走 config 里的 ProxyCommand）：
  ```bash
  rsync -aze ssh <alias>:/var/www/html/wp-config.php /workspace/analysis/
  scp <alias>:/etc/nginx/sites-available/* /workspace/analysis/nginx/
  ```

### 3.2 主题 / 插件分析（WordPress / Typecho 等）
1. 拉取相关子树（避免整站下载）：
   ```bash
   rsync -aze ssh \
     --include='*/' --include='wp-content/themes/*' --include='wp-content/plugins/*' \
     --exclude='*' \
     <alias>:/var/www/html/ /workspace/analysis/wp-content/
   ```
2. 本地分析（不增加线上负载）：
   - 主题：定位 `style.css` 头部、`functions.php`、模板；grep 硬编码 URL、enqueue 资源
   - 插件：扫描危险点（`eval`、`base64_decode`、写非上传目录的 `file_put_contents`、未过滤的 `$_POST/$_GET`）
   - 用内置 `Grep` / `Glob` 工具搜索，`Read` 读文件

### 3.3 网页调试（前端 + 边缘）
- 边缘检查（经沙箱出口）：`curl -sS -o /dev/null -w '%{http_code} %{time_total}\n' https://<site>/`
- 渲染层调试：调用 `browser_use` 子代理，传入站点 URL，返回 console / network / 截图
- 边缘 vs 源站对比：`curl -I https://<site>/` (沙箱) vs `ssh <alias> 'curl -I http://localhost/'`

### 3.4 访客日志分析（nginx / apache access log）
1. 按时间切片拉取（压缩传输，避免拉整 10GB）：
   ```bash
   mkdir -p /workspace/analysis/<site>
   # 当天日志
   ssh <alias> 'gzip -c /www/wwwlogs/<domain>-access.log' > /workspace/analysis/<site>/access-$(date +%Y%m%d).log.gz
   # 历史归档（宝塔按"开始日期"命名：-YYYYMMDD 文件含次日 23:59 轮转前一整天）
   ssh <alias> 'gzip -c /www/wwwlogs/<domain>-access.log-20260930' > ...
   ```
   宝塔实际命名是 `<domain>-access.log`（不是 `<domain>.log`）；error 日志同理 `-error.log`。
2. 快速汇总（控制台）：
   ```bash
   python3 analyze-log.py /workspace/analysis/access.log --top 20
   ```
3. **完整报表（推荐，替代宝塔"网站监控报表"）**：
   ```bash
   python3 site-report.py access-*.log.gz --title "<domain>" --top 25 --out report.html
   ```
   输出自包含 HTML：PV/页面PV/UV、24h 趋势、蜘蛛抓取明细、设备分布、Top 页面/IP/Referer、
   扫描探测、**wp-login 爆破告警**、5xx 错误页。兼容 combined 与 total 插件的 JSON 日志格式。
   生成后用 `computer://` 链接交付。

### 3.5 宝塔 / nginx 环境
- 站点日志：`/www/wwwlogs/<domain>-access.log`、`/www/wwwlogs/<domain>-error.log`
- 站点配置：`/www/server/panel/vhost/nginx/<domain>.conf`
- 网站根目录：`/www/wwwroot/<domain>/`
- 宝塔 CLI：`ssh <alias> 'bt default'`（看面板信息）、`bt 5`（改密）、`bt 14`（看站点）
- 改完配置必先测试：`ssh <alias> 'nginx -t && nginx -s reload'`

### 3.6 备份规范（统一落盘位置）
- **所有**改前备份一律放：`/www/backup/maintain-<YYYYMMDD>/`（如 `/www/backup/maintain-20261003/`），按日期建子目录，改前 `mkdir -p`。
- **禁止**备份到 `/root` 或目标文件当前所在目录（不留 `xxx.bak` 在源目录旁边）。
- 备份命令示例：`DEST=/www/backup/maintain-<日期>; mkdir -p "$DEST"; cp -a <file> "$DEST/"`。
- 大文件/整目录备份存 `/www/backup/maintain-<日期>/`，不要塞进宝塔托管的 `/www/backup/site/`（避免被面板轮转/清理误删）。
- 历史遗留：2026-10-03 前的旧备份仍在 `/root`，如需归档可再统一移入 `/www/backup/maintain-<对应日期>/`。

### 3.7 MCP SSH 连接器（已封装 + 端到端验证 2026-10-03）

技能包 `mcp/` 目录内置 4 个 MCP 服务（stdio），依赖已 `npm install` 到本地 `node_modules`，新沙箱恢复后**无需联网装包**。TRAE 项目级配置在 `/workspace/.trae/mcp.json`，新会话自动拉起。

**选型（用哪个连接器）：**

| 场景 | 用哪个 | 服务名 / 工具 |
|---|---|---|
| **日常运维（首选）** | `@fangjunjie/ssh-mcp-server` v1.9.2 | `ssh-423down`：`execute-command`(cmdString) / `upload` / `download` / `list-servers` |
| 长任务防超时 / 大批日志源码拉取 / 远程目录镜像 | `@lhtdeg/ssh-mcp-server` v1.3.3 | `ssh-423down-async`：`execute-command-task`→`get-command-task-result`（taskId 轮询）、`snapshot-remote-directory-task`→`get-snapshot-task-result` |
| 原生 ssh 兜底（无 Node 依赖心智） | `@aiondadotcom/mcp-ssh` v1.3.9 | `ssh-native`：`runRemoteCommand`(hostAlias+command) / `runCommandBatch` / `uploadFile` / `downloadFile`，自动发现 `~/.ssh/config` 别名 |
| Fail2ban 管理 | 自研 `mcp-fail2ban`（零依赖） | `fail2ban-423down`：`f2b_status` / `f2b_jail_status` / `f2b_ban` / `f2b_unban` / `f2b_log_tail` |

**关键实现事实（改配置前必读）：**
- fangjunjie 原生支持 `--proxy http://127.0.0.1:18080`（CONNECT 隧道），**无需中继**，直连 `45.151.132.50:22`
- lhtdeg 只支持 SOCKS 代理 → 由 `bin/ensure-relay.sh` 起 socat 中继 `127.0.0.1:22022 → 代理 → 服务器:22`，连接器连 `127.0.0.1:22022`
- aiondadotcom 用原生 `ssh`，直接吃 `~/.ssh/config` 里的 `423down` 别名（ProxyCommand 天然生效）
- 凭据统一走密钥 `~/.ssh/id_ed25519`（新主机密码引导见 §1，密码只走 stdin 不落盘）
- 生产黑名单（**仅 fangjunjie/lhtdeg 两个连接器有；ssh-native（aiondadotcom）无黑名单**，跑它时危险命令全靠 §4 规则约束）：`rm -rf /`、`mkfs`、`dd if=/dev/`、`shutdown`、`reboot`、`halt`、`poweroff`、`init 0/6`、停用关键服务（systemctl 与 sysv `service`/`/etc/init.d` 两种形式都拦：sshd/nginx/mysqld/php-fpm*/fail2ban/bt）、`mysqladmin shutdown`
- 本地路径白名单 `/workspace,/tmp`；远程路径白名单 `/www,/tmp,/etc,/root`

**启动脚本（等价于 mcp.json 里的命令）：**
```bash
bash mcp/bin/launch-ssh-423down.sh         # 主连接器
bash mcp/bin/launch-ssh-async-423down.sh   # 异步/快照（自动带起 relay）
bash mcp/bin/launch-f2b.sh                 # fail2ban
```

**一键回归验证（4 个服务全链路 e2e：命令/上传/下载/黑名单/异步任务/快照/封禁解封 + 3 个生产启动脚本 smoke）：**
```bash
bash mcp/bin/e2e-verify-all.sh    # 期望 7 行 PASS + 四个 md5 一致
```
用例在 `mcp/specs/*.json`（`e2e-*` 全链路、`smoke-launch-*` 启动脚本冒烟、`e2e-lhtdeg-connmgr` 多连接管理），测试客户端 `mcp/bin/mcp-e2e-client.mjs`（零依赖，支持 expectError 断言与 taskId 提取链）。

### 3.8 Fail2ban 过滤器正则误伤审计（Nginx 日志场景）

> 由原独立技能 `fail2ban-regex-audit` 合并而来（2026-10-03）。**何时用**：fail2ban 命中量异常、怀疑误封真实用户/蜘蛛、需要修改过滤器正则时。
> **目标**：先量化命中性质 → 再改规则 → 最后用多日双向 diff 证明"误伤清零、攻击零漏"。
> 与 §3.7 的 `mcp-fail2ban`（封/解封操作）配套：这里判断**规则对不对**，那里执行**封不封**。

**适用环境**：Linux + fail2ban + nginx 访问日志（宝塔：日志 `/www/wwwlogs/<site>-access.log*`，过滤器 `/etc/fail2ban/filter.d/`，jail `/etc/fail2ban/jail.local`）。站点登录失败返回 200（WordPress 默认），成功 302。

**① 导出命中与全量日志**（每个轮转日志分别跑，别只看当天）
```bash
L=/www/wwwlogs/<site>-access.log-YYYYMMDD
fail2ban-regex "$L" /etc/fail2ban/filter.d/<filter>.conf --print-all-matched 2>/dev/null \
  | grep '^|' | sed 's/^|  //' > /tmp/audit-matched.txt
```
同时把对应日期全量日志 gzip 拉到本地离线分析（见 §3.4）。

**② 命中归因**（回答"为什么命中这么多"）——离线 Python 统计：
- 状态码分布：444/403/404 多为已被 nginx 拦的攻击；**200 是误伤高危信号**，逐条看。
- 触发特征分类：从 URI 提取 token（`xmlrpc.php`、`.env`、`/admin`、敏感后缀…）+ 与状态码交叉。
- 每 IP 命中次数分布（1 / 2 / 3-5 / 6-20 / >20）。
- 滑窗达阈率：按 jail 的 `findtime/maxretry` 算"命中 IP 中有多少真会被封"；命中多但达阈率低属正常（分布式低频攻击）。
- 小时分布（整点脉冲=脚本定时）、UA 归因（大量不同 IP 共用同一 UA=UA 池轮换）。
- 白名单交叉：命中 IP 与 FCrDNS 验证蜘蛛清单取交集，应为空。

**③ 会话跳转链判定真人 vs 机器**——对命中 IP 在全量日志按时间排序，标注 PAGE/ASSET/POST：
- A 纯命中无浏览 → 攻击；B 末次 POST 后仍继续浏览文章 → 真人强特征；C POST 前 15 秒内集中预热 → 脚本伪装。
- 再算 B 类中 POST 密度达阈值的 IP 数 = 潜在误封真人规模。
- 基线注意：若整站 CDN/反代导致静态资源普遍缺失，别用"是否加载资源"当判据。

**④ 确认"封了之后实际发生什么"**
- 看 jail 的 `action`：`firewallcmd-ipset*` = 硬封（断网）；自定义 `fileonly` 类可能只写标记文件，由 nginx 转人机验证页（读 action.d 确认）。
- 硬封 jail 的误伤必须立即修；软封（验证页可自解、短时自动解除）风险低。
- 状态码语义：POST 登录 200=失败、302=成功，过滤器只应计失败。

**⑤ 误伤根因：字段穿透**（经典 bug）
`failregex` 用 `.*敏感词` 扫**整行**，导致 referer/UA 里的同形子串命中。
例：真实文章页 referer 为 `/search/<含 shell|manage>`，被 `/shell`、`/manage` 子串命中。
**修复原则：把匹配锚定在请求行内部，不让 referer/UA 参与。**
```
# 请求行：IP - - [time] "METHOD URI HTTP/x" status bytes "referer" "ua"
failregex = ^<HOST> [^"]*"[A-Z]+ (?!/search/|/wp-content/|/verify/|/+wp-login\.php(?:\?|\s)|/wp-admin/)(?![^ ]*[?&]s=)(?![^ ]*action=lostpassword)[^"]*(危险token1|token2|...)[^"]*"
```
要点：
- 负向预查只对**请求 URI**生效，禁止 `.*\/wp-admin\/` 这类扫整行的宽松预查（会漏 `/wordpres/wp-admin/install.php` 等猜目录扫描）。
- `/wp-login.php` 放行要限定"路径就此结束（后接 `?` 或空白）"，否则 `/wp-login.php:x/xmlrpc.php` 路径混淆会漏。
- 改前先备份过滤器（带时间戳，落 §3.6 规范目录）。

**⑥ 多日双向 diff 验证**（必做，不可跳）——至少 5-6 天（含当天）分别用旧、新过滤器导出命中，过滤出真实日志行后：
```bash
sort -u old-*.txt > old-all; sort -u new-*.txt > new-all
comm -23 old-all new-all > false-only   # 旧有新无：候选误伤，逐条人工确认
comm -13 old-all new-all > new-only     # 新有旧无：新增捕获，逐条确认是攻击而非新误伤
```
- false-only：逐条看 URI+referer，确认全是正常页；统计涉及 IP，区分"纯误伤"与"混合"。
- new-only：必须全是攻击特征（404/444/恶意路径）；出现 200 正常页即回退。
- 小语料回归 + 全天日志回归 + `fail2ban-client -t` 配置检查。

**⑦ 部署与善后**
1. `fail2ban-client reload`，确认各 jail `Currently banned` 正常、日志无 error。
2. 解封纯误伤 IP：`fail2ban-client set <jail> unbanip <ip>`，确认 ipset 同步移除（也可用 §3.7 的 `f2b_unban`）。
3. 对照实验（可选）：向日志注入验证过的蜘蛛 IP 与保留地址（如 `198.51.100.0/24`）的合成攻击行，确认 ignorecommand 豁免真蜘蛛、对照 IP 被封后立即清理。

**注意**
- `fail2ban-regex --print-all-matched` 输出含报告抬头行，落盘后要用日志行正则（`^<IP> - - \[`）过滤再 diff。
- 改前检查文件是否有 `chattr +i` 不可变属性；有则先 `chattr -i`，改完锁回。
- 写远程文件用带引号的 heredoc（`cat > file <<'EOF'`），避免 `$remote_addr` 被 shell 插值。
- 原始配置统一备份到带时间戳目录，过滤器迭代版本同时留存。

---

## 4. 安全规则

- **绝不**在聊天或日志里回显密码 / 私钥
- 私钥只存 `~/.ssh/`，权限 600；密码由用户通过 `AskUserQuestion` 或直接粘贴提供，**不持久化**
- 改 nginx / 任何配置文件前备份，统一放 `/www/backup/maintain-<YYYYMMDD>/`（见 §3.6），不留 `xxx.bak` 在源目录
- 破坏性命令（`rm` / `DROP` / `dd` / `> file`）执行前用 `AskUserQuestion` 二次确认
- 拉取的日志/源码放 `/workspace/analysis/`，命名含日期，避免覆盖

---

## 5. 本技能附带的辅助脚本

- `bootstrap-key.py` — 密码 → 公钥安装（经代理，pty 喂密码）
- `register-host.py` — 注册主机到 `~/.ssh/config` + `~/.ssh/hosts.json`
- `analyze-log.py` — nginx/apache access log 快速汇总器
- `site-report.py` — 完整网站访问报表（HTML）：PV/UV/趋势/蜘蛛/设备/爆破告警，替代宝塔监控插件
- `mcp/bin/launch-*.sh` — MCP 连接器启动脚本（主/异步/f2b 三个；ssh-native 由 mcp.json 直接 node 拉起，见 §3.7）
- `mcp/bin/e2e-verify-all.sh` — MCP 全链路回归验证
- `mcp/bin/mcp-e2e-client.mjs` — MCP stdio 测试客户端（零依赖）
- `mcp/mcp-fail2ban/server.mjs` — 自研 Fail2ban MCP 服务（零依赖）
- `waf-hit-analysis.sh` — 安全规则命中/误封只读分析脚本（423down，见 §10.5）
- `references/server-map.md` — 423down 生产服务器完整档案（见 §10）
- `persist/ensure-ssh-key.sh` — **零密码回滚自愈**（会话首步，见 §1.0）
- `persist/maintain-close.sh` — **维护收尾**：归档 GitHub + 服务器双镜像 + 三处 sha256 校验（见 §0 / §6）
- `persist/archive-skill.sh` — 归档技能包（推 GitHub 权威源 → 回拉 → 落服务器双镜像，见 §6）
- `persist/restore-skill.sh` — 沙箱回滚后从服务器一键恢复技能包（见 §6，兜底通道）

---

## 6. 持久化与冷启动恢复（防沙箱回滚）

技能包唯一权威副本在 `/workspace/.trae/skills/ssh-site-maintain/`（工作区技能，新会话自动加载）。防沙箱回滚丢失：

> ⚠️ **云端使用必读**：本技能跑在云端沙箱里，沙箱可能被回滚/重建，工作区文件会丢。
> **只要改动了技能包（SKILL.md、脚本、MCP 配置等）或服务器配置，维护任务结束必跑一次收尾归档**，否则改动随回滚丢失：
> ```bash
> bash /workspace/.trae/skills/ssh-site-maintain/persist/maintain-close.sh
> ```
> `maintain-close.sh` = 调 `archive-skill.sh`（推 GitHub → 回拉 → 落服务器双镜像）**并**做三处 `sha256` 一致性校验，输出 `PASS/FAIL`。只要归档本身，可单独跑 `archive-skill.sh`。
> 归档 = 打包技能包本体 + `/workspace/.trae/mcp.json` + `~/.ssh/{id_ed25519,config,hosts.json(如有)}`，**双通道**同步到 `423down:/www/backup/skill-packages/` 与 GitHub 私有仓 `423down-links/skillpack`。

**归档（每次改技能包后执行）：**
```bash
bash /workspace/.trae/skills/ssh-site-maintain/persist/archive-skill.sh
```
归档 = 打包技能包本体 + `/workspace/.trae/mcp.json` + `~/.ssh/{id_ed25519,config,hosts.json(如有)}`（**含私钥**，冷启动免密码）。**GitHub 私有仓 `423down-links/skillpack` 为唯一权威源**；服务器**不留时间戳历史档**，只镜像两处、内容与 GitHub 最新版**逐字节一致**：
① `/www/backup/skill-packages/ssh-site-maintain-latest.tar.gz`（服务器唯一 canonical；root 600）；
② `/www/skill-recovery/skillpack.tar.gz`（HTTPS 恢复点；root:www 640，nginx token 门禁）。
脚本流程：本地构建 → 推 GitHub → **从 GitHub 回拉**再落服务器两处（GitHub 推失败则退用本地构建并告警）。清理与镜像均由 `archive-skill.sh` 一并完成，无需手工。

**冷启动恢复（沙箱被回滚/换新后）——三选一，按优先级：**

**① 首选：GitHub 私有仓（零密码，密钥已打进归档）**
```bash
mkdir -p ~/.ssh /workspace && chmod 700 ~/.ssh && \
curl -fsSL -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github.raw" \
  "https://api.github.com/repos/423down-links/skillpack/contents/ssh-site-maintain-latest.tar.gz" -o /tmp/sp.tgz && \
tar -xzf /tmp/sp.tgz -C /workspace .trae && \
tar -xzf /tmp/sp.tgz -C ~/.ssh --strip-components=1 .ssh && \
chmod 600 ~/.ssh/id_ed25519 ~/.ssh/config
```
`GH_TOKEN` 见云端环境「敏感变量」（423down 账号，可读该私有仓）。本仓已关闭 Actions、未接任何 Cloudflare Pages。

**② 备用：423down HTTPS 恢复点（⚠️ 必须带 `X-Recover-Token` 请求头，否则一律 404）**
```bash
mkdir -p ~/.ssh /workspace && chmod 700 ~/.ssh && \
curl -fSL -H "X-Recover-Token: f7fa765c546c9f238cbfb2a66bc9f265" \
  "https://www.423down.com/sk-8ed7cd677edb0fb9e4ff0b1e640c2a453a14e09ffa625fd4/skillpack.tar.gz" -o /tmp/sp.tgz && \
tar -xzf /tmp/sp.tgz -C /workspace .trae && \
tar -xzf /tmp/sp.tgz -C ~/.ssh --strip-components=1 .ssh && \
chmod 600 ~/.ssh/id_ed25519 ~/.ssh/config
```
内容 = GitHub 最新版（`.trae` 布局，含私钥），解包方式同 ①。实现：nginx 精确 `location =` + 请求头双因子（路径或头缺一即 404），文件置于 webroot 外 `/www/skill-recovery/`。
**加固（2026-10-10）**：该 location `access_log off`（路径 token 不再进日志）+ 专属限流 `zone=recover_rl`（3r/m，防暴力试探），权限 `dir 750 root:www` / `file 640 root:www`。

**③ 兜底：用已恢复 `~/.ssh` 的沙箱直连服务器**
```bash
ssh 423down 'cat /www/backup/skill-packages/ssh-site-maintain-latest.tar.gz' | tar -xz -C /workspace
```
或跑恢复脚本：`bash /workspace/.trae/skills/ssh-site-maintain/persist/restore-skill.sh`

恢复内容含：技能包本体 + `/workspace/.trae/mcp.json`（4 个连接器新会话自动拉起）+ `~/.ssh/id_ed25519` + `~/.ssh/config`（+ `hosts.json` 如有）。恢复后务必回归一次：
```bash
bash /workspace/.trae/skills/ssh-site-maintain/mcp/bin/e2e-verify-all.sh
```

---

## 7. 触发条件（何时调用本技能）

用户要求以下任一，应调用：
- 操作 / 调试 / 分析远程服务器或网站
- 拉取并分析 WordPress 主题或插件
- 拉取并汇总访客访问日志
- 在远程主机上跑命令（SSH）
- 操作宝塔面板 / nginx 配置

**不要调用**：纯本地文件编辑、纯代码库搜索、不含远程执行的构建任务、Lark/IM 通用任务。

---

## 8. 最近维护记录（结论速记）

> 详细过程已固化到正文：fail2ban 审计 → §3.8；缓存清理 → §10.4；jail 对照 → §10.5；
> php-cli 测功能 → §10.7；文件→功能速查 → §10.8。此处只留最近关键结论与变更索引。

### 2026-10-13
- 规则/脚本去冗（压低思考链）

### 2026-10-12
- 评论时间智能格式 + 归属地位置 + 身份标签 → §10.8 ①
- 设备误封修复 → §10.8 ①

### 2026-10-10
- 登录/注册跳转 → §10.8 ①
- 日志审计（momgo 301 + wordpress-crawl jail）→ §3.8 / §10.5
- 存档治理（GitHub 权威源 + 双镜像）→ §6
- 技能包审计 e2e 7/7 → §3.7 / §5

### 2026-10-03
- 站点治理 + MCP 连接器引入 → §10.1~§10.6、references/server-map.md

## 9. 待办 / 观察项

- 日志已于 2026-10-03 清空，**待观察两天**，后续据新日志分析是否存在新问题（重点看 `-error.log` 与 `fail2ban.log` 的新增事件）。
- `/root` 仍遗留 2026-09-28 及更早的旧备份（约 28 个 `*.bak`/`*.save`），未归档；需要时统一移入 `/www/backup/maintain-<对应日期>/`。
- 服务器技能包存档：**GitHub 私有仓为唯一权威源**，服务器只镜像两处——`ssh-site-maintain-latest.tar.gz`（唯一 canonical）+ `/www/skill-recovery/skillpack.tar.gz`（HTTPS 恢复点），均与 GitHub 最新版逐字节一致（2026-10-10 治理，见 §6/§8）。改完技能包须**立即**跑 `archive-skill.sh` 重新归档。

---

## 10. 423down 生产服务器专用档案

> 由旧技能 `423down-ops` 并入（2026-10-03）。完整档案见 [references/server-map.md](references/server-map.md)（拓扑/路径/服务/日志/cron/插件/jail 明细/误封点/凭据审计/历次修复史）。此处只放最常用的速查与关键认知。

### 10.1 服务器速查

| 项 | 值 |
|----|----|
| 主机 | 45.151.132.50（423down.com），CentOS 7.9，3核 2.5G / 60G 盘 |
| 面板 | 宝塔 `/www/server/panel/`，命令 `bt` |
| nginx | Tengine `/www/server/nginx/sbin/nginx`，服务 `/etc/init.d/nginx` |
| 站点配置 | `/www/server/panel/vhost/nginx/www.423down.com.conf` |
| PHP | php-fpm 7.4，服务 `/etc/init.d/php-fpm-74`，ini `/www/server/php/74/etc/php.ini` |
| MySQL | bin `/www/server/mysql/bin/mysql`，库 `423down`，前缀 `wp_` |
| 网站根 | `/www/wwwroot/www.423down.com` |
| 日志 | `/www/wwwlogs/`（明细见 server-map） |
| SSL | `/www/server/panel/vhost/cert/www.423down.com/` |
| wp-cli | **未安装** |

### 10.2 关键认知（先读，避免走弯路）

1. **服务器无 `python3`、无 `wp-cli`**：远程改文件用 `sed` 或 `php -r`；复杂改动写 `/tmp/*.php` 脚本跑（`python3 xx.py` 必 command not found）。离线分析放本地跑。
2. **首页两层特殊行为**：① D7 主题 `functions.php` 顶部"访客→include `index.html`"钩子（⏳ **临时开启**，约 2026-09-28 起配合 ICP 备案复查，非永久架构，别假设它一直在）；② 宝塔「网站加速」site_speed（Lua/OpenResty 边缘缓存，**nginx 层、PHP 之前直出**）→ **改 PHP/主题后首页不更新，须清 site_speed 缓存**（见 §10.4）。验证代码是否生效用无缓存路径（如 `/test-xxx/`）。
3. **nginx 站点 conf 有大量安全规则**（`return 444`、`deny`、feed 403、`.bak/.sql/.git` 封禁等），编辑勿误删；改前必备份 + `nginx -t`。
4. 会话分担：连接服务器干活建议单独开运维会话，上下文干净。

### 10.3 常用 Playbook（远端 bash）

体检（一键）：
```bash
echo "=LOAD="; uptime; echo "=MEM="; free -m|head -2; echo "=DISK="; df -h /|tail -1; \
echo "=SVC="; for s in nginx php-fpm-74 mysqld; do printf "%s:%s " "$s" "$(systemctl is-active $s 2>/dev/null||echo ?)"; done; echo; \
echo "=PORTS="; ss -tlnp|grep -E ':(80|443|3306)'|awk '{print $4}'|sort -u; \
echo "=ERRLOG(tail)="; tail -n 15 /www/wwwlogs/www.423down.com-error.log 2>/dev/null
```
- nginx：测试 `/www/server/nginx/sbin/nginx -t`；重载 `/etc/init.d/nginx reload`
- php-fpm：重载 `/etc/init.d/php-fpm-74 reload`；慢日志 `/www/wwwlogs/php-fpm-74-slow.log`
- MySQL 健康：`/www/server/mysql/bin/mysqladmin status 2>&1 | head -1`；整库备份见 §3.4 与 server-map
- SSL 到期：`for c in /www/server/panel/vhost/cert/www.423down.com/*.pem; do echo "$c:"; openssl x509 -enddate -noout -in "$c"; done`
- 本机探站（绕公网）：`curl -s -k --resolve www.423down.com:443:127.0.0.1 https://www.423down.com/ | grep -io '<title>[^<]*</title>'`
- 远程改文件四步：备份 → 改（`sed -i` 或 `/tmp/*.php`）→ `php -l` 校验 → 生效（改主题记得清缓存）

### 10.4 清网站加速缓存（不走面板）

```bash
/www/server/panel/pyenv/bin/python -c "import sys; sys.path.insert(0,'/www/server/panel/plugin/site_speed'); import site_speed_main as m; print(m.site_speed_main().clean_cache({'site':'www.423down.com'}))"
```
⚠️ 站有**两层**页缓存：① batcache/memcached（`printf 'flush_all\r\nquit\r\n' > /dev/tcp/127.0.0.1/11211` 可清）；② **site_speed lua_shared_dict 边缘缓存（flush memcached 清不到，只随 nginx 重启清）**。改 HTML/主题后公网仍吐旧快照，多半是后者。

### 10.5 Fail2ban jail 对照（`/etc/fail2ban/jail.local`，改前必备份）

> 2026-10-10 已按线上实况重写（`jail.local` + `fail2ban-client` 双源核对，jail 总数 5→11：含当日新增 `wordpress-crawl`）。fileonly = 只写 `/run/f2b_block_<ip>` 标记 → nginx 302 到 `/verify/` 验证码页；ipset-web = 只封 80/443；ipset = 全端口 REJECT。

| jail | 阈值 | 时长 | 动作 = 实际效果 |
|------|------|------|----------------|
| `sshd` | 300s/3次 | 24h 起（bantime 递增 ×2 ↑30天） | `firewallcmd-ipset-ssh`：只 REJECT **22 端口**，不影响网站 |
| `wordpress-high` | 60s/3次 | 3天 | `firewallcmd-ipset-web`：只封 **80/443**（2026-09-29 起，原为全端口） |
| `wordpress-medium` | 60s/6次 | 12h | 同上，只封 80/443 |
| `wordpress-bruteforce` | 60s/20次 | 1天 | `firewallcmd-ipset` 全端口 REJECT（wp-login POST 速率，不看状态码） |
| `wordpress-login` | 300s/3次 | 30分钟 | `fileonly`：写 `/run/f2b_block_<ip>` → nginx 302 到 `/verify/` 验证码页 |
| `wordpress-low` | 120s/20次 | 1天 | `fileonly`（低危软封，同 login 链路） |
| `wordpress-html` | 300s/40次 | 1天 | `fileonly`（低危软封，同 login 链路） |
| `wordpress-crawl` | **12h/150次** | 1天 | `fileonly`（2026-10-10 新增：长窗口累计，专治低速采集农场） |
| `wordpress-scan` | 1h/40次 | 12h | `firewallcmd-ipset-web`：只封 80/443 |
| `verify-fail` | 10min/5次 | 1天 起（递增 ×2 ↑7天） | `firewallcmd-ipset-web`：只封 80/443（验证码屡次不过→硬封） |
| `softban-recidive` | 7天/3次 | 7天 | `firewallcmd-ipset-web`：只封 80/443（fileonly 惯犯再犯→硬封） |

- **改规则用 reload 还是 restart**：只改 **filter** → `reload` 够；改了 jail 的 **action** → 必须 `restart`（reload 不跑 actionstart，会把 iptables 规则摘掉且不报错）。改前 `ipset save` 留快照。
- 已知误封点与历次修复（站内搜索/静态资源/feed/字段穿透/不限端口/双斜杠绕过等）详见 server-map「安全拦截链路」。
- 命中/误封只读分析：`waf-hit-analysis.sh`（上传服务器 `/tmp` 后 `bash`，参数 = 日期 起小时 止小时）。

### 10.6 本档案附带资源

- `references/server-map.md` — 服务器完整档案（路径映射、插件清单、cron、凭据安全审计、fail2ban 链路与历次修复史）
- `waf-hit-analysis.sh` — 安全规则命中/误封只读分析脚本（封禁统计、验证码链路、误封嫌疑清单、访客基线）

### 10.7 无 wp-cli：php CLI 创建临时用户测试主题 / 设备功能（含 batcache 回放坑）

服务器无 `wp-cli`、无 `python3`（§10.2）。要验证主题/插件功能、设备判断、封禁逻辑，用 `php` 脚本 `require wp-load` 直跑 WP 环境；测完**必须清理临时用户与脚本**。

**① CLI 引导头（防 batcache 回放，三行必带，否则命令"串台"）**

```php
<?php
$_SERVER['REQUEST_METHOD'] = 'POST';
$_SERVER['REQUEST_URI']    = '/cli-guard';
define('DONOTCACHEPAGE', true);
require '/www/wwwroot/www.423down.com/wp-load.php';
```

> 不带这三行，batcache 会把 CLI 输出按空 `REQUEST_URI` 写进 memcached，下次任何 `require wp-load` 的脚本先吐旧输出再退出（看着像"命令串台 / 结果回放"）。脏了用 §10.4 清 memcached。

**② 创建临时用户 + 以指定身份调函数 + 测完清理**

```php
$uid = wp_insert_user(array(
  'user_login' => 'd7test_' . time(),
  'user_pass'  => wp_generate_password(),
  'user_email' => 'd7test@example.com',
  'role'       => 'subscriber',
));
wp_set_current_user($uid);               // 以该用户身份跑
// 模拟设备/会话：写 session_tokens，或直接调目标函数
update_user_meta($uid, 'session_tokens', array('t1' => array(/* 会话结构 */)));
$devs = d7_dev_devices($uid);            // 断言设备数 / 归并结果
// 测完清理（必做，别留测试号）：
require_once ABSPATH . 'wp-admin/includes/user.php';
wp_delete_user($uid);
```

脚本放 `/tmp/*.php`，`php /tmp/x.php` 跑完 `rm`；临时用户、`usermeta`、session 必须清干净。多设备/封禁逻辑就靠造多个 `session_tokens` + 不同 `d7_devid` 模拟，先验结果再上生产。

### 10.8 站点主题功能及环境路径（文件 → 功能速查）

> 把历次维护落地的「目标文件」集中到此，下次改功能先查本表定位文件，别全局搜。站根 `$ROOT=/www/wwwroot/www.423down.com`，WP 内容根 `$ROOT/wp-content/`。

**① WordPress 主题 / 插件功能文件**

| 文件（相对 `wp-content/`） | 功能 / 最近改动 |
|------|------|
| `themes/D7/functions.php` | 电脑端主题：菜单「用户中心/用户登录」、登录成功停原页、访客 include `index.html` 钩子（临时，配合 ICP）；**评论时间函数 `d7_comment_time_smart()`（L1330）** + 评论回调 `dtheme_comment_list()`（L1374，时间输出 L1413，`echo d7_comment_time_smart()`） |
| `themes/D7/comments.php` | 电脑端评论列表模板：`wp_list_comments( array( 'callback' => 'dtheme_comment_list' ) )`（L37-39） |
| `themes/D7/inc/comments-ajax.php` | 电脑端 AJAX 评论加载模板：L108 调用 `d7_comment_time_smart()` |
| `plugins/wp-mobile-x/themes/mobx-default/functions.php` | 移动端主题：抽屉菜单文案、`mobile_login_post` 登录停原页 |
| `plugins/wp-mobile-x/themes/mobx-default/functions-common.php` | 移动端 `auto_login_new_user()` 注册后自动登录+跳转（约 L656） |
| `plugins/wp-mobile-x/themes/mobx-default/comments.php` | **移动端评论列表模板**：`wp_list_comments( array( 'callback' => 'mobx_comment' ) )`（L19-24） |
| `plugins/wp-mobile-x/includes/functions-theme.php` | **移动端评论回调 + 时间**：`mobx_comment()`（L238）+ `mobx_comment_time_smart()`（L197，输出 `.comment-time` L263）。⚠️ 移动端评论时间在插件里**单独渲染**，不走 D7 主题 |
| `plugins/erphp-email-register/erphp-email-register.php` | 注册成功 `wp_redirect` → `/vip?pd=info`（约 L270，真正生效入口） |
| `mu-plugins/d7-device-limit.php` | 设备数限制：`d7_dev_ua_fp()` UA 指纹归一化 + `d7_dev_devices()` 同 IP 同 UA 归并 |
| `mu-plugins/user-ip-logger.php` | 用户 IP 记录（独立模块） |
| `mu-plugins/comment-ip-area.php` | 评论 IP 归属地：`cia_get_ip_area($ip)`（L264，两端时间函数手动回填省份用）；`get_comment_time` 过滤器追加 `时间 · 归属地`（L376，PC+移动端，2026-10-12）；后台归属地列 + 列表 24h 时间 |
| `mu-plugins/user-identity-badge.php` | 评论身份标签（管理员/永久·包年·包季·包月/普通/游客），字号 12→11px（2026-10-12） |
| `plugins/wp-opt/` | 已注释外呼（版本检查 / 一键更新 / 定时检查） |
| `plugins/momgo/go.php` | 已卸载旧插件，旧链经 nginx 301 → `/go.php` |

**② WP 核心 / 环境路径**

| 路径 | 用途 |
|------|------|
| `$ROOT/wp-load.php` | php CLI `require` 引导 WP 环境（测功能，见 §10.7） |
| `$ROOT/wp-admin/includes/user.php` | `wp_delete_user` 等用户函数（清临时用户） |
| `wp-content/themes/`、`plugins/` | 主题 / 插件审计 rsync 拉取根 |

**③ nginx / fail2ban / 缓存关键路径**

| 路径 | 用途 |
|------|------|
| `/www/server/panel/vhost/nginx/www.423down.com.conf` | 站点 nginx 配置（安全规则 444/deny/301，改前备份 + `nginx -t`） |
| `/etc/fail2ban/jail.local` | 11 个 jail 定义（改 action 需 restart，见 §10.5） |
| `/etc/fail2ban/filter.d/` | 过滤器正则（只改 filter 可 reload） |
| `/www/server/panel/plugin/site_speed` | 宝塔网站加速（Lua 边缘缓存，清法见 §10.4） |
| memcached `127.0.0.1:11211` | batcache 回放缓存（`flush_all` 清，见 §10.4） |
