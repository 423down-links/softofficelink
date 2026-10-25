# 软件版本探测方式指南

> 最后更新：2026-10-13 ｜ 覆盖 100 款软件 ｜ 代表软件以当前 `data.json` 为准
>
> **新增软件别翻这篇：先跑 `python3 .trae/skills/add-software-detection/probe.py <URL>`，它直接吐定型配置；本文只作原理参考。**

## 探测方式总览

| 方式 | 适用场景 | 效率 | 准确度 | 请求数 | 代表软件 |
|------|----------|------|--------|--------|----------|
| 官方更新API | 软件有check-update接口 | ⭐⭐⭐⭐⭐ | 极高 | 1 | PDFelement |
| 第三方软件库API | 主流软件可查 | ⭐⭐⭐⭐⭐ | 高 | 1 | 微信、迅雷、QQ音乐 |
| GitHub Releases API | 开源/GitHub托管软件 | ⭐⭐⭐⭐⭐ | 高 | 1 | Edge/Chrome安装器 |
| redirect | 固定地址302跳转 | ⭐⭐⭐⭐⭐ | 高 | 1 | XMind |
| fixed+变化检测 | 固定地址始终最新版 | ⭐⭐⭐⭐⭐ | 中 | 1 | IObit、网易云 |
| increment+进位 | URL含版本号，可跨版本 | ⭐⭐⭐⭐ | 高 | 5-20 | 雷电、微信 |
| increment+列车扫描 | 版本按第2段跳变，CDN只留最新包 | ⭐⭐⭐⭐⭐ | 高 | 2轮并发 | YY |
| thunder_cdn | 版本两段同时跳号，官方源滞后 | ⭐⭐⭐⭐⭐ | 高 | ~20 | 迅雷 |
| scrape | 从网页抓取版本信息 | ⭐⭐⭐ | 中 | 1-2 | Edge、Chrome、Xshell |
| lanzou | 蓝奏云网盘API探测 | ⭐⭐⭐⭐ | 高 | 2 | 闪豆下载器 |
| PE版本 | 从exe.rsrc段读FileVersion | ⭐⭐⭐⭐ | 高 | 2-3 | 360浏览器、AnyDesk |
| NSIS版本 | 从install.7z读版本文件夹 | ⭐⭐⭐ | 极高 | 4-5 | 微信 |
| RSS/Atom订阅 | 官网有更新日志Feed | ⭐⭐⭐⭐ | 高 | 1 | 待探索 |
| MD5校验 | 小文件完整性校验 | ⭐ | 高 | 完整下载 | <100MB文件 |

---

## 融合架构（多源探测，按优先级降级）

每个软件配置多个探测源，按优先级依次尝试，前一个失败自动降级到下一个：

```
┌─────────────────────────────────────────────────────────┐
│  优先级1：官方更新检查API（最准，1次请求）                 │
│    例：PDFelement check-upgrade接口                       │
├─────────────────────────────────────────────────────────┤
│  优先级2：第三方软件库API（验证源，1次请求）               │
│    腾讯软件中心API / winget仓库 / 360软件库API             │
├─────────────────────────────────────────────────────────┤
│  优先级3：URL递增+多级进位探测（兜底，5-20次请求）         │
│    递增最后一段 → 连续5个404 → 进位到上一段 → 最多进位2次  │
├─────────────────────────────────────────────────────────┤
│  优先级4：固定地址变化检测（固定URL软件，1次请求）         │
│    检测Content-Length / Last-Modified / ETag变化          │
├─────────────────────────────────────────────────────────┤
│  优先级5：PE/NSIS深度版本探测（精确小版本号，2-5次请求）   │
│    PE头.rsrc段 / NSIS install.7z版本文件夹                │
└─────────────────────────────────────────────────────────┘
```

**核心原则**：递增探测从"主力"降级为"兜底"，优先用API一次请求获取版本号，既快又准。

---

## API探测法总览（已实现3种 + 待实现3种）

API探测是效率最高、最准确的探测方式，一次请求即可获取版本号、下载地址、大小、日期等全部信息。

### 已实现的API探测方式

| 探测方式 | 类型 | 代表软件 | 实现状态 |
|----------|------|----------|----------|
| `luminar_api` | 专用XML API | Luminar Neo | ✅ 已实现 |
| `lanzou` | 网盘API | 闪豆下载器 | ✅ 已实现 |
| `github_release` | GitHub API | Edge/Chrome/开源工具 | ✅ 已实现 |
| `redirect` | HTTP重定向 | XMind/搜狗输入法 | ✅ 已实现 |

### 待实现的API探测方式

| 探测方式 | 类型 | 代表软件 | 状态 |
|----------|------|----------|------|
| `api_json` | 通用JSON API | PDFelement/腾讯软件中心 | 🔲 待实现 |
| `tencent_api` | 腾讯软件中心 | 微信/迅雷/QQ音乐 | 🔲 待实现 |
| `winget_api` | 微软winget仓库 | Edge/Chrome/VS Code | 🔲 待实现 |

### API探测优先级排序

1. **官方更新检查API**（最准确，需逆向签名）
2. **第三方软件库API**（腾讯/winget，厂商提交数据）
3. **专用安装器API**（Luminar模式，安装器硬编码API）
4. **GitHub Releases API**（开源软件标准）
5. **网盘API**（蓝奏云/MediaFire等）
6. **重定向探测**（固定地址302跳转）

---

## 各方式详细说明

### 1. 官方更新检查API（优先级1）
**原理**：软件自身的更新检查接口，直接返回最新版本号、下载地址、更新日志

#### 1.1 已实现：Luminar Neo 专用XML API（luminar_api）
**API入口**：`http://luminarneowin.skylum.com/`（必须访问根路径）
**必需请求头**：`User-Agent: Other`（安装器硬编码）
**返回格式**：XML（声明utf-16实际utf-8）
**关键字段**：`<Version>`、`<DataUrl>`（离线包地址含随机令牌）、`<FrameworkUrl>`、`<RedistributablesUrl>`
**详细说明**：见本文档「luminar_api - 专用安装器API探测」章节

#### 1.2 待实现：PDFelement check-upgrade API
**API入口**：`https://pc-api.wondershare.cc/v5/product/check-upgrade`
**必需参数**：`pid`、`version`、`brand`、`client_sign`（客户端签名，需逆向生成）
**返回格式**：JSON
**关键字段**：`upgradeVersion`、`full_url`、`whats_new_content`、`packageSize`
**障碍**：`client_sign`由ClientSign类基于GreenwichTime+密钥生成，需逆向分析

**优点**：最准确，一次请求获取所有信息
**缺点**：需要逆向分析接口参数（client_sign等签名）
**适用**：有更新检查机制的商业软件

### 2. 第三方软件库API（优先级2，推荐融合）
**腾讯软件中心API**：
```
GET https://s.pcmgr.qq.com/tapi/web/searchcgi.php?type=search&keyword=微信
返回字段：ver(版本)、fs(大小)、url(下载地址)、ux(更新时间)
```
**winget仓库API**（微软官方）：
```
GET https://winget.run/api/v1/packages/Google.Chrome
返回结构化manifest，含版本号和下载URL
```
**360软件库API**：待探索
**优点**：一次请求获取版本+大小+日期+下载地址，厂商提交数据准确度高
**缺点**：非所有软件都收录，小众软件可能查不到
**适用**：微信、迅雷、QQ音乐、搜狗、YY等主流软件

### 3. GitHub Releases API（优先级3）
**原理**：GitHub官方API查询最新release
```
GET https://api.github.com/repos/{owner}/{repo}/releases/latest
```
**优点**：结构化数据，含版本号、发布日期、下载资产
**适用**：Edge/Chrome安装器（Bush2021仓库）、开源工具

### 4. redirect（重定向检测）
**原理**：访问固定地址，从302 Location头提取版本号和下载链接
```python
{
    'detect_type': 'redirect',
    'check_url': 'https://example.com/download',
    'version_regex': r'(\d+\.\d+\.\d+)',
}
```
**优点**：一次请求获取版本和下载链接
**适用**：固定下载地址会302跳转的软件（XMind）

### 5. fixed + 变化检测（固定地址）
**原理**：固定地址始终指向最新版，通过HTTP头变化检测更新
```python
{
    'detect_type': 'fixed',
    'version': '16.0.0.34',
    'download_url': 'https://example.com/latest.exe',
}
```
**变化检测指标**：
- `Content-Length` 变化 → 文件大小变了，可能有更新
- `Last-Modified` 变化 → 文件被修改
- `ETag` 变化 → 文件内容变化
**优点**：URL不变，1次请求检测变化
**缺点**：版本号需手动维护或从其他源获取
**适用**：IObit、网易云音乐等

**版本滞后兜底：官网页面版本交叉校验（可选）**

二进制版本来得慢：CDN 可能长期缓存安装包（如 wftpserver.com 的 `Cache-Control: max-age=604800`，整整 7 天），本地 PE 缓存也有 TTL（6h），新版发布后版本号会滞后。官网页面是即时更新的，配置 `page_version_url` + `page_version_regex` 后，取「页面版本 与 二进制版本」的较大值：
```python
{
    'detect_type': 'fixed',
    'pe_version': True,
    'page_version_url': 'https://www.wftpserver.com/download.htm',
    'page_version_regex': r'Wing FTP Server\s*<b>\s*v([\d.]+)\s*</b>',
    'version': '8.2.5.0',
    'download_url': 'https://www.wftpserver.com/download/WingFtpServer.exe',
}
```
**适用**：安装包被 CDN 长期缓存的软件（Wing FTP Server）；或固定 URL 里无版本号、版本只在官网页面上的软件（Bandizip，版本历史页首行 `<div class="cell1">v7.47</div>`）

### 6. increment + 多级进位探测（兜底主力）
**原理**：从 base_version 递增版本号，连续 N 个 404 后自动进位到上一段。
默认 N=3、最多进位 1 次，可用 `max_skip` / `max_carry` 按软件覆写。

**配置**：
```python
{
    'detect_type': 'increment',
    'base_version': '25.1.13.1631',
    'url_pattern': 'https://down.sandai.net/thunder_pc/ThunderSetup{ver}up.exe',
}
```

**探测流程**（以迅雷为例）：
```
25.1.13.1631 → 递增 → ... → 25.1.13.1636 ✓ (最新)
→ 继续递增 → 1637(404) 1638(404) 1639(404)
→ 连续3个404，自动进位: 25.1.13.1639 → 25.1.14.0
→ 递增探测 25.1.14.x → 再连续404 → 进位 25.1.15.0 ← 可跨小版本
```

**进位规则**：`25.1.13.1636` → `25.1.14.0`（倒数第二段 +1，其后重置为 0）；
`9.5.37` → `9.6.0`。

**参数**：`MAX_INCREMENT = 30`（单轮递增上限）；`max_skip`（默认 3）；
`max_carry`（默认 1）。位数更多、跨度更大的软件（如 Advanced Installer）配 `max_skip: 3, max_carry: 2`。

#### 6.0 小版本「列车」并发扫描（`minor_scan`，版本按第 2 段跳变时用）

**适用**：版本号按**第 2 段**递增、且第三段归 0、CDN 只保留最新几个包（典型：YY `9.59 -> 9.60`）。
这类软件照上面的逐段递增**永远进不到位**——进位只动倒数第二段，够不着第 2 段。

```python
{
    'detect_type': 'increment',
    'base_version': '9.60.0.0',
    'url_pattern': 'https://dl-limit.yystatic.com/4/setup/YYSetup-{ver}-zh-CN.exe',
    'minor_scan': True,          # 开启列车扫描
    'minor_scan_count': 6,       # 第2段向后扫 +1..+6
    'minor_scan_builds': 4,      # 命中段内再扫构建号 0..4
}
```

**两轮并发定位**：
1. 把 `base` 和第 2 段 `+1..+N` 放**同一批并发**探测，取最大命中；
2. 命中段内并发扫构建号 `0..B`，取最大命中。

命中后**跳过第 1~3 层**逐段递增，省掉每次 0.2~0.3s 的节流 sleep。

**优点**：不依赖 API，纯 URL 探测，可覆盖跨版本更新
**缺点**：需要多次请求，版本号无规律时失效
**适用**：雷电、迅雷、微信、搜狗、360浏览器等（YY 用 `minor_scan` 列车扫描）

**url_ver_format（版本号URL格式转换）**：
| 格式 | 示例 | 适用软件 |
|------|------|----------|
| `full`（默认） | 8.40.5000 → 8.40.5000 | 多数软件 |
| `short` | 8.40 → 840 | 部分软件 |
| `major_minor` | 8.40.5000 → 8.40 | 部分软件 |
| `acdsee_year` | 20.0.0.4660 → 2027-0-0-4660 | ACDSee（主版本+2007=年份） |
| `adobe_build` | 2600221996 → 2026.002.21996 | Adobe Acrobat |

### 6.1 Adobe build 号稀疏跳跃（adobe_build 专用）
**问题**：Adobe 的 10 位 build 号（YYMM+序号）在小版本更新时会**跳过几十个序号**，
实测 `2600221931 → 2600221996` 之间 64 个号全部 404，逐个递增探测永远扫不到新版本。
且 CDN 只保留存在的少数版本，**存在性不单调**（21995 不存在而 21996 存在），二分查找也不适用。

**解决**：`version_format: 'adobe_build'` 时自动走并发全扫
（`adobe_build_probe()`），扫描 `base+1 ~ base+adobe_max_jump` 取最大命中版本。

```python
{
    'version_format': 'adobe_build',
    'adobe_max_jump': 700,        # 向前扫描的最大号段跨度
    'adobe_probe_workers': 20,    # 并发线程数（CDN 单次约900ms，需并发才不超时）
    'detect_timeout': 180,        # 该产品单独放宽超时（默认30s不够用）
}
```
实测 20 并发扫描 700 个号约 23~32 秒，可接受。

### 6.2 thunder_cdn（迅雷专用：两段同时跳号）
**问题**：迅雷 PC 客户端版本号形如 `25.1.40.1703`，**第 3 段和第 4 段都在跳号**：
```
第3段: 10 → 12 → 13 → 20 → 21 → 22 → 40      （跨 27，无规律）
第4段: 1610~1615 → 1620~1627 → 1630~1637 → 1640~1646 → 1650 → 1660 → 1702~1703
```
逐段递增（increment）只能动第 4 段，进位只能动第 3 段 → **两套机制都够不着新版**。
实测 2026-10：官网 API（`client-version-quality.xunlei.com/ci/v1/public/versionManage/versions/latest`）、
官网下载页、winget 索引、腾讯软件中心**全部停在 25.1.13.1637**，只有 CDN 已上架 25.1.40.1703。

**解决**：`detect_type: 'thunder_cdn'`，常规一轮只要 **1 次论坛页 GET + 十几个 HEAD**：
1. **论坛提示定起点**：迅雷官方论坛的离线包汇总帖（`bbs.xunlei.com/circles/20/posts/63926`）
   由用户维护，新版上线当天就有人贴 CDN 直链，比官方 API 早约一天。正则取帖内最高版本号，
   例如 25.1.40.1702；
2. **CDN 正向探测**：以提示号/线上号里较大者作锚点，同 minor 往后扫 25 个 build，
   命中最大者即最新版（1702 → 1703 一次命中）；
3. **兜底深度扫描**：论坛拿不到时，两阶段扫 build 十位段——先用 build 0/2 探针
   判断哪些段有包（空段只花 82 个请求），再对存在的最高段做 minor/build 全扫；
   900 请求预算，一次即可从 1637 追到 1703，又不会打几千请求被封 IP。
   线上包 3 天内更新过则跳过深扫（论坛长期不可用时避免每轮空烧请求）。

```python
{
    'detect_type': 'thunder_cdn',
    'base_version': '25.1.13.1631',
    'url_pattern': 'https://down.sandai.net/thunder_pc/ThunderSetup{ver}xl.exe',
    'thunder_hint_url': 'https://bbs.xunlei.com/circles/20/posts/63926',
    'thunder_forward_span': 25,   # 锚点之后探测多少个 build
    'thunder_minor_span': 40,     # 深度扫描：第3段窗口
    'thunder_seg_span': 8,        # 深度扫描：build 十位段窗口
    'thunder_deep_budget': 900,   # 深度扫描请求预算
    'thunder_workers': 8,
    'detect_timeout': 100,
}
```

**要点**：
- 扫描锚点自动取 **max(线上版本, base_version, 论坛提示)**，配置落后也能自愈；
- 论坛只是「提示」，最终版本一律以 CDN HEAD 存在性为准（提示号不存在也不会写进 data.json）；
- 探测用 HEAD（`check_url(get_fallback=False)`），不触发 200MB 包的 GET 兜底；
- ⚠️ `down.sandai.net` 有 advanced rate limit，**几千个并发 HEAD 会直接封 IP**（返回
  403 `deny by advanced rate limit`，冷却约 10 分钟）→ 并发数别调高、深度扫描靠预算兜底；
- 深度扫描每块都补一个「控制探针」（线上已知存在的包），它 404 就判定为限流假阴性并立即停手；
- 404 提示页只有 449 字节且返回 200，靠「体积 < 10000」排除。

### 7. increment + PE版本探测
**原理**：increment 检测到大版本后，用 Range 只下载 PE 头 + `.rsrc` 段读 FileVersion（约 200KB）。

```python
{
    'detect_type': 'increment',
    'pe_version': True,
}
```
**适用**：安装包 PE 头版本与显示版本一致、且比文件名更精确的软件（360浏览器）。
> 微信、YY 等 PE 不可信或解析不出的软件**不要**配 `pe_version`：微信见第 23 节，
> YY 的文件名即真实版本、改用列车扫描（见 6.0）。

### 8. increment + NSIS版本探测
**原理**：解析 NSIS 安装包内 `install.7z` 的版本号文件夹（微信真值来源）。
详见第 23 节；要点：配 `nsis_version: True`，**不要**同时配 `pe_version`（微信 PE 是占位 build）。

### 9. scrape（网页抓取）
**原理**：请求官方页面，用正则提取版本号、日期、下载链接
```python
{
    'detect_type': 'scrape',
    'check_url': 'https://example.com/download',
    'version_regex': r'最新版[:：]\s*(\d+\.\d+\.\d+)',
    'date_regex': r'(\d{4}-\d{2}-\d{2})',
    'download_url_regex': r'(https?://[^\s"]+\.exe)',
    'version': '1.0.0',  # 默认版本优先
}
```
**两步抓取**（Topaz社区）：
```python
{
    'detail_url_regex': r'(https://community\.example\.com/t/[^"]+)',
    'detail_url_index': 0,
}
```
**适用**：版本信息在网页上的软件（Edge、Chrome、Xshell、Topaz）

### 10. RSS/Atom Feed订阅（待融合）
**原理**：订阅软件官网更新日志RSS，解析最新条目
**适用**：有更新日志Feed的软件（Topaz社区、部分开源项目）
**状态**：待探索具体软件的RSS地址

### 11. MD5校验

#### 11.1 基础MD5校验
**原理**：下载完整文件计算MD5
**限制**：>100MB跳过（increment模式），>500MB强制跳过
**适用**：小文件完整性校验

#### 11.2 MD5流式计算法（推荐，大文件适用）

**核心原理**：检测到新版本后，流式下载文件并逐块更新MD5哈希，**不保存完整文件到磁盘**，内存占用恒定（64KB缓冲区）。

**适用场景**：
- PDFelement等大文件（200MB+）需要MD5校验
- 磁盘空间有限的CI/CD环境（GitHub Actions）
- 需要对已有版本补全MD5的场景

**实现要点**：
```python
import urllib.request
import hashlib

def calc_md5_streaming(url, max_size=500*1024*1024, timeout=300):
    """流式下载计算MD5，不保存文件"""
    md5 = hashlib.md5()
    total = 0
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content_length = int(resp.headers.get('Content-Length', 0))
        if content_length > max_size:
            return None  # 超过大小限制，跳过
        while True:
            chunk = resp.read(65536)  # 64KB块
            if not chunk:
                break
            md5.update(chunk)
            total += len(chunk)
    return md5.hexdigest(), total
```

**关键参数**：
- 缓冲区：64KB（`65536`字节），平衡CPU和IO效率
- 大小限制：默认500MB，超过跳过
- 超时：默认300秒（大文件下载需要足够时间）
- User-Agent：必须设置，部分CDN会拒绝默认Python UA

**pdfelement-changelog项目应用**：
- 探测到新版本后自动调用流式MD5计算
- 对已有版本MD5缺失时自动补全（如13.0.4补全MD5）
- 下载速度约10MB/s，207MB文件约19秒完成

**优点**：
- 不占用磁盘空间（GitHub Actions runner磁盘有限）
- 内存占用恒定（仅64KB缓冲区+哈希状态）
- 可中途取消，无临时文件残留

---

## 新增软件探测方式选择流程

> ⚠️ **新增软件必须先走工作流技能 `.trae/skills/add-software-detection/SKILL.md`**：
> 按决策树定型 → 配置 → `--only` 验证判据 → 通过后入库。
> 禁止跳过分析直接裸配 `increment`（既不稳又慢）。下面的流程图是该技能的速览版。

```
1. 软件是否有官方更新检查API？
   ├─ 是 → 优先级1：官方API（需逆向签名）
   └─ 否 ↓

2. 是否能在腾讯软件中心/winget查到？
   ├─ 是 → 优先级2：第三方API（1次请求，推荐）
   └─ 否 ↓

3. 是否GitHub托管？
   ├─ 是 → 优先级3：GitHub Releases API
   └─ 否 ↓

4. 官方是否提供固定下载地址？
   ├─ 是 → 地址是否302跳转？
   │       ├─ 是 → redirect模式
   │       └─ 否 → fixed+变化检测（版本从其他源获取）
   └─ 否 → 下载地址是否含版本号？
           ├─ 是 → increment+多级进位模式
           │       ├─ 安装包是NSIS且install.7z有版本文件夹？→ 加nsis_version
           │       │      └─ 该值即真实版本？→ 同时声明 version_authority: 'nsis'
           │       │         （PE头若是占位 build，不要加 pe_version，否则会被防降级拦截顶掉）
           │       ├─ PE头版本与显示版本不同（且可信）？→ 加pe_version
           │       └─ 版本号可能不连续/跨版本？→ 已自动支持进位
           └─ 否 → 版本信息是否在网页上？
                   ├─ 是 → scrape模式
                   └─ 否 → 需人工研究其他方式
```

---

## 效率优化记录

| 优化项 | 优化前 | 优化后 | 提升 |
|--------|--------|--------|------|
| increment跳过版本 | 遇404停止 | 跳过最多5个 | 微信可检测到跳过版本 |
| increment跨版本 | 只递增最后一段 | 多级进位（最多2次） | 可探测25.1.15、25.2.0 |
| 微信版本探测 | 手动维护4.1.13.65 | NSIS自动获取4.1.15.50 | 全自动 |
| NSIS版本探测 | 下载244MB完整包 | 下载3.2MB头尾 | 98.7%流量节省 |
| 微信明细版本 | 被PE占位值4.1.15.1000顶掉 | 权威源(nsis)放行，显示真值4.1.15.50 | 2026-10-09 修复 |
| 7z工具依赖 | 需系统安装p7zip | 内置tools/7zz | 跨环境可用 |
| 单软件超时 | 无（一个卡住全部卡住） | 45秒超时+重试2次 | 可靠性提升 |
| 检测失败处理 | 覆盖为空 | 保留上次成功数据 | 数据不丢失 |
| MD5计算 | 全文件下载 | >100MB跳过 | 大文件不超时 |
| 检测方式 | 串行逐个 | 并行8线程 | 5-10分钟 → 1.5分钟 |
| 工作流 | 单3小时全量 | 每小时 快检+资源站(fast,normal,resource) + 每30分钟 全量非资源站(fast,normal,slow) | 资源站单独降频，避免被限流 |
| PE缓存 TTL | 固定6h | LM/size 没变时 HEAD 续期 | CDN长期缓存场景不误废 |
| fixed+pe_version | 每次都 Range 下载 PE | 先发 HEAD 比 LM/size 没变就跳过 | 省掉 90% 的 Range 请求 |
| 优先级分层 | 一刀切全跑 | fast(15)/normal(48)/slow(21)/resource(8) 四层 | hourly 58s vs full 79s |
| 单软件检测 | 不支持 | --only + --priority 参数 | 调试/分层调度 |
| 变更即推 | 跑完等 cron 下一轮 | 每轮跑完立即 embed+push | 版本变更 1 分钟内推前端 |
| YY跨版本探测 | 逐段递增（够不着第2段） | 列车扫描两轮并发（见6.0） | 59→60 可探测，1.4s → 0.5s |

---

## 第三方API融合计划

### 已实现 ✅

#### GitHub Releases API（detect_github_release）
- [x] 封装 `detect_github_release(product)` 函数
- [x] Edge/Chrome安装器、开源工具使用API获取最新版
- [x] 支持多资产筛选（按文件名正则匹配）
- [x] 自动获取发布日期和文件大小

#### 蓝奏云API（detect_lanzou）
- [x] 封装 `detect_lanzou(product)` 函数
- [x] 自动提取页面动态参数（t/k/fid/uid/puid）
- [x] 调用 `filemoreajax.php` API获取文件列表
- [x] 解析文件名版本号、大小、相对日期

#### Luminar专用API（detect_luminar_api）
- [x] 封装 `detect_luminar_api(product)` 函数
- [x] 访问 `http://luminarneowin.skylum.com/` 获取XML配置
- [x] 自动解析版本号和离线包地址（含随机令牌）
- [x] 用curl探测真实文件大小和Last-Modified

### 待实现 🔲

#### 腾讯软件中心API
- [ ] 封装 `detect_tencent_api(keyword)` 函数
- [ ] API：`https://s.pcmgr.qq.com/tapi/web/searchcgi.php?type=search&keyword=xxx`
- [ ] 返回字段：ver(版本)、fs(大小)、url(下载地址)、ux(更新时间)
- [ ] 微信、迅雷、QQ音乐、搜狗、YY 添加API验证源
- [ ] API失败自动降级到increment探测

#### winget仓库API
- [ ] 封装 `detect_winget_api(package_id)` 函数
- [ ] API：`https://winget.run/api/v1/packages/{package_id}`
- [ ] 从manifest提取版本号和下载URL
- [ ] Edge、Chrome、VS Code等添加winget源

#### 通用JSON API（api_json）
- [ ] 封装通用 `detect_api_json(product)` 函数
- [ ] 配置：`api_url`、`version_jsonpath`、`url_jsonpath`、`size_jsonpath`、`date_jsonpath`
- [ ] 支持自定义请求头（User-Agent、Referer等）
- [ ] 支持GET/POST请求方式
- [ ] 适用于所有返回JSON的公开API

---

## 已知限制

1. **QQ音乐**：防盗链严格，所有Referer返回403，sign无法自动生成，下载地址指向官网页
2. **Topaz系列**：Cloudflare 403拦截Python urllib，大小用固定值，日期从社区帖子抓取
3. **Xshell**：下载需邮箱接收随机地址，版本从更新历史页抓取
4. **Flash Player**：下载地址是网页，版本从flash-player-links页面抓取
5. **XYplorer**：官网偶尔超时，版本用配置默认值优先
6. **腾讯软件中心 API**：尚未融合；winget 官方索引已融合（见第36节），Luminar/蓝奏云/GitHub API已实现

---

## 14. CyberLink PowerDirector 探测方式（detect_type = cyberlink）

### 特点
- 离线安装包是自解压7z格式，包含PE加载器 + 7z资源包
- 直链里的 VID 令牌会随版本更新而变化，硬编码必然失效
- 官方下载页面本身不直接暴露完整离线包直链，只给一个「下载器」

### 自动探测流程（无需硬编码令牌）
1. `GET https://www.cyberlink.com/api/download/thank-you-page?ProductId={pid}&ostype=Windows`
   （`ProductId`: PowerDirector=4，PhotoDirector=211）→ 返回 JSON 里的 `buildLink`
2. 跟随 `buildLink`（`/prog/trial/user-add.do?...`）的 302，拿到 `build.cyberlink.com/Retail/{产品}/{令牌}/CyberLink_{产品}_Downloader.exe`
   —— 这里的令牌是官方实时下发的，天然不会过期
3. 下载该下载器（约 10MB），用 7z 解出内部 `$_1_/info.ini`，读取 `DisplayBuildNumber`
   —— 即当前官方产品版本号（PowerDirector 实测 `25.0.0904.0`）

### 关键点
- 版本号来自官方下载器内部元数据，随官方更新自动刷新，不再需要手动维护
- 离线包直链仍用配置里的（如 `PowerDirector_DirectorSuite365.exe`）；大小/日期用 HEAD 刷新
- `_cyberlink_extract_build()` 只下载 ≤40MB 的下载器，不会去拉 700MB 的完整离线包
- 7z 命令查找顺序：`7z`/`7zz`/`7za`/`tools/7zz`

### 配置示例
```python
{
    'name': 'PowerDirector',
    'detect_type': 'cyberlink',
    'cyberlink_product_id': 4,          # PowerDirector=4
    'version': '25.0.0.0904.0',          # 兜底值，探测失败时使用
    'size': 691 * 1024 * 1024,
    'md5': 'be7750903c07baa523c0ab0328a1b27a',
    'download_url': 'https://build.cyberlink.com/Retail/PowerDirector/.../PowerDirector_DirectorSuite365.exe',
}
```

### 注意事项
- 该下载器的 `DisplayBuildNumber` 对 PowerDirector 等于产品版本，可信
- PhotoDirector 的下载器 `info.ini` 是其自身框架版本（如 17.6.1826.0），≠ 产品版本（18.x），
  配 `cyberlink_trial_version_trusted=False` 后不用试用值当产品版本号
- 官方「最新版」不等于下载站的破解版；官方离线包更新有滞后（见下）
- 版本号一律过 `_cyberlink_canon_ver()` 归一成 4 段式：`25.0.0.0904.0`（5 段 PE 式）与
  `25.0.0904.0`（4 段 info.ini 式）按段比较不相等，混用会把防降级保护击穿；
  build 段补齐前导零（`904` → `0904`），与官方 DisplayBuildNumber 写法一致

### 14.1 根治「版本永远停在 0904」：零售版版本源（2026-10-25）

**现象**：PowerDirector 在站点上长期显示旧版（先是 `25.0.1007.0`，实为人工核实的值），
而实际最新版已是 `25.0.1019.0`（CyberLink PowerDirector Ultimate 2027）。

**根因（两条官方通道都取不到零售新构建）**：
1. **官方 trial 通道恒定滞后**：`/api/download/thank-you-page?ProductId=4` → 试用下载器
   → info.ini 的 `DisplayBuildNumber=25.0.0904.0`（VDE260910-01），实测长期不变；
   零售新构建（`25.0.1007.0` / `25.0.1019.0`）只走买断/零售通道，匿名通道取不到。
2. **旧办法是写死 `version_display`**（=人工核实的最新零售版号），等于把版本钉死在一个
   常量上——官方再发新版它也不会动，只能人工改一次。这就是「停在旧版很久」的真正原因，
   不是探测失败，是**架构上就没有能自动发现零售新版的源**。

**已排查且无效的官方渠道**（2026-10-25 逐个实测）：
| 渠道 | 结果 |
|------|------|
| `support.cyberlink.com/patch-download`（官方补丁中心） | PowerDirector 产品线只到 **2025**（prodVerId=2051）及其更早，无 2026/2027 线；2027 零售版没有补丁页 |
| `support.cyberlink.com` 的 Next.js 数据 | 内嵌 `productId→prodVerId` 映射（同上，只有 2025 及更早） |
| `www.cyberlink.com/api/download/box`（零售兑换） | 需有效产品密钥 + 人机验证，无密钥拿不到直链 |
| `ProductId=270`（PowerDirector Ultimate Suite） | thank-you API 正常、302 指向 `update.cyberlink.com/Retail/PowerDirectorUltimateSuite/DL/{token}/`，但该 S3 对象匿名可下性为 **403 AccessDenied**（token 每次下发但对象不对外） |
| `www.cyberlink.com/api/download/thank-you-page` 全量 ProductId 扫描（1~700） | 只有 `ProductId=4`（PowerDirector trial）与 `211`（PhotoDirector）可用，其余跳 `trials/index` |
| 官方下载器二进制（解包 NSIS） | 只含 `info.ini`/`Product.ini`/`Custom.ini`（`vtype=trial`），无版本查询接口、无零售直链 |
| 零售离线包（691MB）内 `info.ini` | 用 HTTP Range + py7zr 只拉 0.07MB 列出 9947 个条目：**纯资源包，无 info.ini**（与旧文档记录一致） |
| `dna.cyberlink.com/dna/getconfig.jsp` | 只是遥测频率配置（`{"First_Interval":5,...}`），无版本信息 |

**最终方案（已落地）**：新增 `cyberlink_retail_nsane` 零售版版本源。
- 源：**nsane 论坛「Software Updates」板块列表页**（`/forum/48-software-updates/`）。
  该板块惯例是「一个软件更新开一个新帖」，**标题即精确版本号**
  （如 `CyberLink PowerDirector Ultimate 2027 v25.0.1019`），列表页匿名可读（正文需登录）。
- 解析：`_cyberlink_retail_from_nsane()` 用 `cyberlink_retail_keywords` 限定产品
  （避免把别的软件的版本号误当本产品），取标题里最大版本号 + 该行发帖时间。
- **双向对齐**：官方 trial 通道与零售源**取较新者**。官方试用通道铺开新版本后自动切到官方值；
  nsane 源给出更旧的号时不会被误用。
- **不再写 `version_display`**：版本号完全由检测得出，官方/资源站一更新就跟上。
- 日期取「零售版发布日」与「包 S3 Last-Modified」中**较晚者**：官方换包滞后时，
  直接用 Last-Modified 会把新版本的日期写回旧包的时间。

**实测**：`--only PowerDirector` → `25.0.0904.0`（trial）+ `25.0.1019.0`（零售）→ 输出
`25.0.1019.0 @ 2026-10-25`，自动完成 `25.0.1007.0 → 25.0.1019.0` 的升级。

**降级保护**：nsane 源不可用时检测值退回 `25.0.0904.0`，会被 `main()` 的防降级拦截
（`_ver_tuple` 比较）保留线上旧版本，不会把版本号写小或写空。

---

## 第15节：网盘类发布渠道探测

### 蓝奏云（lanzou）

**适用场景**：软件通过蓝奏云网盘发布，文件夹内有多个版本文件。

**探测原理**：
1. 访问文件夹页面，从JavaScript中提取动态参数（t时间戳、k密钥、fid、uid、puid）
2. 调用API `POST /filemoreajax.php?file={fid}` 获取文件列表
3. 取第一个文件（最新），从文件名提取版本号，获取大小和日期

**API参数**：
```
lx=2, fid={文件夹ID}, uid={用户ID}, puid={加密用户ID},
pg=1, rep=0, t={时间戳}, k={32位MD5密钥}, up=1
```

**日期格式处理**：
- `2026-07-29` → 直接使用
- `昨天02:14` → 当前日期-1天
- `28天前` → 当前日期-28天

**配置示例**：
```python
{
    'name': 'Shandou Downloader',
    'detect_type': 'lanzou',
    'version_regex': r'(\d{4}\.\d{2}\.\d{2})',
    'download_url': 'https://www.lanzoui.com/b015c0ksh',
}
```

**优点**：自动获取最新版本、大小、日期，无需手动维护
**限制**：下载链接为文件页面（需手动点击下载），非直链

#### detect_lanzou() 函数实现详解

**函数签名**：
```python
def detect_lanzou(product):
    """蓝奏云文件夹探测：自动提取参数→调用API→获取最新文件"""
```

**执行流程（3步反爬突破）**：

**Step 1: 访问文件夹页面，提取动态参数**
```python
url = product['download_url']  # 如 https://www.lanzoui.com/b015c0ksh
resp = requests.get(url, headers=HEADERS)
# 从页面JavaScript中提取：
# - t: 时间戳（10位）
# - k: 32位MD5密钥（页面动态生成）
# - fid: 文件夹ID
# - uid: 用户ID
# - puid: 加密用户ID
```

**Step 2: 调用文件列表API**
```python
api_url = f'https://www.lanzoui.com/filemoreajax.php?file={fid}'
payload = {
    'lx': 2, 'fid': fid, 'uid': uid, 'puid': puid,
    'pg': 1, 'rep': 0, 't': t, 'k': k, 'up': 1
}
resp = requests.post(api_url, data=payload, headers=HEADERS)
data = resp.json()
# data['text'] 为文件列表，按时间倒序
```

**Step 3: 解析最新文件信息**
```python
latest = data['text'][0]  # 第一个为最新文件
version = re.search(product['version_regex'], latest['name_all']).group(1)
size = int(latest['size'])
date = parse_lanzou_date(latest['time'])  # 处理"昨天"/"N天前"等格式
```

**反爬关键技术点**：
1. **动态密钥k**：每次访问页面生成不同的32位MD5密钥，必须实时提取，不能硬编码
2. **时间戳t**：与密钥配对，过期失效（约几分钟）
3. **Referer头**：API请求必须带文件夹页面Referer
4. **Cookie**：首次访问页面获取的cookie需在API请求中保持
5. **User-Agent**：必须模拟浏览器，否则返回空数据

**日期格式处理函数**：
```python
def parse_lanzou_date(date_str):
    if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
        return date_str  # 标准日期
    if '昨天' in date_str:
        return (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    if '天前' in date_str:
        days = int(re.search(r'(\d+)天前', date_str).group(1))
        return (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    return date_str
```

**已验证软件**：闪豆下载器（Shandou Downloader）

### MediaFire

**状态**：❌ 无法自动探测

**原因**：
- MediaFire使用Cloudflare交互式反爬保护
- 公开API `/api/1.5/folder/get_content.php` 返回403
- 页面访问返回403（cloudscraper也无法绕过）
- 需要浏览器执行JavaScript挑战才能获取内容

**解决方案**：
1. 使用fixed模式，手动维护版本号
2. 配置固定大小和日期
3. 下载链接为文件夹页面

**配置示例**：
```python
{
    'name': 'WinNTSetup',
    'detect_type': 'fixed',
    'version': '5.4.2',
    'size': 10 * 1024 * 1024,
    'date': '2026-08-01',
    'is_webpage': True,
    'download_url': 'https://www.mediafire.com/folder/53um6k2nmhvd5/',
}
```

### 其他网盘参考

| 网盘 | 自动探测 | 说明 |
|------|----------|------|
| 蓝奏云 | ✅ | 有公开API，参数可从页面提取 |
| MediaFire | ❌ | Cloudflare保护，需浏览器JS挑战 |
| 百度网盘 | ❌ | 需登录，API复杂 |
| 夸克网盘 | ❌ | 需登录，无公开API |
| 阿里云盘 | ❌ | 需登录，无公开API |
| 123云盘 | 待探索 | 可能有公开API |

**建议**：优先选择蓝奏云等有公开API的网盘作为发布渠道，便于自动探测。


---

## 第16节：scrape + url_pattern 动态构造（PicPick模式）

**适用场景**：软件有changelog页面可抓取版本号，但下载链接包含版本号需要动态构造。

**探测原理**：
1. 访问changelog页面，用正则提取最新版本号
2. 根据版本号动态构造下载链接（`url_pattern.format(ver=version)`）
3. HEAD请求验证下载链接有效性，获取大小和日期

**已验证软件**：PicPick Professional

**配置示例**：
```python
{
    'name': 'PicPick Professional',
    'detect_type': 'scrape',
    'scrape_url': 'https://picpick.app/en/changelog/',
    'version_regex': r'PicPick\s+(\d+\.\d+\.\d+)',
    'url_pattern': 'https://download.picpick.net/{ver}/picpick_inst_pro.exe',
    'download_url': 'https://download.picpick.net/7.6.1/picpick_inst_pro.exe',
}
```

**关键技术点**：
- `version_regex` 必须能从changelog页面HTML中精确匹配版本号
- `url_pattern` 中的 `{ver}` 会被提取到的版本号替换
- 构造后需HEAD请求验证，防止changelog更新了但下载包未上传
- 备用方案：如果动态构造失败，回退到配置中的固定 `download_url`

---

## 第17节：论坛帖子抓取模式（微PE模式）

**适用场景**：软件通过论坛帖子发布，版本号和日期在帖子标题或正文中。

**探测原理**：
1. 访问论坛帖子页面
2. 从帖子标题提取版本号（如"微PE工具箱增强版 v2029.09.06"）
3. 从帖子发布时间获取更新日期
4. 下载链接为帖子页面（非直链）

**已验证软件**：微PE工具箱增强版（bbs.wuyou.net）

**配置示例**：
```python
{
    'name': 'WePE Enhanced',
    'detect_type': 'scrape',
    'scrape_url': 'https://bbs.wuyou.net/forum.php?mod=viewthread&tid=448767',
    'version_regex': r'v?(\d{4}\.\d{2}\.\d{2})',
    'date_regex': r'(\d{4}-\d{1,2}-\d{1,2})',
    'is_webpage': True,
    'download_url': 'https://bbs.wuyou.net/forum.php?mod=viewthread&tid=448767',
    'size': 256 * 1024 * 1024,  # 固定大小（网盘资源，无法自动获取）
}
```

**关键技术点**：
- 论坛通常需要Cookie或特殊User-Agent才能访问
- 版本号命名可能不规则（如日期式版本号 `2026.09.06`）
- 大小通常无法自动获取，需配置固定值
- 日期可能在帖子正文的"更新日期"字段中，而非发帖时间

---

## 第18节：博客文章抓取模式（Foobar2000汉化版模式）

**适用场景**：汉化版/修改版软件通过个人博客发布，版本号在文章标题中。

**探测原理**：
1. 访问博客首页/文章列表页
2. 从最新文章标题提取版本号和更新日期
3. 下载链接为博客页面（需手动查找下载地址）

**已验证软件**：Foobar2000 汉化版（cnblogs.com/asionwu）

**配置示例**：
```python
{
    'name': 'Foobar2000',
    'detect_type': 'scrape',
    'scrape_url': 'https://www.cnblogs.com/asionwu',
    'version_regex': r'foobar2000[^\d]*(\d+\.\d+\.\d+)',
    'date_regex': r'(\d{4}\.\d{2}\.\d{2})',
    'is_webpage': True,
    'download_url': 'https://www.cnblogs.com/asionwu',
    'size': 20 * 1024 * 1024,  # 固定大小
}
```

**关键技术点**：
- 博客平台（博客园/CSDN等）通常有反爬，需设置合理的请求间隔
- 文章标题格式可能变化，正则需有一定容错性
- 汉化版版本号通常与官方版本号一致，日期为汉化发布日期
- 适合作为辅助探测源，不适合作为唯一来源

---

## 第19节：GitHub Releases 多资产处理（Win LTSC分卷模式）

**适用场景**：GitHub Release包含多个分卷文件（如ISO分卷），下载链接为Release页面。

**探测原理**：
1. 调用GitHub Releases API获取最新Release
2. 从tag_name提取版本号（如 `Windows_11_LTSC_2024_X64_ZH-CN-26200.9457-20260914-2218`）
3. 从 `published_at` 获取发布日期
4. 汇总所有资产的总大小
5. 下载链接为Release页面（非单个文件直链）

**已验证软件**：Windows 11 LTSC 2024、Windows 10 LTSC 2021（adavak/win_iso_build）

**配置示例**：
```python
{
    'name': 'Win11 LTSC',
    'detect_type': 'github_release',
    'repo': 'adavak/win_iso_build',
    'tag_regex': r'(\d+\.\d+\.\d+\.\d+)',
    'tag_prefix': 'Windows_11_LTSC_2024_X64_ZH-CN-',
    'is_webpage': True,
    'download_url': 'https://github.com/adavak/win_iso_build/releases',
}
```

**关键技术点**：
- 多资产Release需汇总 `assets[].size` 计算总大小
- tag_name格式可能包含日期和构建号，需用正则精确提取版本号
- 大文件（5GB+）不适合计算MD5，跳过
- 下载链接用Release页面而非单个资产，因为用户需要下载全部分卷

---

## 第20节：CyberLink 复测与零售通道（承接第14节）

> 官方接口的自动探测流程（thank-you-page → buildLink → 解下载器读 DisplayBuildNumber）
> 见第 14 节，不再重复。本节只记录复测结论与买断版零售通道。

**2026-10-09 复测（试用通道滞后 → 防降级）**：
- PD 试用下载器 `LJZVDVSX0QV1A/CyberLink_PowerDirector_Downloader.exe`（9.4MB）→
  `DisplayBuildNumber=25.0.0904.0`（SR_No=VDE260910-01）；离线包 `CGQC8ZH75VM6` 直链
  Last-Modified 仍为 2026-09-14 —— 官方渠道尚未铺开 1007
- 最新构建 `25.0.1007.0` 为 Ultimate 零售版（本地包 info.ini：`SR_No=VDE261008-02`、
  `Kernel=1007_25.0.10_365`，2026-10-08）；版本显示用
  `base_version='25.0.0904.0'` + `version_display='25.0.1007.0'` 兜底，官方铺开后自动对齐
- PhD 试用下载器 `430LJXSN7DH2N0`（8.2MB）→ `DisplayBuildNumber=17.6.1826.0`、
  `SR_No=PTD260514-01`，再次确认 ≠ 产品版本 18.x，fixed 模式维持
- 下载站（0daydown 等）会推送尚未铺开的构建（如 `25.0.1005.1`），
  属零售/破解版，官方接口取不到，**不能**当作官方最新版

### 20.1 买断版（Ultimate / Ultra）零售通道：产品密钥兑换

**适用场景**：PowerDirector 2027 Ultimate 等买断版。公开的试用下载器只给 `vtype=trial`
的 `25.0.0904.0`，零售构建（如 `25.0.1005.1`）走的是「产品密钥兑换」通道。

**兑换接口**（从兑换页 `https://www.cyberlink.com/box` 打包 JS 逆出）：
```
POST https://www.cyberlink.com/api/download/box
Content-Type: application/json
{"key": "<产品密钥>", "lang": "ENU", "recaptchaToken": ""}
```
- 成功：`{"status":"OK","data":{"productName":...,"buildlist":[{"buildName":...,
  "fileList":[{"url":...,"fileSizeInBytes":...}]}]}}`，`fileList[].url` 即零售安装包直链
- 失败：`{"status":"FAIL","data":null}`；需人机验证：`{"needVerify":true}`
- 密钥校验：长度 4–35，字符集 `[A-Za-z0-9-]`

**接入方式**：`detect_cyberlink` 读环境变量 `CYBERLINK_RETAIL_KEY`（多个逗号分隔）或产品配置
`retail_product_key`，兑换到直链就用它当 `download_url`；文件名含 4 段版本号时覆盖版本。
未配置密钥时该分支完全跳过，不影响官方接口探测。

**历史零售直链规律**（`update.cyberlink.com` 老包实测仍可 HTTP 200 下载；不存在的路径返回 403，
故以 `HTTP 200 + Content-Length` 判断命中）：

| 时期 | 路径模板 |
|------|----------|
| 早期 PD13-16 | `/Retail/PowerDirector/{SR_No}/{TR_No}/PowerDirector_{build}_GM2_{Ed}_{SR_No}.exe` |
| 推广/赠品(event) | `download.cyberlink.com/ftpdload/event/{SR_No}/PowerDirector_{ver}_{GMx}_{Ed}_{SR_No}.exe` |
| 中期 PD17 | `/Retail/PowerDirector/{Token}/PowerDirector_{build}_{Ed}_{SR_No}.exe` |
| 卷授权 PD18 | `/License/PowerDirector/{Token}/PowerDirector_{build}_GM2.1_{Ed}_{SR_No}.exe` |

`{Token}` 是服务端随版本下发的随机码，无法推算；批量枚举 480 条「当前版本」候选路径全部未命中，
印证**当前版本零售直链只能靠密钥兑换**（见 `redeem_retail_builds` / `_cyberlink_retail_redeem`）。

**线索来源**：nsane 论坛赠品帖回复里给过旗舰版离线包地址 + 共享密钥
（如 PhotoDirector 4 的 `download.cyberlink.com/ftpdload/event/PTD131121-03/...`，
密钥贴在 paste2）。这些 event 包现已失效，但确立了零售通道的路径形态。

**验证记录**：
- `POST /api/download/box` 无效密钥 → `{"status":"FAIL","data":null,"needVerify":false}` ✓
- 3 条历史旗舰包 URL → HTTP 200 + 真实 Content-Length（PD17 包 1.01GB 等）✓
- 下载器 `info.ini` 解析：`SR_No=VDE260910-01`、`TR_No=TR260911-070`、`DisplayBuildNumber=25.0.0904.0` ✓

---

## 第21节：Discourse 社区论坛抓取（Topaz模式）

**适用场景**：软件通过Discourse社区论坛发布版本更新，版本号和日期在帖子标题中。

**探测原理**：
1. 访问Discourse社区的发布分类页面（如 `/c/topaz-photo/topaz-photo-releases/117`）
2. 从帖子列表JSON API（`.json`后缀）获取最新帖子
3. 从帖子标题提取版本号（如"Topaz Photo 1.7.1 Released"）
4. 从帖子 `created_at` 获取发布日期
5. 构造下载链接：`https://downloads.topazlabs.com/deploy/{Product}/{ver}/{Product}-{ver}.msi`

**已验证软件**：Topaz Photo、Topaz Gigapixel、Topaz Video

**Discourse API调用**：
```python
def detect_discourse_release(category_url, version_regex):
    \"\"\"从Discourse社区获取最新发布版本\"\"\"
    api_url = category_url.rstrip('/') + '.json'
    resp = requests.get(api_url, headers=HEADERS)
    data = resp.json()
    # 取最新帖子
    latest_topic = data['topic_list']['topics'][0]
    title = latest_topic['title']
    created_at = latest_topic['created_at']  # ISO格式
    version = re.search(version_regex, title).group(1)
    return version, created_at
```

**关键技术点**：
- Discourse论坛支持在URL后加 `.json` 获取结构化数据，无需解析HTML
- 帖子标题格式可能变化（"Released"、"Update"等），正则需容错
- 发布日期以帖子创建时间为准，而非编辑时间
- 下载链接版本号需与帖子标题中的版本号一致
- 测试版可能先发布，需区分稳定版和测试版

---

## 第22节：PE资源段读取版本号（360/QQ音乐模式）

**适用场景**：安装包文件名只有大版本号（如 `WeChatWin_4.1.15.exe` 这类只带大版本的命名），但安装后显示详细小版本号。

> ⚠️ **不是所有软件都适用**：得先确认 PE 里的 FileVersion 就是产品真实版本。
> 反例：微信安装包 PE 的 FileVersion 是占位 build `4.1.15.1000`（真值在 install.7z，见第23节）；
> YY 安装包的 PE 解析不出 FileVersion，且文件名本身即真实版本（见 6.0 列车扫描）。
> 这类软件**不要**配 `pe_version`。

**探测原理**：
1. 下载安装包（或用Range请求只下载PE头部分）
2. 解析PE文件的 `.rsrc` 资源段
3. 读取 `VS_VERSION_INFO` 中的 `FileVersion` 或 `ProductVersion`
4. 获取详细的四段式版本号

**PE版本号读取实现**：
```python
import struct

def read_pe_version(filepath_or_url, max_read=1024*1024):
    \"\"\"从PE文件资源段读取版本号，只需下载前1MB\"\"\"
    # 下载前1MB（PE头+资源段通常在前1MB内）
    headers = {'Range': f'bytes=0-{max_read-1}', 'User-Agent': UA}
    resp = requests.get(filepath_or_url, headers=headers, stream=True)
    data = resp.content
    
    # 解析PE头定位资源段
    e_lfanew = struct.unpack_from('<I', data, 0x3C)[0]
    # ... 解析节表找到.rsrc段
    # ... 遍历资源目录找到VS_VERSION_INFO
    # ... 读取FileVersion字符串
    
    return file_version  # 如 "4.1.15.9"（仅当该值与产品真实版本一致时才可用）
```

**已验证软件**：360浏览器系列、QQ音乐（微信、YY 不适用，见下方说明）

**关键技术点**：
- 只需下载PE文件前1MB（资源段通常在文件前部），用 `Range` 请求
- VS_VERSION_INFO中的版本号是Unicode字符串（UTF-16LE）
- 部分软件的 `FileVersion` 和 `ProductVersion` 可能不同，以 `ProductVersion` 为准
- NSIS安装包的版本号可能在安装包外层，也可能在内部payload中
- 此方法可作为increment探测的补充，获取更精确的小版本号

---

## 第23节：7z内部版本号探测（微信详细版本模式）

**适用场景**：安装包是 NSIS/7z 自解压格式，内部 `install.7z` 的**版本号文件夹名**就是产品真实版本。

**探测原理**（实现见 `check_versions.py` 的 `get_nsis_install_version`，**无需下载完整包**）：
1. 取 PE 头(1KB) → 算 overlay 偏移，定位 NSIS 数据段
2. 取 NSIS 头部(3MB) → 搜 `37 7A BC AF 27 1C` 7z 签名，拿到 install.7z 偏移
3. 取 install.7z 头 32B → 读 `next_header_offset/next_header_size`，算出精确大小
4. 取 install.7z 头 32KB + 尾 128KB → 构造稀疏文件，用 py7zr / 7z 列出条目
5. 取第一个 `\d+\.\d+\.\d+\.\d+/` 目录名即真实版本

**总下载量**：约 3.2MB（vs 完整包 244MB，省 98.7%）；**单软件耗时**：约 3～4 秒。

**配置**：
```python
{
    'detect_type': 'increment',
    'nsis_version': True,          # 启用 NSIS 版本解析
    'version_authority': 'nsis',   # 该值即真实版本 → 防降级拦截放行（第38节）
    # 不要配 pe_version：微信 PE 是占位 build，会把真值顶掉
}
```

**已验证软件**：微信（WeChat）——真值 `4.1.15.50`（对应文件名 `WeChatWin_4.1.15.exe`）

**关键技术点**：
- 真值来自 install.7z 内的版本号目录，比 PE 的占位 build 可信，故声明为权威源
- 抽头尾构造稀疏文件即可列目录（7z 目录在文件尾），不需要整包下载
- 依赖 py7zr（CI 已装）或内置 `tools/7zz`；两者都没有时跳过，退回 increment 版本

---

## 第24节：固定地址 + 文件名版本号提取（IObit/Vuescan/WinCam模式）

**适用场景**：下载地址固定不变，但文件名包含版本号，每次更新文件名变化。

**探测原理**：
1. 访问固定下载地址（如 `https://cdn.iobit.com/dl/driver_booster_setup.exe`）
2. 从响应头 `Content-Disposition` 或重定向URL中提取文件名
3. 从文件名中正则提取版本号
4. 从 `Last-Modified` 获取更新日期，`Content-Length` 获取大小

**已验证软件**：IObit Driver Booster、IObit Uninstaller、Vuescan、WinCam

**配置示例**：
```python
{
    'name': 'IObit Driver Booster',
    'detect_type': 'fixed',
    'download_url': 'https://cdn.iobit.com/dl/driver_booster_setup.exe',
    'version_from_filename': True,  # 从文件名提取版本号
    'version_regex': r'(\d+\.\d+\.\d+\.\d+)',
}
```

**关键技术点**：
- 固定地址可能通过302重定向到带版本号的文件名
- 需跟随重定向，从最终URL或Content-Disposition提取文件名
- `Last-Modified` 响应头可作为更新日期
- 部分CDN不返回Content-Length，需用HEAD请求确认

---

## 第25节：increment 无分隔符版本号探测（AIDA64模式）

**适用场景**：版本号在URL中无分隔符（如 `aida64extreme840.zip` 代表 `8.40`）。

**探测原理**：
1. 基础版本号转换为无分隔符格式（如 `8.40` → `840`）
2. 递增探测：`840` → `841` → `842` ...
3. 找到最新存在的版本后，转换回带分隔符格式

**配置示例**：
```python
{
    'name': 'AIDA64',
    'detect_type': 'increment',
    'base_version': '8.40',
    'url_pattern': 'https://download.aida64.com/aida64extreme{ver_nosep}.zip',
    'version_nosep': True,  # URL中版本号无分隔符
    'version_display': '{major}.{minor:02d}',  # 显示格式
}
```

**关键技术点**：
- 需配置 `version_nosep: True` 标记URL中版本号无分隔符
- 递增时需注意进位：`8.99` → `9.00`（无分隔符 `899` → `900`）
- 显示格式需单独配置（如 `8.40` 而非 `8.4`）
- 类似软件：WinHex（`winhex.zip` 固定名，版本号在PE头中）

---

## 第26节：第三方GitHub + 官方CDN融合（Edge/Chrome模式）

**适用场景**：官方不提供版本API，但第三方GitHub仓库持续追踪最新版，官方CDN提供下载直链。

**探测原理**：
1. 从第三方GitHub Releases获取最新版本号（如 Bush2021/edge_installer）
2. 根据版本号规律构造官方CDN下载链接
3. HEAD请求验证官方CDN链接有效性
4. 从官方CDN获取大小和日期

**已验证软件**：Microsoft Edge、Google Chrome

**配置示例**：
```python
{
    'name': 'Microsoft Edge',
    'detect_type': 'github_release',
    'repo': 'Bush2021/edge_installer',
    'version_source': 'github',  # 版本号来源
    'download_source': 'official_cdn',  # 下载来源
    'url_pattern': 'https://msedge.sb.tlu.dl.delivery.mp.microsoft.com/filestreamingservice/files/{file_id}?P1={timestamp}&P2=404&P3=2&P4={signature}',
    'official_site': 'https://github.com/Bush2021/edge_installer',
}
```

**关键技术点**：
- 版本号从第三方GitHub获取，下载链接从官方CDN获取
- Edge的CDN链接包含动态签名（P4参数），有时效性，需从第三方仓库获取
- Chrome的CDN链接格式固定：`https://dl.google.com/release2/chrome/{hash}_{ver}/{ver}_chrome_installer_uncompressed.exe`
- 第三方仓库可能更新不及时，需多源交叉验证
- 适合作为官方API不可用时的替代方案

---

## 第27节：多 url_pattern 降级探测（PDFelement模式）

**适用场景**：软件下载URL的build号可能变化（如 `_full5239.exe` → `_full.exe`），单一pattern会失效。

**探测原理**：
1. 配置多个 `url_patterns`（按优先级排序）
2. 对每个版本号，依次尝试所有pattern
3. 第一个返回200的pattern即为有效下载链接
4. 后续版本优先使用上一次成功的pattern

**已验证软件**：Wondershare PDFelement

**配置示例**：
```python
{
    'name': 'Wondershare PDFelement',
    'detect_type': 'increment',
    'base_version': '13.0.0',
    'url_patterns': [
        'https://download.wondershare.com/cbs_down/pdfelement-pro_{ver}_full5239.exe',  # 当前
        'https://download.wondershare.com/cbs_down/pdfelement-pro_{ver}_full.exe',       # 备用
        'https://download.wondershare.com/cbs_down/pdfelement-pro_{ver}.exe',            # 兜底
    ],
    'url_pattern': 'https://download.wondershare.com/cbs_down/pdfelement-pro_{ver}_full5239.exe',  # 兼容旧字段
}
```

**detect_increment 中的实现**：
```python
url_patterns = product.get('url_patterns', [product['url_pattern']])

def get_version_url(version):
    for pattern in url_patterns:
        test_url = pattern.format(ver=_url_ver(version, product))
        exists, size, date = check_url(test_url, referer=referer)
        if exists:
            return test_url, exists, size, date
    last_url = url_patterns[-1].format(ver=_url_ver(version, product))
    return last_url, False, 0, ''
```

**关键技术点**：
- `url_patterns` 按优先级排序，第一个成功的优先使用
- 兼容旧字段 `url_pattern`（如果没有 `url_patterns` 则回退到单个pattern）
- 每次版本探测都会尝试所有pattern，确保build号变化时能自动适配
- 适合软件厂商更改URL命名规则的场景

---



---

## 通用API探测模板（api_json / api_xml，待实现）

### 设计目标
封装通用API探测函数，支持任意返回JSON或XML的公开API，无需为每个软件编写专用函数。

### api_json 配置模板

```python
{
    'name': '示例软件',
    'detect_type': 'api_json',  # 通用JSON API探测
    'api_url': 'https://api.example.com/v1/version',
    'api_method': 'GET',  # GET或POST
    'api_headers': {  # 自定义请求头
        'User-Agent': 'ExampleApp/1.0',
        'Referer': 'https://example.com/',
    },
    'api_params': {  # GET参数或POST数据
        'product': 'xxx',
        'version': 'current',
    },
    'version_jsonpath': 'data.version',  # 版本号JSON路径
    'url_jsonpath': 'data.download_url',  # 下载地址JSON路径
    'size_jsonpath': 'data.size',  # 大小（可选）
    'date_jsonpath': 'data.release_date',  # 日期（可选）
    'md5_jsonpath': 'data.md5',  # MD5（可选）
    'date_format': '%Y-%m-%d',  # 日期格式（可选）
}
```

### api_xml 配置模板

```python
{
    'name': '示例软件',
    'detect_type': 'api_xml',  # 通用XML API探测
    'api_url': 'https://api.example.com/config',
    'api_headers': {'User-Agent': 'Other'},
    'version_xpath': '//Version/text()',  # 版本号XPath
    'url_xpath': '//DataUrl/text()',  # 下载地址XPath
    'encoding': 'utf-8',  # 编码（XML声明可能不准确）
    'size_from_headers': True,  # 从下载地址HTTP头获取大小
    'date_from_headers': True,  # 从下载地址HTTP头获取日期
}
```

### 通用探测函数伪代码

```python
def detect_api_json(product):
    """通用JSON API探测"""
    url = product['api_url']
    headers = product.get('api_headers', {})
    params = product.get('api_params', {})
    
    if product.get('api_method') == 'POST':
        req = urllib.request.Request(url, data=json.dumps(params).encode(), 
                                      headers={**headers, 'Content-Type': 'application/json'})
    else:
        if params:
            url += '?' + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=headers)
    
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    
    # 按JSON路径提取字段
    version = _get_by_jsonpath(data, product['version_jsonpath'])
    download_url = _get_by_jsonpath(data, product['url_jsonpath'])
    size = _get_by_jsonpath(data, product.get('size_jsonpath', ''), 0)
    date = _get_by_jsonpath(data, product.get('date_jsonpath', ''), '')
    
    # 大小/日期从HTTP头获取（如果配置了）
    if product.get('size_from_headers') and download_url:
        size, lm = _curl_get_headers(download_url)
        if lm and product.get('date_from_headers'):
            date = parse_date(lm)
    
    return version, download_url, download_url, size, date, ''
```

### JSON路径提取工具函数

```python
def _get_by_jsonpath(data, path, default=None):
    """简单JSON路径提取，支持点分隔路径：data.version"""
    if not path:
        return default
    keys = path.split('.')
    result = data
    for key in keys:
        if isinstance(result, dict) and key in result:
            result = result[key]
        else:
            return default
    return result
```

### 适用场景

| API类型 | 代表软件 | 探测方式 |
|---------|----------|----------|
| 官方更新检查API | PDFelement（待签名） | api_json |
| 第三方软件库API | 腾讯软件中心/winget | api_json |
| 专用安装器API | Luminar Neo（已实现） | api_xml → luminar_api |
| 网盘API | 蓝奏云（已实现） | api_json → lanzou |
| 开源平台API | GitHub（已实现） | api_json → github_release |

### 实现优先级

1. **api_json**（通用JSON）→ 可覆盖腾讯/winget/PDFelement等多数API
2. **api_xml**（通用XML）→ 可覆盖Luminar类安装器API
3. **多源融合** → API探测失败自动降级到increment/scrape


## 探测方式速查表

| 探测方式 | 代表软件 |
|----------|----------|
| increment + 多级进位 | 雷电、迅雷、Adobe Camera Raw、PDF-XChange |
| increment + 列车扫描 | YY |
| increment + NSIS 权威源 | 微信 |
| increment + PE | 360浏览器 |
| fixed + 文件名提取 | IObit系列、Vuescan、WinCam、WinHex |
| fixed + PE | IObit Driver Booster、AnyDesk |
| fixed + 官网页面版本 | Bandizip |
| github_release | Edge、Win LTSC、Notepad4、Open-Shell、MPC-BE、Operit、GKD |
| scrape | PicPick、微PE、Foobar2000、Xshell、Topaz系列 |
| fixed（纯固定） | WPS、WinNTSetup、XYplorer、XMind |
| lanzou（蓝奏云网盘API） | 闪豆下载器 |
| cyberlink | PowerDirector |
| redirect | 搜狗输入法 |
| 外部页面引用 | Adobe Flash Player |
| luminar_api（XML API） | Luminar Neo |

**更新日期**：2026-10-13（新增 Bandizip、MPC-BE、Wondershare EdrawMax；Open-Shell 改用 exe 资产直链）


### 天翼云盘分享探测 (detect_189pan)

**适用场景**：天翼云盘(cloud.189.cn)带提取码的分享链接，自动获取文件最后更新日期。

**API端点**（无需签名，公开可访问）：
```
GET https://api.cloud.189.cn/open/share/getShareInfoByCode.action?shareCode={分享码}
```

**返回XML关键字段**：
| 字段 | 说明 |
|------|------|
| `<fileName>` | 分享文件/文件夹名称 |
| `<fileLastOpTime>` | 最后操作时间（最新更新日期），格式 `2026-09-12 16:33:32` |
| `<shareDate>` | 分享创建时间 |
| `<fileId>` | 文件ID |

**探测流程**：
1. 从分享链接提取shareCode（`code=`参数）
2. 调用`getShareInfoByCode.action`API
3. 解析XML中的`fileLastOpTime`，取日期部分作为更新日期
4. 版本号固定为配置值（如Win10/11），大小显示"-"

**关键发现**：
- 无需登录、无需签名、无需提取码验证即可获取更新日期
- 提取码仅用于访问文件内容，不影响元数据API
- `fileLastOpTime`是文件夹内所有文件的最后修改时间，最能反映"最近更新"

**配置示例**：
```python
{
    'name': 'xb21cn 精简系统',
    'detect_type': '189pan',
    'version': 'Win10/11',
    'download_url': 'https://cloud.189.cn/web/share?code=xxx&pwd=xxx',
    'size_display': '-',
    'is_webpage': True,
}
```

**已验证死路**：
- `listShareDir.action`需要date/signature签名，无法直接调用
- 分享页面是SPA，内容由JS动态加载，无法直接爬取
- 提取码验证API需要session，复杂且不必要

---

## 第28节：fixed + pe_version 自动版本读取（IObit模式）

**适用场景**：下载地址固定不变（如 `https://cdn.iobit.com/dl/driver_booster_setup.exe`），但版本号需要从安装包PE资源段自动读取，不需要手动维护。

**探测原理**：
1. HEAD请求固定下载地址，获取大小和Last-Modified
2. 用Range请求只下载PE头和.rsrc段（约200KB，不下载完整文件）
3. 解析PE资源段中的FileVersion，获取四段式版本号
4. 如果PE读取失败，回退到配置中的默认版本号

**配置示例**：
```python
{
    'name': 'IObit Driver Booster',
    'detect_type': 'fixed',
    'pe_version': True,           # 关键：启用PE版本自动读取
    'version': '14.0.1.462',      # 回退版本号（PE读取失败时使用）
    'size': 32 * 1024 * 1024,     # 回退大小（HEAD失败时使用）
    'download_url': 'https://cdn.iobit.com/dl/driver_booster_setup.exe',
}
```

**关键技术点**：
- `pe_version: True` 在 `fixed` 和 `increment` 两种模式下都可用
- 只下载PE头(1KB) + .rsrc段(最多2MB)，用HTTP Range请求，总下载量约200KB
- 不下载完整安装包（32MB），节省带宽和时间
- PE版本读取失败时自动回退到配置的 `version` 默认值
- 与 `dll_pe_version: True` 区别：`pe_version` 读安装包本身，`dll_pe_version` 从7z SFX中提取内部DLL

**已验证软件**：
- IObit Driver Booster（固定CDN地址，PE版本14.0.1.462）
- IObit Uninstaller
- 其他固定CDN地址且需要精确版本号的软件

**配置决策树**：
```
固定下载地址？
├─ 是 → 版本号需要精确四段式？
│       ├─ 是 → 加 pe_version: True（自动从PE资源段读取）
│       └─ 否 → 手动维护version即可
└─ 否 → 用increment或scrape模式
```

---

## 第28.1节：版本来源精度（ProductVersion / build 后缀 / 安装器滞后）

> 2026-10-20 实战沉淀。前端版本号「不准确」基本都是这三种根因。

### 根因1：PE 读的是 FileVersion，不是 ProductVersion

PE 资源段（VS_VERSIONINFO）里有两个版本字段，含义不同：

| 字段 | 含义 | DxO PhotoLab 实例 |
|------|------|------------------|
| `FileVersion` | **文件自身**版本（常混入构建号） | 10.2.**20738**.496 |
| `ProductVersion` | **产品**版本（官方对外口径） | **10.2.0.496** |

默认读 FileVersion，前端就会显示 `10.2.20738.496` 这种带构建号的怪版本。

```python
{
    'name': 'DxO PhotoLab',
    'detect_type': 'fixed',
    'pe_version': True,
    'pe_version_source': 'product',   # ← 改读 ProductVersion
    'version': '10.2.0.496',
}
```

**⚠️ 不能全局改**：R-Studio 干脆没有 ProductVersion。所以必须是**按产品显式开启**。

**同源变体：FileVersion 是日期式版本号**（PotPlayer `26.10.21.0`），ProductVersion 才是官方产品版本（`1.7.23159.0`）。这时还要配 `strip_trailing_zero` 去掉末段补位 `.0`，并且因为口径变更导致数值变小（26.x → 1.7.x）会被防降级拦下，需配 `version_authority: 'pe'` 声明权威源放行。

### 根因4：NSIS 安装器外壳版本落后于软件实际版本

PotPlayer 的版本有三套口径，**只有内层那份是对的**：

| 位置 | 值 | 说明 |
|------|-----|------|
| 外壳 `PotPlayerSetup64.exe` FileVersion | `26.10.21.0` | 构建日期式，前端不能用 |
| 外壳 `PotPlayerSetup64.exe` ProductVersion | `1.7.23159.0` | NSIS 打包时写死，**落后一版** |
| 内层 `PotPlayer64.dll` FileVersion | `1.7.23160.0` | ✅ About 框显示 `26021(1.7.23160)`，以此为准 |

配置：

```python
'nsis_inner_version': True,
'nsis_inner_members': ['PotPlayer64.dll'],
'nsis_inner_prefer': 'file',     # 该 DLL 的 ProductVersion 是假的 1.7.0.0
'strip_trailing_zero': True,      # 1.7.23160.0 -> 1.7.23160
'version_authority': 'nsis',      # 数值比旧值小，放行不被防降级拦
```

**两个坑**：

1. **必须用二进制结构读版本**。该 DLL 的字符串表写的是 `1, 7, 23160, 0`（**逗号**分隔），
   正则 `\d+\.\d+` 必然落空。只有 VS_FIXEDFILEINFO（签名 `0xFEEF04BD`，
   `dwFileVersionMS/LS`）能读出 `1.7.23160.0`。
2. **NSIS 是连续 LZMA 流，无法按偏移单独取某个成员**，必须整包下载（54MB）。
   靠 `size + Last-Modified` 缓存兜底：二进制没换就复用缓存版本，零下载。

CI 需装 `p7zip-full`（`7z` 支持解 NSIS），已在 [detect.yml](file:///workspace/.github/workflows/detect.yml) 配好。

### 根因2：官网只给三段版本，末段 build 号在软件 About 框里

HyperSnap 官网全站只显示 `10.4.4`，第四段 `4` 只在软件 About 框里。安装包内 PE 版本是 `10.4.4.0`（末段恒 0），也拿不到。

解法：官网版本 + 配置的末段后缀组合。

```python
{
    'name': 'HyperSnap',
    'detect_type': 'scrape',
    'check_url': 'https://hyperionics.com/hsdx/changelog.asp',
    'version_regex': r'Version history for HyperSnap (\d+\.\d+\.\d+)',
    'prefer_scraped_version': True,
    'version_build_suffix': 4,      # 10.4.4 → 10.4.4.4
    'version': '10.4.4.4',
}
```

官网升到 10.4.5 时自动变 10.4.5.4，只需偶尔更新后缀。

### 根因3：官方安装包比软件版本旧一个修订版

DxO FilmPack 软件内是 `8.11.1.896`，但 CDN 上的安装包 PE 是 `8.11.0.896`（官方包同步慢）。此时 PE 值会**盖掉**正确版本。

解法：`version_strict_prefix` —— 同产品线时保留人工核实的配置值，等官方包同步后 PE 与配置相等，自动切换。

```python
{
    'name': 'DxO FilmPack',
    'detect_type': 'fixed',
    'pe_version': True,
    'pe_version_source': 'product',
    'version_strict_prefix': '8.11',   # 同产品线
    'version': '8.11.1.896',
}
```

### 补充：安装包是 RAR/自解压壳，读不出版本

HyperSnap 的 `HS10SetupCN.exe` 是 **RAR5 SFX**（Method=m5:22）：外壳 PE 无版本资源，真实版本在归档内的 `HprSnap.exe` 里。**7z 不支持 RAR5 解压**，需 `unrar`（或 `unar`）。

```python
{
    'detect_type': 'fixed',
    'rar_sfx_version': True,
    'rar_sfx_members': ['HprSnap.exe'],
}
```

CI 已在 detect.yml 安装 `unrar`（失败则退 `unar`）。注意 unrar 是非自由软件，**不入库**，靠 CI 现场装。

### 速查

| 现象 | 配置 | 说明 |
|------|------|------|
| 版本带构建号 | `pe_version_source: 'product'` | 改读 ProductVersion |
| 版本是日期式（26.10.21.0） | `pe_version_source: 'product'` + `strip_trailing_zero` + `version_authority: 'pe'` | PotPlayer 口径变更后数值变小，需权威源放行 |
| 安装器版本比软件低一版 | `nsis_inner_version: True` + `nsis_inner_members` | NSIS 外壳写死，PotPlayer 外壳 1.7.23159 vs 内层 1.7.23160 |
| 内层 DLL 的 ProductVersion 是假的 | `nsis_inner_prefer: 'file'` | PotPlayer64.dll 的 ProductVersion 是 1.7.0.0 |
| PE 版本字符串读不出 | 读 VS_FIXEDFILEINFO 二进制结构 | 字符串表可能是逗号分隔 `1, 7, 23160, 0` |
| 官网三段、用户要四段 | `version_build_suffix: N` | scrape 模式 |
| PE 版本比正确值低一版 | `version_strict_prefix: 'x.y'` | 保留人工核实值 |
| 装包完全读不出版本 | `rar_sfx_version: True` | 需 unrar |
| 完整包与热更新版本不一致 | `hexhub_api`（取 non-hot 版本） | HexHub 热更 5.4.4，完整包仍 5.1.9；下载站须与实下到的包一致 |
| 抓到正确版本却退回旧值 | `check_url` 体积兜底 / `size_regex_mb` | CDN 不给 Content-Length → size=0 → 判「无体积」作废（WinSnap） |
| 新版本配了旧版本日期 | 页面版本 ≠ 探测版本时不采用页面日期 | PDF-XChange 官网 history 滞后，11.1.1.0 被配 Sep 29 |

---

## 第29节：Google Update API 获取 Chrome 64位包（ap 参数决定架构）

**关键坑**：Chrome 只有一个 appid `{8A69D345-D564-463C-AFF1-A69D9E530F96}`（官方 chromium 源码确认，x86/x64 共用），**架构由 `<app>` 元素的 `ap` 属性决定**：

| ap 值 | 返回包 | 大小 | 说明 |
|-------|--------|------|------|
| 空 / `ap="stable"` | 32位 x86 uncompressed | ~418MB | 前端错误显示这个 |
| `ap="x64-stable"` | **64位 x64 uncompressed** | ~495MB | 正确 |

**完整请求**（POST https://update.googleapis.com/service/update2，Content-Type: application/xml）：
```xml
<request protocol="3.0" version="1.3.36.155">
  <os version="10.0.19045" platform="win" sp="" arch="x64"/>
  <app appid="{8A69D345-D564-463C-AFF1-A69D9E530F96}" version="" nextversion="" lang="" brand="" client="" ap="x64-stable">
    <updatecheck target="" targetchannel=""/>
  </app>
</request>
```

**解析**：
- 版本：`<manifest version="([^"]+)"`
- URL：`<url codebase="(https://dl\.google\.com/[^"]+)"` + 包名 `name="([^"]+\.exe)"`
- 大小：`required="true" size="(\d+)"`

**⚠️ 重要认知**：Chrome 离线安装包（uncompressed）的 PE stub 永远是 x86（0x14c），**不能靠 PE machine 判断 Chrome 安装包是 32 还是 64 位**（官方 standalonesetup64.exe 也是 x86 stub）。判断架构只能靠包大小或 ap 参数。

**不要用的 appid**：`{4DC8B4CA-1BDA-483E-B5FA-D3C12E15B62D}` 裸请求固定返回 56.0.2924.87 旧版（2016 年产品线），勿再尝试。

## 第30节：Edge 官方 CDP API（微软 CDN 直链）

**Step1 获取最新版本**：POST `https://msedge.api.cdp.microsoft.com/api/v2/contents/Browser/namespaces/Default/names/msedge-stable-win-x64/versions/latest?action=select`
- 必须带 User-Agent：`Microsoft Edge Update/1.3.183.29;winhttp`
- ssl verify=False（证书校验问题）
- body 含 targetingAttributes
- 从响应取 `ContentId.Version`

**Step2 获取下载文件**：POST `.../names/{appid}/versions/{version}/files?action=GenerateDownloadInfo`
- **必须空 body**（`data=b''`，GET 会 405）
- 按 `SizeInBytes` 降序取最大文件
- Url 把 `http://msedge.b` 替换为 `https://msedge.sb`（否则国内不可用）

**特点**：返回带 P1 时间签名的 CDN 直链，与官方 readme 格式一致；国内服务器不通但 GitHub Actions（海外）可通。

## 第31节：get_pe_version 正则增强（\x00 分隔 + 2-4 段）

**问题**：UTF-16LE 解码的 PE 资源里版本字段是 `FileVersion\x00\x009.8.0\x00\x008.1...`，`\s*` 匹配不到 `\x00`；且部分软件只有三段版本号。

**修复后的正则**：
```python
match = re.search(r'FileVersion[\x00\s]*(\d+\.\d+\.\d+\.\d+)', text)  # 先试四段
if not match:
    match = re.search(r'FileVersion[\x00\s]*(\d+\.\d+(?:\.\d+)?)', text)  # 兜底2-3段
```

**已验证**：AnyDesk（官网页面滞后显示 8.1.0，PE 真实版本 9.8.0）→ 用 fixed + pe_version 直接从安装包读。

## 第32节：increment 页面发布日期优先（date_regex）

**问题**：CDN Last-Modified 是文件存储时间，与官方页面"发布日期"可能不一致（PDF-XChange：Last-Modified 09-25 vs 页面 Released Sep 29th）。

**方案**：detect_increment 支持 `date_regex`，scrape 页面时同时抓发布日期，**页面日期优先覆盖 CDN 日期**：
```python
'date_regex': r'Released\s*<span class="release-date-value"[^>]*>\s*([A-Za-z]+ \d{1,2}(?:st|nd|rd|th)?, \d{4})',
```

**配套**：parse_date 需支持序数日期格式 `Sep 29th, 2026`（st/nd/rd/th 后缀）。

## 第32.1节：日期来源统一原则（2026-10-19 修订）

**日期永远用「安装包发布 / 最后修改时间」，禁止用 PE 编译时间戳或数字签名日期**。

| 来源 | 优先级 | 说明 |
|------|--------|------|
| 官方发布页日期（`date_regex` / scrape `scraped_date`） | 最高 | 厂商宣告的发布日（GoodSync 官网 `Version 12.11.11 -- 2026-10-17`） |
| HTTP `Last-Modified` | 次之 | 服务器上文件的最后修改时间（UniConverter CDN `Thu, 15 Oct 2026`） |
| PE 编译时间戳 / 数字签名时间 | **禁止** | 只是构建/签名时刻，不是发布或修改时间，会与真实发布日期错位 |

**落地**（`check_versions.py`）：
- `detect_scrape` / `detect_fixed` 的日期一律来自发布页日期或 `check_url_follow` 的 `Last-Modified`；
- PE 版本探测（`get_pe_version` / `alt_download_urls` 多包取最新）**只产出版本号，不产出日期**；
- 服务器不返回 `Last-Modified`（如 GoodSync 的 SibHtmlServer 只有 ETag）→ 退回官方发布页日期；
- 实测教训：曾用 PE 头 TimeDateStamp（编译时间 2026-10-16）当日期，被要求改回官网发布日。

## 第33节：官网页面滞后场景（CDN 递增为准）

**现象**：官网/博客版本信息滞后于 CDN 实际文件（EmEditor 博客 26.2.8 vs CDN 26.2.9；AnyDesk 页面 8.1.0 vs PE 9.8.0）。

**规则**：页面 scrape 的版本仅作**参考/起点**，以 CDN 实际文件探测（increment 递增 / PE 读取）为准。scrape 版本不得覆盖 CDN 探测到的新版本。

## 第34节：官网模板变量页面（Sublime Text 模式）

**问题**：官网下载页改版后链接变成 `sublime_text_build_${version}_x64.zip`（${version} 占位符），从下载链接正则抓版本号会失效。

**方案**：版本号改从页面文字抓取（`<p class="latest">Version: Build 4215</p>`）：
```python
'version_regex': r'Build (\d{4})',   # 页面第一个 Build 即最新
'url_pattern': 'https://download.sublimetext.com/sublime_text_build_{ver}_x64.zip',
```

## 第35节：increment 多参数 URL 构造（ACR 目录模式）

**问题**：URL 含 `{major}.x` 目录（如 Adobe Camera Raw `win/{major}.x/AdobeCameraRaw_x64_{major_minor_underscore}.exe`），detect_increment 内**所有** format 调用都要传 `major/major_minor/major_minor_underscore` 参数。

**曾踩坑**：get_version_url 已支持多参数，但后续 full_url_tmp / full_url 构造处漏传 → `KeyError: 'major'` → 整软件检测失败不推送。

**规则**：凡 url_pattern 含 `{major}` 等占位符，检查 detect_increment 内全部 format 调用点（当前 3 处：get_version_url / full_url_tmp / full_url）。

## 探测方式速查表补充（2026-10 新增）

| 软件 | 探测方式 | 版本来源 | 日期来源 | 关键点 |
|------|----------|----------|----------|--------|
| AnyDesk | fixed + pe_version | PE 资源（9.8.0） | CDN Last-Modified | 官网页面滞后勿用 |
| EmEditor | increment + scrape | CDN 递增（26.2.9） | CDN Last-Modified | 博客滞后勿覆盖 |
| PDF-XChange Editor | increment + scrape | CDN 递增（11.1.0.0） | 页面 Released（date_regex） | 383MB msi |
| Google Chrome | chrome_api | update2 API | CDN Last-Modified | ap="x64-stable" 才返回64位，地址转 gvt1 CDN（见第39.1节） |
| Microsoft Edge | edge_api | CDP API | CDN Last-Modified | Step2 空body POST |
| Adobe Camera Raw | increment | CDN 递增 | CDN Last-Modified | {major}.x 目录，3处format传参 |
| Sublime Text | scrape | 页面 Build XXXX | CDN Last-Modified | ${version} 模板页 |
| GoodSync | scrape + pe_version | PE 资源（完整包+便携包取最新 12.11.11.1） | 官网发布页（无 Last-Modified） | 官网/winget 滞后于安装包；日期见第32.1节 |
| Wondershare UniConverter | fixed + pe_version | PE 资源（18.0.0.58） | CDN Last-Modified | full14204 即最新直链，带版本号 URL 是同一文件 |
| Java(JDK) | java_api | 官方 javaReleases API（4 条版本线） | API releaseDate（2026-10-20） | 多版本线条目，见第39节 |

## 第36节：winget 官方索引作为第二探测源（2026-10-06 新增）

### 背景
部分软件官网有 Cloudflare 反爬（FinePrint 全站 403，返回"Just a moment..."挑战页），
纯官网抓取方案在 CI 环境不稳定或直接失败。需要一个**不依赖官网**的独立探测源。

### 实现
winget 官方索引 `https://cdn.winget.microsoft.com/cache/source2.msix` 是 MSIX 包，
内含 SQLite 数据库 `Public/index.db`，`packages` 表的 `latest_version` 即最新版本。
下载约 3.7MB（解压后 db 约 8MB），查询很快。

```python
def fetch_winget_version(winget_id, timeout=25):
    """从 winget 官方索引查询指定包的最新版本（索引进程内缓存，见第38节）"""
```

### 融合规则（已内置到 detect_scrape 与 detect_increment）
1. 官网/winget 都拿到版本 → 取**更大**的（winget 更新略滞后，官网为新时以官网为准）
2. 官网版本是 winget 的前缀且段数更少 → 用 winget **补全末段 build 号**
   （实测 GoodSync 官网 `12.11.9` + winget `12.11.8.8`；补全场景 `12.11.9` + `12.11.9.9`）
3. 官网失败 → 直接用 winget 结果
4. winget 版本对应的下载链接不可用 → 保留原结果，不降级

### 局限
- winget 索引更新比官网**滞后 1~2 天**，不能作为唯一源
- 不适合 build 号型版本（如 StartAllBack 3.9.27.5412，winget 只到 3.9.x）

### 配置项
```python
'winget_id': 'SiberSystems.GoodSync',   # winget 包 ID
```

### 本次新增的三款软件（均为双源）
| 软件 | 探测方式1 | 探测方式2 | winget_id |
|------|----------|----------|-----------|
| GoodSync Pro | scrape 官网更新日志 + PE 双变体（完整包 `-Setup.exe` + 便携包 `-2Go-Setup.exe` 取最新） | winget 索引 | `SiberSystems.GoodSync` |
| pdfFactory Pro | increment（`pdf{ver}pro.exe`） | winget 索引 | `FineprintSoftware.pdfFactory.Pro` |
| FinePrint | increment（`fp{ver}.exe`） | winget 索引 | `FineprintSoftware.FinePrint` |

## 第37节：StartAllBack 双地址轮询 + 安装包内 DLL 版本探测（2026-10-06 修复）

### 核心机制：两个下载地址，各自独立原地覆盖

StartAllBack 同时在**两个地址**发布安装包，且两边**各自独立地原地覆盖同一个 URL**
（URL 不变，只有 `Content-Length` / `Last-Modified` 变）：

| 地址 | URL | 更新节奏 |
|------|-----|---------|
| CDN（带版本号路径） | `https://startisback.sfo3.cdn.digitaloceanspaces.com/StartAllBack_{ver}_setup.exe` | 慢 |
| 官网（固定文件名） | `https://startisback.com/StartAllBack_setup.exe` | 快 |

**实测两包可以并存不同 build**：CDN = `3.9.27.5398`，官网 = `3.9.27.5412`。
只探测单一地址必然漏检——这就是长期检测不到 5412 的根因。

### 版本号只能从安装包内部拿

安装包本身是 **7z SFX**，PE 版本恒为 `1.0.0`；真实版本号在包内的
`StartAllBackX64.dll` 的 `.rsrc` 段里，必须**下载 → 定位 7z 签名 → 解包 → 读 DLL 的 PE 版本**。

读取方式（`get_startallback_dll_version`）：
1. 下载整个安装器（约 2MB）
2. `rfind(b'7z\xbc\xaf\x27\x1c')` 定位 7z 归档起点（SFX 前面是 PE stub）
3. 用 `tools/7zz` 解出 `StartAllBackX64.dll`
4. 遍历 PE section headers 找 `.rsrc`，在其中搜 `VS_FIXEDFILEINFO` 签名 `0xFEEF04BD`
5. 读 `dwFileVersionMS` / `dwFileVersionLS`，拼成四段版本号

> 注意：**必须优先用项目内置的 `tools/7zz`**。旧代码只找系统 `7z/7zz/7za`，
> 本地和 CI 都可能找不到，导致 DLL 解析被静默跳过。

### 配置项
```python
{
    'detect_type': 'startallback',
    'cdn_url_pattern': 'https://startisback.sfo3.cdn.digitaloceanspaces.com/StartAllBack_{ver}_setup.exe',
    'cdn_base_version': '3.9.27',      # CDN 路径扫描起点
    'startallback_max_scan': 30,       # 每个小版本扫描的 build 数
    'download_url': 'https://startisback.com/StartAllBack_setup.exe',  # 官网地址
}
```

### 踩过的坑
1. **DigitalOcean Spaces 对不存在的路径返回 403 而非 404** —— 不能遇到第一个失败就 `break`
2. **官网单连接带宽极低**：`startisback.com` 只有 ~15KB/s，2MB 装包要 **68 秒**。
   必须用并发分片（Range）下载，见第 38 节
3. **CDN 路径也要读 DLL**：同路径覆盖更新时，路径不变但内容已变

---

## 第38节：全量检测效率优化（2026-10-06）

全量检测 86 个软件，原先 **~10 分钟、超时 7 个、失败若干**；优化后 **121 秒、超时 0、失败 0**。
下面 7 条是通用的，可以套用到任何"多产品批量探测"场景。

### 1. 并发分片（Range）下载小文件 —— 68s → 9s

服务器单连接限速时，`Range` 分片 + 多线程能快一个数量级：

```python
def _fast_download(url, headers, max_size=16*1024*1024, chunks=16, timeout=90):
    # 1. HEAD 拿 Content-Length 和 Accept-Ranges
    # 2. 不支持 Range 或文件过大 → 回退单连接
    # 3. 否则切成 N 片并发 GET，最后拼回并校验总长度
```
适用：文件不大（<16MB）但服务器慢的场景。**文件大时不要用**（内存吃不消）。

### 2. 进程内 HTTP 结果缓存（`check_url` 加 TTL 缓存）

同一轮检测里多个产品、同一产品的多级递增经常探测**同一个 URL**。
加个带 TTL 的字典缓存即可省掉大量重复 HEAD：

```python
_http_cache = {}
def check_url(url, referer=None, use_cache=True):
    key = (url, referer or '')
    hit = _http_cache.get(key)
    if hit and (time.time() - hit[0]) < HTTP_CACHE_TTL:
        return hit[1], hit[2], hit[3]
```
**只缓存成功结果**——失败结果不缓存，避免把偶发网络抖动固化下来。

### 3. winget 索引全局缓存（省 3~4MB × N 次下载）

`source2.msix` 是所有 winget 产品共用的，原来每个 `winget_id` 都重新下载 + 解压一次。
改成进程内单例 + 锁：

```python
_winget_db_lock = threading.Lock()
_winget_db_path = ''
def _winget_index_db(timeout=40):
    global _winget_db_path
    with _winget_db_lock:          # 锁保证并发产品只下一次
        if _winget_db_path and (time.time() - _ts) < WINGET_CACHE_TTL:
            return _winget_db_path
        ...
```
**通用模式**：任何"多个产品共用的大索引/大文件"都该这么干。

### 4. MD5 / PE 版本结果缓存（省整包重下）

MD5 要**下载整个安装包**算哈希，PE 版本要发多次 Range 请求——都是每轮重复劳动。
缓存键用 `URL + Content-Length`（PE 再加 `Last-Modified`），包没换就直接复用：

| 缓存 | 文件 | TTL | 缓存键 |
|------|------|-----|--------|
| StartAllBack DLL 版本 | `startallback_dll_cache.json` | 7 天 | URL + size + Last-Modified |
| MD5 | `md5_cache.json` | 30 天 | URL + size |
| PE 版本 | `pe_version_cache.json` | 30 天 | URL + size + Last-Modified |

> ⚠️ **这些缓存文件必须纳入 git**（不能 gitignore）。
> CI 每次都是全新容器，只有提交上去下一轮才能复用，否则每轮都白下载。

### 5. 超时不重试

原来 `detect_one` 无条件"检测 + 重试"一次，**超时后重试只会把耗时翻倍**，
而且大概率还是超时。改成只在「快速失败」（拿到结果但体积为 0）时才重试：

```python
info, status = detect_with_timeout(product, timeout=timeout)
if status == 'timeout':
    _bump('timeout')      # 超时 → 不重试
elif status == 'error':
    _bump('failed')       # 异常 → 不重试
if info and info.get('size_mb', 0) <= 0 and args.retry > 0:
    ...                   # 只有这种情况才重试
```

### 6. 区分 timeout 和 error

`detect_with_timeout` 原来统一返回 `None`，无法判断是"慢"还是"错"。
改成返回 `(info, status)`：

- `timeout` → 该产品太慢，考虑优化代码或调大 `detect_timeout`
- `error` → 代码/网络有问题，要修

两种问题的处理策略完全不同，混在一起就永远查不出根因。

### 7. 问题清单集中输出

多线程 `print` 会交错，日志里根本分不清哪个超时对应哪个软件。
改成把问题收集到列表，事后按软件名统一输出：

```python
problems = []
def _note(name, kind, detail=''):
    with problems_lock:
        problems.append((name, kind, detail))

# 汇总时
⚠️ 本轮问题清单（7 项）:
   - FinePrint: 超时 120s
   - DxO FilmPack: 版本降级已拦截 7.0.0 -> 7.27.1.34
```

### 8. 防版本降级拦截

**问题**：PE/NSIS 解析偶发失败（服务器掐连接）时，代码会退回配置里的旧版本号，
导致 data.json 里的版本被"降级"，前端版本号来回跳。

**解决**：在 `main()` 里做最终比对，探测值比已有值更小就判定为降级，保留旧值：

```python
if _ver_tuple(new_v) < _ver_tuple(old_v):
    print(f"  ⚠️ 探测版本 {new_v} 低于已有 {old_v}，判定为降级，保留旧值")
    info['version'] = old_v
```
这是**兜底中的兜底**——前面所有缓存/重试都可能是"这一轮恰好失败"，这一层保证数据单调递增。

**例外：权威源放行（2026-10-09 新增）**
上面这条规则默认「数值大的更可信」，但同一条目的不同来源版本号**不可比**时会误伤：
微信安装包 PE 的 FileVersion 是占位 build `4.1.15.1000`，比 install.7z 里的真实版本
`4.1.15.50` 数值大，导致真实版本每轮都被"降级"回占位值，页面上永远看不到真版本。

处理办法：`detect_increment` 把本轮版本来源记到 `_VER_SOURCE[产品名]`（`nsis`/`pe`/`increment`/`winget`），
配置里声明 `version_authority` 后，凡是**权威源命中**的一轮一律放行：

```python
auth = product.get('version_authority')
from_authority = bool(auth) and _VER_SOURCE.get(name) == auth
if old_v and new_v and not from_authority and _ver_tuple(new_v) < _ver_tuple(old_v):
    ...保留旧值...
```
即：权威源没命中（解析失败退化成 increment/PE 值）→ 仍然拦截降级；权威源命中 → 以权威值为准。

**已配置**：`WeChat`（`version_authority: 'nsis'`）。

### 9. 并行度与超时的配比

```python
DEFAULT_PARALLEL = 8          # 原为 4
DEFAULT_DETECT_TIMEOUT = 60    # 原硬编码 30
DEFAULT_RETRY = 1              # 只对"快速失败"生效
```
并行度别开太高——线程太多会互相抢带宽，反而整体变慢（实测 16 线程分片下载时就遇到过）。

### 优化前后对比

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| 全量耗时 | ~600s | **121s** |
| 超时产品 | 7 个 | **0 个** |
| 失败产品 | 多个 | **0 个** |
| StartAllBack 单项 | 134s | **16.5s（冷）/ 4.4s（热）** |
| MD5/PE 重复下载 | 每轮全量 | 仅首次 |

---

## 第39节：资源站文章抓取（detect_type = monkrus / downtopc / nsane）

**定位**：资源站（博客/站群）本身没有安装包、也没有版本号，只跟踪「当天更新了哪些软件文章」。
配置 `category: 资源站` + `allow_no_size: True`，探测结果里版本号位置放「更新日期」，
文章链接通过 `update_items` 交给前端渲染。

### 通用机制

1. 先确定「最新更新日期」：monkrus 直接读 Blogger RSS 的 `<pubDate>`；downtopc 读 DLE RSS。
2. 抓该日期当天的**全部**文章 —— RSS 默认只回 10 条，会漏，所以按日期归档页分页抓全。
3. 只在「当天」范围内输出；当天没有软件文章时回退最近一天。
4. 结果写入模块级 `_site_items[产品名] = [{'title', 'url'}, ...]`，`find_latest` 把它塞进 `update_items`。

### downtopc 实现要点（detect_downtopc）

```python
# 1) RSS 只用来定日期（按 pubDate 取最新，RSS 条目数够用）
# 2) 日期归档 URL：https://downtopc.com/YYYY/MM/DD/ ，分页 /page/N/
#    第 1 页的 <div class="pagination"> 里能读出总页数
# 3) 文章列表结构：<h3><a href="...">标题</a></h3>
# 4) 标题命中「已添加软件名」才输出，没命中跳过
```

### 软件名匹配规则

- 归一化：转小写、非字母数字换成空格（保留词边界），如 `IObit Uninstaller` → `iobit uninstaller`、`7-Zip` → `7 zip`。
- 整词包含：` f' {key} ' in f' {标题归一化} '`，避免 `Thunder` 误命中 `Thunderbird`。
- 名字去空格后长度 < 4 的跳过（`YY` 这类过短名字会大面积误命中）。
- **跳过 `category == '资源站'` 的产品**：否则站点公告帖（如 "DownToPC Update: ..."）会命中自己的站名。

### 踩过的坑

| 问题 | 原因 | 解决 |
|------|------|------|
| 请求 403/406 | 站点有 Mod_Security | 带完整浏览器 UA + `Accept` 头，并加指数退避重试 |
| 文章抓不全 | RSS 默认只回 10 条 | 改用日期归档页分页抓全 |
| 命中站点公告帖 | 站名本身也是一个"软件名" | 构建匹配键时排除资源站自身 |
| 无体积被判失败 | 资源站没有安装包 | 配置 `allow_no_size: True` 跳过体积判定 |

### 配置示例

```python
{
    'name': 'downtopc软件',
    'name_cn': 'downtopc软件',
    'category': '资源站',
    'detect_type': 'downtopc',
    'check_url': 'https://downtopc.com/software/rss.xml',   # 仅用于定日期
    'download_url': 'https://downtopc.com/software/',
    'skip_md5': True,
    'allow_no_size': True,
}
```

### nsane 论坛实现要点（detect_nsane）

nsane（nsaneforums.com，Invision Community 论坛）**主题正文要登录**（匿名点 `/topic/xxx/` 返回 403），
但**板块列表页和前台 widget 匿名可读**，只要标题+时间就够，所以照抓不误。

数据源（`detect_type='nsane'` 时配置）：

```python
'nsane_forums': [                                  # 论坛板块列表页：(标识, URL)
    ('software-updates', 'https://nsaneforums.com/forum/48-software-updates/'),
    ('news-updates',     'https://nsaneforums.com/forum/17-news-updates/'),
],
'nsane_frontpage': 'https://nsaneforums.com/nsane.down/',   # 前台 FrontPage Latest Update 小部件
```

- 板块列表行：`<li data-rowID='NNN' data-controller='forums.front.forum.topicRow'>`，
  行内两个 `<time>`：**第一个=发帖时间**，最后一个=最后回复时间 →
  **按「发帖时间==今天(UTC)」判定今日新帖**（详见下方"踩坑"）。
- 前台小部件：`<h3>FrontPage Latest Update</h3>` 后的 `<li class="ipsDataItem">` 块，取标题锚点 + 首个 `<time>`。
- 命中项合并去重后写入 `_site_items`，前端同 monkrus/downtopc 样式渲染。

> ⚠️ **踩坑（2026-10-08 修正）：不能用「最后回复==今天」判定今日更新。**
> 老帖被回复会被顶起来使"最后回复=今天"，但软件并没有更新 —— 实测 `CyberLink PowerDirector
> Ultimate 2027 v25.0.0806`（topic 488020）**发帖 8/17**、今天只是有人回复（回复者还不是楼主），
> 却被当成"今日更新"推到了前端。板块惯例是**一个软件更新开一个新帖**，所以要用**发帖时间**判。
> 验证口径：改用发帖时间后，命中项与 nsane.down 前台 `FrontPage Latest Update` 小部件完全一致
> （AxCrypt / Google Antigravity / Zed 等，这些帖子的发帖时间=最后回复时间，都是当天新帖）。
>
> **RSS vs 列表页**：`/forum/{id}.xml` 的 `<pubDate>` 就是发帖时间，口径其实是对的；
> 之前误以为"老帖 8/17 建的 10/8 更新会被 RSS 漏掉"才改用列表页——但那种"更新"其实只是回复顶帖，
> 不是真更新。列表页的价值在于**两个时间都给了**（能同时看发帖与最后回复，便于甄别），继续用列表页即可。

**nsane 匿名可达情况（实测）**：`48`/`17`/`86`/`13`/`75`/`47` 列表页匿名可读；
`64 Frontpage Software Updates`、`15 Software Archive` 匿名 404（只读会员），抓不到；
`nsane.down` 前台内容走 `/nsane.down/`，匿名可读。

---

## 探测经验速查（遇到新软件时按这个顺序想）

| 现象 | 根因 | 解法 |
|------|------|------|
| 版本号只到 3 段，实际是 4 段 | 版本号藏在安装包内部 | 下包装 → 找关键 DLL → 读 PE 版本 |
| URL 没变但内容更新了 | 同路径原地覆盖 | 缓存键必须带 `Content-Length` + `Last-Modified` |
| 递增扫描扫不到新版本 | 号段稀疏、存在性不单调 | 并发全量扫描号段取最大命中，别用二分 |
| 官网 403 / "Just a moment..." | Cloudflare 反爬 | 换独立探测源（winget / GitHub API） |
| 服务器单连接极慢 | 限速 | Range 并发分片 |
| 每轮都很慢 | 重复下载大文件 | 结果缓存 + 缓存文件纳入 git |
| 版本号莫名变旧 | 解析偶发失败 | 防降级拦截（比大小） |
| 某个软件把整轮拖死 | 单点超时 | 产品级超时 + 超时不重试 + 异常隔离 |
| 官方 API 地址国内下载慢 | 单点域名跨境拥塞 | 换同内容 CDN 域名（Chrome → gvt1，见第39.1节） |

---

## 第39.1节：官方 API 地址替换为 CDN 域名（Chrome, 2026-10-06）

### 问题
`detect_chrome_api` 从 Google Update API 拿到的 `codebase` 是 `https://dl.google.com/...`，
这是**单点域名**，国内访问拥塞严重。同一份文件在 Google 的 CDN 节点上都有。

### 解法
拿到官方地址后，替换域名为 gvt1 CDN，其余路径原样保留：

```python
_GVT1_CDN = 'https://edgedl.me.gvt1.com/'

def _to_gvt1_cdn(url):
    if not url:
        return url
    new_url = re.sub(r'^https?://(?:dl|www)\.google\.com/', _GVT1_CDN, url)
    if new_url != url and not new_url.startswith(_GVT1_CDN + 'dl/'):
        new_url = _GVT1_CDN + 'dl/' + new_url[len(_GVT1_CDN):]
    return new_url
```

| | 地址 |
|---|---|
| 官方 API 返回 | `https://dl.google.com/release2/chrome/<hash>_<ver>/<ver>_chrome_installer_uncompressed.exe` |
| 替换后 | `https://edgedl.me.gvt1.com/dl/release2/chrome/<hash>_<ver>/<ver>_chrome_installer_uncompressed.exe` |

**验证**：两个地址 `content-length` 完全一致（522619304），都支持 `Accept-Ranges: bytes`，
说明是同一份文件——所以**体积/日期探测结果不受影响**，只改展示和实际下载的域名。

### 顺带修的两个坑
1. **正则只认 `dl.google.com`**：API 其实返回 4 个 `codebase`（`http`/`https` × `dl.google.com`/`www.google.com`），
   原正则只匹配 `https://dl.google.com`。改成两个 `or` 串联，并**优先 https**，避免明文 http 链接。
2. **http 链接**：API 第一条是 `http://`，正则加上 `https?` 兼容，替换后统一为 https。

### 可复用模式
任何"官方 API 返回单点域名"的软件都适用：**先按官方地址探测，再在输出前做域名替换**。
好处是体积、日期等元数据仍来自官方地址（权威），只把最终下载地址指向 CDN（快）。
注意替换后要实测 `content-length` 一致，证明没换错文件。

---

## 第40节：资源站型站点检测（monkrus，2026-10-07）

### 问题类型

有一类"软件条目"根本不是安装包，而是**资源站/博客**——它的"更新"表现为**当天发布了多篇新文章**，
每篇文章对应一款软件。典型：monkrus（`https://w18.monkrus.ws/`）。

这类条目跟常规软件有本质差异，传统检测字段全部失效：

| 常规软件 | 资源站 |
|---|---|
| 有明确版本号 | 无版本号，用**更新日期**代替 |
| 有安装包体积 | 无体积，必须留空 |
| 下载地址是安装包直链 | 下载地址是**固定站点首页** |
| 单元格填版本号/体积 | 单元格可以填**当天文章链接** |

如果硬套常规结构，会出现"版本列空着、大小列显示 `-`"的两块空白，视觉上很浪费。

### 检测端：`detect_monkrus`

数据源用 Blogger/Blogspot 的 RSS（无需登录、结构稳定）：

```
https://w18.monkrus.ws/feeds/posts/default?alt=rss
```

三个关键点：

**1. "当天"必须只比日期部分**

`pubDate` 是带时分秒的 datetime，直接比 `datetime` 只会命中当天**最后一篇**。
必须先 `.date()` 再比：

```python
entries.sort(key=lambda x: x[0], reverse=True)
latest_day = entries[0][0].date()                          # 只取日期
todays = [e for e in entries if e[0].date() == latest_day]  # 当天全部
```

这个坑踩过一次：早期版本只输出 1 篇，修正后正确输出当天 3 篇。

**2. 输出结构：`[{'title': ..., 'url': ...}]` 而不是裸字符串**

早期版本 `update_items` 存纯标题列表，前端拿不到链接。现在存对象，
让前端能直接渲染成可点击标签：

```python
items = [{'title': t, 'url': u} for _, t, u in soft]
_monkrus_items[product['name']] = items
```

`find_latest()` 统一带上 `'update_items': _monkrus_items.get(product['name'], [])`。

**3. 非软件文章过滤**

当天文章里混着求助帖、广告帖。用关键词正则剔除，站点是俄文，
所以正则里混了西里尔字母：

```python
skip_re = re.compile(
    r'КОМПЬЮТЕРНАЯ|ПОМОЩЬ|DONATE|ALIEXPRESS|REKLAM|ADVERT|'
    r'WARNING|BLOG-POST|КУПИТЬ|ПРОДАЖ|СКАЧАТЬ\s*$',
    re.I)
soft = [e for e in todays if not skip_re.search(e[1])]
```

实测当天 4 篇原始文章，过滤掉 1 篇求助帖后剩 3 篇软件文章。
**兜底**：若当天全被过滤掉，回退取最近一篇软件文章，避免整行数据为空。

### 两个必须处理的工程问题

**问题一：RSS 单页只给 25 条**

`max-results` 上限就是 25，写死 25 会在更新量大时截断。
用 `start-index` 翻页累积：

```python
def _fetch_rss_entries(rss_url, max_items=100, page_size=25, max_pages=4,
                       retries=3, pause=1.5):
    entries, seen = [], set()
    for page in range(max_pages):
        start = page * page_size + 1
        sep = '&' if '?' in rss_url else '?'
        page_url = f'{rss_url}{sep}max-results={page_size}&start-index={start}'
        ...
        if len(entries) >= max_items or len(blocks) < page_size:
            break
        if page < max_pages - 1:
            time.sleep(pause)
    return entries[:max_items]
```

`seen` 集合按标题去重（翻页边界可能重复）。

**问题二：Blogger 会掐断短时间连续请求**

连续请求同一 feed 会抛
`ssl.SSLError: UNEXPECTED_EOF_WHILE_READING`——注意这不是网络不通，
`curl` 带间隔访问完全正常（HTTP 200）。**排查时先确认是不是请求太快**，
别误判成站点挂了。解法是每页加重试 + 递增间隔：

```python
for attempt in range(retries):
    try:
        ...
        break
    except Exception as e:
        if attempt == retries - 1:
            print(f"  ⚠️ monkrus RSS 第 {page + 1} 页失败: {e}")
        else:
            time.sleep(pause * (attempt + 1))
```

### 无体积条目的判定：`allow_no_size`

常规逻辑里 `size_mb == 0` 等价于"检测失败"，会触发重试/降级。
资源站没有安装包，必须显式豁免，否则每次检测都会被判失败。

在 [check_versions.py](check_versions.py) 的 `detect_one()` 里共 10 处判定纳入该开关：
重试判断、降级保护、成功计数、日志输出。成功日志改为打印文章数而非体积：

```python
if info and (info.get('size_mb', 0) > 0 or allow_no_size):
    _bump('success')
    if allow_no_size:
        cnt = len(info.get('update_items') or [])
        print(f"  ✅ {info['version']}, 当天更新 {cnt} 款软件")
```

### 日期当版本号：`_ver_tuple()` 支持日期

版本位是 `YYYY-MM-DD` 时，常规的"按 `.` 切分取数字"会退化成无意义比较
（`2026` vs `7` vs `26`）。转成 `YYYYMMDD` 整数即可正确排序：

```python
m = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', s)
if m:
    y, mo, d = map(int, m.groups())
    return (y * 10000 + mo * 100 + d, 0, 0, 0)
```

这样 `2026-10-06 > 2026-10-05` 成立，且与普通版本号混合比较时不会误判。

### 前端：把空白列填成文章链接

不要新增表格列（会破坏所有普通软件的行结构）。做法是**让资源站行的
"版本 + 大小"两列合并成一个 `colspan=2` 单元格**，填入文章链接标签：

```javascript
const hasArticles = items.length > 0 && typeof items[0] === 'object';
let sizeHtml = '<td class="col-size size" data-label="大小">' + sizeStr + '</td>';

if (hasArticles) {
  const links = items.map(it =>
    '<a class="article-link" href="' + escapeHtml(it.url) + '" target="_blank" '
    + 'rel="nofollow noopener" title="' + escapeHtml(it.title) + '">'
    + escapeHtml(it.title) + '</a>').join('');
  versionHtml = '<td class="col-version article-links" data-label="更新文章" colspan="2">'
    + links + '<span class="article-count">共 ' + items.length + ' 篇</span></td>';
  sizeHtml = '';
}
```

关键细节：

- **`typeof items[0] === 'object'` 做向后兼容**：老数据里 `update_items` 是字符串数组，
  这个判断让它继续走普通版本号分支，不会因为数据结构升级而白屏。
- **长标题必须能换行**：`flex-wrap: wrap` + `word-break: break-word`，
  实测 712px 窄屏下无横向溢出。
- **移动端**：`colspan` 在 `display: block` 布局下自动失效堆叠，
  媒体查询里补 `justify-content: flex-end` 让标签右对齐，与其他行对齐。
- 链接用 `escapeHtml` 而非 `attrEncode`：这是 `href` 属性不是事件属性，
  且已做 `rel="nofollow noopener"`。

### ⚠️ 踩坑：colspan 撑破表格，全表行高暴涨

上面这版上线后，**其他所有软件的行都变高了**，下载列被挤成一条竖线、URL 逐字换行。
实测最坏行高从 54px 涨到 **1305px**。两个原因叠加：

**原因一：`colspan=2` 索要额外宽度**

`.article-links .col-version { width: auto }` 覆盖了 `.col-version` 的百分比。
表格默认 `table-layout: auto` 会按内容重算列宽，三个约 300px 的标签
把 version+size 两列撑到 600px+，44% 的下载列只剩几十像素。

**原因二：`word-break: break-all` 逐字拆 URL**

下载列仅剩 45px 时，`word-break: break-all` 让长 URL **一个字符一行**，
单元格高度飙到 690px。注意**受害的是"下载"这一列的所有行**——
因为被挤窄的是列而不是某一行，所以 88 行软件的下载地址全部逐字换行、行高一起暴涨。

**修复三处：**

```css
table { table-layout: fixed; }   /* 1. 列宽严格按声明，不按内容重算 */

/* 2. 下载链接最多两行，超出省略——不再逐字无限换行 */
.direct-link {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  word-break: break-all;
}
/* flex 子项要能收缩，否则 nowrap 会撑破容器 */
.dl-wrap .direct-link { flex: 1 1 auto; min-width: 0; }
```

再用 `<colgroup>` 把列宽钉死，双保险（`table-layout: fixed` 依赖它，
某些情况下百分比会被内容干扰）：

```javascript
html += '<table><colgroup>'
  + '<col style="width:22%"><col style="width:26%"><col style="width:8%">'
  + '<col style="width:10%"><col style="width:34%">'
  + '</colgroup><thead><tr>';
```

**修复效果**：平均行高 54px、最高 91px（仅资源站行，因为它有多个标签）。

### ⚠️ 踩坑二：省略号修好了行高，却把标题截断了

上面用 `text-overflow: ellipsis` 限住了标签宽度，行高正常了，
但窄窗口下标题被截成 `Adobe ...`，**用户看不到软件全名**——
对一个"列出当天更新了什么"的站点来说，这等于功能失效。

**错误做法**：靠省略号硬塞进固定列宽。

**正确做法**：既然纵向空间不紧张（资源站就这一行），就让标题**换行显示**：

```css
.article-links {
  display: flex;
  flex-direction: column;   /* 竖排：一个标签一行 */
  align-items: stretch;
  gap: 3px;
  white-space: normal;
}
.article-link {
  display: block;
  width: 100%;              /* 铺满列宽 */
  white-space: normal;      /* 允许换行，不要 nowrap */
  overflow-wrap: anywhere;  /* 超长无空格字符串也能断 */
}
```

要点：

- **`flex-direction: column` 而非 `wrap`**：竖排时每个标签独占一行，
  宽度由容器决定，不受兄弟元素影响。
- **`width: 100%` + `align-items: stretch`**：标签铺满整列，视觉更整齐。
- **`overflow-wrap: anywhere`**：比 `word-break: break-all` 更温和，
  只在真的放不下时才断词，不会把正常单词拆散。
- 移动端媒体查询要同步改（同样 `column` + `stretch`），
  否则桌面好看、手机又变省略号。

### ⚠️ 踩坑三：flex 直接加在 `<td>` 上，colspan 和列宽全废

按上面的 CSS 改完，行高正常了、标题也不截断了，但**又出现新问题**：
标签框被压到约 60px 宽，标题再次逐词换行，整行又变高。

根因是**把 `display: flex` 加在了 `<td>` 本身**：

```html
<!-- 错误：td 变成 flex 容器 -->
<td class="col-version article-links" colspan="2"> ... </td>
```

这是表格布局的一个经典陷阱：**给 `<td>` 设置 `display: flex` 会让它不再是一个
表格单元格**。浏览器为了维持表格结构，会在它外面自动生成一个匿名单元格，
而**单元格自身的 `colspan` 和 `colgroup` 列宽分配随之全部失效**，
列宽退化成"按内容计算"。再叠加 `overflow-wrap: anywhere`（最小内容宽度趋近 0），
这一列就被压到只剩几十像素。

**正确做法**：`<td>` 保持表格单元格，flex 放到它**内部的 `<div>`** 上：

```html
<td class="col-articles" colspan="2" data-label="更新文章">
  <div class="article-links"> ...链接们... </div>
  <span class="article-count">共 3 篇</span>
</td>
```

```css
/* td 不设 display，保持 table-cell；只给内部 div 设 flex */
.article-links { display: flex; flex-direction: column; align-items: stretch; }
```

改完后：colspan=2 正确生效（占"版本+大小"两列 = 34%），
窄窗口下标题换行 2 行、宽窗口下 1 行，行高恢复正常。

**最终效果**：1000px 窗口下文章列 336px、标题单行、行高 104px；
715px 窄屏下标题 2 行、无截断。两类窗口的平均行高都回到 60px 上下。

### 可复用经验：表格里放不定长内容

1. **不要用 `width: auto` 覆盖已有百分比列宽**——这是列宽失控的头号原因。
2. **`table-layout: fixed` + `<colgroup>`** 组合最稳，不受内容长度影响。
3. **绝不要给 `<td>` / `<th>` 改 `display`**（flex/grid/block 都不行）。
   一改它就不再是表格单元格，**colspan 和 colgroup 列宽立即失效**，
   列宽退化为按内容计算。需要 flex 就在单元格内套一层 `<div>`。
4. **长 URL 必须限行数**（`-webkit-line-clamp`），
   `word-break: break-all` 单独用在窄列里会造成逐字换行。
5. **flex 子项加 `min-width: 0`**，否则 `nowrap` 内容会撑破容器。
6. **别拿省略号解决"放不下"**。省略号只适合"截断可接受"的场景（如超长 URL）；
   标题、名称这类**识别性信息必须完整可见**，应改用换行布局。
7. **验证要看最坏行**：改完量 `Math.max(...rowHeights)` 而不是平均值。
8. **改动后清缓存再测**：浏览器缓存旧 CSS 会让人误判修复无效，
   用 `?v=Date.now()` 强制刷新。

### 可复用模式：资源站/聚合站检测

遇到"以文章形式发布更新"的站点，按这套流程走：

1. **找结构化数据源**：优先 RSS/Atom，其次站点 HTML。Blogger 站必有
   `/feeds/posts/default?alt=rss`；WordPress 用 `?feed=rss2`。
2. **按日期分组而非按条数截取**：取最新日期当天的全部条目，别写死"N 篇"。
3. **日期降级当版本号**：配套扩展 `_ver_tuple()` 支持 `YYYY-MM-DD`。
4. **`allow_no_size` 豁免体积判定**。
5. **条目带链接一起输出**（`{title, url}`），别只存标题。
6. **过滤噪声文章**：求助/广告/公告类关键词正则。
7. **前端复用空白列**：`colspan` 合并 + 标签化链接，不新增列。
   三个必须同时满足的条件：① 锁定列宽（`colgroup` + `table-layout: fixed`）；
   ② **flex 放在单元格内层 `<div>`，不要放在 `<td>` 上**；
   ③ 标签允许换行（`white-space: normal` + `overflow-wrap: anywhere`），
   不要用省略号截断。否则会撑破下载列或压窄成一条竖线（见上节三个踩坑）。
8. **翻页 + 重试 + 间隔**：RSS 单页上限小，且托管平台常掐连续请求。

## 第41节：官网 whats-new 页 + 固定直链（Yamicsoft Windows Manager，2026-10-07）

### 场景特点

跟第40节正好相反，这次是**标准软件**，但下载地址和版本号是**解耦**的：

| 项目 | 情况 |
|---|---|
| 版本号来源 | 官网 whats-new 页的文案 `Windows Manager v2.4.2 发布。` |
| 下载地址 | 固定 zip 直链，**文件名不带版本号**（`windowsmanager_portable.zip`） |
| 发布日期 | 页面同一条目的中文日期 `2026年10月7日` |

因为文件名里没有版本号，用不了 `increment`（无法拼 URL 递增探测），
只能用 `scrape`：版本号靠抓页面，地址写死。

### 配置

```python
{
    'name': 'Yamicsoft Windows Manager',
    'category': '系统工具',
    'detect_type': 'scrape',
    'check_url': 'https://www.yamicsoft.com/cn/whats-new.php',
    'version_regex': r'Windows Manager v(\d+\.\d+(?:\.\d+)?)',
    'date_regex': r'(\d{4}年\d{1,2}月\d{1,2}日)',
    'prefer_scraped_version': True,      # 页面是权威源，抓到的版本直接采用
    'version': '2.4.2',                  # 兜底：抓取失败时用
    'size': 21500924,                    # 兜底：HEAD 失败时用
    'download_url': 'https://yamicsoft.com/windowsmanager/software/windowsmanager_portable.zip',
    'skip_md5': True,                    # 固定包每天都会被覆盖，算 MD5 没意义还费流量
    'detect_timeout': 120,
    'official_site': 'https://www.yamicsoft.com/cn/whats-new.php',
}
```

### 关键点

**1. 页面是"倒序时间轴"，第一个匹配就是最新**

whats-new 页结构是：先一串日期 `<span>2026年10月7日</span>`（倒序），
再一串发布说明 `<ul>`（同样倒序）。两组列表**一一对应且同序**，
所以 `re.search` 取第一个匹配即可，不用做日期/版本配对。

实测页面上 11 个日期 + 11 个版本，第一个就是最新发布。

**2. regex 要锚在"Windows Manager v"上**

页面是站级 whats-new，导航、页脚里可能出现别的数字。把产品名带进正则，
避免抓到无关数字：

```python
r'Windows Manager v(\d+\.\d+(?:\.\d+)?)'   # 而不是裸 r'v(\d+\.\d+)'
```

**3. 中文日期要补零**

原 `parse_date()` 对中文日期只是简单替换分隔符：

```python
date_str.replace('年', '-').replace('月', '-').replace('日', '')   # 2026-10-7
```

结果是 `2026-10-7`（月日不补零），跟其他产品的 `YYYY-MM-DD` 格式不一致，
排序/显示都别扭。改为在通用替换前先精确匹配中文格式：

```python
# 中文格式: 2026年10月7日 / 2026年09月09日（补齐月日为两位）
m = re.match(r'(20\d{2})年(\d{1,2})月(\d{1,2})日', date_str)
if m:
    return f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
```

**4. 固定直链每天原地覆盖，不要算 MD5**

`windowsmanager_portable.zip` 是"同一个 URL 天天换内容"（HTTP 200 + 新
`Last-Modified`）。包 20.5MB，`skip_md5: True` 直接跳过，否则每天白下 20MB。

**5. 下载地址带不带 `www` 都能用**

配置里给了裸域 `https://yamicsoft.com/...`，服务器 301 跳到
`https://www.yamicsoft.com/...`。`check_url_follow()` 会跟随重定向，
体积/`Last-Modified` 都能正常拿到。

### 验证

```
检测 Yamicsoft Windows Manager [scrape]...
  官网版本: 2.4.2 (参考)
  发布日期: 2026-10-07
  跳过MD5计算 (skip_md5=True, size=21MB)
  ✅ 2.4.2, 20.5 MB
```

### 可复用模式：固定直链 + 官网更新日志

遇到"下载地址固定、文件名不带版本号"的软件，按这个模板配：

1. `detect_type: 'scrape'`，`check_url` 指向官方 changelog / whats-new 页。
2. `version_regex` **一定要把产品名带进去**，站级页面容易抓到无关数字。
3. `prefer_scraped_version: True`，官网文案是权威源。
4. `version` / `size` 两个字段都填上兜底值，官网改版抓不到时仍能出数据。
5. `skip_md5: True`——固定 URL 覆盖式更新，MD5 每日必变且无参考价值。
6. 日期是中文格式时，确认 `parse_date()` 能补零成 `YYYY-MM-DD`。

---

## 第42节：资源站/论坛探测的健壮性与效率优化（2026-10-08，downtopc + nsane）

**背景**：资源站（门户下载站 downtopc、论坛 nsane、博客 monkrus）本身没有安装包，只跟踪
「当天更新了哪些软件文章」。它们共同的问题不是"抓不到"，而是**站点抽风**（Cloudflare/Mod_Security
拦截、连接被掐、间歇性超时）导致整轮探测白跑、甚至把前端清单清空。本节的模式可复用到
**论坛 / 门户下载站 / 博客 / 聚合站**等任何"抓列表页当天条目"的场景。

### 一、先诊断：原来有哪些浪费

| 现象 | 根因 | 后果 |
|------|------|------|
| 单个产品超时 | `_fetch_site_html` 默认 `timeout=25` × `retries=3` + 退避，**单个 URL 最坏 80s** | 一个抽风 URL 就吃掉整块 60s 产品预算 |
| 一个源失败 = 全丢 | 只在整个探测末尾一次性写 `_site_items` | 前 2 个源抓到了、第 3 个挂了 → 全部丢弃 |
| 站点宕机反而"更新为空" | 抓不到和"当天确实没更新"返回同样的空结果 | 前端清单被清空，看起来像站点没内容 |
| 分页串行 | `_fetch_downtopc_articles` 一页一页抓 | 当天文章多时（多页）线性变慢 |
| 探测对了但前端不刷新 | `main()` 变更检测只比 version/size/日期/URL，**没比 `update_items`** | 资源站只改文章清单时判 `CHANGED=false`，CI 不重新生成前端，旧文章一直挂着 |

### 二、五个通用修法（已在代码落地）

#### 1. 内部时间预算（deadline 模式）—— 最关键

给每个探测函数设一个**内部预算 `SITE_DETECT_BUDGET`（45s）**，必须**小于**外层看门狗超时
`DEFAULT_DETECT_TIMEOUT`（60s）。所有抓取/重试/翻页都带这个 `deadline`，**到点就不再重试、立即返回**。

```python
SITE_DETECT_BUDGET = 45   # < DEFAULT_DETECT_TIMEOUT(60)，留 15s 余量给匹配/输出
deadline = time.time() + SITE_DETECT_BUDGET
rss = _fetch_site_html(rss_url, deadline=deadline)
```

```python
def _fetch_site_html(url, timeout=15, retries=2, pause=1.0, deadline=None):
    for attempt in range(retries):
        try:
            ...  # 成功直接 return
        except Exception as e:
            last_err = e
            # 重试次数用完 或 已过预算 → 放弃（不再等下一次退避）
            if attempt == retries - 1 or (deadline is not None and time.time() >= deadline):
                break
            wait = min(pause * (attempt + 1), max(0.0, deadline - time.time()))
            if wait > 0:
                time.sleep(wait)
    return ''
```

**要点**：函数"必然在看门狗超时前返回"，这样才谈得上"交出部分结果"，而不是被整体丢弃。

#### 2. 单源隔离 + 边抓边匹配（部分结果即时提交）

多源探测（nsane = 2 个板块 + 1 个前台 widget）时，**每个源独立 try/except**，命中项**就地累积**，
不要等全部抓完再统一匹配：

```python
matched, seen, fetched_ok = [], set(), False
def _collect(pairs):                    # 传进来的是"已确认今日更新"的 (标题, 链接)
    for title, url in pairs:
        if url in seen: continue
        seen.add(url)
        ok, key = _title_hits_product(title, keys)
        if ok: matched.append({'title': title, 'url': url})

for slug, url in product.get('nsane_forums', []):
    if time.time() >= deadline:         # 预算用完，剩余源直接跳过
        break
    try:
        got = _nsane_forum_topics(url, deadline=deadline)
    except Exception:
        continue                        # 单源异常不影响其它源
    # 只认"今天发的帖"：按发帖时间判，不按最后回复（回复顶帖≠更新）
    today_items = [(t, u) for (t, u, created, _last) in got if created == today]
    _collect(today_items)
```

最终 `except` 里也要 `if matched: _site_items[...] = matched`——**异常时别把已命中的结果丢掉**。

#### 3. 区分「抓通但为空」和「没抓通」

这是决定"要不要沿用旧数据"的关键信号，用 **`None`（没抓通）vs `[]`（抓通但无内容）** 表达：

```python
def _nsane_forum_topics(list_url, deadline=None):
    html_text = _fetch_site_html(list_url, deadline=deadline)
    if not html_text:
        return None          # 页面没抓通
    ...                      # 正常解析，可能返回空列表（当天没帖）
    return out
```

上层据此决定返回的"版本"（资源站里版本=更新日期）：

- **抓通了**（哪怕当天没命中）→ 返回**非空日期** → 前端正常显示（当天确实没更新）。
- **一个源都没抓通**（`fetched_ok == False`）→ 返回**空日期 `''`**，交由 `detect_one` 沿用旧数据。

```python
if not fetched_ok:
    print("  ⚠️ nsane 站点无响应，本轮跳过")
    return '', site_url, site_url, 0, '', ''
```

#### 4. 上层兜底：抽风时沿用旧数据，别清空清单

`detect_one` 里加一道资源站专用兜底（`allow_no_size` 的资源站本来就没体积，走不到原有的"保留旧数据"分支）：

```python
# 资源站整轮一个源都没抓通（版本为空）→ 沿用旧数据，避免抽风时把清单清空
if allow_no_size and info is not None and not info.get('version') and name in old_data:
    info = old_data[name].copy()
    _note(name, '资源站未抓通', f"沿用 {info.get('last_modified', '')}")
```

#### 5. 变更检测必须纳入 update_items（否则前端不刷新）

资源站的"更新"只体现在 `update_items`（当天文章清单）——**版本号就是日期，可能不变**。
`main()` 原来只比 `version / size_mb / last_modified / download_url`，清单变了也判 `CHANGED=false`，
CI 于是**不重新生成前端**，已经下掉的旧文章会一直挂在前端（实测：nsane 那篇 8/17 的旧帖）。

```python
old_items = old.get('update_items') or []
new_items = info.get('update_items') or []
if (old.get('version') != info.get('version')
        or old.get('size_mb') != info.get('size_mb')
        or old.get('last_modified') != info.get('last_modified')
        or old.get('download_url') != info.get('download_url')
        or old_items != new_items):          # ← 关键：清单变化也算变化
    changed.append(f"{p['name_cn']}: 更新清单 {len(old_items)}->{len(new_items)} 篇")
```

实测输出：`🔄 版本变化: nsane论坛: 更新清单 2->1 篇` → `CHANGED=true` → 前端重新生成。

> **通用教训**：判定"有没有变化"要覆盖**所有会展示到前端的字段**。只要某个字段会渲染，
> 它变了就得算变化，否则会出现"探测对了、数据也存进 `data.json` 了，前端却永远不刷新"——
> 这类问题最容易误判成"探测没生效"。

### 三、实测效果（沙箱）

```
# 正常：downtopc 6.1s（19 篇/命中 1）  nsane 7.7s（今日新帖 7 帖/命中 1）
# nsane 口径修正后：不再误推 8/17 的老帖 → "更新清单 2->1 篇" → CHANGED=true → 前端重新生成
# 模拟站点宕机（代理指向死端口）：3.0s 快速失败 → 沿用旧数据，清单不清空，进问题清单
  ⚠️ nsane 站点无响应，本轮跳过
  ⚠️ 资源站本轮未抓通，沿用上次数据: 2026-10-08
  ✅ 2026-10-08, 当天更新 1 款软件
```

### 四、效率取舍：要不要并行翻页/并行多源？

**结论：这类小列表页不值得为并行冒反爬风险，优先用"预算 + 快失败"省时间。**

- HTML 列表页很小，正常单页 < 1~2s，瓶颈是 RTT 和反爬挑战，不是带宽，**并行收益有限**。
- nsane 两个板块间刻意 `time.sleep(1.0)`、downtopc 顺序翻页，都是为了**不被 Cloudflare/Mod_Security 掐断**；
  强行并发请求反而更容易触发封禁，得不偿失。
- 真正的浪费在**抽风时反复重试**（一个 URL 吃 80s）——用 `deadline` 干掉它，收益远大于并行。
- 何时才该并行：单个源内部有**大量独立请求**（如 monkrus 分页 RSS、号段扫描），且目标是**不反爬的 API/CDN**。

### 五、可复用模板：适配一个「论坛 / 门户下载站 / 博客」站点

**通用流程**（4 步）：

1. **找匿名可读的数据源**：优先列表页 / RSS / JSON API；**别碰需要登录的详情页**。
   - 论坛（Invision/phpBB/Discourse）：板块列表页匿名可读，标题+时间就够（正文需登录没关系）。
   - 门户下载站（DLE 等）：日期归档页 `/{Y}/{M}/{D}/` + `/page/N/` 分页，`<h3><a>` 是条目。
   - 博客（Blogspot）：RSS `feeds/posts/default?alt=rss`。
2. **定「当天」语义 + 时区**：nsane 时间戳是 `...Z`（UTC），必须用 `datetime.now(timezone.utc)` 判"今日"，
   用本地时间会差一天。downtopc 用 RSS 的 `pubDate` 取最新日期。
   **论坛"今日更新"必须按「发帖时间」判，不能按「最后回复时间」**——回复顶帖 ≠ 软件更新（见第39节踩坑）。
3. **抓全当天条目**：RSS 默认只回 10 条会漏 → 用日期归档页分页抓全（`max_pages` 上限）。
4. **标题匹配本地软件库** → 写 `_site_items[产品名]` → `find_latest` 塞进 `update_items` 交前端渲染。

**配置模板**（字段含义见下表）：

```python
{
    'name': 'xxx资源站', 'name_cn': 'xxx资源站',
    'category': '资源站',              # 参与 _build_match_keys 时会被跳过（避免命中站名）
    'detect_type': 'nsane',            # 换成自研的 detect_xxx
    'check_url': 'https://.../rss.xml',# 定日期用（论坛可指向板块列表页）
    # 论坛型多源（按需）：
    'nsane_forums':    [('板块A', 'https://.../forum/48-xxx/'),
                        ('板块B', 'https://.../forum/17-xxx/')],
    'nsane_frontpage': 'https://.../frontpage/',   # 前台 widget（可选）
    'max_pages': 6,                    # 归档页最多翻几页
    'download_url': 'https://.../',    # 固定站点地址（无安装包）
    'skip_md5': True,                  # 没有安装包，不算 MD5
    'allow_no_size': True,             # 没有体积，跳过"体积为0算失败"的判定
    'detect_timeout': 60,              # 可选；默认 60，需 > SITE_DETECT_BUDGET
}
```

**新增同类站点的自检清单**：

- [ ] 数据源**匿名可读**（用无登录态 curl 验证，返回 200 且有目标内容）。
- [ ] 带上完整浏览器头（`UA` + `Accept` + `Accept-Language`），否则易吃 403/406/挑战页。
- [ ] 「当天」判定的**时区**与站点一致。
- [ ] 论坛/社区的「今日更新」按**发帖时间**判，不用最后回复时间（回复顶帖 ≠ 更新，否则会推历史老帖）。
- [ ] RSS/首页条目会被截断（取 10 条）→ 用归档/分页抓全。
- [ ] 抓取全部走带 `deadline` 的 `_fetch_site_html`，不裸调 `urlopen`。
- [ ] 多源探测：单源 try/except 隔离 + 边抓边匹配 + 异常也提交部分结果。
- [ ] `None`（没抓通）/ `[]`（抓通但为空）语义正确，上层能据此沿用旧数据。
- [ ] **无命中文章要判为「无更新」**：返回空版本让上层沿用旧数据；别因为「抓通了」就上报当天日期，
      否则没有新文章时前端会天天把日期刷成今天（2026-10-10 修复：nsane「更新清单 4->0 篇」却显示更新）。
- [ ] 标题匹配：归一化 + 词边界整词匹配，`category=='资源站'` 自身排除，短名（<4 字符）跳过。

### 六、进一步优化空间（暂未做，按需再上）

| 候选 | 收益 | 代价/风险 | 建议 |
|------|------|-----------|------|
| 同 host 熔断：一个 URL 失败后，同站后续 URL 直接 `retries=1` 快失败 | 抽风时再省几秒 | 少量状态复杂度 | `deadline` 已覆盖大部分收益，暂不需要 |
| 站点健康预检（全量探测前 ping 关键 URL） | 避免对宕机站无效探测 | 多一次请求；宕机时 `deadline` 本就会快速返回 | 暂不需要 |
| 并行翻页 / 并行多源 | 正常态提速有限 | **易触发反爬** | 不建议用于论坛/门户站 |
| `_fetch_site_html` 进程内 HTML 缓存 | 同一轮重复 URL 复用 | 资源站同轮多无重复 URL，收益≈0 | 暂不需要 |

## 第39节：多版本线条目 + Oracle 官方 Java API（2026-10-21 新增）

### 背景
Java 不是"一个最新版本"，而是**多条版本线并行维护**：27（GA）、25（LTS）、21（LTS）、8（LTS）。
用户要求前端只显示一条 Java(JDK) 条目，点标题后展开各版本线，每条带自己的发行说明引用和下载入口。

前端原本只支持单版本号字段，硬拆成 4 个产品条目会得到一堆重复行 —— 所以要**给数据模型加 `version_list`**。

### 数据源：Oracle 官方 javaReleases API

端点：`https://java.oraclecloud.com/javaReleases`（java.com 下载页用的同一份数据）

```json
{"items": [{
  "jdkDetails": {"jdkVersion": "27", "latestReleaseVersion": "27.0.1", "isLts": false},
  "releaseDate": "2026-10-20T00:00:00.000Z",
  "releaseType": "CPU",
  "releaseNotesUrl": "https://www.oracle.com/java/technologies/javase/27-0-1-relnotes.html"
}]}
```

一次请求就能同时拿到：版本号 / 是否 LTS / 发布日期 / 发行说明链接。

**为什么不用 scrape 抓官网页面**：
- downloads 页的版本号混着平台后缀（`8u511`、`jdk-27.0.1`、`1.8.0_511`），正则切不干净；
- 页面只列"当前主推"的几个版本，一次拿不到全部 4 条版本线。

### 关键实现点

**1. 版本号归一化**
API 对 JDK 8 返回 JVM 内部写法 `1.8.0_511`，用户习惯看的是 `8.0 Update 511`：

```python
def _java_display_version(jdk_ver, raw_version):
    m = re.match(r'^1\.(\d+)\.0_(\d+)$', raw)
    if m:
        return f"{m.group(1)}.0 Update {m.group(2)}"
    return raw
```

**2. 同一版本线有多条记录，要挑对**
API 里 JDK 27 既有 `CPU` 补丁记录也有 `FEATURE` 功能版记录（且 27 的 FEATURE 记录 releaseVersion 是 "27"）。
只取 `releaseType == 'CPU'` 的，再按 `releaseDate` 取最新。

**3. 主版本按配置优先级取，不按日期取**
主版本 = `java_lines` 里第一个能取到的版本线。
若按"发布日期最新"选，25 LTS 先发补丁时主版本会从 27.0.1 变成 25.0.6（数值变小），
被 `main()` 里的防降级机制误判成回滚而拦掉。
但**日期**要取所有版本线里最新的（任一条线发补丁都算 Java 有更新）。

**4. SSL 容错**
部分环境 TLS 握手会被中断（`SSLEOFError: UNEXPECTED_EOF`），需用不校验证书的 context 重试一次。

**5. 官网锚点要核对真实 id**
downloads 页的真实锚点是 `jdk27-windows`/`jdk25-windows`/`java21`/`java8`，
不是想当然的 `java27-windows`（该 id 不存在，点了会跳到页首）。
用 `curl` 抓页面 `id="..."` 列表逐个核对。

### 数据模型扩展：version_list

```json
"version_list": [
  {"name": "Java SE Development Kit 27.0.1", "version": "27.0.1", "tag": "GA",
   "official_site": "https://oracle.com/java/technologies/javase/27u-relnotes.html",
   "download_url": "https://www.oracle.com/java/technologies/downloads/#jdk27-windows"}
]
```

探测函数写全局 `_java_versions[产品名]`，`find_latest()` 统一挂到结果上。

### 三条配套规则（缺一不可）

1. **变更检测要带上 `version_list`**
   只比对主 `version` 的话，某条 LTS 线更新时主版本没变 → CI 判"无变化" → 前端永远停在旧清单。
   ```python
   old_vlist = old.get('version_list') or []
   new_vlist = info.get('version_list') or []
   if ... or old_vlist != new_vlist:
   ```

2. **本轮取不到清单要沿用旧的**
   API 抽风时若返回空清单，前端展开列表整块消失、日期被清空 —— 等于把线上数据打回原点。
   上层检测"本轮无子版本清单"时，沿用 `old_data` 的清单和日期。

3. **`allow_no_size: True`**
   下载页不是单一安装包，没有体积可探；不配这个会被"体积为 0 算失败"判定反复重试。

### 前端渲染

版本列渲染成 `<details class="ver-expand">`：

```
点击标题 → 展开
├─ Java SE Development Kit 27.0.1  [GA]    ← 链接到该版本下载页（带锚点）
│  oracle.com/java/technologies/javase/27u-relnotes.html
├─ Java SE Development Kit 25.0.5  [LTS]
└─ ...
```

CSS 要点：
- `.col-version-multi` 覆盖 `.col-version { white-space: nowrap }`（否则长标题被截断）
- 移动端 `tbody td` 是 `display:flex`，多版本列要额外 `display:block !important`，
  否则展开列表被挤成一行

---

## 第43节：版本停更的三个根因（2026-10-22，7-Zip + NVIDIA + SketchUp 新增）

本轮修的两款「线上版本停滞」都不是官网没更新，而是**探测侧自己把自己卡住了**。
新增产品 SketchUp Pro 2027 时也踩到同类坑，一并记在这里。

### 根因 1：多行文本用 `^` 锚定却没开 `(?m)` —— 7-Zip 永远停在 26.04

7-Zip 的权威版本源是官网 `https://www.7-zip.org/history.txt`：

```
HISTORY of the 7-Zip
--------------------

26.05          2026-10-21      ← 版本行在这里
-------------------------
```

原配置写的是：

```python
'version_regex': r'^(\d+\.\d+)\s+(\d{4}-\d{2}-\d{2})',
```

`re.search()` 默认**没有 MULTILINE 开关**，`^` 只匹配整个字符串的开头。
而字符串开头是 `HISTORY of the 7-Zip`，不是版本行 → **永远匹配不到**。

表现极具迷惑性：脚本不报错、不打警告，只是安静地退回 `increment` 逐段试探，
最后停在旧版本 26.04，看上去像"官网没发新版"。

**修法**：正则内联 `(?m)`，不依赖调用方传 flag：

```python
'version_regex': r'(?m)^(\d+\.\d+)\s+(\d{4}-\d{2}-\d{2})',
'date_regex':   r'(?m)^\d+\.\d+\s+(\d{4}-\d{2}-\d{2})',
```

**通用判据**：任何 `^`/`$` 锚定的正则，先确认被匹配的文本是不是多行结构
（history.txt、changelog、release notes、配置列表…）。
是的话就必须 `(?m)`，否则正则静默失效 —— 这类 bug 没有任何报错信息。

### 根因 2：探测用的请求没带 Referer —— NVIDIA 体积恒为 0

NVIDIA 驱动走 `gfwsl.geforce.com` 的 AjaxDriverService，版本号/日期/直链都能正常抓到，
但拿不到**文件体积**：

```
us.download.nvidia.com/Windows/621.01/...exe
  → 301 → us.download.nvidia.cn/Windows/621.01/...exe   （地域镜像）
       → 无 Referer：403（550 字节的拦截页）
       → Referer: https://www.nvidia.com/ ：200，content-length 1037190000
```

体积为 0 会触发上层「无体积 → 整轮作废 → 保留旧数据」的判定，
于是**版本号明明探测对了（621.01），却因为体积为 0 被丢弃，退回 617.42**。

根子在 `detect_scrape()`：`check_url_follow(url)` 没把产品配置的 `referer` 透传下去。
`detect_fixed()` / `detect_increment()` 一直都传了，只有 scrape 漏了。

**修法**（通用修复，不是给 NVIDIA 打补丁）：

```python
exists, detected_size, detected_date = check_url_follow(
    url, referer=product.get('referer'))
```

**注意边界**：`referer` 只用于**探测请求**，不能写进给用户的 `download_url`。
`.com` 直链对海外用户是正常可用的（只有探测端被地域镜像拦），
把直链换成 `.cn` 反而会让用户拿到一个更脆的地址。

**通用判据**：体积/日期拿不到时，先怀疑**请求头**（Referer / User-Agent / Cookie），
而不是先怀疑"文件不存在"。
`exists=True` 但 `size=0` 这个组合，几乎都是"对方返回了拦截页而不是文件"。

### 根因 3：版本号藏在文件名里时，别把 build 号算进版本号 —— SketchUp

SketchUp 官方下载页 `https://help.sketchup.com/en/downloading-sketchup` 一次给全三样东西：
当前版本直链、页面更新日期、以及 Windows 安装包文件名（文件名里带完整版本号）：

```
https://download.sketchup.com/SketchUp-2027-0-264-170.exe
                        └─2027─┘└0┘└264┘└170┘
                         年份   大  小   build
```

展示版本应为 **27.0.264**（官方 release notes 页写的也是 `SketchUp Desktop 2027.0.264`），
末段 build 号（170）不是产品版本号的一部分。

`detect_scrape` 的多捕获组默认用 `.` 拼接 → 正好得到 `27.0.264`：

```python
'version_regex': r'SketchUp-20(\d\d)-(\d+)-(\d+)-\d+\.exe',   # 27 / 0 / 264
'download_url_regex': r'(https://download\.sketchup\.com/SketchUp-20\d\d-\d+-\d+-\d+\.exe)',
```

年份用 `20(\d\d)` 只捕获后两位，`2027` → `27`；末段用 `\d+` 非捕获不参与拼接。

**两个必须注意的坑**：

1. **同页还有 `SketchUpFull-*.exe`（完整离线包）和 `.dmg`（macOS）**。
   直链正则必须锚死 `SketchUp-`（不能只写 `SketchUp`）并以 `\.exe` 结尾，
   否则会抓到 Full 包或 dmg。实测 `re.search` 取第一个匹配，Full 包在后面，安全。
2. **不能用 `fixed` 写死直链**：文件名带版本号，每次更新直链都变，写死必然失效。

**日期**取页面上的 `Last updated`（2026-10-21，即官方发布日），
比安装包 CDN 的 `Last-Modified`（2026-10-13，只是构建上传日）更准。
这里**不要**配 `prefer_config_date` + 写死 `date` —— 那样下一版发布后日期会卡在旧值；
让 `date_regex` 每轮重新抓页面上的日期即可。

### 三条通用判据

| 症状 | 先查什么 |
|------|---------|
| 版本号死活不动、脚本无报错 | 正则的 `^`/`$` 是否需要 `(?m)` |
| 版本探测到了却被丢弃（"无体积"） | 探测请求的 Referer/UA 头 |
| 同一页面有多个安装包变体 | 正则是否锚死了完整文件名 |

### 顺带一提：CI 挂掉 ≠ 代码有问题

站点数据停更时，先确认**检测流水线跑没跑、跑成功没有**（`gh run list`），
再去怀疑探测逻辑。两者症状一样，但修法完全不同。

---

## 第44节：定时检测跑在 GitHub Actions（2026-10-22 更正）

仓库已于 2026-10-21 设为**公开**，公开仓 Actions 分钟数不限，`detect.yml` 是唯一调度源：

```
*/15 * * * *   hourly：fast + normal + resource
5,35 * * * *   full：fast + normal + slow
```

- Cloudflare Worker `soft-detect-cron` 只做兜底补触发（15 分钟内已有运行则跳过）。
- 不走服务器 cron，也没有 `/opt/softofficelink`、`deploy/detect_cron.sh` 这套东西。
- push main 触发 Cloudflare Pages 自动部署，发布链路与 Actions 独立。

### 顺带修掉的 bug：版本号被清空成空字符串

**现象**：线上 AnyDesk 版本号变成空白。

**根因**：`detect_fixed` 里 PE 探测失败（CDN 限流 429 / 运行环境 CA 证书旧
导致 `CERTIFICATE_VERIFY_FAILED`）且缓存里没有旧值时，旧代码执行 `version = pe_ver`
把版本号覆盖成 `''`；而防降级只拦「数值变小」，空串不在拦截范围 → 直接写进线上。

**三层修法**：

```python
# 1) detect_fixed：PE 无结果时保留配置版本，绝不覆盖成空
else:
    pe_ver = _pe_version_cached(url)
    if pe_ver:
        version = pe_ver
    else:
        print(f"  ⚠️ PE版本无结果，保留配置版本: {version}")

# 2) main()：本轮版本号为空 → 沿用旧值（兜所有 detect_type）
if old_v and not new_v:
    print(f"  ⚠️ 本轮版本号为空，沿用旧值: {old_v}")
    info['version'] = old_v

# 3) AnyDesk 双保险：官网 JSON 抓版本（Windows 客户端包 win_exe）
'page_version_url': 'https://anydesk.com/zh/downloads/windows',
'page_version_regex': r'"id":"win_exe","version":"([\d.]+)"',
```

官网页面里的原始数据形如：

```json
"windows":{"packages":[{"size":8553912,"name":"Windows","id":"win_exe",
"version":"9.8.2","url":"https://download.anydesk.com.cn/AnyDesk.exe"}], ...}
```

回归验证（PE 探测失败的两种场景，版本号都保持 9.8.2 不被清空）：

```
场景1（PE 失败 + 缓存空）  → version = '9.8.2'
场景2（PE 失败 + 官网也挂）→ version = '9.8.2'
```
