# 423down 服务器完整映射（探测于 2026-09-28）

> 由旧技能 `423down-ops` 并入 `ssh-site-maintain`（2026-10-03）。本文件是 **423down.com 生产服务器的专用档案**：拓扑 / 路径映射 / 服务 / 日志 / cron / 插件 / fail2ban 安全拦截链路与已知误封点。
> 通用运维流程见 SKILL.md §3；Fail2ban 正则审计流程见 §3.8；备份规范见 §3.6。
> ⚠️ 文中带 `C:/Users/Administrator`、`~/.qoder-cn`、`ssh2-mcp-tools`、Qoder 的部分，是 **2026-10 之前 Windows/Qoder 客户端**的历史记录，**已不适用于云端沙箱**；但**服务器侧的事实（路径、服务、jail、误封点、安全缺陷）仍然有效**。

## 系统

- 主机：45.151.132.50 / 主机名 `423down.com`
- 发行版：CentOS Linux 7.9.2009（内核 elrepo 5.4.163，glibc 2.17 → **不支持 VS Code/Qoder Remote-SSH server**，只能走 ssh_mcp）
- 规格：3 核 / 2490MB 内存（~626MB 可用）/ Swap 1279MB
- 磁盘：`/dev/sda1` 60G，用 13G，余 45G（23%）
- 已稳定运行 75+ 天（探测时）

## 面板

- 宝塔：`/www/server/panel/`，命令行 `bt`（菜单：1 重启面板 / 2 停止 / 8 改端口 / 9 清缓存…）
- 面板站点配置目录：`/www/server/panel/vhost/`
  - nginx 站点：`vhost/nginx/www.423down.com.conf`
  - 证书：`vhost/cert/www.423down.com/`（root:root 0700）
  - 扩展：`vhost/nginx/extension/`，安全响应头 `sec_headers.conf`，限速 `speed.conf`

## nginx（Tengine）

- 二进制：`/www/server/nginx/sbin/nginx`（Tengine/3.1.0，nginx/1.24.0 兼容）
- 服务脚本：`/etc/init.d/nginx`（`start|stop|restart|reload`）
- 主配置：`/www/server/nginx/conf/nginx.conf`
- 运行 pid：`/www/server/nginx/logs/nginx.pid`
- 进程：root 主 + 多 www worker，监听 80/443（IPv4+IPv6）

## PHP

- 版本：php-fpm 7.4，仅装 74（`/www/server/php/` 下只有 `74`）
- 服务脚本：`/etc/init.d/php-fpm-74`
- php.ini：`/www/server/php/74/etc/php.ini`
- fpm 主配置：`/www/server/php/74/etc/php-fpm.conf`
- 状态页：`/www/server/panel/vhost/nginx/phpfpm_status.conf`

## MySQL

- 二进制：`/www/server/mysql/bin/mysql`（mysqldump/mysqladmin 同目录）
- 数据目录：`/www/server/data/`（pid 文件 `423down.com.pid`，运行 pid 2039）
- 服务：`mysqld.service`（systemd，`systemctl` 可管），监听 3306（IPv6 显示 [::]:3306）
- 库名：`423down`，表前缀 `wp_`
- root 密码获取：优先 `/www/server/panel/data/default.pl`（面板存的密文/明文视版本）；取不到则向用户索取或走面板「数据库」页备份
- 备份建议目录：`/www/backup/423down/`，用 `mysqldump --single-transaction` + gzip

## WordPress

- 站点根：`/www/wwwroot/www.423down.com`（属主 www:www）
- 配置文件：`wp-config.php`（含 DB_NAME=423down / DB_USER / DB_PASSWORD；读取时过滤密码行）
- 内容目录：`wp-content/`（uploads / plugins / themes / cache / languages）
- 站点根还含：`ads.txt`、`go.php`、`index.php`、`sitemap.xml`(+`.bak`)、`generate_sitemap.sh`、各搜索引擎验证 HTML、`404.html`、`system.html`、`deathlink.txt`、`ip.txt`
- **wp-cli 未安装**：需要 WP 操作用 `php` 直接跑脚本，或面板，或 mysql 命令；不要假设有 `wp` 命令
- **服务器无 `python3`**：远程脚本用 `sed`/`php -r`，别写 `python3 x.py`

## 首页访客重定向 + 缓存层（重要）

- **访客→静态页机制（⏳ 临时）**：D7 主题 `wp-content/themes/D7/functions.php` 顶部 `template_redirect` 钩子，未登录访客访问任意路径时 `include ABSPATH.'index.html'`（内部引入，地址栏不变）。静态页：`/www/wwwroot/www.423down.com/index.html`（title `zd423 - (423Down)`）。已登录走正常主题（主题首页 title `423Down`）。**此为约 2026-09-28 前后临时开启（配合 ICP 备案复查），非永久**；关闭=注释该钩子。
- **页面缓存 = 宝塔「网站加速」site_speed（Lua/OpenResty 边缘缓存，非 batcache）**：
  - 引擎目录 `/www/server/speed/`：`speed.lua`、`httpd_speed.lua`、`config.lua`（站点缓存配置）、`cookie.lua`、`memcached.lua`、缓存数据 `total/`
  - 面板插件 `/www/server/panel/plugin/site_speed/`：`config.json`、`rules.json`、`sites.json`、`site_speed_main.*.so`
  - 在 **nginx 层、PHP 之前**直出缓存 → 改 PHP/主题后首页 `/` 不更新，须**宝塔面板「网站加速」清缓存**。验证代码生效用无缓存路径（`/test-xxx/`）。
  - nginx conf 有 `set $nocache` + `wordpress_logged_in_`/`wordpress_sec_` cookie 判断，登录态自动绕过缓存。
- ⚠️ 排查缓存别认错：站点装了 batcache 插件目录、也有 `wp-content/advanced-cache.php`，但**首页实际缓存来自 site_speed（宝塔网站加速），不是 batcache、也不是 wpjam-static**。

## 已装插件清单（`wp-content/plugins/`，2026-09-28 探测）

| 插件 | 作用 | 运维注意 |
|------|------|---------|
| `batcache` | 装了但**非首页缓存来源**（首页缓存实为宝塔 site_speed） | 排查缓存别归错，见上节 |
| `erphpdown` / `-add-on-card` / `-email-register` | 付费下载/会员卡/邮箱注册（核心变现） | 动价格/会员逻辑前备份 DB |
| `slider-captcha` / `captcha-code-authentication` / `wp-anti-spam` / `wp-china-yes` | 验证码/防刷/防采集 | functions.php 里有登录图形码 v5.16 |
| `wp-force-login` | 强制登录 | 影响访客可见性，与首页重定向叠加 |
| `wpjam-basic/-script-loader/-search/-static/-sticky-posts/-tinymce/-title/-user` | 一联主题增强 | 改函数名/标题/搜索时留意 |
| `ashuwp-invitaion-code` | 邀请码 | — |
| `advanced-post-cache` | 文章查询缓存 | — |
| `5sec-snow` / `wp-mobile-x` / `wp-opt` / `wp-useragent` | 特效/移动/优化/UA | — |

## 日志目录 `/www/wwwlogs/`

| 文件 | 用途 | 备注 |
|------|------|------|
| `www.423down.com-access.log` | 站点访问日志 | 主用，体积增长快 |
| `www.423down.com-error.log` | 站点错误日志 | 排障首选 |
| `nginx_error.log` | 全局 nginx 错误 | |
| `access.log` | 默认站访问 | 常空 |
| `php-fpm-74.log` | fpm 运行日志 | |
| `php-fpm-74-slow.log` | fpm 慢执行堆栈 | 查卡顿 |
| `tcp-access.log` / `tcp-error.log` | TCP/代理负载 | 常空 |
| `tmp.log` | 临时 | |

日志轮转：宝塔面板计划任务按天/按量切割（见 cron）。

## 宝塔计划任务 cron（`crontab -l` 探测，脚本在 `/www/server/cron/<hash>`）

| 时间 | 作业 hash |
|------|-----------|
| 00:05 | c0207de167f8814087333e4e5b74bd73 |
| 02:05 | 440ed9c41545230d97ee8280c09e0b1f |
| 02:00 | 13bf5306bce6d14f5c6aa2a0a142cf31 |
| 03:35 | b8c14a16703b9f3d7a221de47eaf2ceb |
| 03:50 | 9dc4ad796a546750f35f2fdd50e2e333 |
| 06:30 | ba393dbf76d53134d97459f40173dfe7 |
| 23:59 | 575d7a8dde847da3d33dfaa4d2804df1 |

各作业 `.log` 同目录同名。要看具体任务：`cat /www/server/cron/<hash>`（多为面板备份/日志切割/sitemap 生成）。

## 连接参数

- host `45.151.132.50`，port 22，user root，**密钥认证**。
- 云端主技能走 `~/.ssh/config` 的 `423down` 别名 + 4 个 MCP 连接器（见 SKILL.md §3.7）；新主机密钥引导见 SKILL.md §1。凭据统一走密钥 `~/.ssh/id_ed25519`，密码只在引导时走 stdin。
- ⚠️ 历史遗留（2026-10 之前的 Windows/Qoder 环境）：旧连接器 `ssh2-mcp-tools` 私钥在 `C:/Users/Administrator/.ssh/id_ed25519`，会话语义硬编码 15 分钟绝对到期、无 keepalive，已在旧机打过本地补丁。该套环境**已不适用于云端沙箱**，仅作历史记录。

## 🔐 凭据安全（2026-09-28 审计结论）

- 采用**密钥认证**（ed25519，无口令），私钥仅本机 `~/.ssh/id_ed25519`，ACL 限 Administrator/SYSTEM。
- **服务器仍开着 `PasswordAuthentication yes` + `PermitRootLogin yes`**：早期配置把 root 明文密码写进过 settings.json env，已残留进 Qoder 的 `file-history`/`logs`/`session .jsonl`。
- **明文清理**：跑 `bash ~/.qoder-cn/skills/423down-ops/scripts/purge_secrets.sh`（按密码特征正则替换，脚本不含明文）。⚠️ 当前活动会话的转录会在每轮重新落盘密码（因它在对话上下文里），需**本会话结束后**或**另开干净会话**再跑一次才彻底干净；最彻底是删除本聊天记录。
- 更稳的治本（用户当前选择暂不做）：①服务器改 root 密码 ②`sshd_config` 设 `PasswordAuthentication no` 走密钥-only（改前确认密钥会话可用、留回滚）。
- 传输层本身是 SSH 加密，不泄漏；风险仅在凭据静态存放与会话日志记录。

### 2026-10-01 复审计（本轮实测）

- **Qoder 不做对话隐私保护**：会话全量明文落盘 `~/.qoder-cn\projects\*.jsonl`（89MB）、`logs\`（351MB）、`file-history\`（17MB），同时对话内容发送模型服务端。日志里能看到 `outbound session_message sent`，本机也无脱敏机制。结论：**贴进对话的密钥 = 已泄露**，只能靠"不回显 + 事后抹除 + 服务端轮换"。
- 私钥正文：本机全盘扫描 0 处泄漏（只有路径字符串），无需处理。
- 旧 root 密码残留：`purge_secrets.sh` 复查 0 命中（9 月已清干净）。
- wp-config 明文：在 7 个历史转录里发现 **146 处**（DB 密码 + 8 组 AUTH/SECURE/LOGGED_IN/NONCE 的 KEY 与 SALT），已用 `~\.qoder-cn\skills\shared-rules\scripts\redact_local_secrets.py` 按精确值替换成 `[REDACTED]`；复核 0 残留、32978 行 JSON 零损坏。用法：`SECRETS_B64=<base64 的密码 JSON 数组> python redact_local_secrets.py [--dry]`，脚本只替换值、跳过当前会话文件，密码值取自远端 `wp-config.php` 的 `awk` 结果，全程不回显。
- 远端仍未处理（用户选择暂不做）：`port 22`、`PermitRootLogin yes`、`PasswordAuthentication yes`；`/root/.bash_history` 权限 644（45KB，可能含手敲密码），建议 `chmod 600`；fail2ban 累计失败 4776 次、当前封禁 289 IP，说明爆破持续。
- 面板取库密码的老路子已失效：`/www/server/panel/data/default.pl`、`/root/.my.cnf` 均不存在，`/etc/my.cnf` 无 password 行 → 备份前需向用户索取一次密码并落成 `/root/.my.cnf`（600），之后全部用 `--defaults-extra-file`。

## 🛡 安全拦截链路：fail2ban + 验证码 + nginx 规则（2026-09-28 实测）

**判定/动作对应关系**（`/etc/fail2ban/jail.local`，改前必备份）：

| jail | 阈值 | 时长 | 动作 = 实际效果 |
|------|------|------|----------------|
| `sshd` | 300s/3次（aggressive，bantime 递增×2，上限30天） | 24h起 | `firewallcmd-ipset-ssh`：只 REJECT **22 端口**，不影响网站 |
| `wordpress-high` | 60s/3次 | 3天 | `firewallcmd-ipset`：iptables 规则**不限端口**（`INPUT_direct ... -m set --match-set f2b-wordpress-high src -j REJECT`）→ 整台机器不可达 |
| `wordpress-medium` | 60s/6次 | 12h | 同上，全端口 REJECT |
| `wordpress-bruteforce` | 60s/20次 | 1天 | 全端口 REJECT（按 wp-login POST 速率，不看状态码） |
| `wordpress-login` | 300s/3次 | 30分钟 | `fileonly`：只 `touch /run/f2b_block_<ip>` → nginx 把该 IP 全部请求 302 到 **安全验证码页** `/verify/index.html?redirect=<原路径>` |

- 验证页与接口在 `/www/wwwroot/default/verify/`（`index.html`/`captcha.php`/`action.php`/`allow.php`），`limit_req` 超限 429；`/verify/*` 其余路径 403。
- 通过验证后写服务端标记 `/run/f2b_state/f2b_verify_<ip>`，nginx 用 `-f` 判定放行（2026-09-28 起取代原来的 cookie 判定，cookie 可伪造）。unban 时 `fileonly` 会同时删 block/verify 标记。
- 豁免：`$is_admin=1`、URI 以 `/verify/` 开头、`ignoreip`（含 `14.19.168.0/24` 等，见 jail.local）。
- 计数旁路：`/usr/local/bin/fail2ban_count.sh` 把每次封禁写到 `/run/fail2ban_ban_count/`（`<ip>.count`、`<ip>.jails`、`ip_rule_record.log`，含中文"次数/规则"行）——**唯一能看到"哪个 IP 命中哪条规则"的台账**，ipset 只有当前存活项。
- 命中日志三处：`/var/log/fail2ban.log`（jail 判定 Ban/Found）→ `/www/wwwlogs/www.423down.com-access.log`（原始请求，含 444/403/429）→ `/www/wwwlogs/wpcontent_blocked.log`（wp-content 下非白名单 PHP 被 444，单独日志）。

**已实测的四个误封触发点（改规则时优先处理）**：

1. 站内搜索算高危：`/search/shell`、`/?s=shell` 这类 200 正常页，命中 high filter 的 `/shell|/manage|/backend|admin|/feed` 关键字 → 60 秒内 3 条就 3 天全端口封禁（`fail2ban-regex` 单行实测 matched）。案例 2026-09-28 17:38 `117.158.214.147`（先看文章/翻页，只因为搜了 shell）。→ **2026-09-28 23:56 已修**（见下）。
2. filter 的 `ignoreregex` 静态资源豁免**失效**：写成 `\.(css|js|ico|png…)$`，而 combined 日志行尾是带引号的 UA，`$` 永不匹配 → 任何 444（含 `/favicon.ico`）都计入 medium。案例：`221.210.197.30` 用 okhttp 请求 favicon.ico 被 444 ×12 → 封 12h。→ **2026-09-28 23:56 已修**。
3. `/feed|rss|atom` 被 nginx 统一 403，同时 high filter 又拿它当攻击特征 → 正常 RSS 客户端 3 次即 3 天封。案例：`222.190.234.209`（11:22 试 `/feed`、`/feed.json`、`/blog/feed`）。→ 已人工解封。**2026-09-30 01:51 已治本**：feed 类关键字从 high 移除（见下），并解封复发案例 183.33.70.228、183.214.222.172（均为"读 3 页文章→连点 /feed /rss /rss.xml→封3天"模式）。
4. high/medium 的 iptables 规则**不限端口**（`INPUT_direct -m set --match-set f2b-wordpress-high src -j REJECT`，没写 `-p tcp --dport`）→ 一次封 = 整台机（含 SSH）不可达；运营商大内网（CGNAT，移动/联通/韩国 SKB 常见）下是一批真人一起中招。→ **2026-09-29 00:06 已修**：新 action `firewallcmd-ipset-web` 只封 80/443，`jail.local` 里 high/medium 已切换。`wordpress-bruteforce` 仍是全端口（未动）。

**分析工具**：`bash /tmp/waf_hit_analysis.sh <YYYY-MM-DD> <起小时> <止小时>`（源文件 `scripts/waf_hit_analysis.sh`，只读，上传到服务器 /tmp 跑）。输出含：窗口内各 jail Ban/FOUND 数、被封 IP 画像（是否读过正常内容页）、验证码链路（谁提交并通过）、4xx 命中路径 Top、wp-content 黑名单命中、ipset 现存规模、"被封但今天有 ≥5 次正常内容 200"的误封嫌疑清单+剩余封禁秒数、今日 vs 昨日同文件逐小时独立 IP 基线、两条 filter 自检。

**手动解封单个 IP（属防火墙改动，须先向用户确认）**：
`fail2ban-client set wordpress-high unbanip <ip>`（medium/bruteforce 同理；`fileonly` 类封禁要顺带 `rm -f /run/f2b_block_<ip>`）。
解封后必查三样：① `ipset list <set> | grep -c "^<ip> "` 应为 0；② `php -r` 读 `/var/lib/fail2ban/fail2ban.sqlite3` 的 `bans` 表该 IP 行数应为 0（否则下次重启会 Restore Ban 又封回来）；③ ipset 各集合条数只减不加、`firewall-cmd --direct --get-all-rules` 条数不变、站点仍 200。

**改规则用 reload 还是 restart，看改的是什么**（2026-09-28/29 两次实测）：
- 只改 **filter**（failregex/ignoreregex/阈值）→ `fail2ban-client reload` 就够，ipset 封禁条数前后不变（291/184 保持），日志无报错。
- 改了 jail 的 **action**（换动作文件）→ reload 只跑 actionstop 不跑 actionstart，iptables 规则被摘掉且不报错，变成"名单还在、拦截失效"的空转；必须 `systemctl restart fail2ban`。重启前后各 `ipset save` 一份，起来后核对条数（重启本身不清集），掉了就 `ipset restore -exist -f xxx.save` 回灌。
- `systemctl restart` 只会从 sqlite `bans` 表恢复少量记录（当时仅 8 行 vs ipset 470+ 条），别指望它自动搬名单。
- 改完必查四项：① `fail2ban-client get <jail> ignoreregex|failregex` 是新值；② `iptables -S INPUT_direct | grep <set>` 规则文本带端口限定；③ `ipset list <set>` 的 `References:` ≥1；④ 拿文档保留地址跑闭环 `fail2ban-client set <jail> banip 203.0.113.10` → 查 ipset、`/run/fail2ban_ban_count/ip_rule_record.log`、sqlite `bans` 三处都有，再 `unbanip` → 三处归零；最后 `curl -k --resolve ... https://www.423down.com/` 出 200 且 `/var/log/fail2ban.log` 有新的 Found。
- 效果对照用 `fail2ban-regex <样本文件> <filter路径>`：把备份目录里的旧 filter 当"改前"跑一遍，证明"攻击命中数不变、误判数归零"。

**2026-09-28 23:56 已实施的修改**（备份在 `/www/backup/fail2ban_20260928235318/`）：
- `filter.d/wordpress-high.conf` 第 7 行 failregex 的负向预查开头加了两个豁免：`.*"GET /search/` 和 `.*[?&]s=` → 站内搜索结果页（搜 shell/manage 等含关键词的词）不再算高危攻击。
- `filter.d/wordpress-high.conf` 第 12 行、`filter.d/wordpress-medium.conf` 第 14 行：静态资源豁免从 `.*\.(css|js|…woff)$` 改为 `.*\.(css|js|png|jpg|jpeg|gif|webp|ico|svg|ttf|woff2?|eot)(\?[0-9A-Za-z._=-]*)? HTTP/`（去掉永远匹配不上的 `$`，改为锚在请求行的 ` HTTP/` 处；查询串只允许无 `/` 的字符，防止 `/x.css?u=/phpmyadmin` 绕过）。
- 同时解封 4 个误封 IP：117.158.214.147、222.190.234.209（high）；222.131.3.46、171.82.115.130（medium）。

**仍未修的一个已知缺陷（要改先征得同意）**：
1. ~~`wordpress-medium` 的 failregex 里 `(444|...)` 把 `444` 当子串匹配~~ → **2026-09-29 00:06 已修**。
2. ~~`wordpress-high` 抓不到 `.env` 系列探测~~ → **2026-10-01 18:41 已修**（high 关键字表加 `\.env`，fail2ban-regex 对照 2→9）。

**2026-09-29 00:06 又修了两处**（备份 `/www/backup/fail2ban_20260929000212/`，含改前 ipset 快照 `pre_reload/`、`pre_restart/`）：
- `filter.d/wordpress-medium.conf` 第 8 行 failregex 尾部：`.*(444|/download/|/dl/|/file/).*` → `.*(" 444 |/download/|/dl/|/file/).*`。40k 行日志实测对照：真 444 状态码那组改前改后都是 3905 matched（拦截力没降）；"行内别处出现 444 字样"那组由 177 matched → 0 matched（误判清零）。
- 新增 `action.d/firewallcmd-ipset-web.conf`（照 `firewallcmd-ipset.conf` 派生，**只把 actionstart/actionstop 的两条规则加了 `-p tcp -m multiport --dports 80,443`**，其余 ban/unban/计数器逻辑一字未动），并在 `jail.local` 的 `[wordpress-high]`、`[wordpress-medium]` 各加一行 `action   = firewallcmd-ipset-web`。效果：high/medium 封禁只拒 80/443，不再连带 SSH 22 和宝塔面板端口。`sshd`（只封 22）、`wordpress-bruteforce`（仍是全端口）、`f2b-perm-*`（perm-web 是"除 22 外全拒"）都保持原样。

**2026-09-30 01:51 第三修：high 去掉 feed 类关键字（误封点③治本）**（备份 `/www/backup/fail2ban_20260930015048/wordpress-high.conf`）：
- `filter.d/wordpress-high.conf` 第 7 行 failregex 关键字表：`(/xmlrpc\.php|/feed|/rss|/wp-feed|/atom|(^|/)admin…` → `(/xmlrpc\.php|(^|/)admin…`，即删掉 `/feed|/rss|/wp-feed|/atom` 四项（nginx 已统一 403 feed 路径，扫描器拿不到东西，high 再封只会误伤真人 RSS 客户端，无独特拦截力）。其余关键字一字未动。
- 改后对照（真实日志样本）：feed 类 266 行改前 266 matched → 改后 0 matched；攻击类（xmlrpc/.env/.sql/.bak/phpmyadmin）800 行改前改后均 589 matched，拦截力不变。
- 只改 filter → `fail2ban-client reload` 生效（实测 ipset 159/24/171 前后不变，运行态 `fail2ban-client get wordpress-high failregex` 已无 /feed）。
- 同时解封当日复发的 2 个 feed 误封 IP（183.33.70.228、183.214.222.172）：三查通过（ipset 归 0、sqlite `bans` 表 `ip` 列 0 行、high 159→157 只减不加、站点 200）。注意 sqlite 查询列名是 `ip` 不是 `ipaddr`。
- 09-29 全天 + 09-30 凌晨误封体检结论：网页侧封禁画像全部是扫描器（.env/robots/xmlrpc/wp-json 枚举/wp-login 爆破），"被封且有 ≥5 次正常内容页"仅 1 例且查实为伪装 Chrome 的 WP 用户名枚举工具；独立 IP/小时全天 2074~2981 平稳，无大批量误封。

**坑（这次踩过，必读）**：改了 jail 的 **action**（不是只改 filter）之后，`fail2ban-client reload` 只会执行 actionstop，**不会重跑 actionstart** → 结果 iptables 里 high/medium 的 REJECT 规则消失、集内条目被清空，变成"名单还在、拦截失效"的空转状态，日志里一点报错都没有。正确做法：改 action 前后各做一次 `ipset save <set> > xxx.save`，然后 `systemctl restart fail2ban`（重启不会清 ipset，实测 289/182 条原样保留），起来后若条数掉了就 `ipset restore -exist -f xxx.save` 回灌。只改 filter/jail 参数（如阈值、豁免）才可以用 reload。

**2026-10-01 18:31–18:45 已实施的修改**（备份 `/www/backup/siteops_20261001183157/`，含 4 个 filter、count_scan.sh、站点 conf、主 nginx.conf、D7 functions.php 原件）：
- D7 `functions.php` 尾部新增 `phpmailer_init` 钩子（`$pm->Timeout = 10`）：治注册邮件同步等 SMTP（慢日志实锤卡死 wp-login worker，案例 10-01 10:06 erphp-email-register→SMTP.php stream_select）。`php -l` 通过。
- 站点 nginx conf 两处：① go_limit 所在 location `burst=5`→`burst=10`（速率 3r/s 不动，只放宽连点）；② 新增 `location ~* \.php/ { log_not_found off; return 404; }` 消除 "Primary script unknown" FCGI 噪音。**位置必须在 `location ~ ^/(vip|admin)` 之前**（放后面会被 vip|admin 先截走，实测踩到）；`\.php/.` 写法匹配不到 `/baker.php/` 这种斜杠结尾，必须用 `\.php/`（也踩到）。改后 /baker.php/、/admin.php/2P.php、/index.php/wp-json 全 404 不落 php-fpm，首页/文章/verify/wp-login/wp-admin 行为不变。
- fail2ban 只改 filter → reload 生效。① login/bruteforce/medium/high 的 wp-login 路径 `/` 放宽为 `/+`：治**双斜杠绕过**（`POST //wp-login.php`，案例 51.79.230.178 两天 11488 次、login/bruteforce 零命中）；② high 关键字加 `\.env`（旧缺陷②补上，对照 2→9 全抓）；③ login ignoreregex `webp,ico` 逗号笔误改竖线。fail2ban-regex 对照：double 样本 login 0→29、bruteforce 0→29；单斜杠 POST 30→30 不降；真人 clean 样本 0→0 不误伤。
- `/usr/local/bin/fail2ban_count_scan.sh`（V9.6）新增"24h 内命中 ≥RECENT24_MIN(默认3) → perm"：循环内先算 ip_rule_record.log 近 24h 条数；REQUIRE_MARK 闸门加 `-lt $RECENT24_MIN` 旁路（惯犯不再因"当前无 block 文件"漏网——这是 165.232.167.42 撞墙 38 次没进 perm 的根因）；最终判定前加 RECENT24≥3→NEED_BAN=1（纯中低危仍被规则2先跳过）。实测首轮恰好 4 个惯犯进 f2b-perm-web（134.122.31.30、165.232.167.42、51.79.218.106、59.152.126.179），无网段封禁、无自家 IP。注意该脚本全量跑 7000+ .count 约 1.5 分钟（每 IP 扫一遍 4.8 万行台账）。
- 核查确认：`ignoreip` 从未包含 Cloudflare 出口段（104.16-104.28/172.71/162.159 等），**保持不豁免**——本次就有攻击者藏在 CF 出口（104.28.218.135 刷 wp-login）。
- 闭环测试四项全过：banip 203.0.113.10 → ipset/台账/sqlite 三处均现 → unbanip → 三处归零；iptables INPUT_direct 规则 2 条、perm direct 规则 3 条挂载完好；本机 curl 首页/文章 200。

**2026-10-01 19:10–19:25 安全审计后续处置**（同备份目录 `/www/backup/siteops_20261001183157/`，新增 wp-config.php.bak01、debug.log.moved、go.php.bak.*、wp_user_97219_backup.sql）：
- 删除了管理员账号 `1111333333`（ID 97219，2024-06-10 注册，用户确认为配合调查时的临时号），删除前 11 行数据（users+usermeta）备份成可直接 INSERT 的 SQL。现在管理员仅 zd423。
- 新建 `wp-content/mu-plugins/`（自动加载、主题插件升级不丢）：① `cve-2026-87902-guard.php`——parse_request 优先级 0，unset pagename/page_id/p/name/template/page_template 里含 `..` 或 NUL 的值；② `quiet-deprecated.php`——`error_reporting(E_ALL & ~E_DEPRECATED & ~E_USER_DEPRECATED)` 止住 erphpdown/mobantu.php 的 mcrypt 警告刷 debug.log（用户明确不升级 erphpdown）。
- nginx 站点 conf 261-264 行（`.php/` 块后连插）：`\.php/`→404（已有）、`\.(log|ini|sh|swp|swo|sql\.gz)$`→444、`\.bak(\.|$)`→444（治带时间戳后缀的 bak 变体）、server 级 `if ($args ~* "\.\.|%2[eE]%2[eE]") return 444;`（CVE-2026-87902 的 nginx 兜底；conf 里 139/148 行本来就有 SQLi/XSS args 拦截块，写法可参考）。实测 444 表现为 curl 连接被直接掐断（http_code=000）。
- wp-config.php 第 159 行加 `define('DISALLOW_FILE_EDIT', true);`（插在最后一个 define 之后，备份 bak01）。
- debug.log（10MB，含全站路径/插件内部报错细节）与 go.php.bak.20260930020733 已移出 webroot 存到备份目录。
- 评论排查结论（只读）：269392 条已通过、1832 条随文章删除、0 条待审、未通过带外链 0 条；高危词抽样逐条核过均为技术语境误命中（"上访"实为"访问"子串）。边界样本：#219021（2016 年谈 p2psearcher 政治关键词史）、#182229（骂魔方管家语气重）——留站长自判。
- CVE-2026-87902 背景：9.2 分未授权 pagename 路径穿越 LFI→RCE，影响 WP 4.7.0–7.1.1（官方修复线 7.1.2/7.0.6/6.9.9/6.8.10），本站 WP 6.2 不升级，用上面 mu-guard+nginx+`register_argc_argv=Off`+无 PEAR 四道断链；补丁官方未公开具体 diff（截至处置时），详情页只泛称"查找页面模板过程"。
- **坑（本次踩）**：WP batcache 会把 CLI bootstrap 的整段 echo 输出当"页面"缓存到 memcached 的**空 REQUEST_URI key**，后续任何 `php -r/脚本 require wp-load` 都会先吐出这份旧输出然后退出（真实脚本代码根本不执行，输出看着像"串台/回放"）。真实访客拿不到（key 不同，公网三页实测干净）。**以后所有 CLI 引导脚本必须开头加**：`$_SERVER['REQUEST_METHOD']='POST'; $_SERVER['REQUEST_URI']='/cli-guard'; define('DONOTCACHEPAGE', true);` 再 require wp-load；脏了用 `printf 'flush_all\r\nquit\r\n' > /dev/tcp/127.0.0.1/11211` 清。
- mysqldump 用 root+wp-config 密码不通（面板 root 密码不在 default.pl，wp-config 里是 DB_USER 非 root）→ 单表行备份改用 PHP/wpdb 导出 INSERT。

**2026-10-01 19:40–20:05 登录验证码换血 v5.2 + 注册邀请码核实**（备份 `functions.D7.pre-lv52.php`、`erphp-email-register.pre-lv52.php` 在同 siteops 备份目录）：
- **背景认定**：v5.16"图形码"= 客户端 canvas 自画自报，服务器 `check_login_verify_50` 只查 transient 存在即放行（**从不比对码**，且不区分大小写比对都在前端做）；浮层 3.7.3 滑块=`slider_pass=1` 客户端令牌。两条通道都是纸糊，日志里 wp-login 万级 POST 爆破全从这里过。
- **新实现**：`wp-content/mu-plugins/login-captcha-52.php`——服务器 random_int 出题 4 位、SVG base64（无 GD 依赖）、transient key=md5(IP+UA+wp_hash('lv52'))、TTL 120s、`lv52_verify_submit()` 一次性（对错都销毁）。取码端点 `/wp-login.php?lv52_get=1`（login_init 钩子，**必须带 `isset($_GET['lv52_get'])` 条件守卫**）。wp-login 页 login_footer 注入码行；wp_authenticate_user 仅在 `$_POST['wp-submit']` 且 action=login 时强制。functions.php 侧：v5.16 五钩子注释停用（函数体保留=回滚一键）；浮层 handler `slider_pass` 校验替换为 `lv52_verify_submit()`（缺函数=fail closed），滑块 DOM 缩进隐藏占位（老 JS 引用不崩、`slider-tip` 留作提示行），提交按钮去 disabled，`resetSlider()` 去掉禁按钮三行（否则开弹窗就锁死），错误 case `slider_error` 文案改图形码。
- **实测（本机 curl，UA 固定）**：wp-login 对码+错密码 → 走到"用户不存在"校验（闸门放行）；重放同码 → "图形码"安全错误页；浮层对码 → `login_error=invalid_username/incorrect_password`，错码 → `login_error=slider_error`；对码真登录 → 302 + wordpress_logged_in cookie ✓。测试账号已全部清除，管理员仅剩 zd423。
- **踩坑（都写死为教训）**：① 站有"未登录禁访 wp-admin"→ admin-ajax.php 对游客 302 到 wp-login，**任何游客取码接口不能走 admin-ajax**；② 我把 lv52_ajax 无守卫挂 login_init → 登录页整页输出 JSON（约 5 分钟，已修复；login_init 钩子必须条件短路）；③ patch 脚本单引号 PHP 串里 `\n` 是字面量（写进了 functions.php 的 HTML），要么双引号要么事后单独修；④ 站点空 Referer 的 POST 被 nginx 防盗链规则 403（curl 测表单必须带 `-e 站点URL`）；⑤ wp-login 连打测试请求会撞 login_limit 3r/s 出 429 空页（假阴性），测试节奏 sleep 2-3 秒；⑥ batcache 仍会 CLI 回放旧输出（见上节），核对库内状态用 mysqli 直连（wp-config 三字段用 `define\(\s*'DB_NAME',\s*'([^']+)'` 精确匹配，松散 `[^a]+` 会把密码串抠成用户名）。
- **注册邀请码结论（更正）**：生产链路**早已强制**——ashuwp-invitaion-code 的 `registration_errors`（字段名 `invitation_code`）空码即拒；erphp-email-register 里那段"留空跳过"读的是 `invite_code` 字段=死代码。探针实测：空码注册 200 页面含"邀请码"报错、无用户产生。今日 1054 次注册尝试仅 5 入库，闸门有效。erphp 的 captcha.php 空壳（`echo 0`）与 .bak 属历史遗留，无功能影响。

**2026-10-01 20:10–20:30 v5.2b 修正（同会话两轮返工，全记录）**：
- 用户反馈 1"浮层没有验证码"：site_speed(memcached,15min)在喂改造窗口期的旧 HTML 快照 → `printf 'flush_all\r\nquit\r\n' > /dev/tcp/127.0.0.1/11211` 刷掉即好。**教训：凡改主题 HTML 结构，交付前必须 flush memcached 并从公网无参数路径复验**（site_speed white.uri 里有 `^/wp-login\.php` 直通，登录页不受缓存影响，受影响的是首页/文章页浮层）。
- 用户反馈 2"点登录/注册直接提交、不弹窗"：交互回退成 v5.2 内嵌行。**v5.2b 改弹窗式**：login_footer 输出 mask+img+input，JS 拦 loginform/registerform/lostpasswordform 的 submit → `?lv52_get=1` 取图 → `?lv52_verify=1` POST 比对 → 发放一次性 lv_token(300s) → 表单带 token 重提。mu 文件整体重写覆盖。
- **重大认知修正（旧版和新版 v5.2 共有的洞）**：`wp_authenticate_user` 过滤器只在用户名+密码核查**通过之后**才执行（核心 `wp_authenticate_username_password` 会用 get_user_by 结果直接覆盖上游 WP_Error，authenticate 链 P5 挂闸门同样被吞——实测 apply_filters 返回 invalid_username）。**结论：验证码闸门挂 wp_authenticate_user/authenticate 都拦不住错密码流量**。正解=前置 `login_form_login` 优先级 1 闸门：`lv52_consume_token()` 不过就 unset $_POST 提交字段+置 $GLOBALS['lv52_fail']，wp_signon 不执行（零枚举信息）；`login_message` 过滤器出中文错误；`wp_login_errors` P5 清掉 core 的英文 empty_username/empty_password 噪音；找回密码同法挂 `login_form_lostpassword`。
- 最终断言（公网 curl）：无令牌 POST → 页面仅"请完成图形码验证"（英文错误 0、密码核查提示 0）；过码+对密码 → 302 + wordpress_logged_in；令牌重放 → 拒。测试号 lv52tmp(ID 98192) 已 mysqli 删除。
- 本机侧工具坑：ssh_mcp 连接器一度无响应（MCP -32603），备用通道 git-bash `ssh myserver`/`scp`（`~/.ssh/config` 已配）可全程顶上；pq 交换警告无害。ssh 内嵌复杂引号的 printf 易炸，一律本地写文件→scp→远端执行。

**2026-10-01 20:35–20:50 移动端假码下线 + 空字段中文化 + 已核评论批量删除**：
- 移动端登录页还是老验证码：wp-mobile-x 的 `themes/mobx-default/functions.php` 内嵌了一套 **v5.16 完整复制品**（同名函数+6 钩子）。处理：注释其 5 条钩子行（备份 `mobx-functions.pre-lv52.php`），mu 的 v5.2b 弹窗自动覆盖移动端登录页（login_footer 通用）。移动 UA 实测：旧 canvas 0、新弹窗 2 ✓。以后升级/改 wp-mobile-x 会带回老钩子，需复查（登录页出现 verifyCanvas-50 即回潮）。
- 空字段英文提示：WP 6.2 zh 包缺 empty_username/empty_password 两条译文（历史上中文来自 check_login_verify_50 的自定义报错，该假检查已删）。mu 的 `wp_login_errors` P5 统一中文化；form_gate/lostpw_gate 空字段直接放行交 core；弹窗 JS 空字段不拦提交。实测输出"错误：请输入用户名称"✓。
- **批量删除已核评论（215 条清单）**：连带子回复实删 309 条，全行备份 `comments_deleted_20261001.sql`（218KB，INSERT 可回灌）。踩坑三连，都是硬教训：
  1. **wp_comments.comment_approved 的 DB 值是 `'1'`（不是 `'approve'`！）**——重算 comment_count 的 SQL 用错值把 94 篇计数清零（评论本体无损）。正确：`update wp_posts p set comment_count=(select count(*) from wp_comments c where c.comment_post_ID=p.ID and c.comment_approved='1') where p.post_type='post'`（全量 95 行修复，575=4646、791=4196 复核 ✓）。
  2. **memcached 会在 flush 后死掉**（20:37 发现 11211 拒绝连接，systemctl restart 恢复）——它是 lv52 令牌 + batcache + site_speed 三家的共同底座，挂了=登录链全断。诊断口诀：取码/令牌异常先 `ss -tln | grep 11211`。
  3. 改完 DB 里计数后页面仍显旧值 → 边缘缓存吃了刚生成的坏快照，再 `flush_all` 即恢复；页面 grep"评论："要认头部 `class="comm" style=` 那条（侧栏热榜同名），别拿 head -1 下结论。

**改完必查四项**：① `iptables -S INPUT_direct | grep <set>` 规则文本带端口限定；② `ipset list <set>` 的 `References:` ≥1（规则真的挂了）；③ 拿文档保留地址跑一次闭环 `fail2ban-client set <jail> banip 203.0.113.10` → 查 ipset/`/run/fail2ban_ban_count/ip_rule_record.log`/sqlite `bans` 行，再 `unbanip` → 三处都归零；④ `curl -k --resolve www.423down.com:443:127.0.0.1 https://www.423down.com/` 出 200，`tail /var/log/fail2ban.log` 有新的 Found。

**2026-10-01 22:05–22:35 前端体验：右侧栏吸顶 + 紧凑页脚**（备份 `/www/backup/siteops_fe_20261001220838/`：style.css、footer.php、footer2.php、header.php）：
- **吸顶**：style.css 尾部追加 `.sidebar{position:sticky;top:70px;max-height:calc(100vh - 84px);overflow-y:auto;overscroll-behavior:contain;z-index:1}`（头部 fixed 高 56px+14 间距；z 低于头部 999）。sticky 直接加在 float 列上实测有效（Chrome 支持 float+sticky）；小工具超高时栏内自滚，不再截断。四套 sidebar*.php 同用 `.sidebar` 类，一处 CSS 全覆盖；移动端断点本就 `display:none` 不受影响。
- **页脚**：footer.php（首页/归档等 get_footer 链路，含 11 条友链）与 footer2.php（index/single/page 链路，仅版权行）重写为 `.footer>.footer-inner>.footer-links+.footer-copy` 结构；CSS 深蓝 `#00234C` 与头部同色、12px 小字、inner padding 14px，实测 inner 高 54–83px。**footer.php 尾部保留原多出的那个 `</div>`**——它不是垃圾，是闭合 header.php 打开的 `.wrapper`（首页源码 div 85 开 84 闭，删掉会留 unclosed）。footer2.php 历史上就不闭 wrapper，浏览器隐式闭合，维持原样。
- **header.php 第 247 行** style.css 链接加 `?v=20261001` 防浏览器强缓存（该 link 无版本号，用户不 Ctrl+F5 会一直吃旧样式）。
- **缓存层修正（重要）**：站其实有两层页缓存——① batcache→memcached（flush_all 可清）；② **site_speed lua 边缘缓存→`lua_shared_dict site_cache`（nginx 进程共享内存，flush memcached 清不到它！）**，TTL 900s，`force.ext` 连 css/js 都缓存。清 ② 的办法：重启 nginx（reload 不清 shm）。本次改完 HTML 后公网仍吐旧快照、且 size 一模一样，就是 ② 在作怪。
- **nginx 重启坑**：`systemctl restart nginx` 是 LSB 脚本，stop→start 有 pid 竞态，会报 "nginx (pid xxx) already running" 假失败并把服务留在**停止**状态（本次站点中断约 1 分钟）。恢复：`/etc/rc.d/init.d/nginx start` + `systemctl reset-failed nginx`。以后重启 nginx 后必须 `ps aux|grep 'nginx: master'` + 公网 curl 双确认。
- **验证方法论**：用户浏览器装有翻译类扩展会往 `.footer-copy` 注入 35KB `.google-anno-skip` 节点，把页脚 rect 撑到 3084px（假象）；判断布局问题以**源码 div 配对计数 + footer-inner 实测高**为准，别信被扩展污染的 `.footer` 整体 rect。首页(home.php→get_footer)与文章页(single→footer2)都截图确认：侧栏滚到任何深度都钉在 header 下 70px，页脚一行 54px 紧凑深蓝。
- **顺带发现（未处置，留站长判断）**：文章 16499"飞球直播…"带 `custom_redirect` postmeta，302 到 `https://down.fqzb180.com/?agent=1&app=423down`，该外部域名 TLS 证书无效（浏览器报 ERR_CERT_AUTHORITY_INVALID）；16906 附件文件名也含 fqzb。非入侵（代码/库/options 均无 fqzb 字符串，来源就是这两条 postmeta），但"看球神器"类文章+坏证书外链，建议站长自查该帖是否自己发的。
- **v2 修正（用户反馈）**：① 深蓝页脚不要 → 恢复原配色 `#F3F3F3` 底/黑字，只保留"紧凑压高度"；右侧那片"深蓝"其实是页脚元素被浏览器翻译扩展注入撑高后透出来的底色，配色回灰后无感。② 小工具"宽度显示不完整"根因：`.widget` 实际渲染宽 **394px**（>栏宽 380），v1 的 `overflow-y:auto` 产生 6px 滚动条后按 padding-box 裁切 → 右边裁掉。修法：`.sidebar{box-sizing:border-box;width:406px;padding-right:26px}`（406−6 滚动条=400 可视 ≥394），float/margin-left:-380 不动，视觉位置与改造前一致。**教训：给浮动栏加 overflow 前先量子元素实际渲染宽，widget 体系普遍比栏宽出 14px**。③ 样式链接版本号已递进到 `?v=20261001b`（header.php:247），以后改 style.css 记得继续进位。
- **v3→v4 再返工（重要结论）**：v2 的 `width:406` 破坏了 `.sidebar{float:left;margin-left:-380px;width:380px}` 的"负边距+等宽=0 占位"把戏（占位变 26px 放不下 → float 掉到下一行被 -380 甩到屏幕左外），**该主题右栏宽度/overflow 一律不能动**。v3 改 `sticky;bottom:15px`（底部吸附、随页滚动逐条露小工具）：文章页生效、**首页同 CSS 同结构下 Chrome 就是不吸**（连合成测试 div 都不吸，top 约束正常），根因未定位、不再纠缠。**终版 v4 = JS 跟随**：`mu-plugins/sidebar-follow.php` 挂 wp_footer，scroll 时 `translateY(min(vh-15-自然底边, wrapper底-自然底))`，行为=底部贴视口下沿 15px、随页滚动、各页统一；style.css 里 `.sidebar` 规则全部撤除，只留页脚紧凑样式（用户要求：页脚/右侧恢复原浅灰 #F3F3F3+黑字，不要深蓝）。测试钩子：脚本暴露 `window.__sbFollow()` 可同步强制测量（隐藏标签页 rAF 冻结，自动化验证必须直调）。样式版本现 `?v=20261001d`。

**2026-10-01 23:05–23:25 评论徽章精确系统版本 + 最新评论小工具 12h 缓存 + 验证码无感预取**：
- **UA-CH 精确版本（#15）**：`mu-plugins/ua-precision.php` 在评论表单（D7 comments.php 是手写表单，标准 comment_form 钩子不触发，**必须挂 `do_action('comment_form',$post->ID)` 那个点**）注入隐藏域 `ua_pv`，JS `navigator.userAgentData.getHighEntropyValues(['platformVersion'])` 填值，`comment_post` 存 comment_meta `ua_pv`。`plugins/wp-useragent/wp-useragent-detect-os.php` Windows 分支优先读该 meta，major 映射 UniversalApiContract：13=21H2、14=22H2、15=23H2、16=24H2、17=25H2、18=26H2；**Win10 2004–22H2 全部=10，浏览器侧无法再细分（微软限制，如实告知用户）**；无 meta 的旧评论走原启发式。旧启发式"Edg≥96→Win11"是错的（Edge96+ 也跑 Win10）——本机 Qoder 内置浏览器 platformVersion=10.0.0 证明站长机器其实是 Win10，旧徽章误报 Windows 11。
- **插件坑**：detect-os 的 Windows 分支是一条大 if/elseif 链，**插新分支必须保持链结构 `if($ua_done){}elseif(...)`**；我第一版用 `if(!$ua_done){内嵌if/elseif}` 包了一层，外层 elseif 链继续级联到通用 `Windows NT` 分支把 version 覆盖成 'NT'——CLI 渲染验证才发现。验证法：CLI 设 `$GLOBALS['comment']` + `apply_filters('comment_text',...)` 看徽章 HTML（评论列表前台要登录可见，公网 curl 验不了）。
- **最新评论小工具（#16）**：`themes/D7/widget/widget-comment.php` 旧代码用 `wp_cache_get('my_widget_recent_comments','widget')` **无 TTL**（memcached 30 天不过期、新评论不失效）→ 好几天不更新的根因。改为 `get_transient/set_transient`（key 含 widget_id+instance+`sbx_rc_ver` 选项，TTL 12h），`comment_post`/`wp_set_comment_status` 时 `update_option('sbx_rc_ver', time())` 换 key 即时失效。输出格式 `作者 + Y年n月j日 + 评论了 《标题》`（get_comment_time 本地时区），并修了原代码 `get_comment_author()` 不带参恒取第一条的 bug、去掉 td/tr 非法嵌套。
- **验证码无感显示（#17）**：`login-captcha-52.php` LV52_TTL 120→300；弹窗 JS 页面加载即 `refresh(true)` 预取 dataURI 缓存（pv/pvTs），打开弹窗 `refresh(false)` 用 <240s 的缓存秒显，点图/校验失败才强制换新；`alt=""` 消除裂图 x。D7 浮层同款改造：首次 mouseover/touchstart 预热一次（`{once:true}`），openLoginModal 走缓存。实测：wp-login 未弹窗时 img 已是 dataURI，提交后 30ms 内弹窗带码；首页 hover 预热成功。
- 测试评论 379802 已删（791 计数复原 4197）。备份：`siteops_fe_20261001220838/`（widget-comment、detect-os、login-captcha-52、functions.php 原版）。

**2026-10-02 00:00 移动端悬浮层登录统一（mobx）**：移动端悬浮层在 `wp-mobile-x/themes/mobx-default/functions.php` 的"移动端悬浮登录 1.5.1"段（组件名 `mobileLoginPop`/`slide-bar`，**不叫 loginModal/slider-box**，上轮按桌面组件名 grep 漏判为"移动端无浮层"——搜组件要按行为词全库扫）。改造 9 处：删滑块 CSS/DOM/整段拖拽 JS、按钮去 disabled、`openMobileLogin` 调 `lv52Prefetch` 预热、提交拦截器 `lv52Ask(token→隐藏域 lv_token→submit)`、错误 switch 加 verify_error。**重大补漏：原 `mobile_login_post` 后端处理器是裸 wp_signon 无任何验证码校验（=免验证码爆破口）**，已加 `lv52_consume_token()` 闸门（fail-closed，缺函数即拒）。实测：移动 UA 首页 slide-bar=0、统一弹窗在场、无令牌 POST → 302 login_err=verify_error。备份 `mobx-functions.pre-unify.php`。mobx 的 footer.php 有 wp_footer()，mu 前台弹窗钩子可达。

## 2026-10-02 移动端前端三项（分页/文章间隔/抽屉吸顶）

- **去总页数按钮**：WP 6.2 的 `paginate_links` filter 只作用于单条 URL 字符串，数组/输出级钩子是 `paginate_links_output`（general-template.php:4655）。在 mobx 主题 functions.php 末尾加 `add_filter('paginate_links_output','mobx_drop_last_page_link',10,2)`：正则只删"紧跟 dots 的 total 数字链接"。⚠️ 坑：dots 与 156 之间有换行，必须 `</span>\s*<a`；`.*?</span>` 会跨越中间的 153/154/current-155 把它们一起吞掉（踩过，用 `[^<]*` 限定 dots 内容）。当前页相邻的 total 数字（无 dots 前导）保留，上下页不受影响。首页/分类/搜索页共用 index/category/search.php 的 paginate_links，一次覆盖。
- **文章页间隔**：single.php 上篇/下篇块内联样式 padding:15px→10px 15px、margin:20px 0→8px 0；内联覆写加 `.entry{padding:.5rem 0}`、`.entry-content p:last-child{margin-bottom:0}`。
- **抽屉+吸顶（重要发现：mobx footer.php 内有一套自带 !important 的抽屉样式 + `.active` JS 开关，与 main.js 的 body.menu-on 机制并存）**：改法=①footer.php `.navbar-nav` 块 top:60px→`4.6rem !important`、height:100vh→`calc(100vh - 4.6rem) !important`、开选择器扩为 `.navbar-nav.active, .menu-on .navbar-nav`；②functions.php 新钩子 `mobx_fe_overrides`（wp_add_inline_style 'mobile-x'，enqueue 优先级 10、覆写 20）：`.header` 固定 z100001、`#wrap` padding-top 4.6rem、`.menu-on{position:static;overflow:visible;transform:none}`（中和旧 body 平移冻结，顺带消掉"点外区域只关 active 不关 menu-on 导致页面卡死不滚动"的旧 bug）、`.menu-on .menu-btn` 复位 absolute。style.css 未动（避免 lua 边缘缓存 css 的清理麻烦，覆写全走 inline）。
- **隐藏页签测试假象**：CSS transition 在隐藏 tab 冻结在起始值，getComputedStyle 读到 translateX(-100%) 像没生效——用 `nav.getAnimations().forEach(a=>a.finish())` 后再量；实测 x=0、抽屉顶=header 底、底=视口，全贴合。
- 备份：`/www/backup/siteops_mobfe_20261002001906/{functions,single,footer}.php.bak`；本地归档 `TempWork\423down_20261001_fe\live\mobx-*.{php}`。每次验证都走 memcached flush_all + nginx init 脚本 stop/sleep/start（lua shm 只在停机时清）。

## 2026-10-02 性能优化批（懒加载/jQuery defer/AdSense/存量图/后台评论探针）

- **懒加载根因链**：D7 functions.php:1246 `add_filter('wp_lazy_loading_enabled','__return_false')` 是历史主动禁用；删掉后核心仍不加 lazy——`wp_img_tag_add_loading_attr`（media.php）要求 img 同时带 `src="` `width="` `height="` 三属性，手贴图全没有 → 最终方案=自定义 `the_content` 优先级 11 的 `d7_content_imgs_lazy()`：正则扫 `<img>`，第一张 `loading="eager" fetchpriority="high"`（保 LCP），其余补 `loading="lazy"`。核心 wp_filter_content_tags(p9) 先跑，会给带尺寸属性的图补 srcset/decoding，互不冲突。
- **媒体尺寸**：options medium=800x800 large=1600x1600 medium_large=768x0（原先全 0=不生成中间图）。只影响新上传；要旧图补中间图需重生成工具（未做）。
- **jQuery defer**：header.php:248 `<script src=jquery.js>` 加 `defer`。实测首页+文章页 console 零报错、__sbFollow/lv52/百度统计正常。D7 那套 jquery.js 版本号是 1.3.2（jQuery 本体很老）。
- **AdSense 懒加载**：header.php 原 `async src=adsbygoogle.js` 换成内联加载器：ins.adsbygoogle 进视口(rootMargin 500px)/首次 scroll/pointerdown/keydown/DOMContentLoaded+3.5s 兜底 五触发任一即注入脚本；push 队列天然兼容。**顺带发现并修复 single.php 文章内广告位 pub id 是断的**（`ca-pub-50737749972018` 只有 14 位≠标准 16 位，改为 header 同款 `ca-pub-5073779749772018`）——意味着文章位此前可能一直没有效出广告，需去 AdSense 后台核对历史收入。
- **存量图压缩**：`/tmp/shrink20.sh` 用 ImageMagick（服务器有 convert/mogrify+php imagick）：jpg=`-strip -interlace Plane -resize '1600x1600>' -quality 82`；png=`-strip -resize 1600x1600> -define png:compression-level=9`。先 cp 备份到 `/www/backup/siteops_perf_20261002024146/imgs/`，压后更小才 mv 替换（同名保 URL），chown www:www。top20 里 18 张成功，约省 18MB；2 张 960x1536 png 变体与源同图 SKIP。gif（4.4MB/2.8MB×2）没动（无 gifsicle，动帧有风险）。
- **后台评论列表**：数据量实测 wp_comments=270,927 行、commentmeta=82,178；单查全不慢（COLD `wp_count_comments` 68ms、有 memcached 后 0ms；列表 20 行 2.3ms；索引齐全含 comment_approved_date_gmt/woo_idx_comment_type）。→ 慢点不在 SQL。CLI 模拟 admin bootstrap 会被插件 wp_die（URI 含 /wp-admin 时直接无输出退出），没法离线画像。已装临时探针 `mu-plugins/perf-probe.php`：shutdown 钩子把 edit-comments/comment.php 请求的总耗时/查询数/峰值内存记到 `/tmp/perf-probe.log`（64KB 自截断）。**待用户登录后台刷一次评论列表后读日志定位**；头号嫌疑=后台列表 20 行头像走 `https://weavatar.com/avatar/...` 第三方 gravatar 镜像（wp-china-yes 换的），镜像慢/挂会拖住浏览器 load 事件造成"慢"的主观感受；次嫌疑=heartbeat/admin-ajax。用完记得删探针。
- 本轮全部改动备份在 `/www/backup/siteops_perf_20261002024146/`（functions/header/single .bak + imgs/）。

## 2026-10-02 Brotli 上线 + 后台评论提速诊断（补前一条）

- **Brotli 动态模块**：Tengine 3.1.0 原二进制无 brotli。已用原构建树 `/www/server/nginx/src`（configure 参数照抄 `nginx -V`）+ `--add-dynamic-module=/tmp/ngx_brotli`（git 1.8 不支持 --shallow-submodules，改为手动下载 brotli v1.0.9 源码放 deps/brotli；v1.0.9 布局是 `c/include/brotli/` 不是 `src/c/include`）编出 filter+static 两个 .so → 放 `/www/server/nginx/modules/`，nginx.conf `user` 行后加两行 `load_module`。**configure 前必须 export `LUAJIT_LIB=/usr/local/lib LUAJIT_INC=/usr/local/include/luajit-2.1`**（环境里预置的 /www/server/nginx/luajit 路径是空的）。只 `make modules`，绝不 `make`（不重建二进制零风险）。
- **参数**：vhost `brotli on; brotli_comp_level 5; brotli_min_length 256; brotli_static on; brotli_types text/css js xml json svg...`（不含图片/字体/视频）；gzip_comp_level 6→5；`gzip_static on`。预压：themes/plugins/wp-includes 全部 css/js 生成 `.br`（brotli -q 11）与 `.gz`（**el7 gzip 不支持 -k**，要 `gzip -9 -c f > f.gz`）。实测 style.css 34KB→7.1KB(br)/8KB(gz)，缓存命中的 HTML 也走 brotli 过滤器（X-Cache HIT + Content-Encoding: br 共存）。
- **Cache-Control 去重**：静态 location 里删掉 `add_header Cache-Control "public, max-age=2592000, immutable"`，保留 `expires 30d`（自动生成单条 CC+Expires）✓ 实测图片只剩一条。
- **后台评论列表**：探针实测 edit-comments.php 服务端 971/697ms、~105 queries、12MB 内存 —— 不致命；"慢"主要是每行 2 张 weavatar.com 外链头像拖住浏览器 load。已加 `mu-plugins/admin-avatar-lazy.php`（get_avatar_html 补 loading=lazy）。探针 `mu-plugins/perf-probe.php` 保留备用（数据在 /tmp/perf-probe.log，用完删）。
- ⚠️ **终端显示坑**：ssh_mcp JSON 把文件路径里的 `/` 显示成 `-`（`uploads/2023/11/xx.jpg` 看着像 `uploads/2023-11-xx.jpg`），排查路径时别被骗——用 `ls $U/2023/11` 分段验证。
- 备份：`/www/backup/siteops_perf_20261002024146/`（nginx.conf.bak、www.423down.com.conf.bak、imgs/、三个 D7 文件）。

## 2026-10-02 后台用户列表 注册IP/最后登录 修复

- 根因两条：① 记录代码原来写在 **D7 主题 functions.php**（wp423_log_ip/wp423_save_login_info）——手机端（wp-mobile-x 切主题）注册/登录时 D7 不加载，signup_ip 从不写入，last_login 只剩 wpjam-user 写的时间戳（wpjam 列渲染"最后登录"读的就是这个）；② 就算在桌面端，`user_register` 上 prio=10 有 `auto_login_new_user`（erphp 注册后自动登录，内部 redirect+exit），把 prio≥10 的钩子全部腰斩——所以注册 IP 必须挂 **prio 2**。
- 修复：新建 `mu-plugins/user-ip-logger.php`（全主题生效）：user_register prio=2 写 `signup_ip`（uilog_client_ip：X-Real-IP→XFF首段→REMOTE_ADDR，filter_var 校验）；wp_login prio=20 写 `last_login`=time()（与 wpjam 显示格式对齐）+ `last_login_ip`。D7 functions.php 删掉两个旧钩子块，`wp423_get_ip_area()` 重写为带缓存版（option `wp423_ip_area_cache`，>400 条截半，ip-api.com 每 IP 只查一次——原来每屏 40 次外呼也是后台慢源之一）。
- 历史用户 signup_ip 无法补录（当时没存），列显示"无"属正常；"从未登录"用户显示"无"也正常。
- 验证：CLI 建临时号→signup_ip=REMOTE_ADDR ✓→登录模拟 last_login 时间戳+ip ✓→归属地缓存 ✓→测试号已删。备份 functions.php.pre-ipfix.bak。

## 2026-10-02 移动端抽屉遮挡登录弹窗修复

- 现象：抽屉（.navbar-nav，在 header 内，header z=100001 形成层叠上下文）打开时点"登录账号"，`#mobileLoginPop`（z=99998）被压在抽屉下面。
- 修复（mobx 主题 functions.php 两处）：① `#mobileLoginPop` z-index 99998→**100005**（高于 header 100001、低于 lv52 验证码弹窗 1000000，弹窗顺序=登录窗在下、验证码在上）；② `openMobileLogin()` 开头先关抽屉：`body.classList.remove('menu-on')` + `.navbar-nav` 去 `active` + 移除 `.navbar-on-shadow`。备份 `mobx-functions.pre-loginz.bak`（siteops_perf_20261002024146）。
- 验证：移动 UA curl 确认两处落地；浏览器 file:// 预览确认点登录后 menu-on/active 均被摘除、pop display:flex、z 100005>100001。

## 2026-10-02 主题函数分层与 functions-common.php（重要架构）

- 手机 UA 的前台请求**完全不加载** `themes/D7/functions.php`，只加载 `plugins/wp-mobile-x/themes/mobx-default/functions.php`（实测 `get_stylesheet()=mobx-default`、D7 独有函数不存在）；wp-admin / xmlrpc 请求永远加载 D7。
- 三层落点规则：两端前台都要跑的代码 → `plugins/wp-mobile-x/themes/mobx-default/functions-common.php`（插件 `class-mobile-x.php` 在 `wp_is_mobile()` 判断**之前**就 require，桌面+手机前台+wp-login 都加载，**后台不加载**）；只后台跑的 → D7 functions.php；与主题无关、全场景（含后台）都要跑的 → `wp-content/mu-plugins/`。
- 2026-10-02 已完成整合：`functions-common.php` 36 个函数（反广告、图片懒加载/自动alt、meta 关键字描述、防镜像、站点地图蜘蛛门禁、评论防刷/防冒充、封禁相关文案、登录注册文案、搜索伪静态 301 等）；`mu-plugins/ban-login-guard.php` 提供 `lxtx_rc_authenticate_user`（修复手机 UA 登录绕过封号校验）；两份主题文件删掉对应副本与 ~270 行 LV52 死验证码块；移动端 `login_err` 反射型 XSS 已修（sanitize_text_field + esc_js）。
- **上线顺序坑**：必须"先替换 D7 与 mobx 两份 functions.php，最后再放 functions-common.php"。反过来的话，中间窗口里旧主题文件与 common 同名函数并存，线上会刷 `Cannot redeclare ...` 致命（实测 17 条）。回滚：`/www/backup/theme-refactor-20261002102652/`。
- 清网站加速缓存可以不走面板：`/www/server/panel/pyenv/bin/python -c "import sys; sys.path.insert(0,'/www/server/panel/plugin/site_speed'); import site_speed_main as m; print(m.site_speed_main().clean_cache({'site':'www.423down.com'}))"` → `{'status': True, 'msg': '缓存已清除!'}`。
- 验证套路：写一个临时 `qoder-check-v1.php` 放站点根（require wp-load + `has_filter(...)`），用 curl 分别带手机/桌面 UA 打它，**打完立刻 rm**；比 CLI 探针更接近真实 FPM 环境。

## 2026-10-02 nginx 体检与修复要点（改这套配置前必读）

- **fd 上限真凶**：`/etc/init.d/nginx` 第 25 行写死 `ulimit -n 8192`，systemd 单元是 sysv-generator 造的（`LimitNOFILE=4096`）。配置里 `worker_rlimit_nofile 51200` / `worker_connections 51200` 全是摆设。改 init 脚本后必须 **restart**（reload 不改主进程上限）。复核：`grep 'Max open files' /proc/$(cat /www/server/nginx/logs/nginx.pid)/limits`。
- **宝塔白名单文件是死配置**：`/www/server/panel/vhost/whitelist.conf` 只有 allow 无 deny → include 进 server 块后不产生任何效果（含"DNSPod 监控已放行"的错觉）。真要豁免用 http 级 `geo` + 规则里引用变量。
- **状态页**：`phpfpm_status.conf` 原来只有 `allow 127.0.0.1;` 无 deny → 外部用 `Host: 127.0.0.1` 就能取 `/nginx_status`、`/phpfpm_74_status`。已补 `allow ::1; deny all;`。
- **referer 规则两个坑**：只豁免 GET → 无 Referer 的 HEAD（外部监控）一律 403；无 Referer 的 POST 一律 403 → 支付异步通知会静默掉单且 PHP 侧无日志。已改 `~ ^(GET|HEAD)$` 并给 `/wp-content/plugins/erphpdown/` 放行。
- **location 不匹配查询串**：`location ~* /index\.php\?s=` 永不生效（实测 8 连击零 429）。搜索限流要挂 `location ^~ /search/`。`location ~* (feed|rss|atom)` 是子串匹配会误杀 `/feedback`、`/atomcode.html`；`?feed=` 要用 `set $block_feed` + `/wp-admin/` 豁免写法，否则后台"导出 RSS2"被挡。
- **`/xmpcreate/xml.php`**：既是 `rewrite ^/sitemap.xml$ … last` 的内部目标，又是每日 00:05 CLI 任务（`/www/server/cron/c0207de167f8814087333e4e5b74bd73` → `generate_sitemap.sh` → `php xml.php > sitemap.xml`）的实体。已加 `location ^~ /xmpcreate/ { internal; }` 断公网直连（直连会跑全站查询并覆写 sitemap），CLI 与蜘蛛取图均不受影响。
- **go.php 策略变更**：`/www/wwwroot/www.423down.com/go.php` 的 `$is_internal` 由"必须有本站 Referer"改为"默认允许，仅外站 Referer 判盗链"，解决微信/TG/书签直接点跳转被 403。
- **限流阈值现状**：`verify_page` 5r/s（验证页 burst 10、验证码图 burst 15）、`comment_limit` 300r/m、`verify_action` 10r/m 不变（防爆破）、`/search/` 3r/s burst5 + `limit_conn perip 4`。`client_max_body_size` 已提到 50M 与 PHP 对齐；`keepalive_requests` 1000；`open_file_cache` 已启用。
- **仍未决**：888 端口 phpMyAdmin 对公网开放（HTTP 明文 + 该 server 无 access_log）；PHP/site_speed 仍优先读 `X-Real-IP`/`X-Forwarded-For`，而站点实际无反代 → 这两个头可被访客伪造。
- 改配置固定流程：`cp -a` 到 `/www/backup/nginx-fix-<时间戳>/` → 用 `/tmp/*.php` 脚本做 str_replace 并断言命中次数 → `nginx -t` → 优先 reload（只有主进程级参数才 restart）→ 双端 curl 回归 + 看 error.log。

### 2026-10-02 第三轮：map 合并 if、分 location 超时、限流阈值（含两个 nginx 语法坑）

- **坑一：`location = /xxx.php { include enable-php-74.conf; }` 直接语法报错** —— nginx 不允许在**精确匹配** location 里嵌套 location（报 `location "[^/]\.php(/|$)" cannot be inside the exact location`）。要给单个 PHP 入口设超时，用正则 location（`location ~ ^/wp-cron\.php$`）或写进已有的前缀 location（如 `^~ /wp-admin/`）。正则父级里嵌套 include 的 location 是允许的（erphpdown 白名单那批就是这写法）。
- **坑二：`limit_conn`/`limit_req` 池只能在 http 级定义**，站点里只能引用。放宽阈值优先改已有池的 `burst`，别新建 zone。
- 现状：`wp-login` 30s、`wp-cron` 30s、`/wp-admin/`（含 admin-ajax）120s，其余仍 http 级 300s；`vip|admin` 块已加 `(/\|$)` 边界。
- 限流实测基线（放宽后）：17:00 之后真实访客 429 仅 1 次。**wp-login 的 3r/s+burst2 不要放宽**——它的 429 特征是"8 个 IP、单 IP 最多 19 次"，是爆破。
- if 合并：新增 http 级 `/www/server/panel/vhost/nginx/zz-waf-map.conf`（`$waf_admin_hint`、`$waf_inject`、`$waf_feed_arg`），站点 if 从 40 降到 33。要点：map 键可以是 `"$a|$b"` 复合串；`set $x $mapvar;` 后再用 if 做豁免覆盖；管理员判定必须保留"URI 在 /wp-admin/ 下"这个条件（只认 cookie 会把全站豁免打开）。
- 复测真值表要带"能命中原规则"的载荷：`?a=union+select`（`+` 才算空白类，`%20` 不算）、裸 `<script>`；`select+1+from` 本来就不匹配，别当成回归。`/wp-login.php?action=logout` 的 403 来自 WordPress `wp_die`（响应体是 HTML），不是 nginx。
- 澄清两个常见担心：① `/xmpcreate/xml.php` 加 `internal` 不影响每日 00:05 的 CLI 生成（`generate_sitemap.sh` 走 `php` 命令，不经 nginx）；② 关 888 端口不影响 mysqldump 备份与 gdrive 上传（gdrive 里的 `localhost:8080` 是 Google OAuth 回调），只影响面板"数据库→管理"打开 phpMyAdmin。
