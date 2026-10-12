---
name: "add-software-detection"
description: "为 check_versions.py 新增软件时，按决策树选定最优 detect_type 并验证入库，避免裸配 increment 导致探测不稳/低效。当用户要求新增、添加软件到站点/检测清单时调用。"
---

# 新增软件探测方式选择工作流

> 完整原理见仓库根目录 `DETECTION_GUIDE.md`。本技能是**新增软件时的标准操作流程**：
> 先定型、再配置、后验证，避免「裸配 increment」这种既不稳又慢的初级入库。

## 何时用

用户要求「新增软件 X」「添加 X 到站点」「把 X 加进检测清单」时，先走本流程，再动手改 `check_versions.py`。

## 铁律（约束）

1. **禁止裸配 `increment`**：`increment` 是兜底不是默认。必须先走决策树，能 1 次请求搞定的绝不逐段递增。
2. **版本来源权威优先**：文件名全量版本 > 官方 API/网页 > PE/NSIS 深度解析。
   PE/NSIS 只在「文件名版本不全」时才加，且要**先确认可信**（PE 占位值、解析不出的别用）。
3. **新增必验证**：`--only` 跑通且判据全过才允许入库，没跑通不提交。
4. **只增目标条目**：不改无关产品配置，不手改 `data.json`（它由脚本生成，属输出物）。
5. **大文件跳过 MD5**：包体 >100MB 配 `skip_md5: True`，别让 MD5 拖超时。
6. **验证通过即同步前端（强制）**：判据全过就**立即**把改动推到 `main`（前端发布分支）并触发一轮 `detect.yml`，
   让站点当轮生效——**不等下次整点/半点定时任务，也不再问「要不要推」**。步骤见「同步更新」。

## 决策树（先定型，再写配置）

```
新增软件 X
│
├─ 1. 有 GitHub Releases / GitHub 托管？
│    └─ 是 → github_release（repo=owner/repo；多资产加 asset_filter + use_asset_url）
│
├─ 2. 官方有「更新检查 API」且已实现？
│    └─ 是 → chrome_api / edge_api / luminar_api / yandex（按软件对应）
│
├─ 3. 官方提供固定下载地址（URL 里无版本号）？
│    ├─ 访问后 302 跳转 → redirect（version_regex 从 Location 提版本）
│    └─ 直接返回文件 → fixed + 变化检测（version 手动维护，可加 pe_version 或 page_version 交叉校验）
│
├─ 4. 下载地址含版本号？
│    ├─ 是 → increment 系，再按「版本号规律」选子模式：
│    │    ├─ 版本按第2段跳变、第三段归0、CDN只留最新包 → minor_scan（列车扫描）
│    │    ├─ build 号稀疏跳跃（Adobe 的 YYMM+序号）→ version_format=adobe_build + 并发全扫
│    │    ├─ 文件名只有大版本、真值在 NSIS install.7z → nsis_version（别配 pe_version）
│    │    ├─ 文件名只有大版本、PE FileVersion 可信 → pe_version
│    │    └─ 普通规律 → 多级进位（默认即可，跨度大配 max_skip/max_carry）
│    └─ 否 → 版本在网页上？
│         ├─ 是 → scrape（version_regex / date_regex / download_url_regex）
│         └─ 否 → 网盘/论坛/资源站 → lanzou / 189pan / discourse / monkrus / downtopc / nsane
```

## 探测方式速查（触发条件 + 最少配置）

### 一次请求类（首选，快且稳）

| detect_type | 触发条件 | 关键字段 |
|-------------|----------|----------|
| `github_release` | GitHub 托管/有 Releases | `repo`, `version_regex`；多资产加 `asset_filter`+`use_asset_url`；正式版跳过 beta 默认开启 |
| `redirect` | 固定地址 302 跳转 | `check_url`, `version_regex` |
| `fixed` | 固定地址始终最新版 | `download_url`, `version`(手动)；可选 `pe_version`、`page_version_url`+`page_version_regex` |

### 网页抓取类

| detect_type | 触发条件 | 关键字段 |
|-------------|----------|----------|
| `scrape` | 版本/日期/下载链在网页上 | `check_url`, `version_regex`, `date_regex`, `download_url_regex`, `version`(兜底) |

### increment 系（URL 含版本号的兜底，注意子模式）

| 配置 | 适用 | 关键字段 |
|------|------|----------|
| 多级进位（默认） | 版本逐段递增 | `base_version`, `url_pattern{ver}`；跨度大配 `max_skip`/`max_carry` |
| `minor_scan` | 版本按第2段跳变 | `minor_scan=True`, `minor_scan_count`, `minor_scan_builds` |
| `adobe_build` | build 号稀疏跳跃 | `version_format='adobe_build'`, `adobe_max_jump`, `adobe_probe_workers`, `detect_timeout` |
| `nsis_version` | NSIS install.7z 真值 | `nsis_version=True`（勿同时配 `pe_version`） |
| `pe_version` | 文件名版本不全+PE可信 | `pe_version=True` |

### 特殊渠道（网盘/论坛/资源站，普通软件不碰）

`lanzou`、`189pan`、`cyberlink`、`discourse`、`yandex`、`monkrus`、`downtopc`、`nsane`、`startallback`、`bwcx`。

## 标准流程（6 步）

1. **收集信息**：官方下载页 + GitHub 仓库 + 现有 release 页，确认「下载 URL 形态」和「版本号出现位置」。
2. **走决策树**：定 `detect_type` 和所需字段。
3. **追加条目**：在 `check_versions.py` 的 `PRODUCTS` 列表末尾加一个字典，含
   `name`/`name_cn`/`icon`/`icon_color`/`category`/`detect_type`/探测字段/`download_url`/`official_site`，
   `version` 先填已知现值做兜底；顶部加一行注释说明「为什么选这个方式」。
4. **单点验证**：`python3 check_versions.py --only "<软件名>" --no-save`
5. **核对判据**（见下），不合格回第 2 步换方式/调字段重试。
6. **收尾 + 同步前端**：临时验证条目验证后删除；正式新增的条目保留，**判据全过立即按「同步更新」推 `main` 并触发 `detect.yml`**，不等定时任务、不再询问。

## 同步更新（判据全过 → 立即执行，强制）

判据全过后**一步不停**，按下面顺序把改动落到前端发布分支并当轮生效：

```bash
set -a; . /data/user/skills/gh-cf-tokens/tokens.env; set +a

# 1) 拉远端，避免被 Action 的自动提交挡住
git fetch origin main && git rebase origin/main

# 2) 只提交本次相关文件（不 git add -A，避免误带临时产物）
git add check_versions.py .trae/skills/add-software-detection/SKILL.md
git commit -m "feat(detect): 新增 <软件名> <版本号>"

# 3) 推 main（前端发布分支；推送即触发 Pages 重建）
git push origin main

# 4) 立即手动触发一轮检测，让站点当轮生效（不等整点/半点）
#    新条目 detect_priority 含 slow 的用 full；否则用 hourly（含 fast+normal+resource）
gh workflow run detect.yml --ref main -f mode=hourly   # 或 -f mode=full

# 5) 确认跑起来并盯结果
gh run list --limit 3
gh run view <run-id> --log-failed   # 只在失败时看
```

要点：

- **优先级对应模式**：`detect_priority` 为 `fast`/`normal`/`resource` 的用 `mode=hourly`；含 `slow` 的用 `mode=full`。
- **推送即上线**：`main` 的推送本身就会触发 Pages 重建，手动跑 detect 是为了让**新条目当轮被检测/回填**，两件事都别省。
- **不手改 `data.json`**：它由 detect.yml 里的 `embed_data.py` 生成；本地只改 `check_versions.py`。
- 若 Action 已有提交导致 `git push` 被拒，重复第 1 步 `git fetch && git rebase` 再推，**不要强推**。

## 验证清单（判据全过才入库）

- [ ] 版本号是**新值**，非「未知」、非 `version` 兜底旧值
- [ ] `size` / `size_mb` 有合理值（`skip_md5` 的大文件属正常）
- [ ] `last_modified` 日期合理（非空、非 1970）
- [ ] `download_url` 是可达直链（或符合预期形态）
- [ ] 打印无 `timeout` / `error`（问题清单为空）
- [ ] 耗时符合优先级预期：fast <1s、normal 1-3s、slow 10-60s

## 常见坑（现象 → 根因 → 解法）

| 现象 | 根因 | 解法 |
|------|------|------|
| 版本停更/扫不到新版 | 逐段递增够不着第2段跳变 | 用 `minor_scan` 列车扫描 |
| Adobe 新版扫不到 | build 号稀疏跳跃、存在性不单调 | `adobe_build` 并发全扫 |
| 版本被顶回旧值 | PE 是占位 build（微信）或解析不出（YY） | 别配 `pe_version` |
| GitHub 大小/直链不对 | 多资产（多平台包）混算 | `asset_filter` + `use_asset_url` |
| 大文件探测超时 | MD5 全量下载 | `skip_md5: True` |
| 资源站/论坛被限流 | 请求过重 | `detect_priority='resource'` 单独降频 |