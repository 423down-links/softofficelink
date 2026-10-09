# 常用软件最新版离线安装包下载 - Software Official Links

自动检测常用国内软件的最新版本，提供官方CDN直链下载。

## 已支持软件

| 分类 | 软件 | 最新版本 | 大小 |
|------|------|----------|------|
| 模拟器 | 雷电模拟器 9 | 9.5.37 | 574.1 MB |
| 模拟器 | 雷电模拟器 14 | 14.0.27 | 709.7 MB |
| 下载工具 | 迅雷 | 25.1.13.1631 | 202.4 MB |

## 功能

- **自动检测版本**：从已知版本递增扫描官方CDN，找到最新可用版本
- **官方CDN直链**：直接使用各软件官方下载地址
- **每日自动更新**：GitHub Actions 每日北京时间8:00自动检测
- **支持下载工具**：直链支持 IDM 等下载工具
- **易扩展**：在 `check_versions.py` 的 `PRODUCTS` 列表中添加配置即可支持新软件

## 访问地址

https://423down-links.github.io/softofficelink/

## 添加新软件

编辑 `check_versions.py`，在 `PRODUCTS` 列表中添加：

```python
{
    'name': 'Software Name',
    'name_cn': '软件名称',
    'icon': '图标文字',
    'icon_color': 'linear-gradient(135deg, #color1, #color2)',
    'category': '分类',
    'base_version': '当前版本',
    'url_pattern': 'https://download.example.com/{ver}.exe',
    'param_format': '',  # 可选，带参数的链接格式
    'channel': '',       # 可选，渠道号
    'official_site': 'https://www.example.com/',
}
```

## 文件说明

- `index.html` - 主页面（按分类展示产品卡片）
- `data.json` - 版本数据
- `check_versions.py` - 版本自动检测脚本（支持多产品配置）
- `embed_data.py` - 将数据嵌入HTML
- `.github/workflows/update.yml` - 每日自动更新工作流
- `_headers` - 缓存控制（不缓存）
- `robots.txt` - 禁止搜索引擎收录
