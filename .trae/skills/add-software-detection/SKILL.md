---
name: "add-software-detection"
description: "为 check_versions.py 新增软件时，先跑 probe.py 一键定型（给 URL 就吐配置），再 --only 验证入库。避免裸配 increment 导致探测不稳/低效。当用户要求新增、添加软件到站点/检测清单时调用。"
---

# 新增软件探测入库

> 原理见 `DETECTION_GUIDE.md`。**别先想检测方式——先跑 probe.py，它替你想。**

## 快路径（拿到 URL 就跑，别先分析）

```bash
cd /workspace/.trae/skills/add-software-detection
python3 probe.py --name "<软件名>" <下载URL> [版本历史/更新日志URL]
#  → 直接输出可粘贴的 PRODUCTS 配置 + 定型理由（github_release / fixed / redirect / increment / scrape）

cd /workspace
# 粘到 PRODUCTS 末尾 → 单点验证 → 判据全过就按「同步更新」推 main
python3 check_versions.py --only "<软件名>" --no-save
```

probe.py 会自动做：GitHub API 挑 x64 安装包资产、HEAD 判 302/fixed、页面提版本号并给正则、URL 含版本号则生成 `url_pattern`。
**照抄它的输出即可**；只有它判不了的情况（网盘/论坛站、increment 子模式）才往下看速查表。

## 铁律

1. **禁止裸配 `increment`**：它是兜底不是默认，能 1 次请求搞定的绝不逐段递增。
2. **版本来源权威优先**：文件名全量版本 > 官方 API/网页 > PE/NSIS 深度解析（占位值/解析不出的别用）。
3. **日期来源权威优先**：官方发布页日期 / HTTP `Last-Modified` 优先；**禁止用 PE 编译时间戳（TimeDateStamp）或数字签名日期**当发布日期——那只是构建/签名时间，不是安装包发布或最后修改时间。服务器不给 `Last-Modified` 时退回发布页日期。
4. **新增必验证**：`--only` 跑通且判据全过才入库，没跑通不提交。
5. **只增目标条目**：不碰无关产品，不手改 `data.json`（输出物，由脚本生成）。
6. **大文件跳过 MD5**：包体 >100MB 配 `skip_md5: True`。
7. **判据全过 → 立即推 main 并当轮生效**：不等定时任务、不再问「要不要推」。见「同步更新」。

## 定型速查（probe.py 覆盖不到的）

| 场景 | detect_type | 关键字段 |
|------|-------------|----------|
| GitHub 托管/有 Releases | `github_release` | `repo`, `version_regex`；多资产 `asset_filter`+`use_asset_url` |
| GitLab 托管/有 Releases | `gitlab_release` | `gitlab_project`, `asset_filter`(取主安装包), `version_regex` |
| 固定地址 302 跳转 | `redirect` | `check_url`, `version_regex`（从 Location 提版本） |
| 固定地址直出文件 | `fixed` | `download_url`, `version`(手动)；可选 `pe_version` / `page_version_url`+`page_version_regex`；**日期被 CDN 覆盖时加 `prefer_config_date: True`** |
| 版本在网页上 | `scrape` | `check_url`, `version_regex`, `date_regex`, `download_url_regex` |
| 归档/下载列表页，最新版在**末尾** | `scrape` | `version_regex_take: 'last'` + `date_regex_take: 'last'`（配合 `size_regex` 抓体积） |
| 官方更新检查 API | `chrome_api`/`edge_api`/`luminar_api`/`hexhub_api`/`java_api`/`yandex` | 按软件对应 |
| 一个产品多条版本线（点标题展开子版本） | `java_api` | `java_lines`(版本线列表) + `java_line_cfg`(每线的 relnotes 页 + 下载锚点)；产出 `version_list` 字段 |
| URL 含版本、普通递增 | 多级进位（默认） | `base_version`, `url_pattern{ver}`；跨度大配 `max_skip`/`max_carry` |
| URL 含版本、第2段跳变 | `minor_scan` | `minor_scan=True`, `minor_scan_count`, `minor_scan_builds` |
| build 号稀疏跳跃（Adobe） | `adobe_build` | `version_format='adobe_build'`, `adobe_max_jump`, `adobe_probe_workers`, `detect_timeout` |
| 文件名只有大版本、真值在 NSIS | `nsis_version` | `nsis_version=True`（勿同配 `pe_version`） |
| 文件名只有大版本、PE 可信 | `pe_version` | `pe_version=True` |
| PE 里 FileVersion 带构建号、ProductVersion 才是产品版本 | `pe_version` | `pe_version=True` + **`pe_version_source: 'product'`**（DxO：FileVersion=10.2.20738.496，ProductVersion=10.2.0.496） |
| 官网只给三段版本、末段 build 号只在软件 About 框 | `scrape` | `version_build_suffix: 4`（官网 10.4.4 + 后缀 → 10.4.4.4） |
| 安装器版本比软件版本旧（官方包滞后一版） | `fixed` | `version_strict_prefix: '8.11'` + 人工核实 `version`（同产品线才保留配置值） |
| 安装包是 RAR SFX、版本在归档内 | `fixed` | `rar_sfx_version=True` + `rar_sfx_members:['xxx.exe']`（需 unrar，CI 已装） |
| 网盘/论坛/资源站 | `lanzou`/`189pan`/`cyberlink`/`discourse`/`yandex`/`monkrus`/`downtopc`/`nsane`/`startallback`/`bwcx` | 普通软件不碰 |

## 验证清单（判据全过才入库）

- [ ] 版本号是**新值**，非「未知」、非 `version` 兜底旧值
- [ ] `size` / `size_mb` 有合理值（`skip_md5` 大文件属正常）
- [ ] `last_modified` 日期合理（非空、非 1970），且来源是**发布页日期 / HTTP Last-Modified**，不是 PE 编译/签名时间戳
- [ ] `download_url` 是可达直链（或符合预期形态）
- [ ] 打印无 `timeout` / `error`（问题清单为空）
- [ ] 耗时符合优先级：fast <1s、normal 1-3s、slow 10-60s

## 多版本线条目（一个产品多个版本同时展示）

有些软件不是"一个最新版本"，而是**多条版本线并行维护**（Java 的 27 GA / 25 LTS / 21 LTS / 8 LTS）。
前端原本只支持单版本号，硬拆成多个产品条目会让用户看到一堆重复行。

**做法**：新增 `version_list` 字段，前端渲染成「点标题展开子版本列表」。

### 检测侧

```python
{
    'name': 'Java JDK',
    'name_cn': 'Java(JDK)',
    'alias': 'Java Runtime Environment',
    'detect_type': 'java_api',
    'java_api': 'https://java.oraclecloud.com/javaReleases',
    'java_lines': ['27', '25', '21', '8'],       # 版本线，按优先级降序
    'java_line_cfg': {                            # 每条线的固定链接（官网路径不变）
        '27': {
            'official_site': 'https://oracle.com/java/technologies/javase/27u-relnotes.html',
            'download_url': 'https://www.oracle.com/java/technologies/downloads/#jdk27-windows',
        },
        # ...
    },
    'version': '27.0.1',                          # 主版本（API 挂时的兜底）
    'date': '2026-10-20',                         # 日期兜底
    'download_url': 'https://www.oracle.com/java/technologies/downloads/',
    'official_site': 'https://oracle.com/java/technologies/java-se-glance.html',
    'allow_no_size': True,                        # 下载页不是单一安装包，无体积
    'skip_md5': True,
}
```

探测函数把清单写进全局 `_java_versions[产品名]`，`find_latest()` 统一挂到结果的 `version_list`：

```python
_java_versions[product['name']] = [
    {'name': 'Java SE Development Kit 27.0.1', 'version': '27.0.1', 'tag': 'GA',
     'official_site': '...', 'download_url': '...'},
    # ...
]
```

### 三条必须遵守的规则

1. **主版本按配置优先级取，不按日期取**
   主版本 = `java_lines` 里第一个能取到的版本线。若按"发布日期最新"选，某条 LTS 线先发补丁时
   主版本会从 27.0.1 变成 25.0.6（数值变小），被防降级机制误判成回滚而拦掉。
   但**日期**要取所有版本线里最新的（任一条线发补丁都算有更新）。

2. **`version_list` 必须纳入变更检测**
   只比对主 `version` 的话，某条 LTS 线更新时主版本没变 → CI 判"无变化" → 前端永远停在旧清单。
   `main()` 里要同时比对 `old_vlist != new_vlist`。

3. **本轮取不到清单时要沿用旧的**
   API 抽风时若返回空清单，前端展开列表会整块消失、日期被清空。
   上层要检测"本轮无子版本清单"，此时沿用 `old_data` 里的清单和日期。

### 前端侧

`index.html` 里版本列渲染成 `<details>`：

```javascript
const vlist = Array.isArray(p.version_list) ? p.version_list : [];
if (vlist.length) {
  // <details class="ver-expand"> 标题 + 子版本列表
  // 每条：标题(链接到该版本下载页) + GA/LTS 标记 + relnotes 引用
}
```

配套 CSS：`.col-version-multi`（去掉 nowrap）、`.ver-expand`、`.ver-item`、`.ver-tag`、`.ver-ref`。
移动端要额外覆盖 `display:block`，否则 td 的 flex 布局会把展开列表挤成一行。

## 定时检测跑在哪（2026-10-22 起，重要）

**GitHub Actions 已经跑不动了**：账号被账单门禁卡死（$0 预算硬停 + 支付方式缺失，
GitHub 返回 `400 Payment method is missing`），账单地址又被 GitHub 人工审核冻结中（48h），
**没有可用旁路**。所以 `gh workflow run detect.yml` 这条路作废，别再试。

检测已迁到 **423down 服务器 cron**，行为与原 detect.yml 对齐：

| 项 | 值 |
|---|---|
| 脚本 | `/opt/softofficelink/deploy/detect_cron.sh`（= 仓库里的 `deploy/detect_cron.sh`，推 main 后自动同步） |
| 调度 | `/etc/cron.d/softofficelink`：`0 * * * * hourly`（快检+资源站）、`15,45 * * * * full`（全量非资源站） |
| 仓库 | `/opt/softofficelink`（main 分支） |
| 日志 | `/var/log/softofficelink/cron.log`、`detect-{hourly,full}-YYYYMMDD.log` |
| 流程 | fetch → reset --hard origin/main → check_versions.py → embed_data.py → commit+push main → CF Pages 自动部署 |

要点：

- **推 main 依然触发 Cloudflare Pages 自动部署**（部署链路与 Actions 无关）。
- 现在改 `check_versions.py` 只要**推 main**，服务器下一轮 cron 自己拉新代码；不用手动跑检测。
- 服务器上的 git 是 **1.8.3.1**：`git fetch origin main` 只写 FETCH_HEAD、**不更新 `origin/main`**，
  脚本里必须用显式 refspec `git fetch origin '+refs/heads/main:refs/remotes/origin/main'`，
  否则 reset 回旧代码、push 被拒。
- push 被拒时脚本会自动 fetch + rebase 重试一次；别强推。
- 看服务器跑没跑：`ssh 423down 'tail -30 /var/log/softofficelink/cron.log'`。

## 同步更新（判据全过 → 一步不停）

### A. 本地渲染，让前端当轮生效

```bash
cd /workspace
export GITHUB_TOKEN=$(gh auth token)                     # github_release 类需要，其余可省
python3 check_versions.py --only "<软件名>"               # 不带 --no-save → 回填 data.json
python3 embed_data.py                                    # 生成 index.html
```

### B. 提交并推 main

```bash
# tokens.env 可选：文件在就 source，不在跳过（不要报错）
[ -f /data/user/skills/gh-cf-tokens/tokens.env ] && { set -a; . /data/user/skills/gh-cf-tokens/tokens.env; set +a; }

git fetch origin main && git rebase origin/main          # 躲开 Action 的自动提交
git add check_versions.py data.json index.html DETECTION_GUIDE.md \
        .trae/skills/add-software-detection/SKILL.md .trae/skills/add-software-detection/probe.py
git -c user.name="$(git config user.name || echo 423down)" \
    -c user.email="$(git config user.email || echo 423down@users.noreply.github.com)" \
    commit -m "feat(detect): 新增 <软件名> <版本号>"
git push origin HEAD:main                                # 推送即触发前端重建
```

### C. 触发当轮检测（Actions 死了，走服务器 cron）

```bash
# GitHub Actions 被账单门禁卡死，这两条已作废，别再跑：
# gh workflow run detect.yml --ref main -f mode=hourly
# gh run list --limit 3

# 现在：改完推 main，服务器 cron 下一轮自动跑。
# 想立刻跑一轮（服务器上直接跑脚本）：
ssh 423down '/opt/softofficelink/deploy/detect_cron.sh hourly'    # 快检+资源站
ssh 423down '/opt/softofficelink/deploy/detect_cron.sh full'      # 全量非资源站
ssh 423down 'tail -30 /var/log/softofficelink/cron.log'           # 看结果
```

要点：
- 优先级对应模式：`fast`/`normal`/`resource` → `hourly`；含 `slow` → `full`。
- 不手改 `data.json`，它是脚本产物；但**可以**本地跑脚本生成后一起提交（前端立即生效）。
- push 被拒就重跑 `git fetch && git rebase`，**不要强推**。
- 远端历史被重写过时，别硬 rebase 老分支：`git reset origin/main` 对齐后再重放本次改动。

## 仓库与部署事实（死记，别猜别探）

- 仓库：`423down-links/softofficelink`（main 分支）。**私有仓，从未公开过**，别建议转公开/改 Pages 设置。
- 部署方式：**push 到 main 即自动重建 Cloudflare Pages（线上地址 https://softofficelink.pages.dev/）**，无任何手动步骤；本地预览用 `python3 -m http.server` + OpenPreview。
- **⚠️ `check_versions.py --only` 不带 `--no-save` 会把 data.json 整个覆盖成单产品结构（实测翻车）**：要回填单产品数据，先 `cp data.json /tmp/备份`，跑完校验产品数与当前线上条数一致才继续；否则用 `--no-save` + 手动改。
- **页面本体不在服务器上**（发布仍是 Cloudflare Pages），但**检测脚本跑在 423down 服务器的 cron 上**（见「定时检测跑在哪」）。别去翻服务器站点目录；涉及检测/版本的事找 cron 和仓库。
- data.json 是脚本产物且被 Actions 定时自动提交：**动手前必须 `git fetch origin main`，以远端为基准改**，本地旧快照直接提交会把它人的检测增量顶回旧值（2026-10-15 实际翻车：14 款版本/日期被回滚）。
- **⚠️ 沙箱恢复可能 checkout 到旧 agent 分支（`trae/agent-*`）而非 main，本地会显示旧数据、看着像「回滚」**（2026-10-20 实际发生：凌晨入库的 4 款软件本地全消失，远端/线上其实完好）。开工第一件事：`git checkout main && git fetch origin main && git reset --hard origin/main`，再核对 data.json 里最近入库条目还在再动手，别拿旧分支快照当真相。
- **⚠️ `trae/agent-*` 分支是自动生成的临时工作分支，不要 merge、不要留**。2026-10-22 清理过一批（10 个远程 + 1 个本地），全部确认无独有产品/配置后才删。判断方式：逐个比 `git show <branch>:data.json` 的产品数与 `git show <branch>:check_versions.py` 的 PRODUCTS 集合，只有一家独有才值得抢救。
- **产品数量守卫（2026-10-22 加）**：写盘前会比对数量，线上有产品消失就中止（退出码 3）并点名报出少了谁，`--allow-remove "产品名"` 才能显式放行（英文名或中文名都行）。新增产品导致条数**增加**是正常的，不受拦截。两个脚本都有这层守卫：`check_versions.py`（守 data.json）和 `embed_data.py`（守 index.html）；CI 里退出码 3 会让 Actions 任务直接失败并打出 `::error::`。

## 常见坑（现象 → 根因 → 解法）

| 现象 | 根因 | 解法 |
|------|------|------|
| 版本停更/扫不到新版 | 逐段递增够不着第2段跳变 | `minor_scan` 列车扫描 |
| Adobe 新版扫不到 | build 号稀疏跳跃、存在性不单调 | `adobe_build` 并发全扫 |
| 版本被顶回旧值 | PE 是占位 build（微信）或解析不出（YY） | 别配 `pe_version` |
| 日期是构建/签名时间 | 把 PE 编译时间戳当发布日期 | 用发布页日期 / HTTP `Last-Modified`（见铁律3） |
| 版本号带构建号（10.2.20738.496） | PE 读了 FileVersion（文件自身版本），不是产品版本 | 配 `pe_version_source: 'product'` 改读 ProductVersion（10.2.0.496）；**不能全局改**——R-Studio 没有 ProductVersion |
| 版本号是日期式（26.10.21.0） | 同上，PotPlayer 的 FileVersion 是发布日期 | `pe_version_source: 'product'` 读 ProductVersion（1.7.23159）+ `strip_trailing_zero` 去末段补位 `.0` |
| 安装器版本比软件实际版本低一版 | NSIS 外壳版本打包时写死，软件本体更新后没同步 | `nsis_inner_version: True` 解包读内层 DLL（PotPlayer 外壳 1.7.23159 vs 内层 1.7.23160） |
| 内层 DLL 的 ProductVersion 是假的 | 部分厂商只认真版本，ProductVersion 写成 1.7.0.0 之类占位 | `nsis_inner_prefer: 'file'` 读 FileVersion（1.7.23160.0） |
| PE 版本字符串读不出来 | 字符串表写的是逗号分隔（`1, 7, 23160, 0`） | 读 VS_FIXEDFILEINFO 二进制结构（dwFileVersionMS/LS），正则只认点号会落空 |
| 换成 ProductVersion 后数值变小被拦截 | 口径变更（26.x → 1.7.x）不是真降级 | 配 `version_authority: 'pe'`（或 `'nsis'`），权威源命中即放行 |
| 官网只有三段版本、用户要四段 | 末段 build 号只在软件 About 框里 | `scrape` + `version_build_suffix`（官网 10.4.4 + 4 → 10.4.4.4） |
| PE 读出版本比官网低一版 | 官方安装包滞后一个修订版（DxO FilmPack 装包 8.11.0.896 / 软件 8.11.1.896） | `version_strict_prefix` + 人工核实 `version`，同产品线才保留配置值 |
| 安装包读不出任何版本 | 外壳是 RAR/自解压壳，无版本资源 | `rar_sfx_version=True` 解包读内层 exe（需 unrar，CI 已装）；7z 不支持 RAR5 |
| 官方包 302 跳到 not_available（Windows 包未上架） | 下载服务器整站 302 到提示页，且提示页也是 200 | `check_url_follow` 已识别 not_available 判为不可用；用 `size_regex` 抓页面记录的体积兜底，官方放包后自动切回真实值 |
| 官方包和便携包更新节奏不同 | 只测单一安装包漏新版本 | `pe_version` + `alt_download_urls` 多包取最新 |
| 完整包与热更新版本号不一致 | 厂商只对老包做增量热更，不重新发完整包（HexHub 热更到 5.4.4，完整包仍 5.1.9） | 取 `hexhub_api` 的 non-hot 版本，与用户实际下到的包一致 |
| 下载 URL 带构建时间戳 | 每版时间戳都变，写死进 `url_pattern` 必然扫不到新版（`...-5.1.9-202606072158.exe`） | 别配 increment，走官方 API 直接取完整 URL |
| 抓到正确版本却退回旧值 | CDN 不返回 Content-Length/Last-Modified → size=0 → 判「无体积」整轮作废（WinSnap 抓到 6.3.5 退回 6.3.3） | 优先用页面记录的体积；`check_url` 已加 GET 兜底 |
| 新版本被配上旧版本的发布日期 | 官网 history 页滞后（PDF-XChange 官网还停在 11.1.0.0/Sep 29，包已上架 11.1.1.0/Oct 20），页面日期无条件覆盖 | 页面版本 ≠ 探测版本时不采用页面日期，改用 CDN Last-Modified |
| 官网 history 页滞后、产品页却是新的 | 只盯 history 页 | 版本从产品页抓（PDF-XChange Pro 产品页有 "Current version:"），直链用 `url_pattern` 拼 |
| 页面体积带单位（3 MB） | `size_regex` 只认纯字节数 | 用 `size_regex_mb` 抓「数字+单位」并换算成字节 |
| GitHub 大小/直链不对 | 多资产（多平台包）混算 | `asset_filter` + `use_asset_url` |
| 大文件探测超时 | MD5 全量下载 | `skip_md5: True` |
| 资源站/论坛被限流 | 请求过重 | `detect_priority='resource'` 单独降频 |
| 一个产品有多条版本线要同时展示 | 前端只支持单版本号，得多条产品重复 | 加 `version_list` 字段（详见「多版本线条目」），前端渲染成点标题展开 |
| 子版本更新了但 CI 不推送 | 变更检测只比对主 `version` | `version_list` 也纳入比对（`main()` 里 `old_vlist != new_vlist`） |
| API 抽风把子版本列表清空 | 探测返回空清单 → 整块消失 | 上层检测到「本轮无子版本清单」时沿用 `old_data` 的清单和日期 |
| 全部产品都多出 `version_list: []` | `find_latest` 无条件返回该键 → 113 款单版本产品全被塞空列表，data.json 每次检测几百行 diff 噪声 | 已修：只在真有多版本线时才带该键（`if _vlist:`），单版本产品不带 `version_list` |
| 线上产品被静默截断（少了几个） | 误改 `PRODUCTS`（漏配/name 写错/误删）→ 写回 data.json 就把少的部分抹掉 | 已加**产品数量守卫**：`check_versions.py` 与 `embed_data.py` 写盘前都比对数量，发现线上有产品消失就**中止写盘 + 点名报出少了谁**（退出码 3），确认要下线则显式 `--allow-remove "产品名"` |
| 提交后线上产品数变少 | 手动改 data.json 或 embed 前没比对 | 别手改 data.json；`embed_data.py` 已有守卫兜底 |
| 版本号保住了但体积/日期/下载链接一起变坏 | 防降级拦截只回退 `version` 字段，同轮探测出的坏体积、坏日期、退化成通用页面的直链照样写进线上（实测 Win11 LTSC 直链退成 `releases` 页面、日期倒回 2026-09-14） | 降级时**一并回退** size/size_mb/last_modified/md5/download_url/download_url_with_params；另：GitHub API 必须带 `GITHUB_TOKEN`，否则 60 次/小时限流会让 `github_release` 整片回退成通用链接 |
| **版本号被清空成空字符串**（线上 AnyDesk 显示空白） | `fixed` 模式的 PE 探测失败（CDN 限流 429 / 服务器 SSL 证书旧），缓存里也没有旧值时，旧代码把 `version` 直接覆盖成 `''`；防降级只拦「变小」，空串不在拦截范围 | 已修：`detect_fixed` 里 PE 无结果时**保留配置版本**（不覆盖成空），`main()` 里再兜一层「本轮版本号为空 → 沿用旧值」；AnyDesk 另加 `page_version_url` + `page_version_regex`（抓官网 JSON 里 `win_exe` 的 version）双保险 |
| 服务器 cron 一直跑旧代码 / push 被拒 | 服务器 git 是 1.8.3.1，`git fetch origin main` 不更新 `origin/main`（2.13 前只写 FETCH_HEAD） | 用显式 refspec：`git fetch origin '+refs/heads/main:refs/remotes/origin/main'`；脚本里 push 失败自动 fetch+rebase 重试 |
| 服务器上 PE 解析报 `CERTIFICATE_VERIFY_FAILED` | 面板 pyenv 的 python3.7 CA 证书太旧 | 探测失败不再写空版本（保留配置版本）；要根治需更新该 python 的 cacert |
| 版本死活不动、脚本无报错 | 多行文本（history.txt / release notes）用 `^` 锚定但正则没开 `(?m)` → `re.search` 只匹配整个字符串开头，**永远匹配不到**且不报错（实测 7-Zip 卡在 26.04，官网已发 26.05） | 正则内联 `(?m)`：`r'(?m)^(\d+\.\d+)\s+(\d{4}-\d{2}-\d{2})'`；任何 `^`/`$` 锚定前先确认被匹配文本是不是多行结构 |
| 版本明明探测对了却被丢弃（报"无体积"） | 探测请求没带 `Referer` → 对方返回拦截页（exists=True 但 size=0）→ 上层判「无体积」整轮作废（实测 NVIDIA 抓到 621.01 却退回 617.42） | `check_url_follow(url, referer=product.get('referer'))`（`detect_scrape` 曾漏传，`detect_fixed`/`detect_increment` 一直有传）；referer **只用于探测**，别写进给用户的 download_url |
| 抓到的是同页的另一个安装包变体 | 同页并列多个包（SketchUp 的 `SketchUp-*.exe` / `SketchUpFull-*.exe` / `.dmg`），正则只写了 `SketchUp` 没锚死完整文件名 | 直链正则锚死完整文件名并以 `\.exe` 结尾；`re.search` 取第一个匹配，注意包在页面上的先后顺序 |
| 版本号里混进了 build 号 | 文件名 `SketchUp-2027-0-264-170.exe` 末段是 build 号，不属于产品版本号 | 多捕获组用 `.` 拼接时把 build 段写成非捕获（`\d+`），只保留年/大/小版本三段；年份用 `20(\d\d)` 只取后两位 |
| 线上版本停滞但代码看着没问题 | 定时检测流水线本身没跑（GitHub Actions 账号账单被冻结 → 所有 job "was not started"） | 排查前先 `gh run list` 看 CI 最近一次成功是什么时候，别一上来就怀疑探测逻辑 |

