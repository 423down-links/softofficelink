# ssh-site-maintain 技能包 · 安装与使用说明

本包 = **一个技能**（`ssh-site-maintain`）+ **4 个 MCP SSH 连接器**，用于管理远程服务器 / WordPress 站点。
（免密接入、命令执行、文件传输、主题插件审计、日志分析报表、宝塔/nginx、Fail2ban 封禁管理 + 正则误伤审计、423down 服务器专用档案、备份规范）

> **v20261010 审计版**（在 v20261003 基础上全面审计）：
> - 修复：fail2ban MCP 过期提示、analyze-log 把 `-` 计入 referer/UA 榜、bootstrap-key 验证脆弱拼串、SKILL.md 黑名单描述失实（ssh-native 实际无黑名单）；
> - 加固：黑名单补 `halt/poweroff/sysv 停服/mysqladmin shutdown`；register-host 输入白名单校验；
> - 去冗余：删技能内重复 `mcp.json` 与 4 个 probe specs；node_modules 评估后不动（可清仅 312KB）；
> - 补漏：e2e 回归 4→7 项（新增 3 个生产启动脚本 smoke）、归档补 `hosts.json`、waf 脚本空归档兜底。
>
> **v20261003**：
> - 已把原独立技能 `fail2ban-regex-audit` 合并进主技能 §3.8；
> - 已把电脑端旧技能 `423down-ops` 的高价值内容并入（`references/server-map.md` + `waf-hit-analysis.sh` + §10）；
> - 本包只含 `ssh-site-maintain` **一个技能**。

---

## 一、包内结构

```
ssh-site-maintain/            技能本体（唯一技能）
  SKILL.md                    技能说明（功能总览 / §3.7 MCP 连接器 / §3.8 Fail2ban 正则审计 / §10 423down 服务器档案 / 维护记录 / 安全规则）
  bootstrap-key.py            密码 → 公钥引导（免密前置，一次性）
  register-host.py            注册主机别名到 ~/.ssh/config
  analyze-log.py              访问日志快速汇总
  site-report.py              完整访问报表（HTML）
  waf-hit-analysis.sh         WAF/fail2ban 命中与误封只读分析脚本
  references/
    server-map.md             423down 生产服务器完整档案（拓扑/路径/插件/cron/jail/误封点/修复史）
  persist/                    归档 + 冷启动恢复脚本
  mcp/                        4 个 MCP 连接器（依赖已内置 node_modules，免联网装包）
    bin/                      启动脚本 + 一键回归验证 + 测试客户端
    specs/                    e2e 用例 + 启动脚本 smoke（含 e2e-lhtdeg-connmgr.json 多连接管理）
    mcp-fail2ban/server.mjs   自研 Fail2ban MCP（零依赖）
    node_modules/             三个 npm 连接器及其依赖
.trae/mcp.json                TRAE 项目级 MCP 配置（4 个服务，装上即自动拉起）
README-安装说明.md            就是本文件
```

---

## 二、安装（桌面智能体软件 / 网页版通用）

1. **放技能**：把 `ssh-site-maintain/` 整个目录放到软件的 skills 目录
   - 工作区/项目级：`<你的项目>/.trae/skills/ssh-site-maintain/`（推荐）
   - 全局级（如果软件支持）：`~/.trae/skills/ssh-site-maintain/`
2. **配 MCP**：把本包 `.trae/mcp.json` 的 `mcpServers` 合并进项目的 `.trae/mcp.json`（或软件自带的 MCP 配置界面）。
   > ⚠️ `mcp.json` 里写的是本包在云沙箱里的绝对路径 `/workspace/.trae/skills/ssh-site-maintain`。
   > 装到你电脑上要**改成实际安装路径**，否则 MCP 起不来。一条命令搞定（`<实际路径>` 换成你的）：
   > ```bash
   > sed -i 's#/workspace/.trae/skills/ssh-site-maintain#<实际路径>/ssh-site-maintain#g' .trae/mcp.json
   > ```
3. **重启 / 新开会话**：技能与 4 个 MCP 服务会自动加载。

> 前提：电脑上已装 **Node.js 18+**（连接器是 node 程序）、**OpenSSH 客户端**（ssh/scp）。

---

## 三、首次连接你的服务器（需要输密码一次）

```bash
# 1) 生成密钥（一次性，跨主机复用）
mkdir -p ~/.ssh && chmod 700 ~/.ssh
[ -f ~/.ssh/id_ed25519 ] || ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 -C "my-agent"

# 2) 用密码把公钥装到服务器（密码从 stdin 读，不落盘）
printf '%s' '你的服务器密码' | python3 ssh-site-maintain/bootstrap-key.py --host <服务器IP> --port 22 --user root

# 3) 注册主机别名，之后免密
python3 ssh-site-maintain/register-host.py <别名> <服务器IP> 22 root "用途说明"
ssh <别名> 'hostname && uptime'
```

---

## 四、⚠️ 云端沙箱 vs 桌面/本地：参数差异（重要）

本包默认参数是**为云端沙箱**调的（沙箱屏蔽直连 22，只能走 HTTP 代理 `127.0.0.1:18080`）。
**在桌面/本地网络（通常可直连 22）使用，需去掉代理相关配置**，否则连不上：

| 位置 | 沙箱版（默认） | 桌面/本地版要改成 |
|---|---|---|
| `mcp/bin/launch-ssh-423down.sh` | `--proxy http://127.0.0.1:18080` | **删掉整个 `--proxy` 参数** |
| `mcp/bin/launch-ssh-async-423down.sh` | 连 `127.0.0.1:22022`（中继） | 改成 `--host <服务器IP> --port 22`，删中继调用 |
| `~/.ssh/config` 主机块 | `ProxyCommand nc -X connect -x 127.0.0.1:18080 %h %p` | **删掉 `ProxyCommand` 行** |
| `mcp/bin/ensure-relay.sh` | 起 socat 中继 | 直连环境**不需要** |

另外，连接器里的**路径白名单**（本地 `/workspace,/tmp`；远程 `/www,/tmp,/etc,/root`）和**密钥路径**按你本地实际调整。

> `bootstrap-key.py`（密码引导）在沙箱和桌面都能用，无需改。
> 若你的电脑本身也走代理，则保留 `--proxy` 并把地址换成你本机的代理端口即可。

---

## 五、验证是否装好

```bash
bash ssh-site-maintain/mcp/bin/e2e-verify-all.sh
# 期望：7 行 PASS（4 个 e2e：命令/上传下载/异步任务快照/封禁解封 + 3 个启动脚本 smoke）+ 四个 md5 一致
```

---

## 六、日常使用（技能会自动做这些）

- 跑命令：`ssh <别名> '<命令>'`
- 拉日志分析：`ssh <别名> 'gzip -c /www/wwwlogs/<域名>-access.log' > access.log.gz` → `python3 analyze-log.py access.log.gz`
- 出访问报表：`python3 site-report.py access-*.log.gz --title "<域名>" --out report.html`
- WAF/fail2ban 命中与误封分析：把 `waf-hit-analysis.sh` 传到服务器 `/tmp` 后 `bash waf-hit-analysis.sh <日期> <起> <止>`
- Fail2ban 正则误伤审计：见 `SKILL.md` §3.8
- 423down 服务器专用档案（路径/jail/缓存/误封点）：见 `SKILL.md` §10 与 `references/server-map.md`
- MCP 工具（会话里直接调）：`execute-command`、`upload`、`download`、`f2b_ban`、`f2b_status` …

**记住一条**：改任何配置文件前，先备份到 `/www/backup/maintain-<日期>/`，再动手。