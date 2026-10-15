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
3. **新增必验证**：`--only` 跑通且判据全过才入库，没跑通不提交。
4. **只增目标条目**：不碰无关产品，不手改 `data.json`（输出物，由脚本生成）。
5. **大文件跳过 MD5**：包体 >100MB 配 `skip_md5: True`。
6. **判据全过 → 立即推 main 并当轮生效**：不等定时任务、不再问「要不要推」。见「同步更新」。

## 定型速查（probe.py 覆盖不到的）

| 场景 | detect_type | 关键字段 |
|------|-------------|----------|
| GitHub 托管/有 Releases | `github_release` | `repo`, `version_regex`；多资产 `asset_filter`+`use_asset_url` |
| GitLab 托管/有 Releases | `gitlab_release` | `gitlab_project`, `asset_filter`(取主安装包), `version_regex` |
| 固定地址 302 跳转 | `redirect` | `check_url`, `version_regex`（从 Location 提版本） |
| 固定地址直出文件 | `fixed` | `download_url`, `version`(手动)；可选 `pe_version` / `page_version_url`+`page_version_regex`；**日期被 CDN 覆盖时加 `prefer_config_date: True`** |
| 版本在网页上 | `scrape` | `check_url`, `version_regex`, `date_regex`, `download_url_regex` |
| 官方更新检查 API | `chrome_api`/`edge_api`/`luminar_api`/`yandex` | 按软件对应 |
| URL 含版本、普通递增 | 多级进位（默认） | `base_version`, `url_pattern{ver}`；跨度大配 `max_skip`/`max_carry` |
| URL 含版本、第2段跳变 | `minor_scan` | `minor_scan=True`, `minor_scan_count`, `minor_scan_builds` |
| build 号稀疏跳跃（Adobe） | `adobe_build` | `version_format='adobe_build'`, `adobe_max_jump`, `adobe_probe_workers`, `detect_timeout` |
| 文件名只有大版本、真值在 NSIS | `nsis_version` | `nsis_version=True`（勿同配 `pe_version`） |
| 文件名版本不全、PE 可信 | `pe_version` | `pe_version=True` |
| 网盘/论坛/资源站 | `lanzou`/`189pan`/`cyberlink`/`discourse`/`yandex`/`monkrus`/`downtopc`/`nsane`/`startallback`/`bwcx` | 普通软件不碰 |

## 验证清单（判据全过才入库）

- [ ] 版本号是**新值**，非「未知」、非 `version` 兜底旧值
- [ ] `size` / `size_mb` 有合理值（`skip_md5` 大文件属正常）
- [ ] `last_modified` 日期合理（非空、非 1970）
- [ ] `download_url` 是可达直链（或符合预期形态）
- [ ] 打印无 `timeout` / `error`（问题清单为空）
- [ ] 耗时符合优先级：fast <1s、normal 1-3s、slow 10-60s

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

### C. 触发当轮检测（拿不到权限就跳过，别卡住）

```bash
gh workflow run detect.yml --ref main -f mode=hourly     # 含 slow 的用 mode=full
gh run list --limit 3                                    # 403/无 workflow 权限 → 跳过，等整点定时轮
```

要点：
- 优先级对应模式：`fast`/`normal`/`resource` → `mode=hourly`；含 `slow` → `mode=full`。
- 不手改 `data.json`，它是脚本产物；但**可以**本地跑脚本生成后一起提交（前端立即生效）。
- push 被拒就重跑 `git fetch && git rebase`，**不要强推**。
- 远端历史被重写过时，别硬 rebase 老分支：`git reset origin/main` 对齐后再重放本次改动。

## 仓库与部署事实（死记，别猜别探）

- 仓库：`423down-links/softofficelink`（main 分支）。**私有仓，从未公开过**，别建议转公开/改 Pages 设置。
- 部署方式：**push 到 main 即自动重建 Cloudflare Pages（线上地址 https://softofficelink.pages.dev/）**，无任何手动步骤；本地预览用 `python3 -m http.server` + OpenPreview。
- **⚠️ `check_versions.py --only` 不带 `--no-save` 会把 data.json 整个覆盖成单产品结构（实测翻车）**：要回填单产品数据，先 `cp data.json /tmp/备份`，跑完校验产品数=103 才继续；否则用 `--no-save` + 手动改。
- **本任务与 SSH 服务器（423down.com）完全无关**：这个页面不在服务器上，禁止为此连 SSH、禁止查服务器目录。
- data.json 是脚本产物且被 Actions 定时自动提交：**动手前必须 `git fetch origin main`，以远端为基准改**，本地旧快照直接提交会把它人的检测增量顶回旧值（2026-10-15 实际翻车：14 款版本/日期被回滚）。

## 常见坑（现象 → 根因 → 解法）

| 现象 | 根因 | 解法 |
|------|------|------|
| 版本停更/扫不到新版 | 逐段递增够不着第2段跳变 | `minor_scan` 列车扫描 |
| Adobe 新版扫不到 | build 号稀疏跳跃、存在性不单调 | `adobe_build` 并发全扫 |
| 版本被顶回旧值 | PE 是占位 build（微信）或解析不出（YY） | 别配 `pe_version` |
| GitHub 大小/直链不对 | 多资产（多平台包）混算 | `asset_filter` + `use_asset_url` |
| 大文件探测超时 | MD5 全量下载 | `skip_md5: True` |
| 资源站/论坛被限流 | 请求过重 | `detect_priority='resource'` 单独降频 |
