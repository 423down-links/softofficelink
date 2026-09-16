# 软件版本探测方式指南

## 探测方式总览

| 方式 | 适用场景 | 效率 | 准确度 | 请求数 | 代表软件 |
|------|----------|------|--------|--------|----------|
| 官方更新API | 软件有check-update接口 | ⭐⭐⭐⭐⭐ | 极高 | 1 | PDFelement |
| 第三方软件库API | 主流软件可查 | ⭐⭐⭐⭐⭐ | 高 | 1 | 微信、迅雷、QQ音乐 |
| GitHub Releases API | 开源/GitHub托管软件 | ⭐⭐⭐⭐⭐ | 高 | 1 | Edge/Chrome安装器 |
| redirect | 固定地址302跳转 | ⭐⭐⭐⭐⭐ | 高 | 1 | XMind |
| fixed+变化检测 | 固定地址始终最新版 | ⭐⭐⭐⭐⭐ | 中 | 1 | IObit、网易云 |
| increment+进位 | URL含版本号，可跨版本 | ⭐⭐⭐⭐ | 高 | 5-20 | 雷电、迅雷、微信 |
| scrape | 从网页抓取版本信息 | ⭐⭐⭐ | 中 | 1-2 | Edge、Chrome、Xshell |
| PE版本 | 从exe.rsrc段读FileVersion | ⭐⭐⭐⭐ | 高 | 2-3 | 微信、YY、360浏览器 |
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

## 各方式详细说明

### 1. 官方更新检查API（优先级1）
**原理**：软件自身的更新检查接口，直接返回最新版本号、下载地址、更新日志
**示例**：
```
PDFelement: https://pc-api.wondershare.cc/v5/product/check-upgrade?pid=xxx&version=xxx
```
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

### 6. increment + 多级进位探测（兜底主力）
**原理**：从base_version递增版本号，连续5个404后自动进位到上一段
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
→ 继续递增 → 1637(404) 1638(404) 1639(404) 1640(404) 1641(404)
→ 连续5个404，自动进位: 25.1.13.1641 → 25.1.14.0
→ 递增探测 25.1.14.x → 连续5个404
→ 再次进位: 25.1.14.4 → 25.1.15.0 ← 跨版本可探测
→ 最多进位2次，防止无限探测
```
**进位规则**：
- `25.1.13.1636` → `25.1.14.0`（倒数第二段+1，后面重置为0）
- `4.1.15` → `4.2.0`
- `9.5.37` → `9.6.0`
**参数**：
- `MAX_SKIP = 5`：最多跳过5个不存在版本
- `MAX_CARRY = 2`：最多进位2次
**优点**：不依赖API，纯URL探测，可覆盖跨版本更新
**缺点**：需要多次请求（5-20次），版本号无规律时失效
**适用**：雷电、迅雷、微信、搜狗、YY、360浏览器等

### 7. increment + PE版本探测
**原理**：increment检测到大版本后，从PE文件.rsrc段读取四段版本号
```python
{
    'detect_type': 'increment',
    'pe_version': True,
}
```
**探测流程**：
1. 下载PE头(1KB) + section headers → 找.rsrc段偏移
2. 下载.rsrc段 → UTF-16LE解码 → 找FileVersion字段
**总下载量**：约200KB
**适用**：安装包PE头版本与显示版本不同的软件（YY、360浏览器）

### 8. increment + NSIS版本探测
**原理**：increment检测到版本后，解析NSIS安装包内install.7z的版本号文件夹
```python
{
    'detect_type': 'increment',
    'nsis_version': True,
    'pe_version': True,  # 兜底
}
```
**探测流程**：
1. 下载PE头(1KB) → 获取overlay偏移
2. 下载NSIS头部(3MB) → 搜索7z签名获取install.7z偏移
3. 下载install.7z头部(32B) → 读取next_header_offset计算精确大小
4. 下载install.7z头尾(32KB+128KB) → 构造文件用7z列出内容
5. 提取第一个文件夹名称作为版本号
**总下载量**：约3.2MB（vs 完整下载244MB，节省98.7%）
**7z工具**：项目内置 `tools/7zz`，不依赖系统安装
**适用**：NSIS打包且install.7z内含版本号文件夹的软件（微信4.1.15.9）

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
**原理**：下载完整文件计算MD5
**限制**：>100MB跳过（increment模式），>500MB强制跳过
**适用**：小文件完整性校验

---

## 新增软件探测方式选择流程

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
           │       ├─ PE头版本与显示版本不同？→ 加pe_version
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
| 微信版本探测 | 手动维护4.1.13.65 | NSIS自动获取4.1.15.9 | 全自动 |
| NSIS版本探测 | 下载244MB完整包 | 下载3.2MB头尾 | 98.7%流量节省 |
| 7z工具依赖 | 需系统安装p7zip | 内置tools/7zz | 跨环境可用 |
| 单软件超时 | 无（一个卡住全部卡住） | 45秒超时+重试2次 | 可靠性提升 |
| 检测失败处理 | 覆盖为空 | 保留上次成功数据 | 数据不丢失 |
| MD5计算 | 全文件下载 | >100MB跳过 | 大文件不超时 |
| 检测方式 | 串行逐个 | 并行6线程 | 5-10分钟 → 2-4分钟 |
| 工作流 | 单6小时全量 | 3h高频(有变化才推)+6h全量 | 更新延迟缩短 |
| 单软件检测 | 不支持 | --only参数 | 调试方便 |

---

## 第三方API融合计划（待实现）

### 腾讯软件中心API
- [ ] 封装 `detect_tencent_api(keyword)` 函数
- [ ] 微信、迅雷、QQ音乐、搜狗、YY 添加API验证源
- [ ] API失败自动降级到increment探测

### winget仓库API
- [ ] 封装 `detect_winget_api(package_id)` 函数
- [ ] Edge、Chrome、VS Code等添加winget源
- [ ] 从manifest提取版本号和下载URL

### GitHub Releases API
- [ ] 封装 `detect_github_api(owner/repo)` 函数
- [ ] Edge/Chrome安装器改用API获取最新版

---

## 已知限制

1. **QQ音乐**：防盗链严格，所有Referer返回403，sign无法自动生成，下载地址指向官网页
2. **Topaz系列**：Cloudflare 403拦截Python urllib，大小用固定值，日期从社区帖子抓取
3. **Xshell**：下载需邮箱接收随机地址，版本从更新历史页抓取
4. **Flash Player**：下载地址是网页，版本从flash-player-links页面抓取
5. **XYplorer**：官网偶尔超时，版本用配置默认值优先
6. **第三方API**：腾讯软件中心/winget API尚未融合，当前纯URL探测

---

**最后更新**: 2026.09.15
**版本**: v2.0（融合架构版）

## v2.1 更新（2026-09-15）

### 新增探测方式

#### 12. GitHub Releases API 探测（github_release）
- **适用场景**：软件发布在GitHub Releases，多分卷ISO等
- **配置**：`repo='owner/repo'`, `tag_filter='关键词'`, `version_regex='从tag提取版本号'`
- **原理**：调用 `https://api.github.com/repos/{repo}/releases`，过滤tag，取最新release
- **获取信息**：版本号（从tag提取）、发布日期（published_at转北京时间）、总大小（所有assets求和）、下载链接（发布页html_url）
- **示例**：Windows 11 LTSC 2024 / Windows 10 LTSC 2021（adavak/win_iso_build）
- **注意**：匿名API限流60次/小时，GitHub Actions环境有token不限流；失败时保留配置默认值

#### 13. 页面抓取+动态URL构造（scrape + url_pattern）
- **适用场景**：版本号从官网页面抓取，下载URL需根据版本号动态构造
- **配置**：`detect_type='scrape'`, `check_url='官网下载页'`, `version_regex='抓取版本号'`, `url_pattern='URL模板'`, `url_ver_format='short'`
- **原理**：先从页面抓取版本号，再用_url_ver()转换为URL格式，构造下载链接
- **url_ver_format选项**：
  - `full`：完整版本号（默认），如 8.40.5000
  - `short`：前两段去掉点，如 8.40 -> 840
  - `major_minor`：前两段带点，如 8.40
- **示例**：AIDA64（页面抓8.40.5000 → URL aida64extreme840.zip）

### 新增配置项

| 配置项 | 适用模式 | 说明 |
|--------|---------|------|
| `url_ver_format` | increment/scrape | URL版本号格式转换（full/short/major_minor） |
| `url_pattern` | scrape | 动态构造下载URL的模板 |
| `skip_md5` | scrape/fixed | 跳过MD5计算（大文件或下载慢时） |
| `size` | github_release | API失败时的默认大小（字节） |
| `date` | github_release | API失败时的默认日期 |

### 效率优化记录

- AIDA64原用increment模式需探测8.41~8.45多个版本（超时），改用scrape+动态URL后单次请求完成
- scrape模式MD5计算添加100MB限制，避免大文件下载超时
- GitHub API失败时保留配置默认值，不覆盖为空

## 14. CyberLink PowerDirector / PhotoDirector 探测方式

### 特点
- 离线安装包是自解压7z格式，包含PE加载器 + 7z资源包
- API: `https://www.cyberlink.com/prog/util/downloader/get-link-v2.jsp`
- 需要VID参数，VID会随版本更新失效
- 返回链接和MD5，不返回版本号

### VID自动检测
1. 从下载器PE版本号获取VID候选（如4.1.1.15102）
2. 测试配置的VID候选列表（4.2.1.14316, 4.1.1.15102, 4.1.1.14809）
3. 调用API验证VID有效性，自动切换到有效VID
4. 调用API 15次收集候选令牌（token），选择最新的

### 版本号获取
- PhotoDirector: 7z包内含主程序PhotoDirector_365.exe，可从PE头读取版本号
- PowerDirector: 7z包是纯资源包（9160+文件），不含主程序exe，无法从PE头读取
- PowerDirector版本号需使用default_version配置，当前为25.0.0.0904.0
- 备选：尝试从7z包中其他exe/dll获取版本号（如MUIStartMenu.exe，但版本不匹配）

### 配置示例
```python
{
    'name': 'PowerDirector',
    'detect_type': 'fixed',
    'version': '25.0.0.0904.0',  # default_version，手动维护
    'size': 691 * 1024 * 1024,
    'md5': 'be7750903c07baa523c0ab0328a1b27a',
    'download_url': 'https://build.cyberlink.com/Retail/PowerDirector/...',
}
```
