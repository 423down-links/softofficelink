#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
常用软件最新版离线安装包自动检测脚本
支持多种检测模式：
  increment - 从基础版本递增检测（默认）
  redirect  - 访问固定地址，从 302 Location 头提取版本号和完整下载链接
  fixed     - 固定下载地址，版本号手动维护，只检测文件可用性
  scrape    - 从官网页面抓取版本号，固定下载地址，计算MD5校验
  cyberlink - 从 CyberLink 官方接口解析下载器直链，解包 info.ini 取真实版本号
"""

import hashlib
import html
import json
import os
import re
import threading
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_JSON = os.path.join(BASE_DIR, 'data.json')

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

# ===== 全局性能/容错参数 =====
# winget 索引缓存时长（秒）。官方每天更新，1 小时足够，避免重复下载 3~4MB
WINGET_CACHE_TTL = 3600
# 单次运行内 check_url 的结果缓存时长（秒）：同一轮里多个产品/多次探测常打同一 URL
HTTP_CACHE_TTL = 120
# 单个产品检测的默认超时（秒）；产品可用 detect_timeout 覆盖
DEFAULT_DETECT_TIMEOUT = 60
# 资源站/论坛单次探测的内部时间预算（秒）。必须小于产品超时，
# 这样探测函数一定能在看门狗超时前返回，把已抓到的部分结果提交，
# 而不是被整体丢弃后回退到昨天的数据（站点抽风时的关键保护）。
SITE_DETECT_BUDGET = 45
# 全量检测的默认并行线程数
DEFAULT_PARALLEL = 8
# 单个产品的重试次数（1=不重试）
DEFAULT_RETRY = 1

# 产品配置
PRODUCTS = [
    {
        'name': 'LDPlayer 9',
        'name_cn': '雷电模拟器 9',
        'icon': '9',
        'icon_color': 'linear-gradient(135deg, #ff6b35, #f7931e)',
        'category': '模拟器',
        'detect_type': 'increment',
        'base_version': '9.5.37',
        'url_pattern': 'https://lddl01.ldmnq.com/download/leidian9/ldinst_{ver}.exe',
        'param_format': '?v={ts}&n=ldinst_{ver}_ld_{channel}_ld.exe',
        'channel': '407594',
        'official_site': 'https://www.ldmnq.com/',
    },
    {
        'name': 'LDPlayer 14',
        'name_cn': '雷电模拟器 14',
        'icon': '14',
        'icon_color': 'linear-gradient(135deg, #00d4ff, #7b2ff7)',
        'category': '模拟器',
        'detect_type': 'increment',
        'base_version': '14.0.27',
        'url_pattern': 'https://lddl01.ldmnq.com/download/leidian14/ldinst_{ver}.exe',
        'param_format': '?v={ts}&n=ldinst_{ver}_ld_{channel}_ld.exe',
        'channel': '412570',
        'official_site': 'https://www.ldmnq.com/',
    },
    {
        'name': 'Thunder',
        'name_cn': '迅雷',
        'icon': '迅',
        'icon_color': 'linear-gradient(135deg, #1e88e5, #00acc1)',
        'category': '下载工具',
        'detect_type': 'increment',
        'base_version': '25.1.13.1631',
        'url_patterns': [
            'https://down.sandai.net/thunder_pc/ThunderSetup{ver}xl.exe',
            'https://down.sandai.net/thunder_pc/ThunderSetup{ver}up.exe',
        ],
        'param_format': '',
        'channel': '',
        'official_site': 'https://www.xunlei.com/',
    },
    {
        'name': 'WeChat',
        'name_cn': '微信',
        'icon': '微',
        'icon_color': 'linear-gradient(135deg, #07c160, #10ad56)',
        'category': '社交沟通',
        'detect_type': 'increment',
        'base_version': '4.1.15',
        # 真实产品版本 = 安装包 install.7z 内的版本号目录（如 4.1.15.50）。
        # ⚠️ 不要开 pe_version：该安装包 PE 的 FileVersion 是占位 build（4.1.15.1000），
        # 数值上比真实版本大，会把防降级拦截误触发，导致页面永远显示 4.1.15.1000。
        'nsis_version': True,
        'version_authority': 'nsis',
        'url_pattern': 'https://dldir1v6.qq.com/weixin/Universal/Windows/WeChatWin_{ver}.exe',
        'param_format': '',
        'channel': '',
        'official_site': 'https://pc.weixin.qq.com/',
    },
    {
        'name': 'Sogou Pinyin',
        'name_cn': '搜狗输入法',
        'icon': '搜',
        'icon_color': 'linear-gradient(135deg, #ff6b35, #ff8c42)',
        'category': '输入法',
        'detect_type': 'increment',
        'base_version': '16.8.0.4914',
        'url_pattern': 'https://ime.gtimg.com/pc/build/_sogou_pinyin_{ver}_0.exe',
        # 搜狗 CDN 只保留「当前构建」一个包（相邻 build 号全 404，实测 16.9.0.5522/5524 均 404），
        # 纯递增探测永远追不上跨小版本的跳跃（16.8.0.4914 -> 16.9.0.5523）。
        # 改用官网页面里给自动检测留的机器可读标记 <version>16.9.0.5523</version> 作为版本起点。
        # 注意：该页面是 GBK 编码，需按 page_encoding 解码（<version> 本身是 ASCII，UTF-8 也能命中）。
        'check_url': 'https://pinyin.sogou.com/windows/',
        'version_regex': r'<version>\s*([\d.]+)\s*</version>',
        'page_encoding': 'gbk',
        'param_format': '',
        'channel': '',
        'official_site': 'https://pinyin.sogou.com/windows/',
    },
    {
        'name': 'YY',
        'name_cn': '歪歪语音',
        'icon': 'Y',
        'icon_color': 'linear-gradient(135deg, #00d4ff, #0099cc)',
        'category': '社交沟通',
        # 探测方式：两轮并发「列车扫描」。YY 按第2段递增（9.59 -> 9.60，第三段归0），
        # 且 CDN 只保留最新几个包；逐段递增进不到位且慢，这里一次并发直接定位。
        # 安装包文件名即真实版本，无需再解析 PE（pe_version 对 YY 解析不出来，纯浪费）。
        'detect_type': 'increment',
        'base_version': '9.60.0.0',
        'url_pattern': 'https://dl-limit.yystatic.com/4/setup/YYSetup-{ver}-zh-CN.exe',
        'minor_scan': True,        # ① 小版本段 +1..+6；② 命中段内构建号 0..4
        'minor_scan_count': 6,
        'minor_scan_builds': 4,
        'param_format': '',
        'channel': '',
        'official_site': 'https://www.yy.com/web/pcyy_download/',
    },
    {
        'name': 'QQMusic',
        'name_cn': 'QQ音乐',
        'icon': 'Q',
        'icon_color': 'linear-gradient(135deg, #31c27c, #1db954)',
        'category': '影音娱乐',
        'detect_type': 'scrape',
        'check_url': 'https://y.qq.com/download/download.html',
        'version_regex': r'最新版:(\d+\.\d+\.\d+)',
        'version': '22.6.1',
        'date': '2026-09-02',
        'download_url': 'https://y.qq.com/download/download.html',
        'official_site': 'https://y.qq.com/download/download.html',
    },
    {
        'name': 'Xshell',
        'name_cn': 'Xshell',
        'icon': 'X',
        'icon_color': 'linear-gradient(135deg, #667eea, #764ba2)',
        'category': '开发工具',
        'detect_type': 'scrape',
        'check_url': 'https://www.xshell.com/zh/xshell-update-history/',
        'version_regex': r'Xshell\s*(\d+)\s*Build\s*(\d+)',
        'version': '8.0.0110',
        'date': '2026-09-03',
        'download_url': 'https://www.xshell.com/zh/xshell-update-history/',
        'official_site': 'https://www.xshell.com/zh/xshell-update-history/',
    },
    {
        'name': 'XMind',
        'name_cn': 'XMind',
        'icon': 'M',
        'icon_color': 'linear-gradient(135deg, #f7931e, #ff6b35)',
        'category': '办公效率',
        'detect_type': 'redirect',
        'check_url': 'https://xmind.cn/zen/download/win64/',
        'version_regex': r'Xmind-for-Windows-x64bit-(\d+\.\d+\.\d+)-',
        'official_site': 'https://xmind.cn/',
    },
    {
        'name': 'WinHex',
        'name_cn': 'WinHex',
        'icon': 'W',
        'icon_color': 'linear-gradient(135deg, #667eea, #764ba2)',
        'category': '开发工具',
        'detect_type': 'scrape',
        'check_url': 'https://www.x-ways.net/winhex/',
        'version_regex': r'WinHex\s*(\d+\.\d+(?:\s*SR-\d+)?)',
        'version': '21.8 SR-6',
        'download_url': 'https://www.x-ways.net/winhex.zip',
        'official_site': 'https://www.x-ways.net/winhex/',
    },
    {
        'name': 'XYplorer',
        'name_cn': 'XYplorer',
        'icon': 'X',
        'icon_color': 'linear-gradient(135deg, #00acc1, #1e88e5)',
        'category': '办公效率',
        'detect_type': 'scrape',
        'check_url': 'https://www.xyplorer.com/download.php?bit=64',
        'version_regex': r'(\d+\.\d+\.\d+)\s*\(64-bit,',
        'date_regex': r'\(64-bit,\s*(\d{1,2}-[A-Za-z]{3}-\d{4})\)',
        'prefer_scraped_version': True,
        'version': '28.30.2800',
        'size': 14 * 1024 * 1024,
        'download_url': 'https://www.xyplorer.com/download/xyplorer64_full_noinstall.zip',
        'skip_md5': True,
        'detect_timeout': 120,
        'official_site': 'https://www.xyplorer.com/',
    },
    {
        'name': 'Microsoft Edge',
        'name_cn': 'Microsoft Edge',
        'icon': 'E',
        'icon_color': 'linear-gradient(135deg, #0078d4, #00bcf2)',
        'category': '浏览器',
        'detect_type': 'edge_api',
        'version': '154.0.4258.37',
        'download_url': 'https://www.microsoft.com/en-us/edge/business/download',
        'official_site': 'https://github.com/Bush2021/edge_installer',
    },
    {
        'name': 'Google Chrome',
        'name_cn': 'Google Chrome',
        'icon': 'C',
        'icon_color': 'linear-gradient(135deg, #4285f4, #34a853)',
        'category': '浏览器',
        'detect_type': 'chrome_api',
        'version': '154.0.8037.58',
        'download_url': 'https://dl.google.com/dl/chrome/install/googlechromestandaloneenterprise64.msi',
        'official_site': 'https://github.com/Bush2021/chrome_installer',
    },
    {
        'name': 'NetEase Cloud Music',
        'name_cn': '网易云音乐',
        'icon': '网',
        'icon_color': 'linear-gradient(135deg, #e60026, #ff4d4f)',
        'category': '影音娱乐',
        'detect_type': 'increment',
        'base_version': '3.1.40.205461',
        'url_pattern': 'https://d8.music.126.net/dmusic2/NeteaseCloudMusic_Music_official_{ver}_64.exe',
        'param_format': '',
        'channel': '',
        'referer': 'https://music.163.com/',
        'official_site': 'https://music.163.com/#/download',
    },
    {
        'name': '360 Safe Browser 16',
        'name_cn': '360安全浏览器16',
        'icon': '360',
        'icon_color': 'linear-gradient(135deg, #00b42a, #00d68f)',
        'category': '浏览器',
        'detect_type': 'increment',
        'base_version': '16.3.1053',
        'pe_version': True,
        'url_pattern': 'https://sedl.360tpcdn.com/se/360se{ver}.64.exe',
        'param_format': '',
        'channel': '',
        'official_site': 'https://browser.360.cn/',
    },
    {
        'name': '360 Safe Browser 17',
        'name_cn': '360安全浏览器17',
        'icon': '360',
        'icon_color': 'linear-gradient(135deg, #00b42a, #00d68f)',
        'category': '浏览器',
        'detect_type': 'scrape',
        'check_url': 'https://bbs.360.cn/thread-16184433-1-1.html',
        'version_regex': r'(17\.1\.\d+)\.64',
        'url_pattern': 'https://sedl.360tpcdn.com/se/360se{ver}.64.exe',
        'default_size_mb': 210.5,
        'param_format': '',
        'channel': '',
        'official_site': 'https://bbs.360.cn/thread-16184433-1-1.html',
    },
    {
        'name': '360 Extreme Browser',
        'name_cn': '360极速浏览器',
        'icon': '360',
        'icon_color': 'linear-gradient(135deg, #165dff, #4080ff)',
        'category': '浏览器',
        'detect_type': 'scrape',
        'check_url': 'https://browser.360.cn/browser_download_link.js',
        'version_regex': r'360csex_(\d+\.\d+\.\d+)\.64\.exe',
        'use_newer_scraped': True,
        'version': '23.1.1298',
        'url_pattern': 'https://sedl.360tpcdn.com/cse/360csex_{ver}.64.exe',
        'pe_version': True,
        'official_site': 'https://chromex.360.cn/',
    },
    {
        'name': 'Topaz Photo',
        'name_cn': 'Topaz Photo',
        'icon': 'P',
        'icon_color': 'linear-gradient(135deg, #ff6b35, #f7931e)',
        'category': '图像处理',
        'detect_type': 'discourse',
        'check_url': 'https://community.topazlabs.com/c/topaz-photo/topaz-photo-releases/117.json',
        'version_title_pattern': r'Topaz Photo v?(\d+\.\d+\.\d+)',
        'download_url_template': 'https://downloads.topazlabs.com/deploy/TopazPhoto/{version}/TopazPhoto-{version}.msi',
        'version': '1.7.0',
        'download_url': 'https://downloads.topazlabs.com/deploy/TopazPhoto/1.7.0/TopazPhoto-1.7.0.msi',
        'official_site': 'https://community.topazlabs.com/c/topaz-photo/topaz-photo-releases/117',
    },
    {
        'name': 'Topaz Gigapixel',
        'name_cn': 'Topaz Gigapixel',
        'icon': 'G',
        'icon_color': 'linear-gradient(135deg, #7b2ff7, #a855f7)',
        'category': '图像处理',
        'detect_type': 'discourse',
        'check_url': 'https://community.topazlabs.com/c/topaz-gigapixel/topaz-gigapixel-releases/128.json',
        'version_title_pattern': r'Topaz Gigapixel v?(\d+\.\d+\.\d+)',
        'download_url_template': 'https://downloads.topazlabs.com/deploy/TopazGigapixel/{version}/TopazGigapixel-{version}.msi',
        'version': '1.3.6',
        'download_url': 'https://downloads.topazlabs.com/deploy/TopazGigapixel/1.3.6/TopazGigapixel-1.3.6.msi',
        'official_site': 'https://community.topazlabs.com/c/topaz-gigapixel/topaz-gigapixel-releases/128',
    },
    {
        'name': 'Topaz Video',
        'name_cn': 'Topaz Video',
        'icon': 'V',
        'icon_color': 'linear-gradient(135deg, #ef4444, #f97316)',
        'category': '视频处理',
        'detect_type': 'discourse',
        'check_url': 'https://community.topazlabs.com/c/topaz-video/topaz-video-releases/122.json',
        'version_title_pattern': r'Topaz Video v?(\d+\.\d+\.\d+)',
        'download_url_template': 'https://downloads.topazlabs.com/deploy/TopazVideoStudio/{version}/TopazVideo-{version}.msi',
        'version': '1.7.0',
        'download_url': 'https://downloads.topazlabs.com/deploy/TopazVideoStudio/1.7.0/TopazVideo-1.7.0.msi',
        'official_site': 'https://community.topazlabs.com/c/topaz-video/topaz-video-releases/122',
    },
    {
        'name': 'Adobe Flash Player',
        'name_cn': 'Adobe Flash Player',
        'icon': 'F',
        'icon_color': 'linear-gradient(135deg, #f0282f, #ff6b6b)',
        'category': '运行环境',
        'detect_type': 'scrape',
        'check_url': 'https://flash-player-links.pages.dev/',
        'version_regex': r'"version":\s*"([^"]+)"',
        'date_regex': r'"date":\s*"([^"]+)"',
        'version': '34.0.0.384',
        'download_url': 'https://flash-player-links.pages.dev/',
        'official_site': 'https://flash-player-links.pages.dev/',
    },
    {
        'name': 'Microsoft Visual C++ Redistributable',
        'name_cn': 'Microsoft Visual C++ 运行库',
        # 搜索别名：官方名里没有"VC"字样，用户搜 VC/VC++ 时靠别名命中
        'alias': 'VC VC++ vcredist',
        'icon': 'VC',
        'icon_color': 'linear-gradient(135deg, #a34aa2, #5c2d91)',
        'category': '运行环境',
        'detect_type': 'fixed',
        'version': '14.52.37025.0',
        'date': '2026-10-15',
        # 该安装包的 CDN Last-Modified / 数字签名日期（10-09）早于官方发布日，
        # 用 prefer_config_date 固定为人工核实的发布日期，不被探测值覆盖。
        'prefer_config_date': True,
        # 主链接用于 fixed 探测（HEAD 取体积），x64/x86/arm64 三平台走 downloads
        # 二级链接，前端渲染为平台按钮：左键直接下载，右键/长按弹菜单复制完整地址。
        'download_url': 'https://download.visualstudio.microsoft.com/download/pr/98bcc84f-0a9c-417c-a681-d88411dbb90f/7ACA0477C32519E54D888102ECF02495C8C05F83D61858A73BF75958DDC29835/VC_redist.x64.exe',
        'downloads': [
            {'name': 'x64', 'url': 'https://download.visualstudio.microsoft.com/download/pr/98bcc84f-0a9c-417c-a681-d88411dbb90f/7ACA0477C32519E54D888102ECF02495C8C05F83D61858A73BF75958DDC29835/VC_redist.x64.exe'},
            {'name': 'x86', 'url': 'https://download.visualstudio.microsoft.com/download/pr/9b86116f-5f77-4f8f-8eba-bcea3cbdddc6/067B997E8E2D444EDA6F5ADCE816FCAB23154192C4C04F8EEBB24B01A757F4BF/VC_redist.x86.exe'},
            {'name': 'arm64', 'url': 'https://download.visualstudio.microsoft.com/download/pr/98bcc84f-0a9c-417c-a681-d88411dbb90f/D7396DB95BE3A5F0BC93E02BD915C856081DD5FED9F231A7065F26C57F60ADAC/VC_redist.arm64.exe'},
        ],
        'official_site': 'https://learn.microsoft.com/zh-cn/cpp/windows/latest-supported-vc-redist?view=msvc-170',
    },
    {
        'name': 'VC Runtimes 整合版',
        'name_cn': 'VC运行库整合版 vcredist',
        'icon': 'VR',
        'icon_color': 'linear-gradient(135deg, #0078d4, #005a9e)',
        'category': '运行环境',
        # 探测方式：GitLab Releases。版本/日期取自 release，体积取主安装包
        # （description 里的 /uploads/ 链接，asset_filter 选中 AIO x86+x64 主包）。
        'detect_type': 'gitlab_release',
        'gitlab_project': 'stdout12/vcredist',
        'asset_filter': 'AIO_x86_x64.exe',
        # tag 形如 v0.106.0，去掉前导"0."得到对外展示的 106.0（AIO 主版本号），
        # 且保持单调递增，避免被防降级逻辑拦截、也能跟随新 release 自动更新。
        'version_regex': r'0\.(\d+\.\d+)',
        'version': '106.0',
        'date': '2026-10-14',
        'download_url': 'https://gitlab.com/stdout12/vcredist/-/releases/',
        'official_site': 'https://gitlab.com/stdout12/vcredist/-/releases/',
    },
    {
        'name': 'InnoExtractor',
        'name_cn': 'InnoExtractor 2027',
        'icon': 'IE',
        'icon_color': 'linear-gradient(135deg, #e67e22, #d35400)',
        'category': '系统工具',
        'detect_type': 'fixed',
        'version': '12.1.1.185',
        'date': '2026-10-15',
        'download_url': 'https://www.havysoft.cl/download/IE_Install.zip',
        'official_site': 'https://www.havysoft.cl/descargar.html',
    },
    {
        'name': 'IObit Uninstaller',
        'name_cn': 'IObit Uninstaller',
        'icon': 'I',
        'icon_color': 'linear-gradient(135deg, #ff6b35, #f7931e)',
        'category': '系统工具',
        'detect_type': 'fixed',
        'version': '16.0.0.34',
        'download_url': 'https://cdn.iobit.com/dl/iobituninstaller.exe',
        'official_site': 'https://www.iobit.com/en/advanceduninstaller.php',
    },
    {
        'name': 'WinSnap',
        'name_cn': 'WinSnap',
        'icon': 'W',
        'icon_color': 'linear-gradient(135deg, #667eea, #764ba2)',
        'category': '图像工具',
        # 官方下载页一次给全：版本号 / 文件名 / 体积 / 更新日期
        #   Download WinSnap_6.3.5-setup.exe (3 MB)  Updated on 21-Oct-2026
        # 原来用 increment（从 base_version 逐段递增）有两个致命问题：
        #   ① ntwind.com 的 Cloudflare 不返回 Content-Length/Last-Modified，
        #      check_url 拿不到体积 → 判「无体积」→ 整轮结果作废，
        #      明明页面已经抓到 6.3.5 却退回旧值 6.3.3；
        #   ② 递增扫描依赖 base_version 手动跟进，跳过一个小版本就永远追不上。
        # 改 scrape 后版本/日期/体积/直链全部来自同一次请求，不会再错配。
        'detect_type': 'scrape',
        'check_url': 'https://www.ntwind.com/software/winsnap.html',
        'version_regex': r'WinSnap_(\d+\.\d+\.\d+)-setup\.exe',
        'date_regex': r'WinSnap_\d+\.\d+\.\d+-setup\.exe[^<]*</a>\s*<p>Updated on (\d{2}-[A-Za-z]{3}-\d{4})',
        'size_regex_mb': r'WinSnap_\d+\.\d+\.\d+-setup\.exe\s*\((\d+(?:\.\d+)?)\s*(KB|MB|GB)\)',
        'download_url_regex': r'(https://www\.ntwind\.com/download/WinSnap_\d+\.\d+\.\d+-setup\.exe)',
        'prefer_scraped_version': True,
        'version': '6.3.5',
        'skip_md5': True,
        'download_url': 'https://www.ntwind.com/files/WinSnap_6.3.5-setup.exe',
        'official_site': 'https://www.ntwind.com/software/winsnap.html',
    },
    {
        'name': 'AIDA64',
        'name_cn': 'AIDA64 Extreme',
        'icon': 'A',
        'icon_color': 'linear-gradient(135deg, #e74c3c, #c0392b)',
        'category': '系统工具',
        'detect_type': 'scrape',
        'check_url': 'https://www.aida64.com/downloads',
        'version_regex': r'version">(\d+\.\d+\.\d+)',
        'url_ver_format': 'short',
        'url_pattern': 'https://download.aida64.com/aida64extreme{ver}.zip',
        'version': '8.40.5000',
        'download_url': 'https://download.aida64.com/aida64extreme840.zip',
        'skip_md5': True,
        'official_site': 'https://www.aida64.com/downloads',
    },
    {
        'name': 'Win11 LTSC',
        'name_cn': 'Windows 11 LTSC 2024',
        'icon': '11',
        'icon_color': 'linear-gradient(135deg, #0078d4, #00bcf2)',
        'category': '操作系统',
        'detect_type': 'github_release',
        'repo': 'adavak/win_iso_build',
        'tag_filter': 'Windows_11_LTSC_2024_X64_ZH-CN',
        'version_regex': r'(\d+\.\d+(?:\.\d+)*)',
        'version': '26200.9457',
        'size': 5754 * 1024 * 1024,
        'date': '2026-09-14',
        'download_url': 'https://github.com/adavak/win_iso_build/releases',
        'official_site': 'https://github.com/adavak/win_iso_build/releases',
    },
    {
        'name': 'Win10 LTSC',
        'name_cn': 'Windows 10 LTSC 2021',
        'icon': '10',
        'icon_color': 'linear-gradient(135deg, #0078d4, #50e6ff)',
        'category': '操作系统',
        'detect_type': 'github_release',
        'repo': 'adavak/win_iso_build',
        'tag_filter': 'Windows_10_LTSC_2021_X64_ZH-CN',
        'version_regex': r'(\d+\.\d+(?:\.\d+)*)',
        'version': '19044.7727',
        'size': 4845 * 1024 * 1024,
        'date': '2026-09-14',
        'download_url': 'https://github.com/adavak/win_iso_build/releases',
        'official_site': 'https://github.com/adavak/win_iso_build/releases',
    },
    {
        'name': 'Notepad4',
        'name_cn': 'Notepad4',
        'icon': 'N4',
        'icon_color': 'linear-gradient(135deg, #2c3e50, #3498db)',
        'category': '文本编辑',
        'detect_type': 'github_release',
        'repo': 'zufuliu/notepad4',
        'version_regex': r'v?(\d+\.\d+r\d+)',
        'version': '26.08r6282',
        'date': '2026-08-16',
        'download_url': 'https://github.com/zufuliu/notepad4/releases',
        'official_site': 'https://github.com/zufuliu/notepad4/releases',
    },
    {
        'name': 'Chrome++',
        'name_cn': 'Chrome++',
        'icon': 'C+',
        'icon_color': 'linear-gradient(135deg, #4285f4, #34a853)',
        'category': '浏览器',
        'detect_type': 'github_release',
        'repo': 'Bush2021/chrome_plus',
        'version_regex': r'v?(\d+\.\d+\.\d+)',
        'version': '1.18.2',
        'date': '2026-07-30',
        'download_url': 'https://github.com/Bush2021/chrome_plus/releases',
        'official_site': 'https://github.com/Bush2021/chrome_plus/releases',
    },
    {
        'name': 'WinMerge',
        'name_cn': 'WinMerge',
        'icon': 'WM',
        'icon_color': 'linear-gradient(135deg, #e67e22, #f39c12)',
        'category': '文件对比',
        'detect_type': 'github_release',
        'repo': 'WinMerge/winmerge',
        'version_regex': r'v?(\d+\.\d+\.\d+\.\d+)',
        'version': '2.16.58.2',
        'date': '2026-08-27',
        'download_url': 'https://github.com/WinMerge/winmerge/releases',
        'official_site': 'https://github.com/WinMerge/winmerge/releases',
    },
    {
        'name': 'Beyond Compare',
        'name_cn': 'Beyond Compare',
        'icon': 'BC',
        'icon_color': 'linear-gradient(135deg, #2c3e50, #4ca1af)',
        'category': '文件对比',
        'detect_type': 'scrape',
        'check_url': 'https://www.scootersoftware.com/download/v5changelog',
        'version_regex': r'(\d+\.\d+\.\d+\.\d+)\s*-\s*[A-Z][a-z]+ \d+, \d{4}',
        'date_regex': r'\d+\.\d+\.\d+\.\d+\s*-\s*([A-Z][a-z]+ \d+, \d{4})',
        'url_pattern': 'https://www.scootersoftware.com/files/BCompare-zh-{ver}.exe',
        'prefer_scraped_version': True,
        'version': '5.2.6.32774',
        'size': 29 * 1024 * 1024,
        'download_url': 'https://www.scootersoftware.com/files/BCompare-zh-5.2.6.32774.exe',
        'skip_md5': True,
        'detect_timeout': 120,
        'official_site': 'https://www.scootersoftware.com/download/v5changelog',
    },
    {
        'name': 'MathType',
        'name_cn': 'MathType',
        'icon': 'MT',
        'icon_color': 'linear-gradient(135deg, #e74c3c, #c0392b)',
        'category': '办公效率',
        'detect_type': 'scrape',
        'check_url': 'https://store.wiris.com/en/products/mathtype/download/windows',
        'version_regex': r'MathType-win-[a-z]+-(\d+\.\d+\.\d+\.\d+)',
        'url_pattern': 'https://downloads.wiris.com/mathtype/windows/MathType-win-zh-{ver}.exe',
        'prefer_scraped_version': True,
        'version': '7.12.3.470',
        'size': 45 * 1024 * 1024,
        'download_url': 'https://downloads.wiris.com/mathtype/windows/MathType-win-zh-7.12.3.470.exe',
        'official_site': 'https://store.wiris.com/en/products/mathtype/download/windows',
    },
    {
        'name': 'HEU KMS',
        'name_cn': 'HEU KMS Activator',
        'icon': 'HK',
        'icon_color': 'linear-gradient(135deg, #9b59b6, #8e44ad)',
        'category': '系统工具',
        'detect_type': 'github_release',
        'repo': 'zbezj/HEU_KMS_Activator',
        'version_regex': r'v?(\d+\.\d+\.\d+)',
        'version_source': 'name',
        'version': '64.04.0',
        'date': '2026-07-06',
        'download_url': 'https://github.com/zbezj/HEU_KMS_Activator/releases',
        'official_site': 'https://github.com/zbezj/HEU_KMS_Activator/releases',
    },
    {
        'name': 'qBittorrent EE',
        'name_cn': 'qBittorrent Enhanced',
        'icon': 'qB',
        'icon_color': 'linear-gradient(135deg, #2c3e50, #e74c3c)',
        'category': '下载工具',
        'detect_type': 'github_release',
        'repo': 'c0re100/qBittorrent-Enhanced-Edition',
        'version_regex': r'v?(\d+\.\d+\.\d+\.\d+)',
        'version': '5.2.3.10',
        'date': '2026-07-20',
        'download_url': 'https://github.com/c0re100/qBittorrent-Enhanced-Edition/releases',
        'official_site': 'https://github.com/c0re100/qBittorrent-Enhanced-Edition/releases',
    },
    {
        'name': 'Open-Shell',
        'name_cn': 'Open-Shell Menu',
        'icon': 'OS',
        'icon_color': 'linear-gradient(135deg, #0078d4, #00bcf2)',
        'category': '系统工具',
        # 探测方式：GitHub Releases。release 内含多资产（安装包 OpenShellSetup_*.exe + 符号 7z +
        # Utility.exe），默认会把三者大小相加且推发布页；改用 asset_filter 只取安装包 exe、
        # use_asset_url 返回该 exe 直链。官方只发预发布（prerelease），故 include_prerelease=True。
        'detect_type': 'github_release',
        'repo': 'Open-Shell/Open-Shell-Menu',
        'version_regex': r'v?(\d+\.\d+\.\d+)',
        'include_prerelease': True,
        'asset_filter': 'OpenShellSetup',
        'use_asset_url': True,
        'version': '4.4.202',
        'date': '2026-10-13',
        'download_url': 'https://github.com/Open-Shell/Open-Shell-Menu/releases/download/v4.4.202/OpenShellSetup_4_4_202.exe',
        'official_site': 'https://github.com/Open-Shell/Open-Shell-Menu/releases',
    },
    {
        'name': 'PowerDirector',
        'name_cn': 'PowerDirector 365',
        'icon': 'PD',
        'icon_color': 'linear-gradient(135deg, #2c3e50, #f39c12)',
        'category': '视频编辑',
        'detect_type': 'cyberlink',
        'cyberlink_product_id': 4,
        # 官方版本源排查结论（2026-10-15 复测）：试用下载器 info.ini 的
        # DisplayBuildNumber=25.0.0904.0（VDE260910-01）即试用通道当前基线，官方
        # 新构建 25.0.1007.0（Ultimate 零售版，SR_No=VDE261008-02，2026-10-08）
        # 尚未铺到匿名公开通道。用官方 thank-you API 轮询做根源探测（官方换包即
        # 自动对齐），配合 base_version/version_display 防降级：探测值不比试用基线
        # 新 → 显示 version_display；官方铺开 1007 后自动对齐。
        'version': '25.0.1007.0',
        'base_version': '25.0.0904.0',
        'version_display': '25.0.1007.0',
        'size': 691 * 1024 * 1024,
        'date': '2026-10-08',
        'skip_md5': True,
        'download_url': 'https://build.cyberlink.com/Retail/PowerDirector/CGQC8ZH75VM6/PowerDirector_DirectorSuite365.exe',
        'official_site': 'https://www.cyberlink.com/products/powerdirector-video-editing-software/features_en_US.html',
    },
    {
        'name': 'PhotoDirector',
        'name_cn': 'PhotoDirector 365',
        'icon': 'PhD',
        'icon_color': 'linear-gradient(135deg, #8e44ad, #3498db)',
        'category': '图像处理',
        # 官方版本源排查结论（2026-10-15 复测）：
        #  - 试用下载器（thank-you API → user-add.do → downloader）info.ini 的
        #    DisplayBuildNumber=17.6.1826.0 是安装框架版本，≠ 产品版本 18.x（两次复测一致）；
        #  - build.cyberlink.com 零售直链 Y2QIW32JB74CH 的 S3 对象最后修改仍为 2026-09-08，
        #    实际还是 0908 包；官方新构建 18.0.1011.0 只走订阅 updater 通道分发；
        #  - support 补丁中心 prodId=211 只列 2018 年旧补丁；liveupdate /b/b/r 只剩广告接口。
        # 结论：匿名公开接口均无当前构建 → 用官方 thank-you API 轮询做根源探测（官方换包即自动
        # 对齐），配合 base_version/version_display 防降级，展示已核实的 18.0.1011.0。
        'detect_type': 'cyberlink',
        'cyberlink_product_id': 211,
        'base_version': '18.0.1011.0',
        'version_display': '18.0.1011.0',
        'version': '18.0.1011.0',
        'size': 670 * 1024 * 1024,
        'date': '2026-10-14',
        'skip_md5': True,
        'download_url': 'https://build.cyberlink.com/Retail/PhotoDirector/Y2QIW32JB74CH/PhotoDirector_DirectorSuite365.exe',
        'official_site': 'https://www.cyberlink.com/products/photodirector/features_en_US.html',
    },
    {
        'name': 'WePE Enhanced',
        'name_cn': '微PE工具箱增强版',
        'icon': 'PE',
        'icon_color': 'linear-gradient(135deg, #00bcd4, #009688)',
        'category': '系统工具',
        'detect_type': 'scrape',
        'check_url': 'https://bbs.wuyou.net/forum.php?mod=viewthread&tid=448767',
        'version_regex': r'(\d{4}\.\d{2}\.\d{2})更新',
        'date_regex': r'(\d{4}\.\d{2}\.\d{2})更新',
        'prefer_scraped_version': True,
        'skip_md5': True,
        'is_webpage': True,
        'version': '2026.09.06',
        'size': 256 * 1024 * 1024,
        'date': '2026-09-06',
        'download_url': 'https://bbs.wuyou.net/forum.php?mod=viewthread&tid=448767',
        'official_site': 'https://bbs.wuyou.net/forum.php?mod=viewthread&tid=448767',
    },
    {
        'name': 'WPS Office',
        'name_cn': 'WPS Office 2023',
        'icon': 'W',
        'icon_color': 'linear-gradient(135deg, #e74c3c, #f39c12)',
        'category': '办公软件',
        'detect_type': 'fixed',
        'referer': 'https://ep.wps.cn/',
        'version': '12.1.0.26899',
        'size': 418 * 1024 * 1024,
        'date': '2026-07-06',
        'download_url': 'https://wps-cn-ep.wpscdn.cn/wps/download/ep/WPS2023/WPSPro_12.1.0.26899.exe',
        'official_site': 'https://ep.wps.cn/download',
    },
    {
        'name': 'Shandou Downloader',
        'name_cn': '闪豆下载器',
        'icon': 'SD',
        'icon_color': 'linear-gradient(135deg, #9b59b6, #3498db)',
        'category': '下载工具',
        'detect_type': 'lanzou',
        'version_regex': r'(\d{4}\.\d{2}\.\d{2})',
        'version': '2026.08.28',
        'size': 90 * 1024 * 1024,
        'date': '2026-08-28',
        'download_url': 'https://www.lanzoui.com/b015c0ksh',
        'official_site': 'https://www.lanzoui.com/b015c0ksh',
    },
    {
        'name': 'WinNTSetup',
        'name_cn': 'WinNTSetup',
        'icon': 'WN',
        'icon_color': 'linear-gradient(135deg, #2c3e50, #e74c3c)',
        'category': '系统工具',
        'detect_type': 'fixed',
        'version': '5.4.2',
        'size': 10 * 1024 * 1024,
        'date': '2026-08-01',
        'is_webpage': True,
        'download_url': 'https://www.mediafire.com/folder/53um6k2nmhvd5/',
        'official_site': 'https://www.mediafire.com/folder/53um6k2nmhvd5/',
    },
    {
        'name': 'Foobar2000',
        'name_cn': 'Foobar2000 汉化版',
        'icon': 'FB',
        'icon_color': 'linear-gradient(135deg, #1abc9c, #2c3e50)',
        'category': '影音播放',
        'detect_type': 'scrape',
        'check_url': 'https://www.cnblogs.com/asionwu',
        'version_regex': r'foobar2000\s+v(\d+\.\d+\.\d+)\s+汉化版',
        'date_regex': r'更新日期：(\d+\.\d+\.\d+)',
        'prefer_scraped_version': True,
        'skip_md5': True,
        'is_webpage': True,
        'version': '2.25.10',
        'size': 20 * 1024 * 1024,
        'date': '2026-08-24',
        'download_url': 'https://www.cnblogs.com/asionwu',
        'official_site': 'https://www.cnblogs.com/asionwu',
    },
    {
        'name': 'IObit Driver Booster',
        'name_cn': 'IObit Driver Booster',
        'icon': 'DB',
        'icon_color': 'linear-gradient(135deg, #e74c3c, #f39c12)',
        'category': '系统工具',
        'detect_type': 'fixed',
        'pe_version': True,
        'version': '14.0.1.462',
        'download_url': 'https://cdn.iobit.com/dl/driver_booster_setup.exe',
        'official_site': 'https://www.iobit.com/driver-booster.php',
    },
    {
        'name': 'Advanced SystemCare Ultimate',
        'name_cn': 'Advanced SystemCare Ultimate',
        'icon': 'ASCU',
        'icon_color': 'linear-gradient(135deg, #8e44ad, #9b59b6)',
        'category': '系统工具',
        'detect_type': 'fixed',
        'pe_version': True,
        'version': '18.5.0.120',
        'download_url': 'https://cdn.iobit.com/dl/asc-ultimate-setup.exe',
        'official_site': 'https://www.iobit.com/en/advancedsystemcareultimate.php',
    },
    {
        'name': 'Advanced SystemCare Pro',
        'name_cn': 'Advanced SystemCare Pro',
        'icon': 'ASC',
        'icon_color': 'linear-gradient(135deg, #e67e22, #f1c40f)',
        'category': '系统工具',
        'detect_type': 'fixed',
        'pe_version': True,
        'version': '19.6.0.238',
        'download_url': 'https://cdn.iobit.com/dl/advanced-systemcare-setup.exe',
        'official_site': 'https://www.iobit.com/en/advancedsystemcarepro.php',
    },
    {
        'name': 'Vuescan',
        'name_cn': 'Vuescan',
        'icon': 'VS',
        'icon_color': 'linear-gradient(135deg, #27ae60, #2980b9)',
        'category': '图像工具',
        'detect_type': 'scrape',
        'check_url': 'https://www.hamrick.com/',
        'version_regex': r'softwareVersion["\s:]+"?([\d.]+)',
        'date_regex': r'dateModified["\s:]+"?(\d{4}-\d{2}-\d{2})',
        'prefer_scraped_version': True,
        'version': '9.8.58',
        'download_url': 'https://files.hamrick.com/vuex6498.exe',
        'official_site': 'https://www.hamrick.com/',
    },
    {
        'name': 'W10Privacy',
        'name_cn': 'W10Privacy',
        'icon': 'W10',
        'icon_color': 'linear-gradient(135deg, #2c3e50, #4ca1af)',
        'category': '系统工具',
        'detect_type': 'scrape',
        'check_url': 'https://www.w10privacy.de/deutsch-start/download/',
        'version_regex': r'current version: v\.(\d+\.\d+\.\d+\.\d+)',
        'download_url_regex': r'(/app/download/\d+/W10Privacy\.zip)',
        'prefer_scraped_version': True,
        'version': '6.3.0.2',
        'download_url': 'https://www.w10privacy.de/app/download/13888014036/W10Privacy.zip',
        'official_site': 'https://www.w10privacy.de/',
    },
    {
        'name': 'GoldWave',
        'name_cn': 'GoldWave',
        'icon': 'GW',
        'icon_color': 'linear-gradient(135deg, #f39c12, #e67e22)',
        'category': '影音娱乐',
        'detect_type': 'fixed',
        'filename_version_regex': r'InstallGoldWave(\d)(\d+)',
        'version': '7.09',
        'date': '2026-09-29',
        'download_url': 'https://goldwave.ca/download.php?file=gw',
        'official_site': 'https://goldwave.ca/',
    },
    {
        'name': 'EmEditor',
        'name_cn': 'EmEditor',
        'icon': 'EE',
        'icon_color': 'linear-gradient(135deg, #1e88e5, #0d47a1)',
        'category': '开发工具',
        'detect_type': 'increment',
        'base_version': '26.4.0',
        # 第二段会整段跳（26.2.9 -> 26.3.0 -> 26.4.0），逐段递增够不着，改用列车扫描
        'minor_scan': True,
        'minor_index': 1,
        'minor_scan_count': 8,
        'minor_scan_builds': 4,
        'url_pattern': 'https://emeditor.blob.core.windows.net/emed64_{ver}_portable.zip',
        'param_format': '',
        'channel': '',
        'check_url': 'https://zh-cn.emeditor.com/category/emeditor-core/',
        'version_regex': r'EmEditor v(\d+\.\d+\.\d+)',
        'skip_md5': True,
        'detect_timeout': 120,
        'official_site': 'https://zh-cn.emeditor.com/',
    },
    {
        'name': 'PDF-XChange Editor',
        'name_cn': 'PDF-XChange Editor',
        'icon': 'PX',
        'icon_color': 'linear-gradient(135deg, #009688, #00695c)',
        'category': '办公工具',
        'detect_type': 'increment',
        'base_version': '11.1.0.0',
        'url_pattern': 'https://downloads-11.pdf-xchange.com/{ver}/EditorV11.x64.msi',
        'param_format': '',
        'channel': '',
        'check_url': 'https://tracker-software.com/product/pdf-xchange-editor/history',
        'version_regex': r'(\d+\.\d+\.\d+\.\d+)',
        'date_regex': r'Released\s*<span class="release-date-value"[^>]*>\s*([A-Za-z]+ \d{1,2}(?:st|nd|rd|th)?, \d{4})',
        'official_site': 'https://tracker-software.com/product/pdf-xchange-editor/history',
    },
    {
        'name': 'PDF-XChange Pro',
        'name_cn': 'PDF-XChange Pro',
        'icon': 'PP',
        'icon_color': 'linear-gradient(135deg, #00838f, #006064)',
        'category': '办公工具',
        # 企业版（Editor Plus + Tools + Printer Standard 套装）。
        # 版本从产品页抓：<strong>Current version:</strong> 11.1.1.0
        # 官网 history 页滞后（还停在 11.1.0.0 / Sep 29），产品页更新更及时。
        # 直链按版本拼（官网固定 downloads-11.pdf-xchange.com/{ver}/ProV11.x64.msi）。
        'detect_type': 'scrape',
        'check_url': 'https://www.pdf-xchange.com/product/pdf-xchange-pro',
        'version_regex': r'Current version:</strong>\s*(\d+\.\d+\.\d+\.\d+)',
        'prefer_scraped_version': True,
        'url_pattern': 'https://downloads-11.pdf-xchange.com/{ver}/ProV11.x64.msi',
        'version': '11.1.1.0',
        'skip_md5': True,
        'download_url': 'https://downloads-11.pdf-xchange.com/11.1.1.0/ProV11.x64.msi',
        'official_site': 'https://www.pdf-xchange.com/product/pdf-xchange-pro',
    },
    {
        'name': 'AnyDesk',
        'name_cn': 'AnyDesk',
        'icon': 'AD',
        'icon_color': 'linear-gradient(135deg, #ef5350, #d32f2f)',
        'category': '远程工具',
        'detect_type': 'fixed',
        'pe_version': True,
        'version': '9.8.2',
        'download_url': 'https://download.anydesk.com/AnyDesk.exe',
        # download.anydesk.com 对部分机房 IP 限流（PE 分片请求 429），
        # 版本号改从官网下载页的 JSON 里抓（windows 客户端包 win_exe 的 version 字段），
        # PE 探测失败时由它兜底。
        'page_version_url': 'https://anydesk.com/zh/downloads/windows',
        'page_version_regex': r'"id":"win_exe","version":"([\d.]+)"',
        'official_site': 'https://anydesk.com/zh/downloads/windows',
    },
    {
        'name': 'Adobe Camera Raw',
        'name_cn': 'Adobe Camera Raw',
        'icon': 'ACR',
        'icon_color': 'linear-gradient(135deg, #fa0f00, #b30000)',
        'category': '图像工具',
        'detect_type': 'increment',
        'base_version': '18.7',
        'url_pattern': 'https://download.adobe.com/pub/adobe/photoshop/cameraraw/win/{major}.x/AdobeCameraRaw_x64_{major_minor_underscore}.exe',
        'param_format': '',
        'channel': '',
        'official_site': 'https://helpx.adobe.com/cn/camera-raw/using/whats-new.html',
    },
    {
        'name': 'Wing FTP Server',
        'name_cn': 'Wing FTP Server',
        'icon': 'WF',
        'icon_color': 'linear-gradient(135deg, #e67e22, #d35400)',
        'category': '服务器工具',
        'detect_type': 'fixed',
        'pe_version': True,
        # 二进制在 BunnyCDN 上被缓存 7 天（Cache-Control: max-age=604800），
        # 新版发布后边缘节点可能仍返回旧包；官网下载页即时更新，用它交叉校验版本号。
        'page_version_url': 'https://www.wftpserver.com/download.htm',
        'page_version_regex': r'Wing FTP Server\s*<b>\s*v([\d.]+)\s*</b>',
        'version': '8.2.5.0',
        'size': 77 * 1024 * 1024,
        'download_url': 'https://www.wftpserver.com/download/WingFtpServer.exe',
        'official_site': 'https://www.wftpserver.com/',
    },
    {
        'name': 'Wise Care 365',
        'name_cn': 'Wise Care 365',
        'icon': 'WC',
        'icon_color': 'linear-gradient(135deg, #3498db, #2980b9)',
        'category': '系统工具',
        'detect_type': 'increment',
        'base_version': '8.0.7.735',
        'url_pattern': 'https://downloads.wisecleaner.com/soft/WiseCare365_{ver}.zip',
        # 第三段会跳（8.0.6.734 -> 8.0.7.735），纯递增扫不到，用官网下载页的包名当起点
        'check_url': 'https://www.wisecleaner.com/download.html',
        'version_regex': r'WiseCare365_([\d.]+)\.zip',
        'version': '8.0.7.735',
        'skip_md5': True,
        'size': 60 * 1024 * 1024,
        'download_url': 'https://downloads.wisecleaner.com/soft/WiseCare365_8.0.7.735.zip',
        'official_site': 'https://www.wisecleaner.com/',
    },
    {
        'name': 'Bandicam',
        'name_cn': 'Bandicam',
        'icon': 'BD',
        'icon_color': 'linear-gradient(135deg, #e74c3c, #c0392b)',
        'category': '媒体工具',
        'detect_type': 'scrape',
        'check_url': 'https://bandicam.cn/downloads/version_history',
        'version_regex': r'(\d+\.\d+\.\d+\.\d+)',
        'date_regex': r'(\d{2}/\d{2}/\d{4})',
        'date_format': '%m/%d/%Y',
        'version': '27.0.6.2686',
        'size': 61 * 1024 * 1024,
        'download_url': 'https://dl.bandicam.com/bdcamsetup.exe',
        'official_site': 'https://bandicam.cn/downloads/version_history',
    },
    {
        'name': 'PowerISO',
        'name_cn': 'PowerISO',
        'icon': 'PI',
        'icon_color': 'linear-gradient(135deg, #e74c3c, #f39c12)',
        'category': '光盘工具',
        'detect_type': 'scrape',
        'check_url': 'https://www.poweriso.com/version.ini',
        'version_regex': r'Number=([\d.]+)',
        'date_regex': r'Date=(.+?)$',
        'prefer_scraped_version': True,
        'skip_md5': True,
        'version': '9.5',
        'size': 8.2 * 1024 * 1024,
        'download_url': 'https://www.poweriso.net/PowerISO9-x64.exe',
        'official_site': 'https://www.poweriso.com/',
    },
    {
        'name': 'Ventoy',
        'name_cn': 'Ventoy',
        'icon': 'VT',
        'icon_color': 'linear-gradient(135deg, #16a085, #2ecc71)',
        'category': '光盘工具',
        'detect_type': 'github_release',
        'repo': 'ventoy/Ventoy',
        'version_regex': r'(\d+\.\d+\.\d+)',
        # 直取 release 里 Windows 版压缩包（ventoy-x.x.x-windows.zip）的直链，
        # 大小只算这个包，不含 livecd.iso / linux.tar.gz 等其它分卷
        'use_asset_url': True,
        'asset_filter': 'windows',
        'version': '1.1.18',
        'size': 17 * 1024 * 1024,
        'date': '2026-10-09',
        'download_url': 'https://www.ventoy.net/en/download.html',
        'official_site': 'https://www.ventoy.net/en/doc_news.html',
    },
    {
        'name': 'PicPick Professional',
        'name_cn': 'PicPick Professional',
        'icon': 'PP',
        'icon_color': 'linear-gradient(135deg, #e67e22, #e74c3c)',
        'category': '图像工具',
        'detect_type': 'scrape',
        'check_url': 'https://picpick.app/en/changelog/',
        'version_regex': r'(\d+\.\d+\.\d+)\s*\(\d{4}-\d{2}-\d{2}\)',
        'date_regex': r'\d+\.\d+\.\d+\s*\((\d{4}-\d{2}-\d{2})\)',
        'url_pattern': 'https://download.picpick.net/{ver}/picpick_inst_pro.exe',
        'prefer_scraped_version': True,
        'skip_md5': True,
        'version': '7.6.1',
        'size': 66 * 1024 * 1024,
        'date': '2026-09-16',
        'download_url': 'https://download.picpick.net/7.6.1/picpick_inst_pro.exe',
        'official_site': 'https://picpick.app/en/changelog/',
    },
    {
        'name': 'Winxvideo AI',
        'name_cn': 'Winxvideo AI',
        'icon': 'WV',
        'icon_color': 'linear-gradient(135deg, #9b59b6, #8e44ad)',
        'category': '媒体工具',
        'detect_type': 'scrape',
        'check_url': 'https://www.winxdvd.com/winxvideo-ai/upgrade/version-update.json',
        'version_regex': r'"version":\s*"([\d.]+)"',
        'date_regex': r'"date":\s*"([\d-]+)"',
        'prefer_scraped_version': True,
        'pe_version': True,
        'skip_md5': True,
        'version': '4.11',
        'size': 293 * 1024 * 1024,
        'date': '2026-09-20',
        'download_url': 'https://www.winxdvd.com/download/winxvideo-ai.exe',
        'detect_timeout': 150,
        'official_site': 'https://www.winxdvd.com/winxvideo-ai/',
    },
    {
        'name': 'Glary Utilities Pro',
        'name_cn': 'Glary Utilities Pro',
        'icon': 'GU',
        'icon_color': 'linear-gradient(135deg, #e67e22, #d35400)',
        'category': '系统工具',
        'detect_type': 'fixed',
        'pe_version': True,
        'skip_md5': True,
        'version': '6.48.0.52',
        'size': 27 * 1024 * 1024,
        'date': '2026-09-21',
        'download_url': 'https://download.glarysoft.com/gupsetup.exe',
        'official_site': 'https://www.glarysoft.com/glary-utilities-pro/download',
    },
    {
        'name': 'Sublime Text',
        'name_cn': 'Sublime Text',
        'icon': 'ST',
        'icon_color': 'linear-gradient(135deg, #ff9800, #ff5722)',
        'category': '开发工具',
        'detect_type': 'scrape',
        'check_url': 'https://www.sublimetext.com/download',
        'version_regex': r'Build (\d{4})',
        'prefer_scraped_version': True,
        'skip_md5': True,
        'version': '4215',
        'url_pattern': 'https://download.sublimetext.com/sublime_text_build_{ver}_x64.zip',
        'official_site': 'https://www.sublimetext.com/download',
    },
    {
        'name': 'Start11',
        'name_cn': 'Start11',
        'icon': 'S11',
        'icon_color': 'linear-gradient(135deg, #0078d4, #005a9e)',
        'category': '系统工具',
        'detect_type': 'scrape',
        'check_url': 'https://www.stardock.com/products/start11/history',
        'version_regex': r'Start11 v(\d+\.\d+(?:\.\d+)?)\s+Changelog\s+\(Released',
        'date_regex': r'Released\s+(\d{1,2}/\d{1,2}/\d{4})',
        'date_format': '%m/%d/%Y',
        'prefer_scraped_version': True,
        'skip_md5': True,
        'version': '2.81',
        'size': 55 * 1024 * 1024,
        'date': '2026-09-21',
        'download_url': 'https://stardock.cachefly.net/software/Start11/v2/Start11v2_Setup.exe',
        'official_site': 'https://www.stardock.com/products/start11/history',
    },
    {
        'name': 'WinCam',
        'name_cn': 'WinCam',
        'icon': 'WC',
        'icon_color': 'linear-gradient(135deg, #3498db, #2c3e50)',
        'category': '影音播放',
        'detect_type': 'fixed',
        'version': '4.2',
        'size': 15 * 1024 * 1024,
        'date': '2026-09-16',
        'download_url': 'https://www.ntwind.com/files/WinCam_4.2-setup.exe',
        'official_site': 'https://www.ntwind.com/software/wincam.html',
    },
    {
        'name': 'Wondershare PDFelement',
        'name_cn': 'Wondershare PDFelement',
        'icon': 'PDF',
        'icon_color': 'linear-gradient(135deg, #e74c3c, #c0392b)',
        'category': '办公软件',
        'detect_type': 'increment',
        'base_version': '13.0.5',
        'url_patterns': [
            'https://download.wondershare.com/cbs_down/pdfelement-pro_{ver}_full5239.exe',
            'https://download.wondershare.com/cbs_down/pdfelement-pro_{ver}_full.exe',
            'https://download.wondershare.com/cbs_down/pdfelement-pro_{ver}.exe',
        ],
        'url_pattern': 'https://download.wondershare.com/cbs_down/pdfelement-pro_{ver}_full5239.exe',
        'param_format': '',
        'channel': '',
        'pe_version': True,
        'skip_md5': True,
        'official_site': 'https://pdf.wondershare.com/',
    },
    {
        'name': 'Adobe Acrobat Pro DC',
        'name_cn': 'Adobe Acrobat Pro DC',
        'icon': 'Adobe',
        'icon_color': 'linear-gradient(135deg, #ea0000, #b30000)',
        'category': '办公软件',
        'detect_type': 'increment',
        'base_version': '2600221996',
        'url_pattern': 'https://ardownload2.adobe.com/pub/adobe/acrobat/win/AcrobatDC/{ver}/AcrobatDCx64Upd{ver}.msp',
        'version_format': 'adobe_build',
        'version_display': '2026.002.21996',
        'adobe_max_jump': 700,
        'adobe_probe_workers': 20,
        'detect_timeout': 150,
        'skip_md5': True,
        'official_site': 'https://www.adobe.com/devnet-docs/acrobatetk/tools/ReleaseNotesDC/index.html',
    },
    {
        'name': 'HTTP Debugger',
        'name_cn': 'HTTP Debugger',
        'icon': 'HTTP',
        'icon_color': 'linear-gradient(135deg, #9b59b6, #8e44ad)',
        'category': '开发工具',
        'detect_type': 'scrape',
        'check_url': 'https://www.httpdebugger.com/changes.html',
        'version_regex': r'<h2[^>]*>\s*v(\d+\.\d+)\s*</h2>',
        'date_regex': r'<time[^>]*datetime="([^"]+)"',
        'download_url': 'https://www.httpdebugger.com/downloads/HTTPDebuggerPro.msi',
        'prefer_scraped_version': True,
        'skip_md5': True,
        'official_site': 'https://www.httpdebugger.com/',
    },
    {
        'name': 'CCleaner',
        'name_cn': 'CCleaner',
        'icon': 'CC',
        'icon_color': 'linear-gradient(135deg, #1abc9c, #16a085)',
        'category': '系统工具',
        'detect_type': 'scrape',
        'check_url': 'https://www.ccleaner.com/zh-cn/ccleaner/version-history',
        'version_regex': r'version-history__latest-version">v([\d.]+)',
        'date_regex': r'<span>\((\d{1,2} \w{3} \d{4})\)</span>',
        'download_url': 'https://bits.avcdn.net/productfamily_CCLEANER7/insttype_FREE/platform_WIN/installertype_FULL/build_RELEASE',
        'prefer_scraped_version': True,
        'skip_md5': True,
        'official_site': 'https://www.ccleaner.com/zh-cn',
    },
    {
        'name': '4K Video Downloader Plus',
        'name_cn': '4K Video Downloader Plus',
        'icon': '4K',
        'icon_color': 'linear-gradient(135deg, #e74c3c, #c0392b)',
        'category': '下载工具',
        'detect_type': 'increment',
        'base_version': '26.3.3',
        'url_pattern': 'https://dl.4kdownload.com/app/4kvideodownloaderplus_{ver}_x64.zip',
        'version': '26.3.3',
        'version_format': 'three_part',
        'official_site': 'https://www.4kdownload.com/downloads/34',
    },
    {
        'name': 'Luminar Neo',
        'name_cn': 'Luminar Neo',
        'icon': 'LN',
        'icon_color': 'linear-gradient(135deg, #8e44ad, #9b59b6)',
        'category': '图像处理',
        'detect_type': 'luminar_api',
        'api_url': 'http://luminarneowin.skylum.com/',
        'api_ua': 'Other',
        'version': '1.28.1.17862',
        'skip_md5': True,
        'official_site': 'https://skylum.com/hans/whats-new/luminar-neo',
    },
    {
        'name': 'ACDSee Photo Studio Ultimate',
        'name_cn': 'ACDSee Photo Studio Ultimate 2027',
        'icon': 'AC',
        'icon_color': 'linear-gradient(135deg, #e74c3c, #c0392b)',
        'category': '图像处理',
        'detect_type': 'increment',
        'base_version': '20.0.0.4660',
        'url_ver_format': 'acdsee_year',
        'url_pattern': 'https://dl.acdsystems.com/acdsee/en/acdsee-photo-studio-ultimate-{ver}-win-en.exe',
        'skip_md5': True,
        'official_site': 'https://www.acdsee.com/en/support/photo-studio-ultimate/changelog/',
    },
    {
        'name': 'xb21cn 精简系统',
        'name_cn': 'xb21cn 精简系统 Win10/11',
        'icon': 'XB',
        'icon_color': 'linear-gradient(135deg, #2c3e50, #34495e)',
        'category': '系统工具',
        'detect_type': '189pan',
        'version': 'Win10/11',
        'download_url': 'https://cloud.189.cn/web/share?code=ama22maquuYj&pwd=ci8t',
        'size': 0,
        'size_display': '-',
        'skip_md5': True,
        'is_webpage': True,
        'official_site': 'https://cloud.189.cn/web/share?code=ama22maquuYj&pwd=ci8t',
    },
    {
        'name': '7997 Portable',
        'name_cn': '7997便携作品',
        'icon': '79',
        'icon_color': 'linear-gradient(135deg, #e74c3c, #c0392b)',
        'category': '便携软件',
        'detect_type': 'yandex',
        'public_url': 'https://disk.yandex.ru/d/D8xbOSd7XAUbug',
        'version': '2026.09.19',
        'download_url': 'https://disk.yandex.ru/d/D8xbOSd7XAUbug',
        'size': 0,
        'skip_md5': True,
        'is_webpage': True,
        'official_site': 'https://disk.yandex.ru/d/D8xbOSd7XAUbug',
    },
    {
        'name': 'PotPlayer',
        'name_cn': 'PotPlayer',
        'icon': 'PP',
        'icon_color': 'linear-gradient(135deg, #00a8ff, #0097e6)',
        'category': '影音播放',
        # PotPlayer 的版本有三套口径，必须读内层真实值：
        #   外壳 PE FileVersion    = 26.10.21.0  （构建日期式，前端不能用）
        #   外壳 PE ProductVersion = 1.7.23159.0 （打包时硬编码，落后一版）
        #   内层 PotPlayer64.dll   = 1.7.23160.0 （About 框显示 26021(1.7.23160)，以此为准）
        # 外壳落后是因为 NSIS 打包时版本号写死，软件本体更新后没同步。
        # 内层 DLL 的 ProductVersion 是无意义的 1.7.0.0，故读它的 FileVersion。
        # 末段 .0 是四段补位，官方口径只到三段，用 strip_trailing_zero 去掉。
        'detect_type': 'fixed',
        'nsis_inner_version': True,
        'nsis_inner_members': ['PotPlayer64.dll'],
        'nsis_inner_prefer': 'file',
        'strip_trailing_zero': True,
        # 口径从 26.x 换成 1.7.x 后数值变小，声明权威源以免被防降级当成回退拦下。
        'version_authority': 'nsis',
        'version': '1.7.23160',
        'download_url': 'http://t1.daumcdn.net/potplayer/PotPlayer/Version/Latest/PotPlayerSetup64.exe',
        'official_site': 'https://potplayer.daum.net/',
    },
    {
        'name': 'DxO PureRaw',
        'name_cn': 'DxO PureRaw',
        'icon': 'Dx',
        'icon_color': 'linear-gradient(135deg, #e74c3c, #c0392b)',
        'category': '图像处理',
        # 版本取 PE 资源的 ProductVersion（官方产品版本，如 6.8.0.7）；
        # FileVersion 是安装器自身版本（带构建号），直接用会让前端版本号不准。
        'detect_type': 'fixed',
        'pe_version': True,
        'pe_version_source': 'product',
        'version': '6.8.0.7',
        'skip_md5': True,
        'download_url': 'https://download-center.dxo.com/PureRaw/v6/Win/DxO_PureRaw_v6.exe',
        'official_site': 'https://www.dxo.com/dxo-pureraw/',
    },
    {
        'name': 'DxO FilmPack',
        'name_cn': 'DxO FilmPack',
        'icon': 'DF',
        'icon_color': 'linear-gradient(135deg, #8e44ad, #9b59b6)',
        'category': '图像处理',
        # 同上：ProductVersion 才是产品版本（8.11.1.896），FileVersion 无/带构建号
        # 注：官方安装包当前仍是 8.11.0.896（滞后一个修订版），配置 version_strict_prefix
        # 让「同产品线的安装器版本」不覆盖人工核实的软件版本，等官方包同步后自动对齐。
        'detect_type': 'fixed',
        'pe_version': True,
        'pe_version_source': 'product',
        'version_strict_prefix': '8.11',
        'version': '8.11.1.896',
        'skip_md5': True,
        'download_url': 'https://download-center.dxo.com/FilmPack/v8/Win/DxO_FilmPack8.exe',
        'official_site': 'https://www.dxo.com/dxo-filmpack/',
    },
    {
        'name': 'DxO ViewPoint',
        'name_cn': 'DxO ViewPoint',
        'icon': 'DV',
        'icon_color': 'linear-gradient(135deg, #2980b9, #3498db)',
        'category': '图像处理',
        # 同上：ProductVersion 才是产品版本（5.18.0.52）
        'detect_type': 'fixed',
        'pe_version': True,
        'pe_version_source': 'product',
        'version': '5.18.0.52',
        'skip_md5': True,
        'download_url': 'https://download-center.dxo.com/ViewPoint/v5/Win/DxO_ViewPoint5_Setup.exe',
        'official_site': 'https://www.dxo.com/dxo-viewpoint/',
    },
    {
        'name': 'DxO PhotoLab',
        'name_cn': 'DxO PhotoLab',
        'icon': 'DP',
        'icon_color': 'linear-gradient(135deg, #16a085, #1abc9c)',
        'category': '图像处理',
        # 同上：ProductVersion=10.2.0.496 是产品版本，
        # FileVersion=10.2.20738.496 的 20738 是构建号，前端展示要前者
        'detect_type': 'fixed',
        'pe_version': True,
        'pe_version_source': 'product',
        'version': '10.2.0.496',
        'skip_md5': True,
        'download_url': 'https://download-center.dxo.com/PhotoLab/v10/Win/DxO_PhotoLab10_Setup.exe',
        'official_site': 'https://www.dxo.com/dxo-photolab/',
    },
    {
        'name': 'StartAllBack',
        'name_cn': 'StartAllBack',
        'icon': 'SA',
        'icon_color': 'linear-gradient(135deg, #1a73e8, #4285f4)',
        'category': '系统工具',
        'detect_type': 'startallback',
        'cdn_url_pattern': 'https://startisback.sfo3.cdn.digitaloceanspaces.com/StartAllBack_{ver}_setup.exe',
        'cdn_base_version': '3.9.27',
        'startallback_max_scan': 30,
        'version': '3.9.27.5412',
        'download_url': 'https://startisback.com/StartAllBack_setup.exe',
        'detect_timeout': 90,
        'official_site': 'https://www.startisback.com/',
    },
    {
        'name': 'NVIDIA Driver',
        'name_cn': 'NVIDIA显卡驱动',
        'icon': 'NV',
        'icon_color': 'linear-gradient(135deg, #76b900, #5a9e00)',
        'category': '驱动程序',
        'detect_type': 'scrape',
        'check_url': 'https://gfwsl.geforce.com/services_toolkit/services/com/nvidia/services/AjaxDriverService.php?func=DriverManualLookup&psid=110&pfid=910&osID=135&languageCode=1033&isWHQL=1&beta=0&dltype=-1&dch=1&upCRD=0&sort1=0&numberOfResults=1',
        'version_regex': r'"Version"\s*:\s*"([\d.]+)"',
        'date_regex': r'"ReleaseDateTime"\s*:\s*"[A-Za-z]{3}\s+([A-Za-z]{3}\s+\d{1,2},?\s+20\d{2})"',
        'download_url_regex': r'"DownloadURL"\s*:\s*"(https://[^"]+\.exe)"',
        'download_url_wrapper': 'https://www.nvidia.com/content/DriverDownloads/confirmation.php?url={path}&lang=us&type=geforce',
        'prefer_scraped_version': True,
        'url_pattern': 'https://us.download.nvidia.com/Windows/{ver}/{ver}-desktop-win10-win11-64bit-international-dch-whql.exe',
        'version': '616.92',
        'official_site': 'https://www.nvidia.com/en-us/geforce/forums/game-ready-drivers/13/',
        'referer': 'https://www.nvidia.com/',
    },
    {
        'name': 'Camtasia',
        'name_cn': 'Camtasia',
        'icon': 'Ca',
        'icon_color': 'linear-gradient(135deg, #ff6d00, #ff9100)',
        'category': '视频编辑',
        'detect_type': 'increment',
        'base_version': '26.2.2',
        'url_pattern': 'https://download.techsmith.com/camtasiastudio/releases/{ver_dot}/camtasia.exe',
        'url_ver_format': 'dots_to_none',
        'official_site': 'https://www.techsmith.com/camtasia-version-history.html',
    },
    {
        'name': 'Vegas Pro',
        'name_cn': 'VEGAS Pro',
        'icon': 'Ve',
        'icon_color': 'linear-gradient(135deg, #00b8d4, #0072bc)',
        'category': '视频编辑',
        # Boris FX 收购后改为 Hub 在线授权，安装包只经 Hub 下发，
        # 官网/论坛都不暴露直链。但 Hub 客户端启动时拉的官方清单接口
        # (borisfx.com/api/1/downloads) 一次就给全「版本号 + 直链 + 发布日期」，
        # 不用猜带构建时间戳的文件名（Vegas_Pro_2027.0.0.31_x64_RELEASE_261020_132721.exe）。
        'detect_type': 'borisfx_hub',
        'hub_product_name': 'Vegas Pro',
        # 只认 2027 版本线：产品同时挂着 2026 旧版，用 product 前缀区分
        'hub_product_prefix': 'Vegas Pro 2027',
        'version': '2027.0.0',
        'download_url': 'https://borisfxdownloads.com/borisfx/store/vegas/Vegas_Pro_2027.0.0.31_x64_RELEASE_261020_132721.exe',
        'skip_md5': True,
        'official_site': 'https://www.borisfx.com/vegas/',
    },
    {
        'name': 'Geek Uninstaller',
        'name_cn': 'Geek Uninstaller',
        'icon': 'GU',
        'icon_color': 'linear-gradient(135deg, #4caf50, #2e7d32)',
        'category': '系统工具',
        'detect_type': 'scrape',
        'check_url': 'https://geekuninstaller.com/download',
        'version_regex': r'<b>(\d+\.\d+\.\d+\.\d+)</b>',
        'date_regex': r'\[(\d+\s+\w+\s+20\d{2})\]',
        'download_url': 'https://geekuninstaller.com/geek.zip',
        'skip_md5': True,
        'detect_timeout': 120,
        'official_site': 'https://geekuninstaller.com/download',
    },
    {
        'name': 'Foxit PDF Editor',
        'name_cn': 'Foxit PDF Editor Pro',
        'icon': 'FP',
        'icon_color': 'linear-gradient(135deg, #e53935, #b71c1c)',
        'category': '办公软件',
        'detect_type': 'scrape',
        'check_url': 'https://www.foxit.com/pdf-editor/version-history.html',
        'version_regex': r'(\d{4}\.\d+\.\d+\.\d+)',
        'date_regex': r'([A-Za-z]+ \d+, 20\d{2})',
        'download_url': 'https://cdn01.foxitsoftware.com/product/Editor/desktop/win/2026.2.1/FoxitPDFEditor202621_L10N_Setup_Website_x64.exe',
        'official_site': 'https://www.foxit.com/pdf-editor/version-history.html',
        'size': 700 * 1024 * 1024,
    },
    {
        'name': 'Foxit PDF Editor LTSC',
        'name_cn': 'Foxit PDF Editor Pro LTSC',
        'icon': 'FL',
        'icon_color': 'linear-gradient(135deg, #ff7043, #d84315)',
        'category': '办公软件',
        'detect_type': 'scrape',
        'check_url': 'https://www.foxit.com/pdf-editor/version-history.html',
        'version_regex': r'(14\.\d+\.\d+\.\d+)',
        'date_regex': r'([A-Za-z]+ \d+, 20\d{2})',
        'download_url': 'https://cdn01.foxitsoftware.com/product/Editor/desktop/win/14.0.8/FoxitPDFEditor1408_L10N_Setup_Website_x86.exe',
        'official_site': 'https://www.foxit.com/pdf-editor/version-history.html',
        'size': 500 * 1024 * 1024,
    },
    {
        'name': 'BuWangChuXin Windows',
        'name_cn': '不忘初心Windows',
        'icon': 'BW',
        'icon_color': 'linear-gradient(135deg, #9c27b0, #6a1b9a)',
        'category': '操作系统',
        'detect_type': 'bwcx',
        'check_url': 'https://www.wycad.com/windows',
        'version': 'v2026.09.16',
        'date': '2026-09-27',
        'size': 0,
        'official_site': 'https://www.wycad.com/windows',
    },
    {
        'name': 'Internet Download Manager',
        'name_cn': 'IDM 下载器',
        'icon': 'ID',
        'icon_color': 'linear-gradient(135deg, #4caf50, #2e7d32)',
        'category': '下载工具',
        'detect_type': 'scrape',
        'check_url': 'https://www.internetdownloadmanager.com/news.html',
        'version_regex': r'(\d+\.\d+)\s+Build\s+(\d+)',
        'version_format': 'idm_build',
        'date_regex': r'([A-Z][a-z]+ \d+, 20\d{2})',
        'download_url': 'https://mirror2.internetdownloadmanager.com/idman643build11.exe',
        'skip_md5': True,
        'detect_timeout': 120,
        'official_site': 'https://www.internetdownloadmanager.com/news.html',
    },
    {
        'name': 'GoodSync',
        'name_cn': 'GoodSync Pro',
        'icon': 'GS',
        'icon_color': 'linear-gradient(135deg, #2196f3, #0d47a1)',
        'category': '同步工具',
        # 探测方式1：官网更新日志 scrape（版本号+发布日期，常滞后于安装包）
        # 探测方式2：winget 官方索引（兜底，不依赖官网）
        # 探测方式3：读安装包内 PE FileVersion（最权威，官方页面/winget 常落后）
        # 完整包作主下载；便携包(2Go)并行探测，两者取最新者（各自更新节奏不同）
        'detect_type': 'scrape',
        'check_url': 'https://www.goodsync.com/news-windows',
        'version_regex': r'Version\s+(\d+\.\d+\.\d+(?:\.\d+)?)\s*--\s*\d{4}-\d{2}-\d{2}',
        'date_regex': r'Version\s+\d+\.\d+\.\d+(?:\.\d+)?\s*--\s*(\d{4}-\d{2}-\d{2})',
        'download_url': 'https://services.goodsync.com/download/GoodSync-vsub-Setup.exe',
        'alt_download_urls': [
            'https://services.goodsync.com/download/GoodSync-vsub-2Go-Setup.exe',
        ],
        'pe_version': True,
        'prefer_scraped_version': True,
        'use_newer_scraped': True,
        'winget_id': 'SiberSystems.GoodSync',
        'version': '12.11.11.1',
        'size': 83390048,
        'skip_md5': True,
        'detect_timeout': 120,
        'official_site': 'https://www.goodsync.com/',
    },
    {
        'name': 'monkrus软件',
        'name_cn': 'monkrus软件',
        'icon': 'M',
        'icon_color': 'linear-gradient(135deg, #8e44ad, #6c3483)',
        'category': '资源站',
        # 资源站：只跟踪"最新更新日期当天"发布了哪些软件文章，无体积、无版本号
        'detect_type': 'monkrus',
        'check_url': 'https://w18.monkrus.ws/feeds/posts/default?alt=rss&max-results=25',
        'version': '2026-10-06',
        'download_url': 'https://w18.monkrus.ws/',
        'skip_md5': True,
        'allow_no_size': True,
        'official_site': 'https://w18.monkrus.ws/',
    },
    {
        'name': 'downtopc软件',
        'name_cn': 'downtopc软件',
        'icon': 'D',
        'icon_color': 'linear-gradient(135deg, #2e7d32, #1b5e20)',
        'category': '资源站',
        # 资源站：抓「最新更新日期当天」的文章，标题命中已添加软件名的才输出（没命中跳过）。
        # RSS 只用于确定最新日期，文章清单靠日期归档页分页抓全（RSS 默认只有 10 条）。
        'detect_type': 'downtopc',
        'check_url': 'https://downtopc.com/software/rss.xml',
        'version': '2026-10-08',
        'download_url': 'https://downtopc.com/software/',
        'skip_md5': True,
        'allow_no_size': True,
        'official_site': 'https://downtopc.com/software/',
    },
    {
        'name': 'nsane论坛',
        'name_cn': 'nsane论坛',
        'icon': 'N',
        'icon_color': 'linear-gradient(135deg, #4a6fa5, #2b3f63)',
        'category': '资源站',
        # 资源站：抓指定板块「今天」有新帖/有新回复的主题，标题命中已添加软件名才输出（没命中跳过）。
        # 主题正文需登录，但板块列表页与前台 widget 匿名可读，只要标题和时间即可。
        'detect_type': 'nsane',
        'check_url': 'https://nsaneforums.com/forum/48-software-updates/',
        # 论坛板块列表页：(标识, URL)。列表行含发帖时间与最后回复时间，按「最后回复==今天」判定今日更新
        'nsane_forums': [
            ('software-updates', 'https://nsaneforums.com/forum/48-software-updates/'),
            ('news-updates', 'https://nsaneforums.com/forum/17-news-updates/'),
        ],
        # nsane.down 前台「FrontPage Latest Update」小部件
        'nsane_frontpage': 'https://nsaneforums.com/nsane.down/',
        'version': '2026-10-08',
        'download_url': 'https://nsaneforums.com/nsane.down/',
        'skip_md5': True,
        'allow_no_size': True,
        'official_site': 'https://nsaneforums.com/',
    },
    {
        'name': '7-Zip',
        'name_cn': '7-Zip',
        'icon': '7Z',
        'icon_color': 'linear-gradient(135deg, #2f6fed, #1a4fb4)',
        'category': '系统工具',
        # 探测方式1：官网 history.txt scrape（权威，形如 "26.05          2026-10-21"）
        # 探测方式2：increment 探测 7z{ver}-x64.exe（文件名无点，用 dots_to_none）
        # ⚠️ history.txt 的版本行在文件中部（前面是标题和分隔线），
        #    正则必须带 (?m) 多行开关，否则 ^ 只匹配整个文件开头 → 永远抓不到版本 → 版本停更。
        'detect_type': 'increment',
        'base_version': '26.05',
        'check_url': 'https://www.7-zip.org/history.txt',
        'version_regex': r'(?m)^(\d+\.\d+)\s+(\d{4}-\d{2}-\d{2})',
        'date_regex': r'(?m)^\d+\.\d+\s+(\d{4}-\d{2}-\d{2})',
        'url_pattern': 'https://www.7-zip.org/a/7z{ver}-x64.exe',
        'url_ver_format': 'dots_to_none',
        'prefer_scraped_version': True,
        'use_newer_scraped': True,
        'version': '26.05',
        'download_url': 'https://www.7-zip.org/a/7z2605-x64.exe',
        'skip_md5': True,
        'official_site': 'https://www.7-zip.org/',
    },
    {
        'name': 'pdfFactory Pro',
        'name_cn': 'pdfFactory Pro',
        'icon': 'PF',
        'icon_color': 'linear-gradient(135deg, #e53935, #b71c1c)',
        'category': '文档工具',
        # 探测方式1：官网 release 页 increment（文件名含版本号 pdf{ver}pro.exe）
        # 探测方式2：winget 官方索引（绕过官网 Cloudflare 反爬）
        'detect_type': 'increment',
        'base_version': '9.35',
        'url_pattern': 'https://fineprint.com/release/pdf{ver}pro.exe',
        'url_ver_format': 'dots_to_none',
        'winget_id': 'FineprintSoftware.pdfFactory.Pro',
        'use_newer_scraped': True,
        'version': '9.35',
        'download_url': 'https://fineprint.com/release/pdf935pro.exe',
        'detect_timeout': 120,
        'official_site': 'https://fineprint.com/pdffactory',
    },
    {
        'name': 'FinePrint',
        'name_cn': 'FinePrint',
        'icon': 'FP',
        'icon_color': 'linear-gradient(135deg, #8e24aa, #4a148c)',
        'category': '文档工具',
        # 探测方式1：官网 release 页 increment（文件名含版本号 fp{ver}.exe）
        # 探测方式2：winget 官方索引（绕过官网 Cloudflare 反爬）
        'detect_type': 'increment',
        'base_version': '12.35',
        'url_pattern': 'https://fineprint.com/release/fp{ver}.exe',
        'url_ver_format': 'dots_to_none',
        'winget_id': 'FineprintSoftware.FinePrint',
        'use_newer_scraped': True,
        'version': '12.35',
        'download_url': 'https://fineprint.com/release/fp1235.exe',
        'detect_timeout': 120,
        'official_site': 'https://fineprint.com/',
    },
    {
        'name': 'Yamicsoft Windows Manager',
        'name_cn': 'Yamicsoft Windows Manager',
        'icon': 'YM',
        'icon_color': 'linear-gradient(135deg, #16a085, #0e6655)',
        'category': '系统工具',
        # 探测方式：官网 whats-new 页抓版本号+发布日期（页面按发布时间倒序，
        # 首个 "Windows Manager vX.Y.Z" 与首个中文日期一一对应）
        # 下载地址固定（便携版 zip 文件名不带版本号）
        'detect_type': 'scrape',
        'check_url': 'https://www.yamicsoft.com/cn/whats-new.php',
        'version_regex': r'Windows Manager v(\d+\.\d+(?:\.\d+)?)',
        'date_regex': r'(\d{4}年\d{1,2}月\d{1,2}日)',
        'prefer_scraped_version': True,
        'version': '2.4.2',
        'size': 21500924,
        'download_url': 'https://yamicsoft.com/windowsmanager/software/windowsmanager_portable.zip',
        'skip_md5': True,
        'detect_timeout': 120,
        'official_site': 'https://www.yamicsoft.com/cn/whats-new.php',
    },
    {
        'name': 'Advanced Installer',
        'name_cn': 'Advanced Installer',
        'icon': 'AI',
        'icon_color': 'linear-gradient(135deg, #3498db, #2980b9)',
        'category': '开发工具',
        # 探测方式：版本路径 {major.minor}/advinst.msi 递增探测（如 24.1 -> 24.2 -> ... -> 25.0）。
        # 注意：前端下载地址恒定 302 到 storage.advancedupdater.cloud，需跟随重定向判存在性
        # （check_url 默认跟随重定向，不存在的版本最终返回 404）。
        'detect_type': 'increment',
        'base_version': '24.1',
        'url_pattern': 'https://www.advancedinstaller.com/downloads/{ver}/advinst.msi',
        'param_format': '',
        'channel': '',
        'max_skip': 3,      # 连续3个404后进位（24.x -> 25.0）
        'max_carry': 2,     # 最多进位2次，保证能跨到下一个大版本（24.x -> 25.0 -> 26.0）
        'skip_md5': True,   # 安装包约 300MB，跳过 MD5
        'official_site': 'https://www.advancedinstaller.com/',
    },
    {
        'name': 'Operit',
        'name_cn': 'Operit AI',
        'icon': 'OP',
        'icon_color': 'linear-gradient(135deg, #6366f1, #8b5cf6)',
        'category': '安卓应用',
        # 探测方式：GitHub Releases API 取最新正式版 tag（vX.Y.Z），
        # 直取 release 里 APK（app-release.apk）的直链
        'detect_type': 'github_release',
        'repo': 'AAswordman/Operit',
        'version_regex': r'v?(\d+\.\d+\.\d+)',
        'use_asset_url': True,
        'asset_filter': 'apk',
        'skip_md5': True,   # APK 约 385MB，跳过 MD5
        'version': '1.12.2',
        'size': 404265417,
        'date': '2026-09-18',
        'download_url': 'https://github.com/AAswordman/Operit/releases',
        'official_site': 'https://github.com/AAswordman/Operit/releases',
    },
    {
        'name': 'GKD',
        'name_cn': 'GKD 搞快点',
        'icon': 'GKD',
        'icon_color': 'linear-gradient(135deg, #10b981, #059669)',
        'category': '安卓应用',
        # 探测方式：GitHub Releases API 取最新正式版 tag（vX.Y.Z，跳过 beta），
        # 直取 release 里 APK（gkd-x.y.z.apk）的直链，大小只算这个包
        'detect_type': 'github_release',
        'repo': 'gkd-kit/gkd',
        'version_regex': r'v?(\d+\.\d+\.\d+)',
        'use_asset_url': True,
        'asset_filter': 'apk',
        'version': '1.12.1',
        'size': 3287479,
        'date': '2026-05-20',
        'download_url': 'https://github.com/gkd-kit/gkd/releases',
        'official_site': 'https://github.com/gkd-kit/gkd/releases',
    },
    {
        'name': 'CrystalDiskInfo',
        'name_cn': 'CrystalDiskInfo',
        'icon': 'CD',
        'icon_color': 'linear-gradient(135deg, #2f80ed, #1c4fd6)',
        'category': '系统工具',
        # 探测方式1：官网 history 页抓版本号+发布日期（页面按版本倒序，首个标题即最新版）
        # 探测方式2：winget 官方索引兜底（crystalmark.info 对部分数据中心 IP 反爬，winget 不依赖官网）
        # 下载：SourceForge 目录含版本号（目录用点号 9.9.3、文件名用下划线 CrystalDiskInfo9_9_3.zip），
        #       用 url_pattern 动态构造，{ver}=9.9.3、{ver_us}=9_9_3，随版本自动更新
        'detect_type': 'scrape',
        'check_url': 'https://crystalmark.info/en/software/crystaldiskinfo/crystaldiskinfo-history/',
        'version_regex': r'(\d+\.\d+\.\d+)\s*\[\d{4}/\d{2}/\d{2}\]',
        'date_regex': r'\d+\.\d+\.\d+\s*\[(\d{4}/\d{2}/\d{2})\]',
        'winget_id': 'CrystalDewWorld.CrystalDiskInfo',
        'prefer_scraped_version': True,
        'url_pattern': 'https://sourceforge.net/projects/crystaldiskinfo/files/{ver}/CrystalDiskInfo{ver_us}.zip/download',
        'version': '9.9.3',
        'date': '2026-10-11',
        'download_url': 'https://sourceforge.net/projects/crystaldiskinfo/files/latest/download',
        'official_site': 'https://crystalmark.info/en/software/crystaldiskinfo/',
    },
    {
        'name': 'FXSound',
        'name_cn': 'FXSound',
        'icon': 'FX',
        'icon_color': 'linear-gradient(135deg, #8e2de2, #4a00e0)',
        'category': '影音娱乐',
        # 探测方式：官方下载页(github.com/fxsound2/fxsound-app/releases)直接托管 GitHub Releases。
        # 稳定版 tag 固定为 'latest'（不含版本号），真实版本在 release name（"Version 1.2.16.0"），
        # 所以 version_source='name' 从 name 提取；x64/ARM64 双资产用 asset_filter 只取 x64 的
        # fxsound_setup.exe（子串不含 arm64 包），use_asset_url 返回该资产直链；beta 预发布自动跳过。
        'detect_type': 'github_release',
        'repo': 'fxsound2/fxsound-app',
        'version_source': 'name',
        'version_regex': r'v?(\d+\.\d+\.\d+\.\d+)',
        'asset_filter': 'fxsound_setup.exe',
        'use_asset_url': True,
        'version': '1.2.16.0',
        'size': 77988432,
        'date': '2026-09-17',
        'download_url': 'https://github.com/fxsound2/fxsound-app/releases/download/latest/fxsound_setup.exe',
        'official_site': 'https://www.fxsound.com/',
    },
    {
        'name': 'Wondershare UniConverter',
        'name_cn': '万兴转换器',
        'icon': 'UC',
        'icon_color': 'linear-gradient(135deg, #536dfe, #304ffe)',
        'category': '视频转换',
        # 官方 CDN 固定最新直链（full14204 即 18.0.0 全量包，文件名不含完整版本），
        # 版本号权威来源 = 安装包 PE FileVersion（18.0.0.58）；带版本号的
        # uniconverter_64bit_18.0.0_full14204.exe 与 full14204 为同一文件，仅作佐证。
        'detect_type': 'fixed',
        'download_url': 'https://download.wondershare.com/cbs_down/uniconverter_64bit_full14204.exe',
        'pe_version': True,
        'version': '18.0.0.58',
        'size': 424551880,
        'skip_md5': True,
        'detect_timeout': 60,
        'official_site': 'https://www.wondershare.com/uniconverter/',
    },
    {
        'name': 'Bandizip',
        'name_cn': 'Bandizip Professional',
        'icon': 'BZ',
        'icon_color': 'linear-gradient(135deg, #2e9fe6, #1b6fbf)',
        'category': '压缩解压',
        # 探测方式：官方固定下载地址（URL 里无版本号，直出安装包）→ fixed。
        # 版本号在版本历史页首行（<div class="cell1">v7.47</div>），用 page_version_url +
        # regex 交叉校验：页面版本比二进制/配置更新时自动采用，免手改。安装包 <10MB，
        # fixed 只 HEAD 取 size/日期，秒级完成。
        'detect_type': 'fixed',
        'version': '7.47',
        'size': 7356400,
        'date': '2026-10-13',
        'download_url': 'https://bandisoft.app/bandizip/BANDIZIP-SETUP-STD-X64.EXE',
        'page_version_url': 'https://www.bandisoft.com/bandizip/history/',
        'page_version_regex': r'<div class="cell1">v([\d.]+)</div>',
        'official_site': 'https://www.bandisoft.com/bandizip/history/',
    },
    {
        'name': 'MPC-BE',
        'name_cn': 'MPC-BE',
        'icon': 'MB',
        'icon_color': 'linear-gradient(135deg, #e74c3c, #c0392b)',
        'category': '影音播放',
        # 探测方式：官方 Releases 在 GitHub → github_release。tag 形如 '1.9.2'（无 v 前缀）。
        # 单个 release 含 x64/x86 的 installer.zip 与 .7z 等多资产，用 asset_filter 只取
        # x64-installer.zip（子串不含 x86 包），use_asset_url 返回该资产直链。
        'detect_type': 'github_release',
        'repo': 'Aleksoid1978/MPC-BE',
        'version_regex': r'v?(\d+\.\d+\.\d+)',
        'asset_filter': 'x64-installer.zip',
        'use_asset_url': True,
        'version': '1.9.2',
        'date': '2026-10-13',
        'download_url': 'https://github.com/Aleksoid1978/MPC-BE/releases/download/1.9.2/MPC-BE.1.9.2.x64-installer.zip',
        'official_site': 'https://github.com/Aleksoid1978/MPC-BE/releases',
    },
    {
        'name': 'EdrawMax',
        'name_cn': 'Wondershare EdrawMax',
        'icon': 'EM',
        'icon_color': 'linear-gradient(135deg, #4a6cf7, #2b3fd6)',
        'category': '办公软件',
        # 探测方式：官网固定名 edraw-max_64bit_{ver}_full5371.exe（5371 是发行通道号，恒定），
        # 版本号就在文件名里 → increment，无需解析 PE。CDN 只保留最近若干版本且跳号稀疏
        # （实测 15.1.6 / 15.2.9 / 16.0.2 存在，中间 15.2.x、16.0.0~16.0.1 均 404），
        # 故放宽 max_skip/max_carry，让跨小版本也能摸到；包体 166MB>100MB，跳过 MD5。
        'detect_type': 'increment',
        'base_version': '16.0.2',
        'url_pattern': 'https://download.wondershare.com/cbs_down/edraw-max_64bit_{ver}_full5371.exe',
        'max_skip': 6,
        'max_carry': 2,
        'skip_md5': True,
        'version': '16.0.2',
        'size': 174526984,
        'date': '2026-10-13',
        'download_url': 'https://download.wondershare.com/cbs_down/edraw-max_64bit_16.0.2_full5371.exe',
        'official_site': 'https://www.edrawsoft.com/download-edrawmax.html',
    },
    {
        'name': 'R-Studio',
        'name_cn': 'R-Studio',
        'icon': 'RS',
        'icon_color': 'linear-gradient(135deg, #1e88e5, #0d47a1)',
        'category': '数据恢复',
        # 官网无版本号页面（主页无版本、下载目录反爬 403），版本从安装包 PE FileVersion 读取；
        # RStudio9.exe 是 Network 版固定直链，Technician 版与 Network 同步发版，只测主包
        'detect_type': 'fixed',
        'pe_version': True,
        'version': '9.5.191.85',
        'size': 74126024,
        'skip_md5': True,
        'detect_timeout': 120,
        'download_url': 'https://www.r-studio.com/downloads/RStudio9.exe',
        'official_site': 'https://www.r-studio.com/',
    },
    {
        'name': 'MKVToolNix',
        'name_cn': 'MKVToolNix',
        'icon': 'MK',
        'icon_color': 'linear-gradient(135deg, #e53935, #b71c1c)',
        'category': '视频工具',
        # 版本历史 NEWS.md 首行 `# Version 103.0 "The Darkness" 2026-10-18` 即最新版本+日期；
        # 下载用官方便携版 .7z（URL 目录只到前两段 releases/103.0/），url_pattern 用
        # {major_minor} 拼接；.7z 非 PE 无法读完整版，展示版本用配置 103.0.0 兜底
        'detect_type': 'scrape',
        'check_url': 'https://mkvtoolnix.download/doc/NEWS.md',
        'version_regex': r'# Version (\d+\.\d+(?:\.\d+)?) "',
        'date_regex': r'# Version \d+\.\d+(?:\.\d+)? "[^"]*" (\d{4}-\d{2}-\d{2})',
        'url_pattern': 'https://mkvtoolnix.download/windows/releases/{major_minor}/mkvtoolnix-64-bit-{major_minor}.7z',
        'use_newer_scraped': True,
        'version': '103.0.0',
        'size': 31400293,
        'skip_md5': True,
        'download_url': 'https://mkvtoolnix.download/windows/releases/103.0/mkvtoolnix-64-bit-103.0.7z',
        'official_site': 'https://mkvtoolnix.download/',
    },
    {
        'name': 'PlayerFab',
        'name_cn': 'PlayerFab',
        'icon': 'PF',
        'icon_color': 'linear-gradient(135deg, #7c4dff, #512da8)',
        'category': '影音播放',
        # 版本页 media-player-new.htm 的 whatsnew 区块 `<strong>7.0.6.4</strong> 2026-10-17`；
        # 下载为固定 mlink 链接（301 后落地带版本号的 CDN 文件），版本号以页面 whatsnew 为准
        'detect_type': 'scrape',
        'check_url': 'https://playerfab.dvdfab.cn/media-player-new.htm?v=7',
        'version_regex': r'whatsnew[^0-9]{0,100}(\d+\.\d+\.\d+\.\d+)',
        'date_regex': r'<strong>7\.\d+\.\d+\.\d+</strong>\s*<span>([A-Z][a-z]{2} \d{1,2}, \d{4})',
        'prefer_scraped_version': True,
        'skip_md5': True,
        'version': '7.0.6.4',
        'download_url': 'https://dvdfab.cn/mlink/download.php?g=PlayerFab_X64_OFFLINE',
        'official_site': 'https://playerfab.dvdfab.cn/media-player-new.htm?v=7',
    },
    {
        'name': 'Light Image Resizer',
        'name_cn': 'Light Image Resizer',
        'icon': 'LI',
        'icon_color': 'linear-gradient(135deg, #26a69a, #00796b)',
        'category': '图像工具',
        # 历史页顶部第一行 `7.6.7.182 – 2026-10-19` 即最新版本+日期；下载 URL 含完整版本号
        'detect_type': 'scrape',
        'check_url': 'https://www.obviousidea.com/windows-software/light-image-resizer/light-image-resizer-history/',
        'version_regex': r'(\d+\.\d+\.\d+\.\d+)\s*&#8211;',
        'date_regex': r'\d+\.\d+\.\d+\.\d+\s*&#8211;\s*(\d{4}-\d{2}-\d{2})',
        'url_pattern': 'https://download2.obviousidea.com/light_image_resizer7_setup_{ver}.exe',
        'prefer_scraped_version': True,
        'version': '7.6.7.182',
        'size': 48364072,
        'skip_md5': True,
        'download_url': 'https://download2.obviousidea.com/light_image_resizer7_setup_7.6.7.182.exe',
        'official_site': 'https://www.obviousidea.com/windows-software/light-image-resizer/',
    },
    {
        'name': 'HyperSnap',
        'name_cn': 'HyperSnap',
        'icon': 'HS',
        'icon_color': 'linear-gradient(135deg, #e91e63, #ad1457)',
        'category': '截图工具',
        # 下载地址固定 latest（HS10SetupCN.exe），无版本号。
        # 版本：changelog.asp 抓官网版本（10.4.4），官网只给三段，
        # 末段 build 号只在软件 About 框里 → version_build_suffix 补全（10.4.4.4）。
        # （安装包是 RAR5 SFX，外壳无版本资源；内层 HprSnap.exe 的 PE 版本是
        #  10.4.4.0，末段恒 0，拿不到 build 号，故不走 PE 探测。）
        # 日期用发布日 2026-10-19（prefer_config_date，不被 CDN Last-Modified 覆盖）；
        # 数字签名 10.17 只是签名时间，不作发布日期（铁律3）。
        'detect_type': 'scrape',
        'check_url': 'https://hyperionics.com/hsdx/changelog.asp',
        'version_regex': r'Version history for HyperSnap (\d+\.\d+\.\d+)',
        'date_regex': r'<strong>(\d{4}\.\d{2}\.\d{2}) Hypersnap',
        'prefer_scraped_version': True,
        'version_build_suffix': 4,
        'version': '10.4.4.4',
        'date': '2026-10-19',
        'prefer_config_date': True,
        'skip_md5': True,
        'download_url': 'https://www.hyperionics.com/downloads/HS10SetupCN.exe',
        'official_site': 'https://hyperionics.com/hsdx/downloads.asp',
    },
    {
        'name': 'AOMEI Partition Assistant',
        'name_cn': 'AOMEI 分区助手',
        'icon': 'AO',
        'icon_color': 'linear-gradient(135deg, #f39c12, #d35400)',
        'category': '磁盘工具',
        # 官网下载中心页直接给出最新版号与更新日期：
        #   <div class="num"> 10.12.2 </div><div class="ms">Version</div>
        #   <div class="num">Oct. 20, 2026</div><div class="ms"> Updated </div>
        # 走 scrape：一次请求拿到版本 + 发布日（铁律3 发布页优先）。
        # 下载地址用 Technician 版（302 跳到 www2.aomeisoftware.com 真实文件）。
        'detect_type': 'scrape',
        'check_url': 'https://www.diskpart.com/download.html?theme_id=10040',
        'version_regex': r'<div class="num">\s*(\d+\.\d+\.\d+)\s*</div>\s*<div class="ms">Version',
        'date_regex': r'<div class="num">\s*([A-Z][a-z]{2}\.\s*\d{1,2},\s*\d{4})\s*</div>\s*<div class="ms">\s*Updated',
        'prefer_scraped_version': True,
        'version': '10.12.2',
        'skip_md5': True,
        'download_url': 'https://www.diskpart.com/ss/download/pa/PAssist_TechDemo.exe',
        'official_site': 'https://www.diskpart.com/download.html?theme_id=10040',
    },
    {
        'name': 'BitComet',
        'name_cn': 'BitComet',
        'icon': 'BC',
        'icon_color': 'linear-gradient(135deg, #607d8b, #455a64)',
        'category': '下载工具',
        # 官方归档页 download.bitcomet.com/achive 每条记录含「版本号 + 发布日期 + 大小」，
        # 最新版本排在最后：
        #   <a href="BitComet_2.23.zip">BitComet_2.23.zip</a>  20-Oct-2026 06:51  47145787
        # 用 scrape + version_regex_take='last' 取末尾那条（最新版），
        # 版本/日期用同一条目锚定的正则，保证两者来自同一行、不会错配。
        # 下载地址按版本号动态拼（BitComet_{ver}.zip）。
        'detect_type': 'scrape',
        'check_url': 'https://download.bitcomet.com/achive',
        'version_regex': r'<a href="BitComet_([0-9.]+)\.zip">',
        'version_regex_take': 'last',
        'date_regex': r'<a href="BitComet_[0-9.]+\.zip">[^<]*</a>\s+(\d{2}-[A-Za-z]{3}-\d{4} \d{2}:\d{2})',
        'date_regex_take': 'last',
        # 归档页同一条记录里还有文件大小（BitComet_2.23.zip 47145787 字节）。
        # 官方包未上架时（302 → /not_available/）探测不到真实大小，
        # 用归档页记录的大小兜底，前端照常显示体积。
        'size_regex': r'<a href="BitComet_[0-9.]+\.zip">[^<]*</a>\s+\d{2}-[A-Za-z]{3}-\d{4} \d{2}:\d{2}\s+(\d+)',
        'size_regex_take': 'last',
        'prefer_scraped_version': True,
        'version': '2.23',
        'url_pattern': 'https://download.bitcomet.com/achive/BitComet_{ver}.zip',
        'skip_md5': True,
        'download_url': 'https://download.bitcomet.com/achive/BitComet_2.23.zip',
        'official_site': 'https://www.bitcomet.com/en/downloads',
    },
    {
        'name': 'HexHub',
        'name_cn': 'HexHub',
        'icon': 'HX',
        'icon_color': 'linear-gradient(135deg, #557bdf, #3a5bbf)',
        'category': '开发工具',
        # 数据库 / Docker / SSH / SFTP 桌面 GUI 工具。
        # 走官方版本 API，一次请求拿到版本号 + 直链 + 体积 + 发布日期。
        # 取 windows-amd64-portable（64 位便携版）。
        # 不能用 increment：下载 URL 带构建时间戳
        # （...-5.1.9-202606072158.exe），每版时间戳都变，pattern 写死就扫不到新版。
        # 也不能取 history-exact 的最新记录——那是热更新版（5.4.4），
        # 官网并没有对应的新完整包，实际下到的仍是 5.1.9。
        'detect_type': 'hexhub_api',
        'hexhub_channel': 'windows-amd64-portable',
        'skip_md5': True,
        'version': '5.1.9',
        'download_url': 'https://oss.hexhub.cn/plugin/HexHub-Client-windows-amd64-portable-5.1.9-202606072158.exe',
        'official_site': 'https://www.hexhub.cn/',
    },
    {
        'name': 'Java JDK',
        'name_cn': 'Java(JDK)',
        'alias': 'Java Runtime Environment',
        'icon': 'J',
        'icon_color': 'linear-gradient(135deg, #f89820, #e76f00)',
        'category': '运行环境',
        # Oracle Java 一次要展示多条版本线（27 GA / 25 LTS / 21 LTS / 8 LTS），
        # 前端是「点标题展开子版本列表」，所以这里不是单版本条目：
        #   - 主版本走官方 javaReleases API，版本号/LTS 标记/发布日期全从 API 取；
        #   - 每条版本线的发行说明页与下载锚点是官网固定路径，写在 java_line_cfg 里。
        # 不能用 scrape 抓 downloads 页：页面里版本号混着平台后缀
        # （8u511 / jdk-27.0.1），正则切不干净，而且一次只拿得到主推版本。
        'detect_type': 'java_api',
        'java_api': 'https://java.oraclecloud.com/javaReleases',
        'java_lines': ['27', '25', '21', '8'],
        'java_line_cfg': {
            '27': {
                'official_site': 'https://oracle.com/java/technologies/javase/27u-relnotes.html',
                'download_url': 'https://www.oracle.com/java/technologies/downloads/#jdk27-windows',
            },
            '25': {
                'official_site': 'https://oracle.com/java/technologies/javase/25u-relnotes.html',
                'download_url': 'https://www.oracle.com/java/technologies/downloads/#jdk25-windows',
            },
            '21': {
                'official_site': 'https://oracle.com/java/technologies/javase/21u-relnotes.html',
                'download_url': 'https://www.oracle.com/cn/java/technologies/downloads/#java21',
            },
            '8': {
                'official_site': 'https://oracle.com/java/technologies/javase/8u-relnotes.html',
                'download_url': 'https://www.oracle.com/java/technologies/downloads/#java8',
            },
        },
        'version': '27.0.1',
        # API 抽风时的日期兜底（正常情况下用 API 返回的 releaseDate）
        'date': '2026-10-20',
        'download_url': 'https://www.oracle.com/java/technologies/downloads/',
        'official_site': 'https://oracle.com/java/technologies/java-se-glance.html',
        # 下载页不是单一安装包，没有体积可探
        'allow_no_size': True,
        'skip_md5': True,
    },
    {
        'name': 'SketchUp Pro 2027',
        'name_cn': 'SketchUp Pro 2027',
        'alias': 'SketchUp',
        'icon': 'SU',
        'icon_color': 'linear-gradient(135deg, #00a3a3, #007a7a)',
        'category': '图像工具',
        # 官方下载页（help.sketchup.com/en/downloading-sketchup）一次性给出
        # 「当前版本安装包直链 + 页面更新日期」，且 Windows 安装包文件名里带完整版本号：
        #   https://download.sketchup.com/SketchUp-2027-0-264-170.exe
        # 文件名结构 = SketchUp-{年}-{大版本}-{小版本}-{build}.exe
        #   2027-0-264-170 → 展示版本 27.0.264（年份去掉 "20" 前缀 + 后两段），
        #   末段 build 号（170）不属于产品版本号，不进展示。
        # 用 scrape 而不是 fixed：直链文件名带版本号，每次更新直链都变，写死必然失效。
        'detect_type': 'scrape',
        'check_url': 'https://help.sketchup.com/en/downloading-sketchup',
        'version_regex': r'SketchUp-20(\d\d)-(\d+)-(\d+)-\d+\.exe',
        'date_regex': r'Last updated:\s*([A-Za-z]{3}\s+\d{1,2},\s*20\d{2})',
        'download_url_regex': r'(https://download\.sketchup\.com/SketchUp-20\d\d-\d+-\d+-\d+\.exe)',
        'prefer_scraped_version': True,
        'version': '27.0.264',
        'download_url': 'https://download.sketchup.com/SketchUp-2027-0-264-170.exe',
        'official_site': 'https://help.sketchup.com/en/downloading-sketchup',
        # 日期取页面上的 "Last updated"（官方发布页日期），比安装包 CDN 的
        # Last-Modified（构建上传日 10-13）更准；这里不用 prefer_config_date 写死，
        # 否则下一版发布后日期会卡在旧值。
        # 安装包 1.3GB，远超 100MB，不做 MD5
        'skip_md5': True,
    },
]

MAX_INCREMENT = 30  # 最多递增检测30个版本


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """禁止跟随重定向，302/301视为不存在（用于increment模式）"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CaptureRedirect(urllib.request.HTTPRedirectHandler):
    """捕获重定向Location，不跟随（用于redirect模式）"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_no_redirect_opener = urllib.request.build_opener(NoRedirect)
_capture_redirect_opener = urllib.request.build_opener(CaptureRedirect)


_http_cache = {}
_http_cache_lock = threading.Lock()


def check_url(url, referer=None, use_cache=True, get_fallback=True):
    """检测URL是否存在，返回 (exists, size, last_modified)
    302重定向到CDN签名URL时跟随重定向获取大小

    带进程内短 TTL 缓存：同一轮检测里多个产品/多级递增常探测同一 URL，
    缓存能显著减少请求数；只缓存"成功"结果，避免把偶发网络失败固化下来。

    get_fallback=False 时只做一次 HEAD，不再补 GET 探测体积。
    increment 递增扫描动辄十几次请求，每次都可能触发 20s+ 的 GET 兜底，
    一轮下来必然超时（迅雷就是这样被拖到 96s、长期保留旧数据的）；
    扫描阶段只需要"存在/不存在"，体积留到确定最新版本后补一次。

    ⚠️ 部分 CDN（Cloudflare 代理的站点，如 ntwind.com）既不返回
    Content-Length 也不返回 Last-Modified，HEAD 只能拿到 exists=True、
    size=0。此时若不兜底，调用方会因"无体积"丢弃已探测到的正确版本
    （WinSnap 抓到 6.3.5 却被退回旧值 6.3.3）。
    这里补一次 GET 流式探测：只读前 64KB 估算体积并取 Last-Modified，
    不把整个安装包下完。
    """
    key = (url, referer or '')
    if use_cache:
        with _http_cache_lock:
            hit = _http_cache.get(key)
        if hit and (time.time() - hit[0]) < HTTP_CACHE_TTL:
            return hit[1], hit[2], hit[3]

    headers = {'User-Agent': UA}
    if referer:
        headers['Referer'] = referer
    try:
        req = urllib.request.Request(url, method='HEAD', headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            # 部分站点把下架包 302 到 404 提示页且返回 200（迅雷 down.sandai.net/404/404.html），
            # 不识别就会被当成"包存在"，探测直接卡在这个假版本上。
            final_url = resp.geturl() or ''
            if final_url != url and re.search(r'(^|/)404(/|\.html)', final_url):
                return False, 0, ''
            size = resp.headers.get('Content-Length', '0')
            last_modified = resp.headers.get('Last-Modified', '')
            result = (resp.status == 200, int(size) if size and size.isdigit() else 0, last_modified)
            if get_fallback and result[0] and (result[1] == 0 or not result[2]):
                # CDN 没给 Content-Length / Last-Modified → GET 兜底
                g_size, g_lm = _curl_get_headers(url, referer)
                if g_size > 0:
                    result = (result[0], g_size, result[2] or g_lm)
                elif result[1] == 0 and not result[2]:
                    # curl 也没拿到（chunked 响应）→ 流式读前 64KB 估算
                    try:
                        req2 = urllib.request.Request(url, headers=headers)
                        with urllib.request.urlopen(req2, timeout=20) as resp2:
                            total = 0
                            while total < 65536:
                                chunk = resp2.read(65536)
                                if not chunk:
                                    break
                                total += len(chunk)
                            if total:
                                result = (result[0], total, result[2])
                    except Exception:
                        pass
            if use_cache and result[0]:
                with _http_cache_lock:
                    _http_cache[key] = (time.time(),) + result
            return result
    except urllib.error.HTTPError:
        return False, 0, ''
    except Exception:
        return False, 0, ''


def _curl_get_headers(url, referer=None):
    """用curl获取URL的Content-Length和Last-Modified，返回 (size, last_modified)"""
    import subprocess
    try:
        cmd = ['curl', '-sI', '--max-time', '20', '-A', UA, url]
        if referer:
            cmd.extend(['-e', referer])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        output = result.stdout
        size = 0
        last_modified = ''
        for line in output.split('\n'):
            line = line.strip()
            if line.lower().startswith('content-length:'):
                val = line.split(':', 1)[1].strip()
                if val.isdigit():
                    size = int(val)
            elif line.lower().startswith('last-modified:'):
                last_modified = line.split(':', 1)[1].strip()
        return size, last_modified
    except Exception:
        return 0, ''


def check_url_follow(url, referer=None):
    """检测URL（跟随重定向），返回 (exists, size, last_modified)
    用于fixed模式，因为有些固定地址会302到CDN
    HEAD无Content-Length时用GET探测
    urllib失败时用curl兜底（应对Cloudflare拦截）
    """
    import subprocess
    headers = {'User-Agent': UA}
    if referer:
        headers['Referer'] = referer
    try:
        req = urllib.request.Request(url, method='HEAD', headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            # 官方下架标记页（如 BitComet 的 /not_available/）：302 过去仍是 200，
            # 但拿到的是 1KB 左右的提示页，不是安装包 → 判定为不可用，
            # 避免把提示页大小当成安装包大小写进 data.json。
            final_url = (resp.url or '').lower()
            if 'not_available' in final_url or '/not-found' in final_url:
                return False, 0, ''
            size = resp.headers.get('Content-Length', '0')
            last_modified = resp.headers.get('Last-Modified', '')
            if resp.status == 200 and (not size or int(size) == 0):
                try:
                    req2 = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req2, timeout=20) as resp2:
                        size = resp2.headers.get('Content-Length', '0')
                        # 只有HEAD和GET都没返回Content-Length时才流式探测，
                        # 但最多读 MAX_GET_BYTES，不把整个安装包下完（几十MB→几百MB太浪费）
                        if not size or int(size) == 0:
                            MAX_GET_BYTES = 65536  # 64KB 足够估体积
                            total = 0
                            while True:
                                chunk = resp2.read(65536)
                                if not chunk:
                                    break
                                total += len(chunk)
                                if total >= MAX_GET_BYTES:
                                    break
                            size = str(total)
                except Exception:
                    pass
            # urllib返回200但size=0时，尝试curl兜底
            if resp.status == 200 and (not size or int(size) == 0):
                curl_size, curl_date = _curl_get_headers(url, referer)
                if curl_size > 0:
                    return True, curl_size, parse_date(curl_date or last_modified)
            return resp.status == 200, int(size) if size and size.isdigit() else 0, parse_date(last_modified)
    except urllib.error.HTTPError as e:
        if e.code == 403:
            # 403时尝试curl兜底（Cloudflare可能拦截urllib但允许curl）
            curl_size, curl_date = _curl_get_headers(url, referer)
            if curl_size > 0:
                return True, curl_size, parse_date(curl_date)
            return True, 0, ''
        size = e.headers.get('Content-Length', '0') if e.headers else '0'
        return False, int(size) if size.isdigit() else 0, ''
    except Exception:
        # urllib失败（超时/Cloudflare拦截），用curl兜底
        curl_size, curl_date = _curl_get_headers(url, referer)
        if curl_size > 0:
            return True, curl_size, parse_date(curl_date)
        return False, 0, ''


def get_redirect_location(url):
    """获取302重定向的Location头，返回 (location, status)"""
    try:
        req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': UA})
        with _capture_redirect_opener.open(req, timeout=15) as resp:
            return resp.url if resp.status in (301, 302) else None, resp.status
    except urllib.error.HTTPError as e:
        location = e.headers.get('Location', '') if e.headers else ''
        return location, e.code
    except Exception:
        return None, 0


def parse_date(date_str):
    """解析多种日期格式为 YYYY-MM-DD（统一转换为北京时间UTC+8日期）"""
    from datetime import datetime, timedelta
    date_str = date_str.strip()
    if not date_str:
        return ''
    # ISO格式: 2026-08-27T17:23:08+00:00 或 2026-08-27T17:23:08Z
    m = re.match(r'(20\d{2})-(\d{2})-(\d{2})T(\d{2}):(\d{2})', date_str)
    if m:
        y, mo, d, h, mi = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
        dt = datetime(y, mo, d, h, mi) + timedelta(hours=8)
        return dt.strftime('%Y-%m-%d')
    # 只有日期的ISO格式: 2026-08-27
    m = re.match(r'(20\d{2}-\d{2}-\d{2})$', date_str)
    if m:
        return m.group(1)
    # 点分日期: 2026.09.06 或 2026.9.16
    m = re.match(r'(20\d{2})\.(\d{1,2})\.(\d{1,2})$', date_str)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
    # M/D/YYYY格式: 9/21/2026
    m = re.match(r'(\d{1,2})/(\d{1,2})/(20\d{2})$', date_str)
    if m:
        return f"{m.group(3)}-{m.group(1).zfill(2)}-{m.group(2).zfill(2)}"
    # GMT/HTTP格式: Mon, 06 Jul 2026 03:04:19 GMT -> 转换为北京时间
    months = {'jan':'01','feb':'02','mar':'03','apr':'04','may':'05','jun':'06',
              'jul':'07','aug':'08','sep':'09','oct':'10','nov':'11','dec':'12'}
    m = re.match(r'[A-Za-z]{3},\s*(\d{1,2})\s+([A-Za-z]{3})\s+(20\d{2})\s+(\d{2}):(\d{2})', date_str)
    if m:
        d, mon_str, y, h, mi = int(m.group(1)), m.group(2).lower(), int(m.group(3)), int(m.group(4)), int(m.group(5))
        mon = months.get(mon_str, '01')
        dt = datetime(y, int(mon), d, h, mi) + timedelta(hours=8)
        return dt.strftime('%Y-%m-%d')
    # 只有日期的GMT格式: Mon, 06 Jul 2026
    m = re.match(r'[A-Za-z]{3},\s*(\d{1,2})\s+([A-Za-z]{3})\s+(20\d{2})', date_str)
    if m:
        mon = months.get(m.group(2).lower(), '01')
        return f"{m.group(3)}-{mon}-{m.group(1).zfill(2)}"
    # 日 月 年格式: 16 Sep 2026
    m = re.match(r'(\d{1,2})\s+([A-Za-z]{3})\s+(20\d{2})', date_str)
    if m:
        mon = months.get(m.group(2).lower(), '01')
        return f"{m.group(3)}-{mon}-{m.group(1).zfill(2)}"
    # 日 完整月份 年格式: 22 September 2026
    months_full = {'january':'01','february':'02','march':'03','april':'04','may':'05','june':'06',
              'july':'07','august':'08','september':'09','october':'10','november':'11','december':'12'}
    m = re.match(r'(\d{1,2})\s+([A-Za-z]+)\s+(20\d{2})', date_str)
    if m:
        mon = months_full.get(m.group(2).lower(), months.get(m.group(2).lower()[:3], '01'))
        return f"{m.group(3)}-{mon}-{m.group(1).zfill(2)}"
    # 英文月份+序数日: Sep 29th, 2026 或 September 29th, 2026
    m = re.match(r'([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th),?\s*(20\d{2})', date_str)
    if m:
        mon = months_full.get(m.group(1).lower(), months.get(m.group(1).lower()[:3], '01'))
        return f"{m.group(3)}-{mon}-{m.group(2).zfill(2)}"
    # 英文月份: September 9, 2026
    m = re.match(r'([A-Za-z]+)\s+(\d{1,2}),?\s*(20\d{2})', date_str)
    if m:
        mon = months_full.get(m.group(1).lower(), months.get(m.group(1).lower()[:3], '01'))
        return f"{m.group(3)}-{mon}-{m.group(2).zfill(2)}"
    # 英文缩写月份+点号: Oct. 20, 2026 / Sep. 1, 2026
    # （AOMEI 官网下载中心用这种格式；注意要在 fallback 替换 '.' 之前处理）
    m = re.match(r'([A-Za-z]{3,})\.\s*(\d{1,2}),?\s*(20\d{2})', date_str)
    if m:
        mon = months_full.get(m.group(1).lower(), months.get(m.group(1).lower()[:3], '01'))
        return f"{m.group(3)}-{mon}-{m.group(2).zfill(2)}"
    # DD-Mon-YYYY格式: 18-Sep-2026 或 4-Sep-2026
    m = re.match(r'(\d{1,2})-([A-Za-z]{3})-(20\d{2})', date_str)
    if m:
        mon = months.get(m.group(2).lower(), '01')
        return f"{m.group(3)}-{mon}-{m.group(1).zfill(2)}"
    # D/Mon/YYYY格式: 4/Sep/2026
    m = re.match(r'(\d{1,2})/([A-Za-z]{3})/(20\d{2})', date_str)
    if m:
        mon = months.get(m.group(2).lower(), '01')
        return f"{m.group(3)}-{mon}-{m.group(1).zfill(2)}"
    # 中文格式: 2026年10月7日 / 2026年09月09日（补齐月日为两位）
    m = re.match(r'(20\d{2})年(\d{1,2})月(\d{1,2})日', date_str)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
    date_str = date_str.replace('年', '-').replace('月', '-').replace('日', '')
    # 斜杠/点格式
    date_str = date_str.replace('/', '-').replace('.', '-')
    return date_str


def increment_version(version):
    """递增版本号的最后一段，支持任意段数"""
    parts = version.split('.')
    parts[-1] = str(int(parts[-1]) + 1)
    return '.'.join(parts)


def carry_version(version):
    """进位到上一段：将倒数第二段+1，最后一段重置为0
    例如 25.1.13.1636 -> 25.1.14.0
         4.1.15 -> 4.2.0
         1.2（两段特殊）-> 交给 increment_version 处理
    注意：只清最后一段，倒数第三段及以前不动。
         因为调用方在 MAX_INCREMENT 次递增失败后进位，
         此时除倒数第二段外的前置段都是探测起点，不应清0。
    """
    parts = version.split('.')
    if len(parts) < 2:
        return increment_version(version)
    # 倒数第二段+1
    parts[-2] = str(int(parts[-2]) + 1)
    # 仅清最后一段
    for i in range(-1, -len(parts), -1):
        if i == -2:
            break
        parts[i] = '0'
    return '.'.join(parts)


def carry_version_n(version, k):
    """向上进位 k 个段：倒数第二段 +k，最后一段归 0
    例如 25.1.13.1637 + k=2 -> 25.1.15.0
    用于一次并发探测多个进位段，替代串行“进位一次、再试、再进位”。
    """
    if k <= 1:
        return carry_version(version)
    parts = version.split('.')
    if len(parts) < 2:
        return increment_version(version)
    parts[-2] = str(int(parts[-2]) + k)
    parts[-1] = '0'
    return '.'.join(parts)


def adobe_build_probe(base_ver, exists_fn, max_jump=700, workers=20):
    """Adobe build 号稀疏跳跃定位：并发探测 base 之后的号段，取最大存在版本

    Adobe 每次小版本更新会跳过几十个序号（实测 21931 -> 21996，中间64个全部404），
    逐个递增探测永远扫不到目标；且 CDN 仅保留存在的少数版本，存在性不单调
    （实测 21995 不存在而 21996 存在），二分查找同样不适用。

    实测 base+1..base+700 全量探测中只有目标版本存在，因此采用并发全扫：
    20 并发下约 700 次请求 23 秒完成，可接受。

    exists_fn(int_ver, workers) -> (list[int], int) 由调用方注入（内部并发+缓存）
    返回命中的最大存在版本号（int），未命中返回 None
    """
    base = int(base_ver)
    cands = list(range(base + 1, base + max_jump + 1))
    hits, _ = exists_fn(cands, workers)
    return max(hits) if hits else None


def _url_ver(version, product):
    """将版本号转换为URL需要的格式
    url_ver_format:
      - 'full' (默认): 完整版本号，如 8.40.5000
      - 'short': 前两段去掉点，如 8.40 -> 840
      - 'major_minor': 前两段带点，如 8.40
    """
    fmt = product.get('url_ver_format', 'full')
    if fmt == 'short':
        parts = version.split('.')
        return ''.join(parts[:2])
    elif fmt == 'major_minor':
        parts = version.split('.')
        return '.'.join(parts[:2])
    elif fmt == 'dots_to_none':
        return version.replace('.', '')
    elif fmt == 'acdsee_year':
        # ACDSee特殊格式: 20.0.0.4660 -> 2027-0-0-4660 (主版本+2007=年份)
        parts = version.split('.')
        if len(parts) >= 4:
            year = str(int(parts[0]) + 2007)
            return f"{year}-{parts[1]}-{parts[2]}-{parts[3]}"
        return version
    return version


# 记录每款软件「本轮版本号来自哪个源」，供防降级拦截判断是否该放行。
# 键=产品名，值 ∈ {'nsis','pe','increment'}。仅 increment 探测模式写入。
_VER_SOURCE = {}

# 线上已发布的版本号（main 里 data.json 的值），供 increment 探测当起点。
# 配置里的 base_version 写死在源码里，一旦落后于线上就没法自愈：
# 探测永远从旧基线往上爬，遇到跨小版本跳版（26.2.9->26.4.0）就永远追不上。
_LIVE_VERSIONS = {}


def detect_increment(product):
    """递增检测模式：多级进位探测
    第0层：小版本「列车」并发扫描（minor_scan=True 时）
           针对版本号按第2段递增、且 CDN 只保留最新包的软件（如 YY 9.59 -> 9.60）。
           两轮并发定位：① 小版本段（含 base）+1..+N 取最大命中；
           ② 命中段内并发扫构建号 0..B 取最大命中。命中后跳过第1~3层，省掉节流 sleep。
    第1层：递增最后一段（build号），遇到不存在的版本跳过（最多5个）
    第2层：连续N个404后进位到上一段（如25.1.13.1636 -> 25.1.14.0），重置后段为0
    第3层：最多进位3次，确保能探测到跨小版本（25.1.15、25.2.0、26.4.0）
    第4层：检测到最新版本后，探测四段小版本号（NSIS/PE）
    第5层：获取安装包大小、更新日期、MD5
    """
    base_version = product['base_version']
    current = base_version
    latest = current
    latest_size = 0
    latest_date = ''
    referer = product.get('referer')
    MAX_SKIP = product.get('max_skip', 3)
    # 默认允许连续进位 3 次：跨小版本跳版（26.2.9 -> 26.3.0 -> 26.4.0）需要多次进位，
    # 只给 1 次时一旦连跳两个段就必然停在旧版，这才是历史上版本停歇的直接原因。
    MAX_CARRY = product.get('max_carry', 3)
    MD5_SIZE_LIMIT = 100 * 1024 * 1024

    # 起点优先用线上已发布版本：base_version 只是「最低基线」，
    # 线上版本比它新就以线上版本为起点，避免配置落后导致探测永远追不上。
    live_ver = _LIVE_VERSIONS.get(product['name'], '')
    if live_ver and _ver_newer(live_ver, current):
        current = live_ver
        latest = live_ver
        print(f"  以线上版本为起点: {current}（配置基线 {base_version}）")

    # 支持多个url_pattern（按优先级尝试，应对build号变化）
    if 'url_patterns' in product:
        url_patterns = product['url_patterns']
    else:
        url_patterns = [product['url_pattern']]
    
    def get_version_url(version, fast=True):
        """返回 (url, exists, size, date)。fast=True 只做 HEAD，不补 GET 体积。"""
        ver_full = _url_ver(version, product)
        ver_nodot = version.replace('.', '')
        parts = version.split('.')
        major = parts[0]
        major_minor = '.'.join(parts[:2])
        major_minor_underscore = '_'.join(parts[:2])
        for pattern in url_patterns:
            test_url = pattern.format(ver=ver_full, ver_dot=ver_nodot, major=major, major_minor=major_minor, major_minor_underscore=major_minor_underscore)
            exists, size, date = check_url(test_url, referer=referer, get_fallback=not fast)
            if exists:
                return test_url, exists, size, date
        last_url = url_patterns[-1].format(ver=ver_full, ver_dot=ver_nodot, major=major, major_minor=major_minor, major_minor_underscore=major_minor_underscore)
        return last_url, False, 0, ''

    # 从论坛/官网抓取版本号作为起点（双保险：论坛版本 + CDN递增扫描）
    scrape_url = product.get('check_url')
    version_regex = product.get('version_regex')
    date_regex = product.get('date_regex')
    scraped_ver = ''
    scraped_date = ''
    if scrape_url and (version_regex or date_regex):
        try:
            req = urllib.request.Request(scrape_url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
            # 部分站点（如搜狗官网）是 GBK，用 page_encoding 指定；未知编码退回 utf-8
            _enc = product.get('page_encoding', 'utf-8')
            try:
                html = raw.decode(_enc, errors='ignore')
            except LookupError:
                html = raw.decode('utf-8', errors='ignore')
            if version_regex:
                m = re.search(version_regex, html)
                if m:
                    scraped_ver = m.group(1)
                    print(f"  页面版本: {scraped_ver}")
                    # 抓到的版本比当前起点新才采用（按段比较、缺失段补 0，
                    # 避免 '16.9' 与 '16.8.0.4914' 这类段数不等的版本被错判）
                    if _ver_newer(scraped_ver, current):
                        current = scraped_ver
                        print(f"  以页面版本为起点: {current}")
            if date_regex:
                m2 = re.search(date_regex, html)
                if m2:
                    scraped_date = m2.group(1)
                    print(f"  页面发布日期: {scraped_date}")
        except Exception as e:
            print(f"  ⚠️ 页面版本获取失败: {e}")

    # 检测基础版本是否存在（列车扫描会把 base 并入同一轮并发，故这些产品跳过单独 HEAD）
    if not product.get('minor_scan'):
        url, exists, size, date = get_version_url(current)
        if exists:
            latest = current
            latest_size = size
            latest_date = date
        else:
            print(f"  ⚠️ 警告: 基础版本 {current} 不存在，可能已下架或网络异常")
            # 线上版本可能来自占位 build / 误抓（数值虚高、包实际不存在），
            # 这时回退配置基线再试一次，避免整轮围着不存在的版本空转。
            if current != base_version:
                print(f"  ↩️ 线上起点无效，回退配置基线: {base_version}")
                current = base_version
                latest = base_version
                url, exists, size, date = get_version_url(current)
                if exists:
                    latest_size = size
                    latest_date = date
                    print(f"  ✓ 配置基线存在: {current}")
            # 如果scrape到了版本号但CDN HEAD失败，仍使用scrape版本
            if scraped_ver and not exists:
                latest = scraped_ver
                latest_size = product.get('default_size_mb', 0) * 1024 * 1024
                latest_date = ''
                print(f"  ✓ 使用scrape版本作为fallback: {latest} ({latest_size/1024/1024:.1f}MB)")

    # 小版本「列车」并发扫描：版本号按第2段递增、CDN 只留最新包时（如 YY 9.59 -> 9.60），
    # 逐段递增永远进不到位。这里两轮并发即可定位最新版：
    #   ① 小版本段 base+1..base+N（build 归 0）取最大命中；
    #   ② 在该小版本内并发扫构建号 0..B 取最大命中。
    # 命中后跳过下面的逐段递增（含每次 0.2~0.3s 的节流 sleep），墙钟≈两次 RTT。
    _train_done = False
    if product.get('minor_scan'):
        _scan_n = product.get('minor_scan_count', 8)
        _scan_b = product.get('minor_scan_builds', 4)
        _scan_w = product.get('minor_scan_workers', max(_scan_n, 8))
        _mi = product.get('minor_index', 1)
        _parts = current.split('.')
        if len(_parts) > _mi and _parts[_mi].isdigit():
            _base = int(_parts[_mi])

            def _scan(cands):
                with ThreadPoolExecutor(max_workers=_scan_w) as ex:
                    res = list(ex.map(get_version_url, cands))
                best = None
                for v, (_u, ok, s, d) in zip(cands, res):
                    if ok and (best is None or _ver_newer(v, best[0])):
                        best = (v, s, d)
                return best

            _mcands = [current]  # 并入当前 base，省掉单独的 base HEAD
            for k in range(1, _scan_n + 1):
                cp = _parts[:]
                cp[_mi] = str(_base + k)
                for i in range(_mi + 1, len(cp)):
                    cp[i] = '0'
                _mcands.append('.'.join(cp))
            print(f"  小版本并发扫描: {current} ~ {_mcands[-1]} ({_scan_w}并发)")
            _best = _scan(_mcands)
            _bp = (_best[0] if _best else current).split('.')
            _bcands = []
            for b in range(0, _scan_b + 1):
                cp = _bp[:]
                cp[-1] = str(b)
                _bcands.append('.'.join(cp))
            _bbest = _scan(_bcands)
            _final = max([x for x in (_best, _bbest) if x],
                         key=lambda t: _ver_tuple(t[0]), default=None)
            if _final:
                latest, latest_size, latest_date = _final
                current = _final[0]
                print(f"  ✓ 列车扫描命中: {latest}")
            else:
                print(f"  ⏹ 列车扫描无命中，保留 {latest}")
            _train_done = True

    # Adobe build 号稀疏跳跃：并发探测 base 之后的号段取最大命中版本
    if product.get('version_format') == 'adobe_build':
        max_jump = product.get('adobe_max_jump', 700)
        workers = product.get('adobe_probe_workers', 20)
        cur_int = int(latest) if str(latest).isdigit() else int(current)
        _cache = {}
        _lock = threading.Lock()

        def _probe_many(cands, _workers):
            """并发探测一批版本号，返回命中的版本列表"""
            def _one(v):
                with _lock:
                    if v in _cache:
                        return _cache[v]
                _u, _ok, _s, _d = get_version_url(str(v))
                with _lock:
                    _cache[v] = _ok
                return _ok
            out = []
            with ThreadPoolExecutor(max_workers=_workers) as ex:
                for v, ok in zip(cands, ex.map(_one, cands)):
                    if ok:
                        out.append(v)
            return out, len(cands)

        print(f"  Adobe build 并发探测: 基线 {cur_int}, 扫描 +1~+{max_jump} ({workers}并发)")
        found = adobe_build_probe(cur_int, _probe_many, max_jump=max_jump, workers=workers)
        if found:
            fu, fok, fsize, fdate = get_version_url(str(found))
            if fok:
                latest = str(found)
                latest_size = fsize
                latest_date = fdate
                current = str(found)
                print(f"  ✓ Adobe 探测命中: {latest}")
            else:
                print(f"  ⚠️ 命中 {found} 但复查失败，保留 {latest}")
        else:
            print(f"  ⏹ Adobe 探测未发现新版本，保留 {latest}")

    # 多级进位递增探测（列车扫描已定位时跳过，省掉逐段探测与节流 sleep）
    carry_count = 0
    skip_count = 0
    _loop_iters = 0 if _train_done else MAX_INCREMENT * (MAX_CARRY + 1)
    for _ in range(_loop_iters):
        next_ver = increment_version(current)
        url, exists, size, date = get_version_url(next_ver)
        if exists:
            latest = next_ver
            latest_size = size
            latest_date = date
            current = next_ver
            skip_count = 0
            time.sleep(0.3)
        else:
            skip_count += 1
            if skip_count >= MAX_SKIP:
                # 连续 N 个 404：并发探测上面 1..MAX_CARRY 个段的起始版本
                # （25.1.14.0 / 25.1.15.0 / 25.1.16.0），取最大命中后继续递增。
                # 一次并发只花一轮 RTT，比串行「进位一次→再试→再进位」快数倍，
                # 也能覆盖跨多个小版本的跳版（26.2.9 -> 26.4.0）。
                if carry_count < MAX_CARRY:
                    cands = [carry_version_n(current, k) for k in range(1, MAX_CARRY + 1)]
                    carry_count = MAX_CARRY
                    print(f"  🔄 连续{MAX_SKIP}个404，并发进位探测: {', '.join(cands)}")
                    with ThreadPoolExecutor(max_workers=len(cands)) as _ex:
                        _res = list(_ex.map(get_version_url, cands))
                    _best = None
                    for v, (_u, ok, s, d) in zip(cands, _res):
                        if ok and (_best is None or _ver_newer(v, _best[0])):
                            _best = (v, s, d)
                    if _best:
                        current = _best[0]
                        latest = _best[0]
                        latest_size = _best[1]
                        latest_date = _best[2]
                        skip_count = 0
                        print(f"  ✓ 进位命中: {current}")
                        continue
                    print(f"  ⏹ 进位段全无命中（已覆盖 {MAX_CARRY} 个段），停止探测")
                    break
                else:
                    print(f"  ⏹ 已进位{MAX_CARRY}次，停止探测")
                    break
            current = next_ver
            time.sleep(0.2)

    # 扫描阶段只做 HEAD（避免每次都触发 40s+ 的 GET 兜底把整轮拖超时），
    # 定版后再对最终包补一次完整探测，把体积/日期填上。
    if latest_size <= 0 and latest:
        _lp = latest.split('.')
        _lu = url_patterns[0].format(
            ver=_url_ver(latest, product), ver_dot=latest.replace('.', ''),
            major=_lp[0], major_minor='.'.join(_lp[:2]),
            major_minor_underscore='_'.join(_lp[:2]))
        _lok, _ls, _ld = check_url(_lu, referer=referer, use_cache=False)
        if _lok and _ls > 0:
            latest_size = _ls
            latest_date = _ld or latest_date
            print(f"  补体积: {latest_size/1024/1024:.1f}MB")

    # 第2层：多源版本号探测
    # NSIS版本优先（安装包内部真实版本，最精确）
    # PE版本与increment版本取最高的作为兜底
    display_version = latest  # increment探测到的大版本
    nsis_ver = None
    pe_ver = None
    parts = latest.split('.')
    if len(parts) >= 3:
        _p = latest.split('.')
        full_url_tmp = url_patterns[0].format(ver=_url_ver(latest, product), ver_dot=latest.replace('.', ''), major=_p[0], major_minor='.'.join(_p[:2]), major_minor_underscore='_'.join(_p[:2]))
        # NSIS install.7z内的版本号文件夹（如微信4.1.15.9）- 最精确，优先
        if product.get('nsis_version'):
            print(f"  解析NSIS install版本号...")
            nsis_ver = get_nsis_install_version(full_url_tmp, referer=referer)
            if nsis_ver:
                print(f"  NSIS版本: {nsis_ver}")
        # PE文件版本（如4.1.15.1000）- 安装包本身版本，兜底
        if product.get('pe_version'):
            print(f"  解析PE文件版本信息...")
            pe_ver = get_pe_version(full_url_tmp, referer=referer)
            if pe_ver:
                print(f"  PE版本: {pe_ver}")

    # 版本号比较键：统一走 _ver_tuple（按段补 0，段数不等也不会错判）
    def version_key(v):
        return _ver_tuple(v)

    # NSIS版本优先（最精确的真实版本），否则PE与increment取最高
    ver_source = 'increment'
    if nsis_ver:
        display_version = nsis_ver
        ver_source = 'nsis'
        print(f"  采用NSIS精确版本: {display_version}")
    elif pe_ver:
        # PE版本与increment版本取最高的
        display_version = max([latest, pe_ver], key=version_key)
        ver_source = 'pe'
        if display_version != latest:
            print(f"  PE版本更高，采用: {display_version} (increment={latest})")
    else:
        display_version = latest

    # 第二探测源：winget 官方索引（不依赖官网，可绕过 Cloudflare 反爬）
    # 与 increment 结果对比取更大值，并按新版号重新构造下载链接
    winget_id = product.get('winget_id')
    if winget_id:
        wg_ver = fetch_winget_version(winget_id)
        if wg_ver:
            print(f"  winget 版本: {wg_ver}")
            if _ver_newer(wg_ver, display_version):
                print(f"  ℹ️ winget 更新: {wg_ver} > increment {display_version}")
                wg_url = url_patterns[0].format(
                    ver=_url_ver(wg_ver, product), ver_dot=wg_ver.replace('.', ''),
                    major=wg_ver.split('.')[0],
                    major_minor='.'.join(wg_ver.split('.')[:2]),
                    major_minor_underscore='_'.join(wg_ver.split('.')[:2]))
                w_exists, w_size, w_date = check_url_follow(wg_url)
                if w_exists:
                    display_version = wg_ver
                    latest = wg_ver
                    full_url = wg_url
                    param_url = wg_url
                    ver_source = 'winget'
                    if w_size:
                        latest_size = w_size
                    if w_date:
                        latest_date = w_date
                    print(f"  ✓ 采用 winget 版本 {wg_ver} ({w_size/1024/1024:.1f}MB)")
                else:
                    print(f"  ⚠️ winget 版本 {wg_ver} 下载链接不可用，保留 {display_version}")
            else:
                print(f"  winget 版本不新，保留 {display_version}")

    # 落盘来源标记（供上层防降级拦截判断权威源是否命中）
    _VER_SOURCE[product['name']] = ver_source

    # 第3层：MD5计算（小于100MB才计算）
    md5 = ''
    _p = latest.split('.')
    full_url = url_patterns[0].format(ver=_url_ver(latest, product), ver_dot=latest.replace('.', ''), major=_p[0], major_minor='.'.join(_p[:2]), major_minor_underscore='_'.join(_p[:2]))
    skip_md5 = product.get('skip_md5', False)
    if not skip_md5 and latest_size > 0 and latest_size < MD5_SIZE_LIMIT:
        print(f"  计算MD5 ({latest_size/1024/1024:.1f}MB)...")
        md5 = get_file_md5(full_url, referer=referer)
        if md5:
            print(f"  MD5: {md5}")
    elif skip_md5:
        print(f"  跳过MD5计算 (skip_md5=True)")
    elif latest_size >= MD5_SIZE_LIMIT:
        print(f"  文件过大({latest_size/1024/1024:.0f}MB)，跳过MD5计算")

    # 生成下载链接
    if product.get('param_format'):
        timestamp = int(time.time() * 1000)
        param_url = full_url + product['param_format'].format(
            ts=timestamp, ver=latest, channel=product.get('channel', '')
        )
    else:
        param_url = full_url

    # 统一日期格式
    if latest_date:
        latest_date = parse_date(latest_date)
    # 页面发布日期优先于CDN Last-Modified（如PDF-XChange页面显示Released日期）
    # ⚠️ 但只有当「页面版本 == 最终探测版本」时才能用页面日期：
    # 官网 history 页常滞后（PDF-XChange 官网还停在 11.1.0.0 / Sep 29，
    # 而安装包已上架 11.1.1.0 / Oct 20），若无条件覆盖，
    # 新版 11.1.1.0 会被配上旧版 11.1.0.0 的发布日期（日期与版本错配）。
    # 版本对不上时改用 CDN Last-Modified（=安装包上传时间，贴近真实发布日）。
    if scraped_date:
        sd = parse_date(scraped_date)
        if sd:
            if scraped_ver and display_version and _ver_tuple(scraped_ver) != _ver_tuple(display_version):
                print(f"  ⚠️ 页面版本({scraped_ver})与探测版本({display_version})不一致，"
                      f"不采用页面日期({sd})，改用安装包时间")
            else:
                latest_date = sd
                print(f"  ✓ 采用页面发布日期: {latest_date}")

    return display_version, full_url, param_url, latest_size, latest_date, md5


def detect_redirect(product):
    """重定向检测模式：访问固定地址，从302 Location提取版本号和完整链接"""
    location, status = get_redirect_location(product['check_url'])
    if not location:
        print(f"  ⚠️ 警告: 未获取到重定向地址 (status={status})")
        return product.get('version', '未知'), product['check_url'], product['check_url'], 0, ''

    # 从Location提取版本号
    version = '未知'
    regex = product.get('version_regex', r'(\d+\.\d+\.\d+)')
    m = re.search(regex, location)
    if m:
        version = m.group(1)

    # 获取文件大小和修改时间（跟随重定向）
    exists, size, date = check_url_follow(location)

    return version, location, location, size, date, ''


def detect_fixed(product):
    """固定地址模式：版本号手动维护，只检测文件可用性
    支持配置 size/date/md5 作为默认值（大文件避免重复检测）
    """
    url = product['download_url']
    # 网页链接不检测大小
    is_webpage = product.get('is_webpage', False) or url.endswith('/') or '#' in url or '.html' in url or 'pages.dev' in url or 'update-history' in url or 'forum.php' in url or 'mediafire.com' in url or 'lanzoui.com' in url
    size = product.get('size', 0)
    date = product.get('date', '')
    md5 = product.get('md5', '')
    has_configured_size = 'size' in product
    if is_webpage:
        # 网页链接：如果配置了size则使用配置值，否则为0
        if not has_configured_size:
            size = 0
        if not date:
            date = ''
    else:
        # 检测文件可用性，如果检测到大小则用检测值，否则用配置值
        referer = product.get('referer')
        exists, detected_size, detected_date = check_url_follow(url, referer=referer)
        if exists and detected_size > 0:
            size = detected_size
            # prefer_config_date: 日期以人工核实的发布日期为准，不被 CDN
            # Last-Modified 覆盖（如 VC++ 运行库的数字签名日期早于官方发布日）
            if detected_date and not product.get('prefer_config_date'):
                date = detected_date
        elif not exists:
            print(f"  ⚠️ 警告: 固定地址不可用，可能链接已失效（使用配置值）")

        # 从content-disposition文件名提取版本号（如 InstallGoldWave709.exe -> 7.09）
        fname_regex = product.get('filename_version_regex')
        if fname_regex:
            try:
                req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': UA})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    cd = resp.headers.get('Content-Disposition', '')
                    m = re.search(fname_regex, cd)
                    if m:
                        groups = [g for g in m.groups() if g]
                        if len(groups) > 1:
                            version = '.'.join(groups)
                        elif groups:
                            version = groups[0]
                        print(f"  文件名版本: {version}")
            except Exception as e:
                print(f"  ⚠️ 文件名版本提取失败: {e}")
    version = product.get('version', '最新版')
    # PE 版本来源开关：'product' 时优先读 ProductVersion（DxO 专用）
    prefer_product_version = product.get('pe_version_source', '') == 'product'
    # DLL PE版本探测：从7z SFX安装器中提取DLL读取版本号
    if product.get('dll_pe_version') and not is_webpage:
        try:
            dll_ver = get_startallback_dll_version(url, referer=product.get('referer'))
            if dll_ver:
                print(f"  DLL版本: {dll_ver}")
                version = dll_ver
        except Exception as e:
            print(f"  DLL版本读取失败: {e}")
    elif product.get('pe_version') and not is_webpage:
        # HEAD-first 快路径：check_url_follow 已经拿到了 cur_size/cur_lm，
        # 跟 PE 缓存比没变就跳过 Range 下载，省掉两次分片请求（每次 200ms+）。
        # 绝大多数 fixed 产品（Wing FTP、IObit 系列、PotPlayer 等）一天只更一次，
        # 99% 场景 LM 没变 → 直接命中缓存，耗时从 2-5s 降到 < 1s。
        head_skip_pe = False
        cached_pe = ''
        cache_hot = False
        # 与 get_pe_version 保持一致的缓存键（product 模式单独一份，避免读到 FileVersion）
        _head_key = url + ('#product' if prefer_product_version else '')
        try:
            _c = _pe_cache_load()
            with _pe_cache_lock:
                hit = _c.get(_head_key)
            if hit and detected_size and detected_size == hit.get('size') and (
                    not hit.get('lm') or detected_date == hit['lm'] or detected_date == hit.get('date')):
                # LM/size 没变 → 二进制没换，缓存版本仍然正确
                cached_pe = hit.get('ver', '')
                cache_hot = cached_pe and (time.time() - hit.get('ts', 0)) < PE_CACHE_TTL
                if cached_pe:
                    print(f"  PE版本(HEAD命中缓存): {cached_pe}")
                    version = cached_pe
                    head_skip_pe = True
                    _VER_SOURCE[product['name']] = 'pe'
        except Exception:
            pass
        if not head_skip_pe:
            try:
                pe_ver = get_pe_version(url, referer=product.get('referer'),
                                        prefer_product_version=prefer_product_version)
                if pe_ver:
                    print(f"  PE版本: {pe_ver}")
                    version = pe_ver
                    # 标记版本来源（供上层防降级判断）：PE 读出的值来自安装包本体，
                    # 属权威源。产品显式声明 version_authority='pe' 时，
                    # 即便数值比旧值小也放行（旧值可能是错误口径，如 PotPlayer 的
                    # FileVersion 日期式 26.10.21.0 换成 ProductVersion 1.7.23159）。
                    _VER_SOURCE[product['name']] = 'pe'
                    # DxO 场景：软件内版本（8.11.1.896）比安装器版本（8.11.0.896）高一位，
                    # 官方安装包滞后一个修订版。此时保留人工核实的配置版本，
                    # 前提是两者主版本段一致（同一条产品线），否则以 PE 为准。
                    cfg_ver = product.get('version')
                    strict_prefix = product.get('version_strict_prefix')
                    if cfg_ver and strict_prefix and pe_ver != cfg_ver:
                        if pe_ver.startswith(strict_prefix) or cfg_ver.startswith(strict_prefix):
                            print(f"  ℹ️ PE版本({pe_ver})与配置版本({cfg_ver})同产品线，保留配置版本")
                            version = cfg_ver
                else:
                    pe_ver = _pe_version_cached(url)
                    if pe_ver:
                        print(f"  PE版本(缓存): {pe_ver}")
                        version = pe_ver
                    else:
                        # 探测和缓存都没结果 → 保留配置版本，绝不能把版本号写成空
                        print(f"  ⚠️ PE版本无结果，保留配置版本: {version}")
            except Exception as e:
                print(f"  PE版本读取失败: {e}")
                pe_ver = _pe_version_cached(url)
                if pe_ver:
                    print(f"  PE版本(缓存兜底): {pe_ver}")
                    version = pe_ver
                else:
                    print(f"  ⚠️ PE版本兜底失败，保留配置版本: {version}")
    elif product.get('nsis_inner_version') and not is_webpage:
        # NSIS 安装器：外壳 PE 版本是打包时硬编码的，可能落后于实际软件版本。
        # 典型：PotPlayer 外壳 ProductVersion=1.7.23159.0，实际软件
        # PotPlayer64.dll 的 FileVersion=1.7.23160.0（About 框显示 26021(1.7.23160)）。
        # 解包取内层真实版本，用 size/LM 缓存避免每轮重下 50MB+ 整包。
        cache_hit_ver = ''
        _nsis_key = url + '#nsis'
        try:
            _c = _pe_cache_load()
            with _pe_cache_lock:
                hit = _c.get(_nsis_key)
            if hit and detected_size and detected_size == hit.get('size') and (
                    not hit.get('lm') or detected_date == hit['lm'] or detected_date == hit.get('date')):
                if hit.get('ver'):
                    print(f"  NSIS内层版本(HEAD命中缓存): {hit['ver']}")
                    cache_hit_ver = hit['ver']
                    version = cache_hit_ver
                    _VER_SOURCE[product['name']] = 'nsis'
        except Exception:
            pass
        if not cache_hit_ver:
            try:
                inner_ver = get_nsis_inner_version(
                    url,
                    member_names=product.get('nsis_inner_members'),
                    referer=product.get('referer'),
                    prefer=product.get('nsis_inner_prefer', 'file'))
                if inner_ver:
                    version = inner_ver
                    _VER_SOURCE[product['name']] = 'nsis'
                    with _pe_cache_lock:
                        _pe_cache[_nsis_key] = {'ver': inner_ver, 'ts': time.time(),
                                                'size': detected_size, 'lm': detected_date}
                    _pe_cache_save()
                else:
                    cached = _pe_version_cached(url)
                    if cached:
                        print(f"  NSIS内层版本(缓存兜底): {cached}")
                        version = cached
            except Exception as e:
                print(f"  NSIS内层版本读取失败: {e}")
    elif product.get('rar_sfx_version') and not is_webpage:
        # RAR 自解压安装包（SFX）：外壳 PE 无版本资源，真实版本在归档内的主程序里。
        # 典型：HyperSnap 的 HS10SetupCN.exe（RAR5 SFX，7z 解不了，需 unrar）。
        # 复用 PE 版本缓存（键=URL），LM/size 不变时直接命中，避免反复下整包。
        cache_hit_ver = ''
        try:
            _c = _pe_cache_load()
            with _pe_cache_lock:
                hit = _c.get(url)
            if hit and detected_size and detected_size == hit.get('size') and (
                    not hit.get('lm') or detected_date == hit['lm'] or detected_date == hit.get('date')):
                if hit.get('ver'):
                    print(f"  RAR SFX版本(HEAD命中缓存): {hit['ver']}")
                    cache_hit_ver = hit['ver']
                    version = cache_hit_ver
        except Exception:
            pass
        if not cache_hit_ver:
            try:
                sfx_ver = get_rar_sfx_version(
                    url,
                    member_names=product.get('rar_sfx_members'),
                    referer=product.get('referer'))
                if sfx_ver:
                    version = sfx_ver
                    with _pe_cache_lock:
                        _pe_cache[url] = {'ver': sfx_ver, 'ts': time.time(),
                                          'size': detected_size, 'lm': detected_date}
                    _pe_cache_save()
                else:
                    cached = _pe_version_cached(url)
                    if cached:
                        print(f"  RAR SFX版本(缓存兜底): {cached}")
                        version = cached
            except Exception as e:
                print(f"  RAR SFX版本读取失败: {e}")
    # 官网页面版本交叉校验（可选）：二进制可能被 CDN 长期缓存（如 wftpserver.com 的
    # Cache-Control: max-age=604800，整整 7 天），或被本地 PE 缓存（TTL 6h）挡住，
    # 导致刚发布的新版本号滞后。官网页面即时更新，配置 page_version_url + regex 后，
    # 取「页面版本 与 二进制版本」的较大值，保证新版本能被及时发现。
    page_url = product.get('page_version_url')
    page_regex = product.get('page_version_regex')
    if page_url and page_regex:
        try:
            req = urllib.request.Request(page_url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=20) as resp:
                html = resp.read().decode('utf-8', errors='ignore')
            m = re.search(page_regex, html, re.I)
            if m and m.group(1):
                page_ver = m.group(1)
                if _ver_newer(page_ver, version):
                    print(f"  官网页面版本: {page_ver} (高于 {version}，采用)")
                    version = page_ver
                else:
                    print(f"  官网页面版本: {page_ver} (不高于 {version}，忽略)")
        except Exception as e:
            print(f"  ⚠️ 官网页面版本抓取失败: {e}")
    # 去掉末段补位的 .0：PE ProductVersion 常写成四段（PotPlayer 1.7.23159.0），
    # 官方口径只到三段（1.7.23159）。只对配了该开关的产品生效，避免误伤需要四段的。
    if product.get('strip_trailing_zero') and isinstance(version, str):
        m = re.fullmatch(r'(\d+(?:\.\d+)*)\.0+', version)
        if m:
            print(f"  ℹ️ 去除末段补位0: {version} -> {m.group(1)}")
            version = m.group(1)
    return version, url, url, size, date, md5


def _cyberlink_canon_ver(v):
    """CyberLink 版本号归一：统一成下载器 info.ini DisplayBuildNumber 的 4 段式。

    同一构建存在两种写法：5 段 PE 式 '25.0.0.0904.0'（build 在第 4 段，第 3 段恒 0）
    与 4 段 info.ini 式 '25.0.0904.0'（build 在第 3 段）。_ver_tuple 按段比较时
    (25,0,0,904) != (25,0,904,0)，旧配置的 5 段写法会把试用通道探测出的同版本
    误判为「更新」，击穿 base_version/version_display 防降级保护，这里统一归一。
    非「5 段且第 3 段为 0」的输入原样返回，不影响其它格式。
    """
    s = str(v).strip()
    parts = []
    for p in s.split('.'):
        m = re.match(r'(\d+)', p)
        if not m:
            return s
        parts.append(int(m.group(1)))
    if len(parts) == 5 and parts[2] == 0:
        return f'{parts[0]}.{parts[1]}.{parts[3]:04d}.{parts[4]}'
    return s


def _cyberlink_extract_build(url, referer=None):
    """下载 CyberLink 官方安装器（下载器约 10MB），解出内部 info.ini 的 DisplayBuildNumber。
    返回版本号字符串，失败返回空字符串。"""
    import shutil
    import subprocess
    import tempfile

    headers = {'User-Agent': UA}
    if referer:
        headers['Referer'] = referer
    tmpdir = None
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=90) as resp:
            total = int(resp.headers.get('Content-Length', 0) or 0)
            if total > 40 * 1024 * 1024:
                print(f"  安装器体积过大({total})，跳过内部版本提取")
                return ''
            data = resp.read(40 * 1024 * 1024)
        tmpdir = tempfile.mkdtemp(prefix='clver_')
        exe_path = os.path.join(tmpdir, 'pkg.exe')
        with open(exe_path, 'wb') as f:
            f.write(data)

        script_dir = os.path.dirname(os.path.abspath(__file__))
        seven_zip = None
        for cmd in ['7z', '7zz', '7za',
                    os.path.join(script_dir, 'tools', '7zz'),
                    os.path.join(script_dir, 'tools', '7z')]:
            try:
                subprocess.run([cmd, '--help'], capture_output=True, timeout=5)
                seven_zip = cmd
                break
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
        if not seven_zip:
            print("  未找到7z命令，跳过版本提取")
            return ''

        out_dir = os.path.join(tmpdir, 'out')
        os.makedirs(out_dir, exist_ok=True)
        # CyberLink 安装器内 info.ini 位于 $_1_/ 子目录，用通配符提取
        subprocess.run([seven_zip, 'x', exe_path, '-o' + out_dir, '-y', '*/info.ini'],
                       capture_output=True, text=True, timeout=60)
        content = ''
        for root, _dirs, files in os.walk(out_dir):
            if 'info.ini' in files:
                with open(os.path.join(root, 'info.ini'), 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                break
        if not content:
            print("  安装器内未找到 info.ini")
            return ''
        m = re.search(r'DisplayBuildNumber\s*=\s*([0-9][0-9.]*)', content)
        if m:
            return m.group(1)
    except Exception as e:
        print(f"  内部版本提取失败: {e}")
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
    return ''


# CyberLink 买断版（Ultimate / Ultra）零售通道：产品密钥兑换。
# 官方兑换页 https://www.cyberlink.com/box 前端即调用该接口（从其打包 JS 逆出）：
#   POST /api/download/box  application/json  {"key","lang","recaptchaToken"}
# 成功：{"status":"OK","data":{"productName":...,"buildlist":[{"buildName":...,
#        "fileList":[{"url":...,"fileSizeInBytes":...}]}]}}
# 失败：{"status":"FAIL","data":null}；需人机验证：{"needVerify":true}
# 当前版本的零售直链含服务端下发的随机令牌、无法推算，只能靠密钥兑换拿到。
# 密钥来源：环境变量 CYBERLINK_RETAIL_KEY（多个逗号分隔）或产品配置 retail_product_key。
CYBERLINK_BOX_API = 'https://www.cyberlink.com/api/download/box'
CYBERLINK_BOX_PAGE = 'https://www.cyberlink.com/box'


def _cyberlink_retail_redeem(key, lang='ENU'):
    """用产品密钥在官方兑换接口换取买断版零售离线包直链。

    返回 [{'product_name','build','url','size'}]；无有效密钥/失败返回 []。
    """
    payload = json.dumps({'key': key.strip().upper(), 'lang': lang,
                          'recaptchaToken': ''}).encode()
    req = urllib.request.Request(CYBERLINK_BOX_API, data=payload, headers={
        'User-Agent': UA,
        'Content-Type': 'application/json',
        'Origin': 'https://www.cyberlink.com',
        'Referer': CYBERLINK_BOX_PAGE,
    })
    with urllib.request.urlopen(req, timeout=25) as resp:
        obj = json.loads(resp.read().decode('utf-8', 'ignore'))
    out = []
    if obj.get('status') == 'OK':
        data = obj.get('data') or {}
        for b in (data.get('buildlist') or []):
            for f in (b.get('fileList') or []):
                out.append({
                    'product_name': data.get('productName', ''),
                    'build': b.get('buildName', ''),
                    'url': f.get('url', ''),
                    'size': f.get('fileSizeInBytes', 0),
                })
    return out


def detect_cyberlink(product):
    """CyberLink 官方版本自动探测（无需硬编码 VID 令牌）。

    流程全走官方接口：
      1. /api/download/thank-you-page?ProductId=N  取 buildLink
      2. 跟随 buildLink(user-add.do) 的 302 拿到 build.cyberlink.com 官方下载器直链
      3. 解出下载器内 info.ini 的 DisplayBuildNumber（= 当前官方产品版本）
      4. 若配置了 CYBERLINK_RETAIL_KEY，再走零售兑换接口拿买断版（Ultimate/Ultra）直链

    这样令牌/版本随官方更新自动刷新；下载链接仍用配置的官方离线包。
    """
    version = product.get('version', '')
    download_url = product.get('download_url', '')
    size = product.get('size', 0)
    date = product.get('date', '')
    md5 = product.get('md5', '')
    pid = product.get('cyberlink_product_id')
    if pid:
        try:
            api = ('https://www.cyberlink.com/api/download/thank-you-page'
                   f'?ProductId={pid}&ostype=Windows')
            req = urllib.request.Request(api, headers={
                'User-Agent': UA,
                'Referer': f'https://www.cyberlink.com/prog/trial/download-notice.jsp?ProductId={pid}&ostype=Windows',
            })
            with urllib.request.urlopen(req, timeout=20) as resp:
                info = json.loads(resp.read().decode('utf-8', 'ignore'))
            build_link = info.get('buildLink', '')
            if build_link:
                if build_link.startswith('/'):
                    build_link = 'https://www.cyberlink.com' + build_link
                req2 = urllib.request.Request(build_link, headers={'User-Agent': UA})
                with urllib.request.urlopen(req2, timeout=20) as resp2:
                    downloader_url = resp2.geturl()
                print(f"  官方下载器: {downloader_url[:90]}...")
                detected = _cyberlink_canon_ver(_cyberlink_extract_build(downloader_url))
                if detected:
                    version = detected
                    print(f"  官方版本: {version}")
        except Exception as e:
            print(f"  ⚠️ CyberLink 官方接口探测失败: {e}")

    # 买断版零售通道（产品密钥兑换）：配置了 CYBERLINK_RETAIL_KEY 才启用。
    # 兑换到的直链即「Ultimate / Ultra 买断版」离线包；无密钥时不影响其它探测。
    retail_key = (os.environ.get('CYBERLINK_RETAIL_KEY')
                  or product.get('retail_product_key') or '').strip()
    if retail_key:
        for rk in [k.strip() for k in re.split(r'[,\s]+', retail_key) if k.strip()]:
            try:
                builds = _cyberlink_retail_redeem(rk)
            except Exception as e:
                print(f"  ⚠️ 零售密钥兑换失败: {e}")
                continue
            if not builds:
                print("  零售密钥未兑换到直链（密钥无效或需人机验证）")
                continue
            rb = builds[0]
            print(f"  零售买断版直链: [{rb['build']}] {rb['url'][:90]}")
            if rb['url']:
                download_url = rb['url']
            if rb['size']:
                size = rb['size']
            # 文件名里若带版本号，则用它覆盖官方试用版版本号（归一成 4 段式）
            m = re.search(r'(\d+(?:\.\d+){3,4})', rb['url'])
            if m:
                version = _cyberlink_canon_ver(m.group(1))
                print(f"  零售买断版版本: {version}")
            break

    # 刷新离线包链接可用性/大小/日期
    try:
        exists, dsize, ddate = check_url_follow(download_url)
        if exists and dsize > 0:
            size = dsize
            if ddate:
                date = ddate
    except Exception:
        pass

    return version, download_url, download_url, size, date, md5


def detect_lanzou(product):
    """蓝奏云网盘探测模式：从文件夹页面提取参数，调用API获取文件列表
    返回最新文件的版本号、大小、日期、下载链接
    """
    folder_url = product['download_url']
    headers = {'User-Agent': UA}
    
    try:
        # 第一步：访问页面提取参数
        req = urllib.request.Request(folder_url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
        
        # 提取动态参数
        t_match = re.search(r"var\s+\w+\s*=\s*'(\d{10})'", html)
        k_match = re.search(r"var\s+\w+\s*=\s*'([a-f0-9]{32})'", html)
        fid_match = re.search(r"file=(\d+)", html)
        uid_match = re.search(r"'uid':'(\d+)'", html)
        puid_match = re.search(r"'puid':'([^']+)'", html)
        
        if not all([t_match, k_match, fid_match, uid_match, puid_match]):
            print(f"  ⚠️ 无法提取蓝奏云参数")
            return product.get('version', ''), folder_url, folder_url, product.get('size', 0), product.get('date', ''), ''
        
        t = t_match.group(1)
        k = k_match.group(1)
        fid = fid_match.group(1)
        uid = uid_match.group(1)
        puid = puid_match.group(1)
        
        # 第二步：调用API获取文件列表
        api_url = f'https://www.lanzoui.com/filemoreajax.php?file={fid}'
        data = {
            'lx': 2, 'fid': int(fid), 'uid': uid, 'puid': puid,
            'pg': 1, 'rep': 0, 't': t, 'k': k, 'up': 1,
        }
        headers['Referer'] = folder_url
        headers['X-Requested-With'] = 'XMLHttpRequest'
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
        
        req2 = urllib.request.Request(api_url, data=urllib.parse.urlencode(data).encode(), headers=headers)
        with urllib.request.urlopen(req2, timeout=20) as resp2:
            result = json.loads(resp2.read().decode('utf-8', errors='ignore'))
        
        if str(result.get('zt')) != '1':
            print(f"  ⚠️ 蓝奏云API返回错误: {result.get('info')}")
            return product.get('version', ''), folder_url, folder_url, product.get('size', 0), product.get('date', ''), ''
        
        files = result.get('text', [])
        if not files:
            print(f"  ⚠️ 文件列表为空")
            return product.get('version', ''), folder_url, folder_url, product.get('size', 0), product.get('date', ''), ''
        
        # 取第一个文件（最新）
        latest = files[0]
        name = latest.get('name_all', '')
        size_str = latest.get('size', '0 M')
        time_str = latest.get('time', '')
        file_id = latest.get('id', '')
        
        # 从文件名提取版本号
        version = product.get('version', '')
        version_regex = product.get('version_regex')
        if version_regex:
            m = re.search(version_regex, name)
            if m:
                version = m.group(1)
        
        # 解析大小
        size = product.get('size', 0)
        if size_str:
            try:
                size_mb = float(size_str.replace('M', '').replace(' ', ''))
                size = int(size_mb * 1024 * 1024)
            except:
                pass
        
        # 解析日期（蓝奏云日期格式：前天02:14、昨天02:14、28天前、2026-07-29）
        date = product.get('date', '')
        if time_str:
            if re.match(r'\d{4}-\d{2}-\d{2}', time_str):
                date = time_str
            elif '前天' in time_str:
                from datetime import datetime, timedelta
                date = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
            elif '昨天' in time_str:
                from datetime import datetime, timedelta
                date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            elif '天前' in time_str:
                days = int(re.search(r'(\d+)', time_str).group(1))
                from datetime import datetime, timedelta
                date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        # 下载链接为文件页面
        download_url = f'https://www.lanzoui.com/{file_id}' if file_id else folder_url
        
        print(f"  最新文件: {name}")
        print(f"  版本: {version}, 大小: {size_str}, 日期: {date}")
        
        return version, download_url, folder_url, size, date, ''
        
    except Exception as e:
        print(f"  ⚠️ 蓝奏云探测失败: {e}")
        return product.get('version', ''), folder_url, folder_url, product.get('size', 0), product.get('date', ''), ''


_pe_cache = {}
_pe_cache_lock = threading.Lock()
# PE 版本缓存纳入 git：CI 全新环境也能复用，避免重复 Range 下载，
# 同时防止偶发网络失败导致版本号被"降级"回配置里的旧值。
# 缓存键 = URL（原地覆盖的包最多延迟 PE_CACHE_TTL 才发现新版本；
# 带版本号的 URL 变更时自然失效，所以 TTL 不需要太长）。
PE_CACHE_FILE = os.path.join(BASE_DIR, 'pe_version_cache.json')
PE_CACHE_TTL = 6 * 3600


def _pe_cache_load():
    """加载 PE 缓存并做 TTL 自适应续期：TTL 过期但 Last-Modified/size 没变
    说明二进制没换（CDN 可能缓存很久），主动发一次 HEAD 探测，没变就续期。
    这样既不会把过期缓存泄漏给调用方，又避免了固定 TTL 导致的无效 Range 下载。"""
    global _pe_cache
    with _pe_cache_lock:
        if _pe_cache:
            return _pe_cache
        try:
            with open(PE_CACHE_FILE, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            now = time.time()
            expired = []
            for k, v in (raw.get('entries') or {}).items():
                age = now - v.get('ts', 0)
                if age < PE_CACHE_TTL:
                    _pe_cache[k] = v
                else:
                    expired.append((k, v))
            # 过期但 LM/size 没变 → 续期（省掉 Range 下载）
            for url, hit in expired:
                try:
                    req = urllib.request.Request(url, method='HEAD',
                                                 headers={'User-Agent': UA})
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        cur_lm = resp.headers.get('Last-Modified', '') or ''
                        cur_size = int(resp.headers.get('Content-Length', 0) or 0)
                    if cur_lm and cur_lm == hit.get('lm') and (not hit.get('size')
                            or cur_size == hit['size']):
                        hit['ts'] = now
                        _pe_cache[url] = hit
                        print(f"  PE缓存续期(HEAD): {hit['ver']} ({os.path.basename(url)[:40]})")
                except Exception as _e:
                    pass
        except Exception:
            pass
        return _pe_cache


def _pe_cache_save():
    with _pe_cache_lock:
        try:
            with open(PE_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump({'entries': _pe_cache}, f, ensure_ascii=False)
        except Exception:
            pass


def _pe_version_cached(url):
    """只读缓存里的 PE 版本（探测失败时的兜底，不发起网络请求）"""
    cache = _pe_cache_load()
    with _pe_cache_lock:
        hit = cache.get(url)
    return hit['ver'] if hit else ''


def _range_download(url, headers, start, end, workers=8, timeout=60, min_chunk=64 * 1024):
    """并发分片下载字节区间 [start, end]（含两端），返回拼接后的 bytes。

    慢速服务器（单连接被限速，如 startisback.com 只有 ~15KB/s）用多线程 Range
    分片能快一个数量级。区间很小、或服务器不支持 Range（返回 200 全量）时
    自动回退单连接，保证正确性。

    参数：
      min_chunk 每片最小字节数，用于决定分片数量（避免小文件开太多线程）
    """
    span = end - start + 1
    if span <= 0:
        return b''

    def _single():
        req = urllib.request.Request(url, headers={**headers, 'Range': f'bytes={start}-{end}'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            # 服务器忽略 Range 返回了完整文件时，从正确位置截取
            if resp.status == 200 and len(data) > span:
                return data[start:end + 1]
            return data

    n = min(workers, max(1, span // min_chunk))
    if n <= 1:
        return _single()

    step = (span + n - 1) // n

    def _one(i):
        s = start + i * step
        e = min(end, s + step - 1)
        if s > e:
            return b''
        req = urllib.request.Request(url, headers={**headers, 'Range': f'bytes={s}-{e}'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            if resp.status != 206 and len(data) != (e - s + 1):
                # 服务器不支持分片（返回全量），交由调用方回退
                raise Exception('server does not honor Range')
            return data

    parts = [b''] * n
    try:
        with ThreadPoolExecutor(max_workers=n) as ex:
            for i, data in enumerate(ex.map(_one, range(n))):
                parts[i] = data
        blob = b''.join(parts)
        if len(blob) != span:
            raise Exception(f"分片下载不完整 {len(blob)}/{span}")
        return blob
    except Exception as e:
        print(f"  分片下载失败({e})，回退单连接...")
        return _single()


def get_pe_version(url, referer=None, prefer_product_version=False):
    """读取 PE 文件版本，带 URL 级缓存。

    热跑加速的关键：缓存键 = URL，命中且未过期时**零网络请求**直接返回。
    这对高延迟服务器（如 winxdvd.com 单次请求 TTFB 就要 20 秒）尤其重要——
    原来每轮都要发 HEAD + 2 次 Range，稳态也要 ~60 秒；现在直接读缓存。
    TTL 到期后重新探测；探测失败时用缓存旧值兜底，避免版本号被"降级"。

    prefer_product_version=True 时优先读 PE 资源里的 ProductVersion
    （DxO / PotPlayer 专用：ProductVersion 才是官方产品版本；
    其它软件不能开，如 R-Studio 干脆没有 ProductVersion）。
    """
    # 缓存键要区分版本来源：同一 URL 在 product/file 两种模式下读出的值不同，
    # 共用 'url' 会互相污染（先把 FileVersion 写进缓存，product 模式就命中脏值）。
    cache_key = url + ('#product' if prefer_product_version else '')
    cache = _pe_cache_load()
    with _pe_cache_lock:
        hit = cache.get(cache_key)
    if hit and (time.time() - hit.get('ts', 0)) < PE_CACHE_TTL:
        print(f"  PE版本(缓存): {hit['ver']}")
        return hit['ver']

    ver, size, lm = _get_pe_version_raw(url, referer, prefer_product_version)
    if ver:
        with _pe_cache_lock:
            _pe_cache[cache_key] = {'ver': ver, 'ts': time.time(), 'size': size, 'lm': lm}
        _pe_cache_save()
        return ver

    # 探测失败（网络抖动等）→ 用已有缓存值兜底，防止版本回退
    if hit:
        print(f"  PE版本(缓存兜底): {hit['ver']}")
        return hit['ver']
    return ''


def _get_pe_version_raw(url, referer=None, prefer_product_version=False):
    """从PE文件的.rsrc段读取FileVersion（四段版本号），只下载PE头和资源段，不需要下载整个文件。
    返回 (版本号, 文件大小, Last-Modified)，失败返回 ('', 0, '')。

    请求策略（针对高延迟服务器优化，如 winxdvd.com 首字节要 20s）：
    原来分 3 次串行 Range（前1KB → PE头4KB → .rsrc），每次一个 RTT，慢源上要 60s+。
    改为：第 1 次一次取前 64KB（足够覆盖 e_lfanew + PE 头 + 段表），
    顺便从 Content-Range 响应头拿文件总大小和 Last-Modified（省掉单独 HEAD）；
    第 2 次取 .rsrc 段（大区间内部再并发分片）。把 3 次串行降到 2 次。
    """
    import struct
    import re
    headers = {'User-Agent': UA}
    if referer:
        headers['Referer'] = referer

    def download_range(start, end, workers=8):
        # 用并发分片下载：慢速服务器上大区间（如 .rsrc 段）能快数倍
        return _range_download(url, headers, start, end, workers=workers, timeout=45)

    size, lm = 0, ''
    try:
        # 1. 一次取前 64KB：含 DOS 头(0x3C 处 e_lfanew) + PE 签名 + 可选头 + 段表
        #    单独发请求以便读取响应头里的 总大小 / Last-Modified
        req = urllib.request.Request(url, headers={**headers, 'Range': 'bytes=0-65535'})
        with urllib.request.urlopen(req, timeout=45) as resp:
            head = resp.read()
            lm = resp.headers.get('Last-Modified', '') or ''
            cr = resp.headers.get('Content-Range', '') or ''
            if '/' in cr:
                try:
                    size = int(cr.rsplit('/', 1)[1])
                except Exception:
                    size = 0
            if not size:
                size = int(resp.headers.get('Content-Length', 0) or 0)
            if resp.status == 200 and len(head) > 65536:
                head = head[:65536]

        pe_offset = struct.unpack_from('<I', head, 0x3C)[0]
        if pe_offset == 0 or pe_offset + 24 > len(head):
            print(f"  PE偏移异常: {pe_offset}")
            return '', size, lm

        # 2. 直接从这 64KB 里解析段表（pe_offset 及段表都远在 64KB 内）
        pe_data = head[pe_offset:]
        num_sections = struct.unpack_from('<H', pe_data, 6)[0]
        opt_header_size = struct.unpack_from('<H', pe_data, 20)[0]
        section_offset = 24 + opt_header_size

        # 3. 找.rsrc段
        for i in range(num_sections):
            off = section_offset + i * 40
            if off + 40 > len(pe_data):
                # 段表超出已下载的 64KB（极少见），补取一次 PE 头区域
                pe_data = download_range(pe_offset, pe_offset + 4096, workers=4)
                off = section_offset + i * 40
                if off + 40 > len(pe_data):
                    break
            name = pe_data[off:off+8].rstrip(b'\x00').decode('ascii', errors='replace')
            if name == '.rsrc':
                raw_offset = struct.unpack_from('<I', pe_data, off+20)[0]
                raw_size = struct.unpack_from('<I', pe_data, off+16)[0]
                # 4. 下载.rsrc段（最多2MB），大区间内部分片并发
                rsrc = download_range(raw_offset, raw_offset + min(raw_size, 2*1024*1024), workers=16)
                # 5. 解析版本信息（UTF-16LE编码）
                text = rsrc.decode('utf-16-le', errors='replace')
                # ⚠️ 版本来源可选：pe_version_source='product' 时优先 ProductVersion。
                # ProductVersion 才是官方产品版本（DxO: 10.2.0.496），
                # FileVersion 是文件自身版本（DxO: 10.2.20738.496，20738 是构建号）。
                # 但**不能全局改**：PotPlayer 的 ProductVersion 是播放器历史版本
                # (1.7.23118.0)、R-Studio 干脆没有 ProductVersion，
                # 所以只在产品显式配置 pe_version_source='product' 时才用。
                if prefer_product_version:
                    m = re.search(r'ProductVersion[\x00\s]*(\d+\.\d+(?:\.\d+){0,2})', text)
                    if m:
                        print(f"  PE ProductVersion: {m.group(1)}")
                        return m.group(1), size, lm
                # 默认走 FileVersion（支持四段/三段/两段；UTF-16资源中FileVersion后有\x00分隔）
                match = re.search(r'FileVersion[\x00\s]*(\d+\.\d+\.\d+\.\d+)', text)
                if not match:
                    match = re.search(r'FileVersion[\x00\s]*(\d+\.\d+(?:\.\d+)?)', text)
                if match:
                    print(f"  PE FileVersion: {match.group(1)}")
                    return match.group(1), size, lm
                # 兜底2：找所有四段版本号，取出现最多的
                versions = re.findall(r'\d+\.\d+\.\d+\.\d+', text)
                if versions:
                    from collections import Counter
                    return Counter(versions).most_common(1)[0][0], size, lm
                # 兜底3：ProductVersion（FileVersion 都没有时）
                m = re.search(r'ProductVersion[\x00\s]*(\d+\.\d+(?:\.\d+){0,2})', text)
                if m:
                    print(f"  PE ProductVersion(兜底): {m.group(1)}")
                    return m.group(1), size, lm
                break
    except Exception as e:
        print(f"  PE版本解析失败: {e}")
    return '', size, lm


def get_nsis_install_version(url, referer=None):
    """从NSIS安装包中提取install.7z内的版本号文件夹名称。
    高效探测：只下载NSIS头部(2MB)搜索7z签名，再下载install.7z头部(4KB)读取文件列表。
    返回版本号字符串，失败返回空字符串。
    """
    import struct
    import subprocess
    import tempfile
    import os

    headers = {'User-Agent': UA}
    if referer:
        headers['Referer'] = referer

    def download_range(start, end):
        # 用并发分片下载：NSIS 需拉取前 3MB 头，慢速源上提速明显
        return _range_download(url, headers, start, end, workers=8, timeout=60)

    try:
        # 1. 下载PE头获取overlay偏移
        head = download_range(0, 1024)
        pe_offset = struct.unpack_from('<I', head, 0x3C)[0]
        pe_data = download_range(pe_offset, pe_offset + 4096)
        num_sections = struct.unpack_from('<H', pe_data, 6)[0]
        opt_header_size = struct.unpack_from('<H', pe_data, 20)[0]
        section_offset = 24 + opt_header_size
        overlay_offset = 0
        for i in range(num_sections):
            off = section_offset + i * 40
            raw_offset = struct.unpack_from('<I', pe_data, off+20)[0]
            raw_size = struct.unpack_from('<I', pe_data, off+16)[0]
            if raw_offset + raw_size > overlay_offset:
                overlay_offset = raw_offset + raw_size

        # 2. 下载NSIS头部(3MB)，搜索7z签名找到install.7z位置
        nsis_data = download_range(overlay_offset, overlay_offset + 3*1024*1024)
        sig = b'\x37\x7a\xbc\xaf\x27\x1c'
        sig_pos = nsis_data.find(sig)
        if sig_pos < 0:
            print(f"  NSIS中未找到7z签名")
            return ''

        install_7z_offset = overlay_offset + sig_pos
        print(f"  install.7z偏移: {install_7z_offset}")

        # 3. 从7z签名头部读取精确大小，下载头尾构造完整文件
        # 7z头部: 6字节签名 + 2字节版本 + 4字节CRC + 8字节next_header_offset + 8字节next_header_size + 4字节CRC
        sig_head = download_range(install_7z_offset, install_7z_offset + 32)
        if sig_head[:6] != b'\x37\x7a\xbc\xaf\x27\x1c':
            print(f"  7z签名不匹配")
            return ''
        next_header_offset = struct.unpack_from('<Q', sig_head, 12)[0]
        next_header_size = struct.unpack_from('<Q', sig_head, 20)[0]
        install_size = 32 + next_header_offset + next_header_size + 4
        print(f"  install.7z大小: {install_size}")

        # 下载开头32KB和末尾128KB
        install_head = download_range(install_7z_offset, install_7z_offset + 32768)
        install_tail = download_range(install_7z_offset + install_size - 131072, install_7z_offset + install_size - 1)

        # 构造完整大小的稀疏文件
        with tempfile.NamedTemporaryFile(suffix='.7z', delete=False) as f:
            f.write(install_head)
            f.seek(install_size - 131072)
            f.write(install_tail)
            f.truncate(install_size)
            tmp_path = f.name

        # 4. 用7z列出文件，找第一个文件夹名称（版本号）
        try:
            import os
            import re
            # 优先用py7zr（纯Python，不依赖系统命令）
            try:
                import py7zr
                with py7zr.SevenZipFile(tmp_path, mode='r') as z:
                    names = z.getnames()
                    # 找第一个版本号文件夹
                    for name in names:
                        m = re.match(r'(\d+\.\d+\.\d+\.\d+)/', name)
                        if m:
                            print(f"  NSIS install版本号(py7zr): {m.group(1)}")
                            return m.group(1)
                    # 兜底：找所有路径中的版本号
                    versions = re.findall(r'(\d+\.\d+\.\d+\.\d+)', ' '.join(names))
                    if versions:
                        print(f"  NSIS install版本号(py7zr兜底): {versions[0]}")
                        return versions[0]
            except ImportError:
                pass
            except Exception as e:
                print(f"  py7zr解析失败({e})，尝试系统7z命令")
            # 备选：系统7z命令
            script_dir = os.path.dirname(os.path.abspath(__file__))
            seven_zip = None
            for cmd in ['7z', '7zz', '7za',
                        '/usr/bin/7z', '/usr/local/bin/7z',
                        os.path.join(script_dir, 'tools', '7zz'),
                        os.path.join(script_dir, 'tools', '7z')]:
                try:
                    subprocess.run([cmd, '--help'], capture_output=True, timeout=5)
                    seven_zip = cmd
                    break
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    continue
            if not seven_zip:
                print(f"  未找到7z命令且py7zr不可用，跳过NSIS版本解析")
                return ''
            result = subprocess.run(
                [seven_zip, 'l', tmp_path],
                capture_output=True, text=True, timeout=30
            )
            # 解析输出，找第一个文件夹（D....属性）
            for line in result.stdout.split('\n'):
                if ' D.... ' in line or ' D....' in line:
                    parts = line.split()
                    for part in parts:
                        if part and part[0].isdigit() and '.' in part and '/' not in part:
                            print(f"  NSIS install版本号: {part}")
                            return part
            # 兜底：找所有路径中的版本号文件夹
            versions = re.findall(r'(\d+\.\d+\.\d+\.\d+)', result.stdout)
            if versions:
                print(f"  NSIS install版本号(兜底): {versions[0]}")
                return versions[0]
        finally:
            os.unlink(tmp_path)

    except Exception as e:
        print(f"  NSIS版本解析失败: {e}")
    return ''


def get_nsis_inner_version(url, member_names=None, referer=None, max_size=96 * 1024 * 1024,
                          prefer='file'):
    """从 NSIS 安装器中解出内层文件并读取其 PE 版本号。

    背景：PotPlayer 的官方安装包 PotPlayerSetup64.exe 是 NSIS 包。
    外壳 PE 的 ProductVersion（1.7.23159.0）比实际软件版本落后一版，
    因为外壳的版本是打包时硬编码的；真正的版本在内层 PotPlayer64.dll 上，
    其 FileVersion = 1.7.23160.0，正是 About 框显示的 26021(1.7.23160)。
    注意该 DLL 的 ProductVersion 是无意义的 1.7.0.0，所以默认读 FileVersion。

    流程：下载整包 → 7z 解出指定成员 → 读该文件的 PE 版本。
    member_names 为候选文件名（按优先级），依次尝试。
    prefer='file' 读 FileVersion，'product' 读 ProductVersion。
    返回版本号字符串，失败返回 ''。
    """
    import os
    import shutil
    import subprocess
    import tempfile

    headers = {'User-Agent': UA}
    if referer:
        headers['Referer'] = referer

    # 找 7z（CI 装 p7zip-full，本地通常也有）
    seven_zip = None
    for cand in ['7z', '7zz', '7za', '/usr/bin/7z', '/usr/local/bin/7z',
                 os.path.join(BASE_DIR, 'tools', '7zz'),
                 os.path.join(BASE_DIR, 'tools', '7z')]:
        exe = shutil.which(cand) if not os.path.isabs(cand) else (cand if os.path.exists(cand) else None)
        if exe:
            seven_zip = exe
            break
    if not seven_zip:
        print("  未找到7z命令，跳过NSIS内层版本解析")
        return ''

    tmp_path = None
    try:
        # NSIS 是连续 LZMA 流，无法按偏移单独取某成员，必须整包下载。
        # 并发分片拉取，daum CDN 单连接 ~11MB/s，分片更快。
        total = 0
        try:
            req = urllib.request.Request(url, method='HEAD', headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                total = int(resp.headers.get('Content-Length', 0) or 0)
        except Exception:
            total = 0
        if total and total <= max_size:
            data = _range_download(url, headers, 0, total - 1,
                                   workers=16, timeout=180, min_chunk=65536)
        else:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = resp.read()
        if not data:
            print("  NSIS安装包下载为空")
            return ''
        if len(data) > max_size:
            print(f"  NSIS安装包过大({len(data)}字节)，跳过")
            return ''

        with tempfile.NamedTemporaryFile(suffix='.exe', delete=False) as f:
            f.write(data)
            tmp_path = f.name
        print(f"  NSIS安装包: {len(data)} bytes")

        # 列出归档成员（7z 支持 NSIS）
        lst = subprocess.run([seven_zip, 'l', '-ba', tmp_path],
                             capture_output=True, text=True, timeout=120)
        members = []
        for line in lst.stdout.split('\n'):
            parts = line.split()
            if len(parts) >= 2 and ('.' in parts[-1]):
                members.append(parts[-1])

        # 定位目标成员：优先按配置的名字精确/后缀匹配
        targets = []
        for want in (member_names or []):
            for m in members:
                if m.lower() == want.lower() or m.lower().endswith('/' + want.lower()):
                    targets.append(m)
                    break
        if not targets:
            # 兜底：取最大的 .dll（PotPlayer 的主体是 PotPlayer64.dll）
            dlls = [m for m in members if m.lower().endswith('.dll')
                    and not m.lower().startswith('$plugin')]
            if dlls:
                targets = dlls[:1]

        for target in targets:
            tmpdir = tempfile.mkdtemp()
            try:
                subprocess.run([seven_zip, 'e', '-y', '-o' + tmpdir, tmp_path, target],
                               capture_output=True, timeout=180)
                for root, _dirs, files in os.walk(tmpdir):
                    for fn in files:
                        p = os.path.join(root, fn)
                        fv, pv = _read_pe_local_versions(p)
                        if not fv and not pv:
                            continue
                        ver = fv if prefer == 'file' else pv
                        if not ver:
                            ver = fv or pv
                        if ver:
                            print(f"  NSIS内层版本({fn}, {prefer}): {ver}")
                            return ver
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
        return ''
    except Exception as e:
        print(f"  NSIS内层版本解析失败: {e}")
        return ''
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def get_rar_sfx_version(url, member_names=None, referer=None, max_size=64 * 1024 * 1024):
    """从 RAR 自解压安装包（SFX）里解出主程序并读取其 PE 版本号。

    背景：HyperSnap 的安装包 HS10SetupCN.exe 是 RAR5 SFX（Method=m5:22），
    外壳 PE 没有版本资源（读不出 FileVersion），真实版本在归档内的
    HprSnap.exe 里。7z 不支持 RAR5 解压，需要 unrar（或 unar）。

    流程：下载整包 → 用 unrar 解出指定成员 → 读该 exe 的 PE 版本。
    member_names 为候选文件名（按优先级），依次尝试。
    返回版本号字符串，失败返回 ''。
    """
    import os
    import re
    import shutil
    import subprocess
    import tempfile

    headers = {'User-Agent': UA}
    if referer:
        headers['Referer'] = referer

    # 找可用的 RAR 解包器：unrar 原生支持 RAR5；unar(The Unarchiver) 也支持
    unrar = None
    for cand in ['unrar', '/usr/bin/unrar', '/usr/local/bin/unrar',
                 os.path.join(BASE_DIR, 'tools', 'unrar')]:
        exe = shutil.which(cand) if not os.path.isabs(cand) else (cand if os.path.exists(cand) else None)
        if exe:
            unrar = exe
            break
    if not unrar:
        # 备选：unar（lsar 列目录 + unar 解压），CI 里 apt install unar 可用
        unar = shutil.which('unar')
        lsar = shutil.which('lsar')
        if not (unar and lsar):
            print("  未找到unrar/unar，跳过RAR SFX版本解析")
            return ''
    else:
        unar = lsar = None

    tmp_path = None
    try:
        # 慢源（如 hyperionics.com 单连接仅 ~14KB/s）必须并发分片拉，
        # 实测 24 并发聚合 ~130KB/s，比单连接快 5 倍以上。
        total = 0
        try:
            req = urllib.request.Request(url, method='HEAD', headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                total = int(resp.headers.get('Content-Length', 0) or 0)
        except Exception:
            total = 0
        if total and total <= max_size:
            data = _range_download(url, headers, 0, total - 1,
                                   workers=24, timeout=180, min_chunk=32768)
        else:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = resp.read()
        if len(data) > max_size:
            print(f"  RAR SFX包过大({len(data)}字节)，跳过")
            return ''
        with tempfile.NamedTemporaryFile(suffix='.exe', delete=False) as f:
            f.write(data)
            tmp_path = f.name

        # 列出归档成员，找主程序（优先指定名，其次取最大的 .exe）
        members = []
        if unrar:
            try:
                lst = subprocess.run([unrar, 'lb', tmp_path], capture_output=True,
                                     text=True, timeout=60)
                members = [m.strip() for m in lst.stdout.split('\n') if m.strip()]
            except Exception as e:
                print(f"  RAR列出失败: {e}")
                return ''
        else:
            try:
                lst = subprocess.run([lsar, '-l', tmp_path], capture_output=True,
                                     text=True, timeout=60)
                for line in lst.stdout.split('\n'):
                    parts = line.split()
                    if parts:
                        members.append(parts[-1])
            except Exception as e:
                print(f"  RAR列出失败(lsar): {e}")
                return ''

        targets = []
        for want in (member_names or []):
            for m in members:
                if m.lower() == want.lower() or m.lower().endswith('/' + want.lower()):
                    targets.append(m)
                    break
        if not targets:
            exes = [m for m in members if m.lower().endswith('.exe')
                    and not m.lower().endswith('setup.exe')]
            if exes:
                targets = exes[:1]

        for target in targets:
            tmpdir = tempfile.mkdtemp()
            try:
                if unrar:
                    subprocess.run([unrar, 'x', '-inul', '-y', tmp_path, target, tmpdir],
                                   capture_output=True, timeout=120)
                else:
                    # unar 只能整包解压，指定成员靠解完再在目录里找
                    subprocess.run([unar, '-quiet', '-force-overwrite',
                                    '-output-directory', tmpdir, tmp_path],
                                   capture_output=True, timeout=180)
                for root, _dirs, files in os.walk(tmpdir):
                    for fn in files:
                        if not fn.lower().endswith('.exe'):
                            continue
                        p = os.path.join(root, fn)
                        ver = _read_pe_file_version(p)
                        if ver:
                            print(f"  RAR SFX版本({fn}): {ver}")
                            return ver
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
        return ''
    except Exception as e:
        print(f"  RAR SFX版本解析失败: {e}")
        return ''
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _read_pe_local_versions(path):
    """读取本地 PE 文件的版本号，返回 (file_version, product_version)。

    两个来源都取：
    1. VS_FIXEDFILEINFO 二进制结构（最可靠，dwFileVersionMS/LS）
    2. .rsrc 里的字符串表（UTF-16LE）

    为什么必须用二进制结构：PotPlayer 的 PotPlayer64.dll 里，
    字符串表写的是 "1, 7, 23160, 0"（逗号分隔），正则匹配点号必然落空；
    而它的 ProductVersion 是无意义的 1.7.0.0，只有 FileVersion 是真版本
    （1.7.23160.0，即 About 框显示的 26021(1.7.23160)）。
    """
    import struct
    try:
        with open(path, 'rb') as f:
            data = f.read()
        if len(data) < 1024 or data[:2] != b'MZ':
            return '', ''
        pe = struct.unpack_from('<I', data, 0x3C)[0]
        if pe + 24 > len(data) or data[pe:pe+4] != b'PE\x00\x00':
            return '', ''
        num_sections = struct.unpack_from('<H', data, pe + 6)[0]
        opt_header_size = struct.unpack_from('<H', data, pe + 20)[0]
        section_offset = pe + 24 + opt_header_size
        for i in range(num_sections):
            off = section_offset + i * 40
            if off + 40 > len(data):
                break
            name = data[off:off+8].rstrip(b'\x00').decode('ascii', errors='replace')
            if name != '.rsrc':
                continue
            raw_offset = struct.unpack_from('<I', data, off + 20)[0]
            raw_size = struct.unpack_from('<I', data, off + 16)[0]
            rsrc = data[raw_offset:raw_offset + min(raw_size, 4 * 1024 * 1024)]

            fv = pv = ''
            # 方法1：VS_FIXEDFILEINFO 二进制结构（签名 0xFEEF04BD）
            sig_pos = rsrc.find(struct.pack('<I', 0xFEEF04BD))
            if sig_pos >= 0:
                ver_ms = struct.unpack_from('<I', rsrc, sig_pos + 8)[0]
                ver_ls = struct.unpack_from('<I', rsrc, sig_pos + 12)[0]
                fv = f'{ver_ms >> 16}.{ver_ms & 0xFFFF}.{ver_ls >> 16}.{ver_ls & 0xFFFF}'
                prod_ms = struct.unpack_from('<I', rsrc, sig_pos + 16)[0]
                prod_ls = struct.unpack_from('<I', rsrc, sig_pos + 20)[0]
                pv = f'{prod_ms >> 16}.{prod_ms & 0xFFFF}.{prod_ls >> 16}.{prod_ls & 0xFFFF}'

            # 方法2：字符串表兜底（点号或逗号分隔都认）
            text = rsrc.decode('utf-16-le', errors='replace')
            if not pv:
                m = re.search(r'ProductVersion[\x00\s]*(\d+[.,]\d+(?:[.,]\d+){0,2})', text)
                if m:
                    pv = m.group(1).replace(',', '.')
            if not fv:
                m = re.search(r'FileVersion[\x00\s]*(\d+[.,]\d+(?:[.,]\d+){0,2})', text)
                if m:
                    fv = m.group(1).replace(',', '.')
            return fv, pv
        return '', ''
    except Exception:
        return '', ''


def _read_pe_file_version(path):
    """读取本地 PE 文件的版本号：ProductVersion 优先，其次 FileVersion。"""
    import struct
    try:
        with open(path, 'rb') as f:
            data = f.read()
        if len(data) < 1024 or data[:2] != b'MZ':
            return ''
        pe = struct.unpack_from('<I', data, 0x3C)[0]
        if pe + 24 > len(data) or data[pe:pe+4] != b'PE\x00\x00':
            return ''
        num_sections = struct.unpack_from('<H', data, pe + 6)[0]
        opt_header_size = struct.unpack_from('<H', data, pe + 20)[0]
        section_offset = pe + 24 + opt_header_size
        for i in range(num_sections):
            off = section_offset + i * 40
            if off + 40 > len(data):
                break
            name = data[off:off+8].rstrip(b'\x00').decode('ascii', errors='replace')
            if name != '.rsrc':
                continue
            raw_offset = struct.unpack_from('<I', data, off + 20)[0]
            raw_size = struct.unpack_from('<I', data, off + 16)[0]
            rsrc = data[raw_offset:raw_offset + min(raw_size, 2 * 1024 * 1024)]
            text = rsrc.decode('utf-16-le', errors='replace')
            m = re.search(r'ProductVersion[\x00\s]*(\d+\.\d+(?:\.\d+){0,2})', text)
            if m:
                return m.group(1)
            m = re.search(r'FileVersion[\x00\s]*(\d+\.\d+(?:\.\d+){0,2})', text)
            if m:
                return m.group(1)
        return ''
    except Exception:
        return ''


def _fast_download(url, headers, max_size=8 * 1024 * 1024, chunks=16, timeout=90):
    """并发分片（Range）下载小文件，比单连接快一个数量级。

    startisback.com 单连接只有 ~15KB/s（2MB 装包要 68 秒），
    16 线程分片实测降到 ~9 秒。服务器不支持 Range 时自动回退单连接。
    内部复用 _range_download，与 PE/NSIS 探测共用同一套分片逻辑。
    """
    # 先拿总大小
    req = urllib.request.Request(url, method='HEAD', headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        if resp.status != 200:
            raise Exception(f"HTTP {resp.status}")
        total = int(resp.headers.get('Content-Length', 0) or 0)
        accept_ranges = (resp.headers.get('Accept-Ranges', '') or '').lower()

    if total <= 0 or total > max_size or 'bytes' not in accept_ranges:
        # 回退：单连接整文件下载
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()

    return _range_download(url, headers, 0, total - 1,
                           workers=chunks, timeout=timeout, min_chunk=65536)


def get_startallback_dll_version(url, referer=None):
    """从StartAllBack 7z SFX安装器中提取StartAllBackX64.dll的PE版本号。
    安装器本身PE版本是1.0.0(SFX)，实际版本在StartAllBackX64.dll中。
    """
    import struct, subprocess, tempfile, os, re

    headers = {'User-Agent': UA}
    if referer:
        headers['Referer'] = referer

    try:
        # 1. 并发分片下载整个安装器（约2MB，官网单连接很慢，分片可快10倍）
        try:
            installer_data = _fast_download(url, headers, max_size=16 * 1024 * 1024)
        except Exception as e:
            print(f"  分片下载失败({e})，回退单连接...")
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=90) as resp:
                installer_data = resp.read()
        print(f"  安装器: {len(installer_data)} bytes")

        # 2. 找7z签名
        sig = b'7z\xbc\xaf\x27\x1c'
        sig_pos = installer_data.rfind(sig)
        if sig_pos < 0:
            print("  未找到7z签名")
            return ''

        # 3. 保存为.7z文件
        sevenz_data = installer_data[sig_pos:]
        tmp7z = tempfile.NamedTemporaryFile(suffix='.7z', delete=False)
        tmp7z.write(sevenz_data)
        tmp7z.close()

        # 4. 找7z命令（优先用项目内置 tools/7zz，本地/CI 都可用）
        seven_zip = None
        for cmd in [os.path.join(BASE_DIR, 'tools', '7zz'),
                    os.path.join(BASE_DIR, 'tools', '7z'),
                    '7z', '7zz', '7za', '/usr/bin/7z', '/usr/local/bin/7z']:
            try:
                subprocess.run([cmd, '--help'], capture_output=True, timeout=5)
                seven_zip = cmd
                break
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue

        if not seven_zip:
            print("  未找到7z命令，跳过DLL版本读取")
            os.unlink(tmp7z.name)
            return ''

        # 5. 解压StartAllBackX64.dll
        tmpdir = tempfile.mkdtemp()
        try:
            subprocess.run([seven_zip, 'x', tmp7z.name, '-o' + tmpdir,
                          'StartAllBackX64.dll', '-y'],
                         capture_output=True, timeout=30)
            dll_path = os.path.join(tmpdir, 'StartAllBackX64.dll')
            if not os.path.exists(dll_path):
                print("  StartAllBackX64.dll未解压成功")
                return ''

            # 6. 读取DLL的PE版本
            with open(dll_path, 'rb') as f:
                dll_data = f.read()

            pe_offset = struct.unpack_from('<I', dll_data, 0x3C)[0]
            num_sections = struct.unpack_from('<H', dll_data, pe_offset+6)[0]
            opt_header_size = struct.unpack_from('<H', dll_data, pe_offset+20)[0]
            section_offset = pe_offset + 24 + opt_header_size

            for i in range(num_sections):
                off = section_offset + i * 40
                name = dll_data[off:off+8].rstrip(b'\x00').decode('ascii', errors='replace')
                if name == '.rsrc':
                    raw_offset = struct.unpack_from('<I', dll_data, off+20)[0]
                    raw_size = struct.unpack_from('<I', dll_data, off+16)[0]
                    rsrc = dll_data[raw_offset:raw_offset+raw_size]

                    # 方法1: 从VS_FIXEDFILEINFO二进制结构读取（最可靠）
                    # 签名 0xFEEF04BD
                    sig_bytes = struct.pack('<I', 0xFEEF04BD)
                    sig_pos = rsrc.find(sig_bytes)
                    if sig_pos >= 0:
                        # dwFileVersionMS at offset+8, dwFileVersionLS at offset+12
                        ver_ms = struct.unpack_from('<I', rsrc, sig_pos + 8)[0]
                        ver_ls = struct.unpack_from('<I', rsrc, sig_pos + 12)[0]
                        major = ver_ms >> 16
                        minor = ver_ms & 0xFFFF
                        build = ver_ls >> 16
                        private = ver_ls & 0xFFFF
                        ver = f"{major}.{minor}.{build}.{private}"
                        print(f"  StartAllBackX64.dll版本(二进制): {ver}")
                        return ver

                    # 方法2: 字符串匹配兜底
                    text = rsrc.decode('utf-16-le', errors='replace')
                    match = re.search(r'FileVersion\s*(\d+\.\d+\.\d+\.\d+)', text)
                    if match:
                        ver = match.group(1)
                        print(f"  StartAllBackX64.dll版本(字符串): {ver}")
                        return ver
                    break
        finally:
            os.unlink(tmp7z.name)
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    except Exception as e:
        print(f"  StartAllBack DLL版本解析失败: {e}")
    return ''


def detect_bwcx(product):
    """不忘初心Windows专用检测：页面按时间倒序，成对匹配"文章标题+time日期"，
    取最新的标题含"不忘初心"的文章。版本号=标题内日期，更新日期=该文章time日期，
    下载链接=该文章URL。避免最新文章不含"不忘初心"时日期错位。
    """
    default_version = product.get('version', '未知')
    default_date = product.get('date', '')
    check_url = product['check_url']

    try:
        req = urllib.request.Request(check_url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode('utf-8', errors='ignore')

        # 成对匹配: 标题链接 + 标题文字 + 该文章time日期（页面最新在前）
        # time标签在h2之后、同一文章条目内，用非贪婪跨过中间内容
        pattern = re.compile(
            r'<h2[^>]*class="entry-title"[^>]*>\s*<a href="(https://www\.wycad\.com/\d+\.html)"[^>]*>(.*?)</a>\s*</h2>.*?<time[^>]*datetime="(\d{4}-\d{2}-\d{2})',
            re.S
        )
        matches = pattern.findall(html)
        print(f"  页面文章条目: {len(matches)}")

        found = None
        for href, title, dt in matches:
            title_clean = re.sub(r'<[^>]+>', '', title).strip()
            # 只看标题含"不忘初心"的文章（含【不忘初心】/【不忘初心游戏版】等变体）
            if '不忘初心' in title_clean:
                # 提取标题内日期（如 2026.9.16 / (2026.9.16)），保持点分隔格式
                m = re.search(r'(20\d{2}[./]\d{1,2}[./]\d{1,2})', title_clean)
                ver_raw = m.group(1) if m else ''
                ver = f"v{ver_raw}" if ver_raw else default_version
                found = (href, title_clean, dt[:10], ver)
                print(f"  匹配不忘初心文章: {title_clean[:60]}...")
                break

        if not found:
            print(f"  ⚠️ 未找到标题含'不忘初心'的文章，保留旧数据: {default_version}")
            return default_version, product.get('download_url', ''), product.get('download_url', ''), 0, default_date, ''

        href, title, dt, ver = found
        # 版本号决策: 标题日期版本 + 日期取该文章time
        date = parse_date(dt) if dt else default_date
        print(f"  版本: {ver}, 日期: {date}")

        # 下载链接: 该文章URL；获取大小（网页，size=0）
        url = href
        # 尝试从文章页获取发布时间作为日期补充（time已是发布日期，足够）
        return ver, url, url, 0, date, ''
    except Exception as e:
        print(f"  ⚠️ 不忘初心探测失败: {e}")
        return default_version, product.get('download_url', ''), product.get('download_url', ''), 0, default_date, ''


def _startallback_dll_cache_key(url, size, lm):
    """DLL 版本缓存键：URL + 大小 + Last-Modified。
    官方是"同路径原地覆盖"，URL 不变，只有 size/Last-Modified 变，
    用这三个字段组合就能判断安装包是否真的换了内容。
    """
    return f"{url}|{size}|{lm}"


_sab_cache = {}
_sab_cache_lock = threading.Lock()
# 这个缓存文件**纳入 git 管理**：CI 每次都是全新环境，
# 提交后 GitHub Actions 才能复用上次的解析结果（否则每轮都要重下 2 个安装包）
SAB_CACHE_FILE = os.path.join(BASE_DIR, 'startallback_dll_cache.json')
SAB_CACHE_TTL = 7 * 24 * 3600


def _sab_cache_load():
    """载入 StartAllBack DLL 版本缓存（进程内 + 磁盘），避免每轮都下载解包 2 个安装包"""
    global _sab_cache
    with _sab_cache_lock:
        if _sab_cache:
            return _sab_cache
        try:
            with open(SAB_CACHE_FILE, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            now = time.time()
            for k, v in (raw.get('entries') or {}).items():
                if now - v.get('ts', 0) < SAB_CACHE_TTL:
                    _sab_cache[k] = v
        except Exception:
            pass
        return _sab_cache


def _sab_cache_save():
    with _sab_cache_lock:
        try:
            with open(SAB_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump({'entries': _sab_cache}, f, ensure_ascii=False)
        except Exception:
            pass


def get_startallback_dll_version_cached(url, size=0, lm='', referer=None):
    """带缓存的 StartAllBack DLL 版本读取。

    缓存命中条件：同一 URL 且 Content-Length 与 Last-Modified 都没变
    → 说明安装包内容没换，直接复用上次解析出的 DLL 版本号（省一次 2MB 下载+解包）。
    缓存只保留 SAB_CACHE_TTL 秒，且解析失败的结果不入缓存。
    """
    key = _startallback_dll_cache_key(url, size, lm)
    cache = _sab_cache_load()
    with _sab_cache_lock:
        hit = cache.get(key)
    if hit:
        print(f"  StartAllBackX64.dll版本(缓存): {hit['ver']}")
        return hit['ver']

    ver = get_startallback_dll_version(url, referer=referer)
    if ver:
        with _sab_cache_lock:
            _sab_cache[key] = {'ver': ver, 'ts': time.time()}
        _sab_cache_save()
    return ver


def detect_startallback(product):
    """StartAllBack专用检测：双地址并行轮询 + 安装包内DLL版本探测。

    StartAllBack 的版本号只存在于安装包内部的 StartAllBackX64.dll
    （安装包本身是 7z SFX，PE 版本恒为 1.0.0），所以必须下载解包才能拿到真实版本。

    官方同时在两个地址发布安装包，且**各自独立原地覆盖**（URL 不变、Last-Modified 变）：
      - CDN 固定版本路径：StartAllBack_3.9.27_setup.exe（更新较慢）
      - 官网固定文件名：  StartAllBack_setup.exe（更新较快）
    实测两者可同时存在不同 build：CDN=3.9.27.5398 / 官网=3.9.27.5412，
    只探测单一地址必然漏检。

    优化要点（把原来的 ~135 秒压到 ~20 秒）：
      1. CDN 版本路径扫描 + 官网地址 HEAD 全部**并发**执行（原为串行 90+ 次请求）
      2. DLL 版本结果按 (URL + Content-Length + Last-Modified) 缓存 3 小时；
         官方没更新时两个包都命中缓存 → 0 次下载，稳态运行只要几秒
      3. 缓存未命中的包才并发下载解包，正确性不受影响（两个地址都验证，取版本号最高者）
    """
    cdn_pattern = product.get('cdn_url_pattern', '')
    cdn_base = product.get('cdn_base_version', '3.9.25')
    main_url = product['download_url']
    referer = product.get('referer')
    max_scan = product.get('startallback_max_scan', 30)

    def parse_ts(d):
        """解析Last-Modified为时间戳用于比较"""
        if not d:
            return 0
        from email.utils import parsedate_to_datetime
        try:
            return parsedate_to_datetime(d).timestamp()
        except Exception:
            return 0

    # ---- 1. 组装全部候选 URL：官网固定地址 + CDN 版本路径（从已知版本往后扫）----
    parts = cdn_base.split('.')
    base_major, base_minor, base_build = int(parts[0]), int(parts[1]), int(parts[2])
    cdn_probe_vers = []
    for major_i, minor_i, bstart in ((base_major, base_minor, base_build),
                                     (base_major, base_minor + 1, 0),
                                     (base_major + 1, 0, 0)):
        for build in range(bstart, bstart + max_scan):
            cdn_probe_vers.append(f"{major_i}.{minor_i}.{build}")

    probe_urls = [main_url] + [cdn_pattern.format(ver=v) for v in cdn_probe_vers]

    # ---- 2. 全部并发 HEAD，一次拿回 (exists, size, last_modified) ----
    def _head(u):
        return u, check_url(u, referer=referer)

    heads = []
    with ThreadPoolExecutor(max_workers=16) as ex:
        for res in ex.map(_head, probe_urls):
            heads.append(res)

    # ---- 3. 官网地址 + CDN命中的最高版本路径，去重后作为候选安装包 ----
    candidates = []
    seen = set()
    main_info = None
    for u, (ok, size, lm) in heads:
        if u == main_url:
            main_info = (ok, size, lm)
    if main_info and main_info[0]:
        candidates.append((main_url, main_info[1], main_info[2]))
        seen.add(main_url)

    cdn_hits = [(u, s, lm) for u, (ok, s, lm) in heads
                if ok and u != main_url and u not in seen]
    # CDN 侧取版本号最高的那个路径（版本号来自 URL，字典序不可靠，用数字比较）
    def _url_ver_key(u):
        m = re.search(r'StartAllBack_(\d+)\.(\d+)\.(\d+)_setup', u)
        return [int(m.group(i)) for i in (1, 2, 3)] if m else [0, 0, 0]

    if cdn_hits:
        cdn_hits.sort(key=lambda r: _url_ver_key(r[0]), reverse=True)
        cdn_best = cdn_hits[0]
        candidates.append(cdn_best)
        print(f"  CDN 最高版本路径: {cdn_best[0].split('/')[-1]} ({cdn_best[1]/1024/1024:.1f}MB, {cdn_best[2]})")
    if main_info and main_info[0]:
        print(f"  官网地址: {main_info[1]/1024/1024:.1f}MB, {main_info[2]}")

    if not candidates:
        return (product.get('version', ''), main_url, main_url, 0,
                product.get('date', ''), '')

    # ---- 4. 读 DLL 版本：命中缓存的直接用，未命中的并发下载解包 ----
    #      稳态运行（官方没更新）两个包都命中缓存 → 0 次下载；
    #      官方更新了只有新包未命中 → 只下载变化的包。
    candidates.sort(key=lambda c: parse_ts(c[2]), reverse=True)

    def _read(c):
        url, size, lm = c
        return url, size, lm, get_startallback_dll_version_cached(url, size, lm, referer=referer)

    dll_results = []
    with ThreadPoolExecutor(max_workers=max(1, min(4, len(candidates)))) as ex:
        for res in ex.map(_read, candidates):
            dll_results.append(res)

    def ver_key(v):
        nums = re.findall(r'\d+', str(v))
        return [int(n) for n in nums] if nums else [0]

    valid = [r for r in dll_results if r[3]]
    valid.sort(key=lambda r: ver_key(r[3]), reverse=True)

    if valid:
        best_url, best_size, best_date, version = valid[0]
        if len(valid) > 1:
            others = ', '.join(f"{r[3]}@{r[0].split('/')[-1]}" for r in valid[1:])
            print(f"  其他候选版本: {others}")
        print(f"  ✓ 采用版本 {version} ({best_url.split('/')[-1]})")
    else:
        # 全部解析失败：退回按 Last-Modified 最新的地址，保留原版本号
        best_url, best_size, best_date, _ = max(
            dll_results, key=lambda r: parse_ts(r[2]))
        version = product.get('version', '')
        print(f"  ⚠️ DLL版本全部解析失败，保留版本 {version}")

    # 5. 日期：优先用所选地址的 Last-Modified
    date_str = ''
    if best_date:
        from datetime import timedelta
        from email.utils import parsedate_to_datetime
        try:
            dt = parsedate_to_datetime(best_date) + timedelta(hours=8)
            date_str = dt.strftime('%Y-%m-%d')
        except Exception:
            date_str = ''

    return version, best_url, best_url, best_size, date_str, ''


def detect_189pan(product):
    """天翼云盘分享链接自动探测。
    API: https://api.cloud.189.cn/open/share/getShareInfoByCode.action?shareCode=xxx
    返回XML中的fileLastOpTime为最新更新日期，无需签名。
    """
    import re
    share_url = product.get('download_url', '')
    share_code = ''
    m = re.search(r'code=([a-zA-Z0-9]+)', share_url)
    if m:
        share_code = m.group(1)
    if not share_code:
        return product.get('version', ''), 0, '', ''
    
    api_url = f"https://api.cloud.189.cn/open/share/getShareInfoByCode.action?shareCode={share_code}"
    try:
        req = urllib.request.Request(api_url, headers={
            'User-Agent': UA,
            'Referer': 'https://cloud.189.cn/',
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode('utf-8', errors='ignore')
        
        # 解析XML
        file_name = ''
        last_op_time = ''
        m = re.search(r'<fileName>([^<]+)</fileName>', body)
        if m:
            file_name = m.group(1)
        m = re.search(r'<fileLastOpTime>([^<]+)</fileLastOpTime>', body)
        if m:
            last_op_time = m.group(1)
        
        # 转换日期格式: 2026-09-12 16:33:32 -> 2026-09-12
        date_str = ''
        if last_op_time:
            date_str = last_op_time.split(' ')[0]
        
        version = product.get('version', 'Win10/11')
        size = product.get('size', 0)
        print(f"  天翼云盘: {file_name}, 最后更新: {date_str}")
        return version, share_url, '', size, date_str, ''
    except Exception as e:
        print(f"  天翼云盘探测失败: {e}")
        return product.get('version', ''), share_url, '', 0, '', ''


_md5_cache = {}
_md5_cache_lock = threading.Lock()
# MD5 缓存纳入 git：CI 每次全新环境，提交后 GitHub Actions 才能复用上次的哈希，
# 避免每轮都把几十 MB 的安装包重下重算一遍
MD5_CACHE_FILE = os.path.join(BASE_DIR, 'md5_cache.json')
MD5_CACHE_TTL = 30 * 24 * 3600


def _md5_cache_load():
    global _md5_cache
    with _md5_cache_lock:
        if _md5_cache:
            return _md5_cache
        try:
            with open(MD5_CACHE_FILE, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            now = time.time()
            for k, v in (raw.get('entries') or {}).items():
                if now - v.get('ts', 0) < MD5_CACHE_TTL:
                    _md5_cache[k] = v
        except Exception:
            pass
        return _md5_cache


def _md5_cache_save():
    with _md5_cache_lock:
        try:
            with open(MD5_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump({'entries': _md5_cache}, f, ensure_ascii=False)
        except Exception:
            pass


def _parallel_md5(url, headers, size, workers=8, chunk=4 * 1024 * 1024, timeout=120):
    """对支持 Range 的服务器分段并发下载并计算 MD5。

    MD5 必须按字节顺序计算，无法真正并行"算"，但可以并行"下载"：
    多线程分片取回内存，再按片号顺序 update。对单连接被限速的服务器提速明显。
    用滑动窗口限制在途分片数，避免一次性把整个文件读进内存。
    """
    n = (size + chunk - 1) // chunk

    def _fetch(i):
        s = i * chunk
        e = min(size - 1, s + chunk - 1)
        req = urllib.request.Request(url, headers={**headers, 'Range': f'bytes={s}-{e}'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            if resp.status != 206 and len(data) != (e - s + 1):
                raise Exception('server does not honor Range')
            return i, data

    md5 = hashlib.md5()
    expect = 0          # 下一个该被 update 的分片号
    window = max(workers, workers * 2)
    next_i = 0          # 下一个该提交下载的分片号
    done = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {}
        # 先填满窗口
        while next_i < n and len(futs) < window:
            futs[ex.submit(_fetch, next_i)] = next_i
            next_i += 1
        while futs:
            fut = next(as_completed(futs))
            i, data = fut.result()
            del futs[fut]
            done[i] = data
            # 按片号顺序消费就绪的分片，保证 MD5 输入顺序正确
            while expect in done:
                md5.update(done.pop(expect))
                expect += 1
            # 补充新分片
            while next_i < n and len(futs) < window:
                futs[ex.submit(_fetch, next_i)] = next_i
                next_i += 1
    return md5.hexdigest()


def get_file_md5(url, max_retries=2, max_size_mb=100, referer=None):
    """下载文件并计算MD5，返回md5十六进制字符串。支持重试。

    带缓存：缓存键 = URL + Content-Length。安装包不变则复用上次哈希，
    省掉"每轮重下整个安装包"的开销（这是全量检测最大的时间黑洞）。
    官方原地覆盖更新时 size/Last-Modified 通常都会变，缓存自然失效。
    超过 max_size_mb 的文件跳过（避免大文件下载过慢）。
    服务器支持 Range 时用并发分片下载（见 _parallel_md5），慢速源提速明显。
    """
    headers = {'User-Agent': UA}
    if referer:
        headers['Referer'] = referer
    # 先 HEAD 请求获取文件大小与是否支持分片
    size = 0
    accept_ranges = ''
    try:
        req = urllib.request.Request(url, headers=headers, method='HEAD')
        with urllib.request.urlopen(req, timeout=15) as resp:
            size = int(resp.headers.get('Content-Length', '0') or 0)
            accept_ranges = (resp.headers.get('Accept-Ranges', '') or '').lower()
            if size > max_size_mb * 1024 * 1024:
                print(f"  文件过大({size/1024/1024:.0f}MB > {max_size_mb}MB)，跳过MD5计算")
                return ''
    except Exception:
        pass

    cache_key = f"{url}|{size}"
    cache = _md5_cache_load()
    with _md5_cache_lock:
        hit = cache.get(cache_key)
    if hit:
        print(f"  MD5(缓存): {hit['md5']}")
        return hit['md5']

    # 支持分片且文件不太小时走并发下载
    use_parallel = size > 2 * 1024 * 1024 and 'bytes' in accept_ranges

    for attempt in range(max_retries):
        try:
            if use_parallel:
                try:
                    digest = _parallel_md5(url, headers, size)
                except Exception as e:
                    print(f"  并发分片MD5失败({e})，回退单连接...")
                    digest = _md5_single(url, headers, timeout=120)
            else:
                digest = _md5_single(url, headers, timeout=120)
            if digest:
                with _md5_cache_lock:
                    _md5_cache[cache_key] = {'md5': digest, 'ts': time.time()}
                _md5_cache_save()
                return digest
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"  MD5下载重试 ({attempt+1}/{max_retries}): {e}")
                time.sleep(2)
            else:
                print(f"  ⚠️ MD5计算失败: {e}")
    return ''


def _md5_single(url, headers, timeout=120):
    """单连接流式下载并计算 MD5（Range 不被支持或分片失败时的回退）"""
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        md5 = hashlib.md5()
        total = 0
        while True:
            chunk = resp.read(262144)
            if not chunk:
                break
            md5.update(chunk)
            total += len(chunk)
        return md5.hexdigest() if total > 0 else ''


def detect_github_release(product):
    """GitHub Releases检测模式：从GitHub API获取最新release的版本号、日期、大小
    下载链接用发布页URL（html_url），适用于多分卷ISO等场景
    配置：repo='owner/repo', tag_filter='关键词过滤tag', version_regex='从tag提取版本号'
    """
    import json
    repo = product.get('repo', '')
    tag_filter = product.get('tag_filter', '')
    version_regex = product.get('version_regex', r'(\d+\.\d+\.\d+)')
    if not repo:
        return product.get('version', '未知'), product.get('download_url', ''), '', 0, '', ''

    try:
        api_url = f'https://api.github.com/repos/{repo}/releases?per_page=30'
        headers = {'User-Agent': UA, 'Accept': 'application/vnd.github.v3+json'}
        gh_token = os.environ.get('GITHUB_TOKEN', '')
        if gh_token:
            headers['Authorization'] = f'token {gh_token}'
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            releases = json.loads(resp.read().decode('utf-8'))

        # 过滤tag并找最新的
        # include_prerelease=True时包含预发布版，默认只取稳定版
        include_pre = product.get('include_prerelease', False)
        latest_release = None
        for r in releases:
            tag = r.get('tag_name', '')
            if tag_filter and tag_filter not in tag:
                continue
            if r.get('draft', False):
                continue
            if not include_pre and r.get('prerelease', False):
                continue
            latest_release = r
            break

        if not latest_release:
            print(f"  ⚠️ 未找到匹配的release (filter={tag_filter})")
            return product.get('version', '未知'), product.get('download_url', ''), '', 0, '', ''

        tag = latest_release.get('tag_name', '')
        name = latest_release.get('name', '')
        html_url = latest_release.get('html_url', '')
        published = latest_release.get('published_at', '')

        # 从tag或name提取版本号（version_source: 'tag'默认, 'name'）
        version_source = product.get('version_source', 'tag')
        source_text = name if version_source == 'name' else tag
        version = product.get('version', '未知')
        m = re.search(version_regex, source_text)
        if m:
            version = m.group(1)
        print(f"  Release: {tag[:60]}")
        print(f"  版本: {version} (from {version_source}), 发布: {published[:10]}")

        # 计算asset大小（支持asset_filter过滤特定分卷）
        assets = latest_release.get('assets', [])
        asset_filter = product.get('asset_filter', '')
        if asset_filter:
            filtered_assets = [a for a in assets if asset_filter in a.get('name', '')]
            if filtered_assets:
                assets = filtered_assets
        total_size = sum(a.get('size', 0) for a in assets)
        print(f"  分卷: {len(assets)}个, 总大小: {total_size/1024/1024:.0f}MB")

        # 日期转换
        from datetime import datetime, timezone, timedelta
        date = ''
        if published:
            try:
                dt = datetime.fromisoformat(published.replace('Z', '+00:00'))
                dt = dt.astimezone(timezone(timedelta(hours=8)))
                date = dt.strftime('%Y-%m-%d')
            except Exception:
                date = published[:10]

        # use_commits_date: 用最新commit日期替代release发布日期
        if product.get('use_commits_date'):
            try:
                commits_url = f'https://api.github.com/repos/{repo}/commits?per_page=1'
                req_c = urllib.request.Request(commits_url, headers=headers)
                with urllib.request.urlopen(req_c, timeout=15) as resp_c:
                    commits = json.loads(resp_c.read().decode('utf-8'))
                if commits:
                    commit_date = commits[0]['commit']['committer']['date']
                    dt_c = datetime.fromisoformat(commit_date.replace('Z', '+00:00'))
                    dt_c = dt_c.astimezone(timezone(timedelta(hours=8)))
                    date = dt_c.strftime('%Y-%m-%d')
                    print(f"  Commit日期: {date} (SHA: {commits[0]['sha'][:8]})")
            except Exception as e:
                print(f"  ⚠️ 获取commit日期失败，使用release日期: {e}")

        # use_asset_url: 返回直接下载链接而非releases页面URL
        if product.get('use_asset_url'):
            # 优先从assets取
            if assets:
                asset_url = assets[0].get('browser_download_url', html_url)
                print(f"  Asset下载: {asset_url[:80]}")
                return version, asset_url, asset_url, total_size, date, ''
            # assets为空时从release body提取.exe/.msi链接
            body = latest_release.get('body', '') or ''
            dl_pattern = product.get('body_dl_regex', r'(https?://[^\s\)\]]+\.(?:exe|msi))')
            dl_match = re.search(dl_pattern, body, re.I)
            if dl_match:
                asset_url = dl_match.group(1)
                print(f"  Body下载: {asset_url[:80]}")
                return version, asset_url, asset_url, total_size, date, ''
            print(f"  ⚠️ 未找到asset或body下载链接")
        return version, html_url, html_url, total_size, date, ''

    except Exception as e:
        print(f"  ⚠️ GitHub API失败: {e}")
        # API失败时保留配置的默认值（版本、下载地址、大小、日期）
        return (product.get('version', '未知'),
                product.get('download_url', ''),
                product.get('download_url', ''),
                product.get('size', 0),
                product.get('date', ''), '')


def detect_gitlab_release(product):
    """GitLab Releases检测模式：从GitLab API取最新release的版本号、发布日期、体积。
    版本/日期取自 release（tag_name / released_at）；体积取 description 里
    /uploads/<secret>/<file> 形式的主安装包，用 API uploads 端点 HEAD Content-Length。
    下载链接默认用发布页 URL（多文件发布页场景）。
    配置：gitlab_project='owner/repo', asset_filter='主包含关键词', version_regex
    """
    import json
    import urllib.parse
    project = product.get('gitlab_project', '')
    version_regex = product.get('version_regex', r'(\d+\.\d+\.\d+)')
    page = product.get('download_url', '') or f'https://gitlab.com/{project}/-/releases/'

    def _fallback():
        return (product.get('version', '未知'), page, page,
                product.get('size', 0), product.get('date', ''), '')

    if not project:
        return _fallback()

    enc = urllib.parse.quote(project, safe='')
    try:
        api_url = f'https://gitlab.com/api/v4/projects/{enc}/releases?per_page=10'
        req = urllib.request.Request(api_url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            releases = json.loads(resp.read().decode('utf-8'))
        if not releases:
            print("  ⚠️ GitLab 无 release")
            return _fallback()

        rel = releases[0]
        tag = rel.get('tag_name', '')
        released = rel.get('released_at', '') or rel.get('created_at', '')
        description = rel.get('description', '') or ''

        version = product.get('version', '未知')
        m = re.search(version_regex, tag or '')
        if m:
            version = m.group(1)
        print(f"  Release: {tag}, 发布: {released[:10]}, 版本: {version}")

        # 发布日期转北京时间
        date = ''
        if released:
            try:
                dt = datetime.fromisoformat(released.replace('Z', '+00:00'))
                dt = dt.astimezone(timezone(timedelta(hours=8)))
                date = dt.strftime('%Y-%m-%d')
            except Exception:
                date = released[:10]

        # assets.links 通常为空，安装包以 /uploads/<32位secret>/<文件名> 写在 description；
        # 只取 asset_filter 命中的主安装包（避免多文件体积相加）
        asset_filter = product.get('asset_filter', '')
        size = product.get('size', 0)
        target = None
        for secret, fname in re.findall(r'/uploads/([0-9a-f]{32})/([^\s)"\]]+)', description):
            if not asset_filter or asset_filter.lower() in fname.lower():
                target = (secret, fname)
                break
        if target:
            secret, fname = target
            head_url = f'https://gitlab.com/api/v4/projects/{enc}/uploads/{secret}/{urllib.parse.quote(fname)}'
            try:
                hreq = urllib.request.Request(head_url, method='HEAD', headers={'User-Agent': UA})
                with urllib.request.urlopen(hreq, timeout=30) as hresp:
                    cl = hresp.headers.get('Content-Length', '')
                    if cl and cl.isdigit() and int(cl) > 0:
                        size = int(cl)
                        print(f"  主安装包: {fname}  {size/1024/1024:.1f}MB")
            except Exception as e:
                print(f"  ⚠️ 主安装包体积获取失败: {e}")

        return version, page, page, size, date, ''

    except Exception as e:
        print(f"  ⚠️ GitLab API失败: {e}")
        return _fallback()


def _ver_tuple(v):
    """把版本号转成可比较的元组，缺失段补0，非数字段忽略。
    例：'12.11.9.9' -> (12, 11, 9, 9)；'9.35' -> (9, 35, 0)
    日期型版本（资源站用，如 '2026-10-06'）按 YYYYMMDD 折成单个整数，
    否则按 '.' 切分只会取到年份，月/日丢失导致不同日期被判定相等。
    """
    s = str(v).strip()
    m = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return (y * 10000 + mo * 100 + d, 0, 0, 0)
    parts = []
    for p in s.split('.'):
        m = re.match(r'^(\d+)', p)
        parts.append(int(m.group(1)) if m else 0)
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])


def _ver_newer(a, b):
    """a 是否比 b 新（按段比较、缺失段补 0，支持日期型版本）。

    例：'16.9.0.5523' > '16.8.0.4914' → True；'1.10' > '1.9' → True；
        '25.1.13' vs '25.1.13.1636' → False（短者按 0 补到 4 段再比）。
    相等或无法比较时返回 False：调用方只在"确认更新"时才覆盖现有版本，
    避免把版本号误降级。
    """
    return _ver_tuple(a) > _ver_tuple(b)


def prefer_scraped_hint(product):
    """是否优先采用抓取到的版本号（含 winget 融合结果）"""
    return bool(product.get('prefer_scraped_version', False)
                or product.get('use_newer_scraped', False))


_winget_db_lock = threading.Lock()
_winget_db_path = ''
_winget_db_time = 0.0


def _winget_index_db(timeout=40):
    """下载并解压 winget 官方索引，返回 index.db 本地路径（进程内只做一次）。

    source2.msix 约 3~4MB，多个产品共用同一份索引，
    用模块级变量缓存，避免每个 winget_id 都重复下载+解压。
    缓存有效期 WINGET_CACHE_TTL 秒（官方每天更新，1 小时足够）。
    """
    global _winget_db_path, _winget_db_time
    with _winget_db_lock:
        if _winget_db_path and os.path.exists(_winget_db_path) and \
                (time.time() - _winget_db_time) < WINGET_CACHE_TTL:
            return _winget_db_path

        import tempfile, zipfile, shutil
        src_url = 'https://cdn.winget.microsoft.com/cache/source2.msix'
        tmpdir = tempfile.mkdtemp(prefix='winget_idx_')
        try:
            local_msix = os.path.join(tmpdir, 'source2.msix')
            req = urllib.request.Request(src_url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                with open(local_msix, 'wb') as f:
                    f.write(resp.read())
            db_path = os.path.join(tmpdir, 'index.db')
            with zipfile.ZipFile(local_msix) as zf:
                with zf.open('Public/index.db') as src, open(db_path, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
            _winget_db_path = db_path
            _winget_db_time = time.time()
            print(f"  winget 索引已缓存 ({os.path.getsize(db_path)/1024/1024:.1f}MB db)")
            return _winget_db_path
        except Exception as e:
            print(f"  ⚠️ winget 索引下载失败: {e}")
            shutil.rmtree(tmpdir, ignore_errors=True)
            return ''


def fetch_winget_version(winget_id, timeout=25):
    """从 winget 官方索引（source2.msix 的 index.db）查询指定包的最新版本。

    winget 索引是 SQLite 格式，内嵌在 MSIX 包内，官方每天更新。
    优点：不依赖软件官网（可绕过 Cloudflare 等反爬），作为第三方独立探测源。
    缺点：版本更新比官网略滞后（实测 GoodSync 官网 12.11.9 / winget 12.11.8.8）。
    仅支持 3 段以上版本号（纯数字 x.y 或 x.y.z），不适合 build 号型版本。
    """
    import sqlite3
    db_path = _winget_index_db(timeout=max(timeout, 40))
    if not db_path:
        return ''
    for attempt in range(2):
        try:
            conn = sqlite3.connect(db_path, timeout=10)
            try:
                row = conn.execute(
                    "SELECT latest_version FROM packages WHERE id = ?", (winget_id,)
                ).fetchone()
            finally:
                conn.close()
            if row and row[0]:
                return row[0]
            return ''
        except Exception as e:
            # index.db 被并发写锁/占用时重试一次
            if attempt == 0:
                time.sleep(1.5)
                continue
            print(f"  ⚠️ winget 索引查询失败({winget_id}): {e}")
            return ''


def detect_scrape(product):
    """抓取模式：从官网页面抓取版本号、发布日期、下载链接
    支持两步抓取：列表页提取详情页URL → 详情页抓发布日期
    下载地址为网页时不计算MD5；为文件时计算MD5
    版本号优先使用配置默认值，官网抓取仅作参考
    """
    default_version = product.get('version', '未知')
    scraped_version = None
    scraped_date = None
    scraped_download_url = None
    scraped_size = 0

    # 从官网抓取版本号、发布日期、下载链接
    try:
        req = urllib.request.Request(product['check_url'], headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode('utf-8', errors='ignore')

        # 两步抓取：如果配置了 detail_url_regex，从列表页提取详情页URL并访问
        detail_url_regex = product.get('detail_url_regex')
        if detail_url_regex:
            matches = re.findall(detail_url_regex, html, re.I)
            # 取第N个匹配（detail_url_index，默认1即第二个，跳过置顶帖）
            idx = product.get('detail_url_index', 1)
            if len(matches) > idx:
                detail_url = matches[idx]
                print(f"  详情页: {detail_url[:80]}...")
                try:
                    req2 = urllib.request.Request(detail_url, headers={'User-Agent': UA})
                    with urllib.request.urlopen(req2, timeout=20) as resp2:
                        html = resp2.read().decode('utf-8', errors='ignore')
                except Exception as e:
                    print(f"  ⚠️ 详情页访问失败: {e}")
            elif matches:
                detail_url = matches[0]
                print(f"  详情页(第1个): {detail_url[:80]}...")
                try:
                    req2 = urllib.request.Request(detail_url, headers={'User-Agent': UA})
                    with urllib.request.urlopen(req2, timeout=20) as resp2:
                        html = resp2.read().decode('utf-8', errors='ignore')
                except Exception as e:
                    print(f"  ⚠️ 详情页访问失败: {e}")

        # 抓取版本号（支持多捕获组，用.连接）
        regex = product.get('version_regex')
        if regex:
            m = re.search(regex, html, re.I)
            # 取最后一个匹配（归档列表页：最新版本排在最后，如 BitComet 归档页）
            if product.get('version_regex_take') == 'last':
                all_m = list(re.finditer(regex, html, re.I))
                if all_m:
                    m = all_m[-1]
            if m:
                groups = [g for g in m.groups() if g]
                if len(groups) > 1:
                    if 'Build' in regex or 'build' in regex:
                        scraped_version = f"{groups[0]}.0.{groups[1]}"
                    else:
                        scraped_version = '.'.join(groups)
                else:
                    scraped_version = groups[0]
                print(f"  官网版本: {scraped_version} (参考)")

        # 抓取发布日期
        date_regex = product.get('date_regex')
        if date_regex:
            m = re.search(date_regex, html, re.I)
            if m:
                if product.get('date_regex_take') == 'last':
                    all_d = list(re.finditer(date_regex, html, re.I))
                    if all_d:
                        m = all_d[-1]
                scraped_date = parse_date(m.group(1))
                print(f"  发布日期: {scraped_date}")

        # 抓取文件大小（归档页记录里带体积，官方包未上架时兜底用）
        size_regex = product.get('size_regex')
        mb_regex = product.get('size_regex_mb')
        if size_regex:
            m = re.search(size_regex, html, re.I)
            if m:
                if product.get('size_regex_take') == 'last':
                    all_s = list(re.finditer(size_regex, html, re.I))
                    if all_s:
                        m = all_s[-1]
                try:
                    scraped_size = int(m.group(1))
                    print(f"  页面文件大小: {scraped_size} 字节")
                except (ValueError, IndexError):
                    pass
        # 带单位的体积（如 "WinSnap_6.3.5-setup.exe (3 MB)"）：
        # 单独用 size_regex_mb 抓「数字 + 单位」，换算成字节
        if mb_regex and not scraped_size:
            m2 = re.search(mb_regex, html, re.I)
            if m2:
                try:
                    _num = float(m2.group(1))
                    _unit = (m2.group(2) or 'MB').upper()
                    _mult = {'KB': 1024, 'MB': 1024 * 1024, 'GB': 1024 ** 3}.get(_unit, 1024 * 1024)
                    scraped_size = int(_num * _mult)
                    print(f"  页面文件大小: {_num} {_unit} = {scraped_size} 字节")
                except (ValueError, IndexError):
                    pass

        # 抓取下载链接
        dl_regex = product.get('download_url_regex')
        if dl_regex:
            m = re.search(dl_regex, html, re.I)
            if m:
                scraped_download_url = m.group(1)
                # 解码HTML实体
                scraped_download_url = scraped_download_url.replace('&amp;', '&')
                # 相对URL转换为完整URL
                if scraped_download_url.startswith('forum.php') or scraped_download_url.startswith('/'):
                    from urllib.parse import urljoin
                    scraped_download_url = urljoin(product['check_url'], scraped_download_url)
                print(f"  抓取下载链接: {scraped_download_url[:80]}...")
                wrapper = product.get('download_url_wrapper')
                if wrapper:
                    from urllib.parse import urlparse
                    parsed = urlparse(scraped_download_url)
                    scraped_download_url = wrapper.format(path=parsed.path, url=scraped_download_url)
                    print(f"  包装下载链接: {scraped_download_url[:80]}...")
    except Exception as e:
        print(f"  ⚠️ 官网抓取失败: {e}")

    # 第二探测源：winget 官方索引（不依赖官网，可绕过 Cloudflare 反爬）
    # 与官网版本对比取更大值（winget 更新略滞后，官网为新时以官网为准）
    winget_id = product.get('winget_id')
    if winget_id and (not scraped_version or prefer_scraped_hint(product)):
        wg_ver = fetch_winget_version(winget_id)
        if wg_ver:
            print(f"  winget 版本: {wg_ver}")
            if scraped_version:
                if _ver_tuple(wg_ver) > _ver_tuple(scraped_version):
                    print(f"  ℹ️ winget 更新: {wg_ver} > 官网 {scraped_version}")
                    scraped_version = wg_ver
                # 官网只给3段、winget给4段且前缀一致时，用winget补全末段build号
                # （如官网 12.11.9 + winget 12.11.9.9 -> 12.11.9.9）
                elif (len(wg_ver.split('.')) > len(scraped_version.split('.'))
                      and wg_ver.startswith(scraped_version + '.')):
                    print(f"  ℹ️ winget 补全末段: {scraped_version} -> {wg_ver}")
                    scraped_version = wg_ver
            else:
                scraped_version = wg_ver

    # 版本号决策：默认优先使用配置的默认版本号，配置prefer_scraped_version时优先使用抓取版本
    prefer_scraped = product.get('prefer_scraped_version', False)
    use_newer = product.get('use_newer_scraped', False)
    # 末段 build 后缀：官网只给三段版本、末段 build 号只在软件 About 框里时
    # （HyperSnap: 官网 10.4.4 + build 4 = 10.4.4.4），
    # 用配置的后缀补全末段。官网版本升级时自动跟着变，只需偶尔更新后缀。
    build_suffix = product.get('version_build_suffix')
    if build_suffix and scraped_version and '.' in scraped_version:
        segs = scraped_version.split('.')
        # 只在三段版本时补末段（'10.4.4' → '10.4.4.4'）；
        # 注意不能用 endswith 判断：'10.4.4' 本身就以 '.4' 结尾，会误判成已补全。
        if len(segs) == 3:
            full_ver = f"{scraped_version}.{build_suffix}"
            print(f"  ℹ️ 补全末段build号: {scraped_version} -> {full_ver}")
            scraped_version = full_ver
    if prefer_scraped and scraped_version:
        version = scraped_version
        if default_version and default_version != scraped_version:
            print(f"  ℹ️ 使用官网抓取版本: {scraped_version} (配置版本: {default_version})")
    elif use_newer and scraped_version and default_version and scraped_version > default_version:
        version = scraped_version
        print(f"  ℹ️ 官网版本更新: {scraped_version} > {default_version}")
    elif default_version and default_version != '未知':
        version = default_version
        if scraped_version and scraped_version not in default_version:
            print(f"  ⚠️ 官网版本({scraped_version})与配置版本({default_version})不一致，以配置为准")
    elif scraped_version:
        version = scraped_version
    else:
        version = default_version

    # 下载链接：优先使用抓取到的，其次用配置的
    # 如果配置了url_pattern，根据版本号动态构造URL（如AIDA64）
    # {ver_us}：版本号点换下划线（如 9.9.3 -> 9_9_3），应对文件名用下划线、目录用点号的情况
    # {major}/{major_minor}/{major_minor_underscore}：取版本前1/2段（如 103.0.0 -> major=103, major_minor=103.0），
    # 应对下载路径只用大版本、而展示版本更完整（如 MKVToolNix releases/103.0/ 目录）
    if product.get('url_pattern'):
        _vp = version.split('.')
        url = product['url_pattern'].format(
            ver=_url_ver(version, product), ver_dot=version.replace('.', ''),
            ver_us=version.replace('.', '_'),
            major=_vp[0], major_minor='.'.join(_vp[:2]),
            major_minor_underscore='_'.join(_vp[:2]))
        print(f"  动态构造URL: {url}")
    else:
        url = scraped_download_url or product['download_url']

    # 获取文件信息（仅当下载地址是文件时）
    is_webpage = product.get('is_webpage', False) or url.endswith('.html') or url.endswith('/') or 'download.html' in url or 'update-history' in url or 'pages.dev' in url or 'forum.php' in url or 'viewthread' in url
    size = product.get('size', 0)
    date = ''
    md5 = ''

    if is_webpage:
        date = scraped_date or ''
        if not product.get('size'):
            size = 0
        print(f"  下载地址为网页，大小{'使用配置值' if product.get('size') else '不适用'}")
    else:
        # ⚠️ 必须传 referer：NVIDIA 下载服务器（us.download.nvidia.com → .cn 镜像）
        #    没有 Referer 头时对 HEAD 返回 403 → 拿不到体积 → 整轮判「无体积」→ 保留旧版本。
        exists, detected_size, detected_date = check_url_follow(
            url, referer=product.get('referer'))
        # 页面记录的真实体积优先于探测值：
        # 有些 CDN（如 ntwind.com 的 Cloudflare）不返回 Content-Length，
        # check_url_follow 会流式读 64KB 当体积估算（3.7MB 的包估成 0.1MB），
        # 这种估算值不能写进 data.json，页面写的体积才准。
        if scraped_size > 0:
            size = scraped_size
            if detected_size and detected_size != scraped_size:
                print(f"  ℹ️ 使用页面记录体积: {scraped_size} 字节 ({scraped_size/1024/1024:.1f}MB)")
        elif detected_size > 0:
            size = detected_size
        # prefer_config_date: 日期以人工核实的发布日期为准，不被 CDN Last-Modified 覆盖
        # （HyperSnap 的 Last-Modified 是 10.17 签名/上传日，真实发布日是 10.19）
        if detected_date and not product.get('prefer_config_date'):
            date = detected_date
        elif product.get('prefer_config_date') and product.get('date'):
            date = product['date']
            print(f"  发布日期(人工核实): {date}")
        if not date and scraped_date:
            date = scraped_date
        # 官方包还没上架（302 → not_available）时，用页面记录的大小兜底，
        # 并跳过「递减版本」回退（回退只会拿到更旧且同样下架的包）
        if not exists and scraped_size > 0:
            size = scraped_size
            print(f"  ℹ️ 下载暂不可用，用页面记录大小兜底: {size} 字节")
        elif not exists and size == 0:
            print(f"  ⚠️ 下载地址不可用，尝试递减版本...")
            # 尝试递减版本号（补丁版可能没有完整离线包）
            base_ver = version
            for attempt in range(5):
                parts = base_ver.split('.')
                if len(parts) >= 2:
                    parts[-1] = str(int(parts[-1]) - 1)
                    base_ver = '.'.join(parts)
                    if product.get('url_pattern'):
                        _fbp = base_ver.split('.')
                        fallback_url = product['url_pattern'].format(
                            ver=_url_ver(base_ver, product), ver_dot=base_ver.replace('.', ''),
                            ver_us=base_ver.replace('.', '_'),
                            major=_fbp[0], major_minor='.'.join(_fbp[:2]),
                            major_minor_underscore='_'.join(_fbp[:2]))
                    else:
                        break
                    f_exists, f_size, f_date = check_url_follow(fallback_url)
                    if f_exists:
                        print(f"  ✅ 回退到 v{base_ver}: {fallback_url}")
                        version = base_ver
                        url = fallback_url
                        exists, size, date = f_exists, f_size, f_date
                        break
                    time.sleep(0.3)
            if not exists:
                print(f"  ⚠️ 所有版本均不可用")
        if exists:
            # MD5计算：小于100MB且未配置skip_md5才计算
            if not product.get('skip_md5') and size > 0 and size < 100 * 1024 * 1024:
                md5 = get_file_md5(url)
                if md5:
                    print(f"  MD5: {md5}")
            else:
                print(f"  跳过MD5计算 (skip_md5={product.get('skip_md5', False)}, size={size/1024/1024:.0f}MB)")

    # scrape日期优先于HEAD日期（官方发布日期比文件上传时间更准确）
    # 但 prefer_config_date 时以人工核实的发布日期为准（页面日期也可能滞后，
    # 如 HyperSnap：changelog 写 10.04，实际发布日 10.19）
    if product.get('prefer_config_date') and product.get('date'):
        if date != product['date']:
            print(f"  ℹ️ 发布日期(人工核实): {product['date']}")
        date = product['date']
    elif scraped_date:
        date = scraped_date
    elif not date and product.get('date'):
        date = product['date']

    # PE版本探测：当下载地址是 exe 文件且配置了 pe_version 时
    # 配置 alt_download_urls（如「完整包 + 便携包」多个安装包变体）时，逐个读安装包内
    # 真实 PE 版本，取最新者作为下载链接与版本号——因为官方页面/winget 可能滞后于安装包，
    # 而完整包与便携包各自更新节奏不同，只认一个容易停在旧版。
    # 注意：日期不从这里取，始终用官网发布日 / HTTP Last-Modified（见上方 date 处理）。
    if not is_webpage and product.get('pe_version') and url.lower().endswith('.exe'):
        alt_urls = [u for u in (product.get('alt_download_urls') or []) if u and u != url]
        if alt_urls:
            print(f"  解析PE文件版本信息（{1 + len(alt_urls)} 个安装包变体）...")
            best_url, best_ver = url, version
            for cu in [url] + alt_urls:
                pe_ver = get_pe_version(cu)
                if not pe_ver:
                    continue
                print(f"  PE版本[{os.path.basename(cu)}]: {pe_ver}")
                if _ver_newer(pe_ver, best_ver):
                    best_ver, best_url = pe_ver, cu
            if best_ver != version or best_url != url:
                print(f"  ℹ️ 采用最新安装包: v{best_ver} @ {os.path.basename(best_url)}")
            version, url = best_ver, best_url
        else:
            print(f"  解析PE文件版本信息...")
            pe_ver = get_pe_version(url)
            if pe_ver:
                print(f"  PE版本: {pe_ver}")
                version = pe_ver

    return version, url, url, size, date, md5



def detect_luminar_api(product):
    """Luminar Neo专用API探测：访问http://luminarneowin.skylum.com/获取版本和离线包地址"""
    import re
    api_url = product.get('api_url', 'http://luminarneowin.skylum.com/')
    ua = product.get('api_ua', 'Other')
    
    try:
        req = urllib.request.Request(api_url, headers={'User-Agent': ua})
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
            # XML声明写utf-16但实际是utf-8
            text = body.decode('utf-8', errors='ignore')
            
            # 解析版本号
            ver_match = re.search(r'<Version>([^<]+)</Version>', text)
            version = ver_match.group(1) if ver_match else product.get('version', '')
            
            # 解析DataUrl（离线包地址）
            url_match = re.search(r'<DataUrl>([^<]+)</DataUrl>', text)
            full_url = url_match.group(1) if url_match else product.get('download_url', '')
            param_url = full_url
            
            # 探测离线包大小和日期（用curl，Range请求会导致Content-Length不准确）
            size = 0
            date = ''
            if full_url:
                size, lm = _curl_get_headers(full_url)
                if lm:
                    date = parse_date(lm)
            
            print(f"    API版本: {version}, 离线包: {full_url[:60]}...")
            return version, full_url, param_url, size, date, ''
    except Exception as e:
        print(f"    ⚠️ Luminar API错误: {e}")
        return product.get('version', ''), product.get('download_url', ''), product.get('download_url', ''), 0, '', ''


# Chrome 离线包 CDN：官方 API 返回 dl.google.com，国内访问慢。
# 换成 gvt1 的 CDN 域名，同内容同体积，节点更多跨境更快。
_GVT1_CDN = 'https://edgedl.me.gvt1.com/'


def _to_gvt1_cdn(url):
    """把 Google 官方下载地址替换为 gvt1 CDN 地址"""
    if not url:
        return url
    import re as _re
    # dl.google.com/... 或 www.google.com/dl/... → edgedl.me.gvt1.com/dl/...
    new_url = _re.sub(r'^https?://(?:dl|www)\.google\.com/', _GVT1_CDN, url)
    # 若原地址是 /dl/ 开头，确保 CDN 域名后也是 /dl/
    if new_url != url and not new_url.startswith(_GVT1_CDN + 'dl/'):
        new_url = _GVT1_CDN + 'dl/' + new_url[len(_GVT1_CDN):]
    return new_url


def detect_chrome_api(product):
    """Chrome Google Update API探测：发送XML updatecheck请求获取最新版本和离线包直链"""
    import re
    api_url = product.get('api_url', 'https://update.googleapis.com/service/update2')
    app_id = product.get('app_id', '{8A69D345-D564-463C-AFF1-A69D9E530F96}')

    xml_body = '<?xml version="1.0" encoding="UTF-8"?>' + \
        '<request protocol="3.0" version="1.3.36.155">' + \
        '<os version="10.0.19045" platform="win" sp="" arch="x64"/>' + \
        '<app appid="' + app_id + '" version="" nextversion="" lang="" brand="" client="" ap="x64-stable">' + \
        '<updatecheck target="" targetchannel=""/></app></request>'

    try:
        req = urllib.request.Request(api_url, data=xml_body.encode(), headers={'Content-Type': 'application/xml', 'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode('utf-8', errors='ignore')

        ver_match = re.search(r'<manifest version="([^"]+)"', text)
        version = ver_match.group(1) if ver_match else product.get('version', '')

        # 优先取 https 的 dl.google.com codebase，取不到再退 www.google.com
        url_match = re.search(r'<url codebase="(https://dl\.google\.com/[^"]+)"', text) or \
                    re.search(r'<url codebase="(https://www\.google\.com/[^"]+)"', text)
        pkg_match = re.search(r'name="([^"]+\.exe)"', text)
        size_match = re.search(r'required="true" size="(\d+)"', text)

        download_url = product.get('download_url', '')
        if url_match and pkg_match:
            download_url = url_match.group(1) + pkg_match.group(1)
            download_url = _to_gvt1_cdn(download_url)

        size = int(size_match.group(1)) if size_match else 0
        date = ''
        if download_url:
            _, lm = _curl_get_headers(download_url)
            if lm:
                date = parse_date(lm)

        print(f"  Chrome API: v{version}, {size/1024/1024:.0f}MB, {date}")
        return version, download_url, download_url, size, date, ''
    except Exception as e:
        print(f"  ⚠️ Chrome API错误: {e}")
        return product.get('version', ''), product.get('download_url', ''), product.get('download_url', ''), 0, '', ''


def detect_hexhub_api(product):
    """HexHub 官方版本 API 探测：取指定渠道（默认 windows-amd64-portable）的
    版本号、直链、体积、发布日期，一次请求全拿到。

    端点：https://api.hexhub.cn/client/version/latest-non-hot-detail
    必须带 Referer/Origin（否则 403）：API 做了来源校验。

    为什么用 latest-non-hot-detail 而不是 history-exact：
    HexHub 的版本分两类——完整包（hotUpdate=false）和热更新（hotUpdate=true）。
    history-exact 的最新记录是热更版（如 5.4.4），但官网并不提供对应的新完整包；
    完整包/便携版最新仍是 5.1.9（2026-06-07）。下载站展示的版本必须与用户
    实际下到的包一致，所以取 non-hot 的完整包版本。

    注意：不能配 increment——下载 URL 里带构建时间戳
    （HexHub-Client-windows-amd64-portable-5.1.9-202606072158.exe），
    每版时间戳都变，写死进 url_pattern 必然扫不到新版。
    """
    import json as _json

    api = product.get('hexhub_api') or 'https://api.hexhub.cn/client/version/latest-non-hot-detail'
    channel = product.get('hexhub_channel', 'windows-amd64-portable')
    headers = {
        'User-Agent': UA,
        'Referer': 'https://www.hexhub.cn/',
        'Origin': 'https://www.hexhub.cn',
        'Accept': 'application/json, text/plain, */*',
    }

    try:
        req = urllib.request.Request(api, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = _json.loads(resp.read().decode('utf-8', errors='ignore'))

        if payload.get('code') != 0:
            raise Exception(f"API返回异常 code={payload.get('code')} msg={payload.get('msg')}")

        ch = (payload.get('data') or {}).get(channel)
        if not ch:
            raise Exception(f"未找到渠道 {channel}")

        version = ch.get('versionName') or ''
        download_url = ch.get('downloadUrl') or ''
        size = int(ch.get('totalSize') or 0)
        # created/updated 是毫秒时间戳；created 为该完整包入库时间，
        # 与官方更新日志里的发布日期一致，比 CDN Last-Modified 更贴近"发布日"。
        ts = ch.get('created') or ch.get('updated') or 0
        date = ''
        if ts:
            import datetime
            date = datetime.datetime.fromtimestamp(ts / 1000, datetime.timezone.utc).strftime('%Y-%m-%d')

        print(f"  HexHub API版本: {version} ({channel}), {size/1024/1024:.1f}MB, {date}")
        if not version or not download_url:
            raise Exception("API 未返回版本号或下载链接")
        return version, download_url, download_url, size, date, ''
    except Exception as e:
        print(f"  ⚠️ HexHub API错误: {e}")
        return (product.get('version', ''), product.get('download_url', ''),
                product.get('download_url', ''), 0, '', '')


# Java 多子版本清单（供前端展开显示），按产品名存放：
# {'产品名': [{'version': '27.0.1', 'tag': 'GA', 'official_site': '...', 'download_url': '...'}, ...]}
_java_versions = {}


def _java_version_tag(is_lts):
    """LTS → 'LTS'，非 LTS → 'GA'（Oracle 官网的两种发布类型标记）"""
    return 'LTS' if is_lts else 'GA'


def _java_display_version(jdk_ver, raw_version):
    """把 API 的原始版本号转成前端展示用的版本号。

    API 对 JDK 8 返回 '1.8.0_511'（JVM 内部版本号写法），
    官网/用户习惯看到的是 '8.0 Update 511'，这里做一次归一化。
    其余版本号原样输出（27.0.1 / 25.0.5 / 21.0.13）。
    """
    raw = (raw_version or '').strip()
    m = re.match(r'^1\.(\d+)\.0_(\d+)$', raw)
    if m:
        return f"{m.group(1)}.0 Update {m.group(2)}"
    return raw


def detect_java_api(product):
    """Oracle 官方 Java Releases API 探测：一次请求拿全各版本线的最新版本号/LTS 标记/发布日期。

    端点：https://java.oraclecloud.com/javaReleases
    返回 {"items": [...]}，每项含：
      jdkDetails.jdkVersion        主版本号（27 / 25 / 21 / 8 …）
      jdkDetails.latestReleaseVersion  该版本线的最新版本（27.0.1 / 1.8.0_511）
      jdkDetails.isLts             是否长期支持版
      releaseDate                  发布日期（2026-10-20）
      releaseNotesUrl              该版本的发行说明页

    为什么走这个 API 而不是抓官网页面：
    - 官网页面（/java/technologies/downloads/）只列"当前主推"的几个版本，
      且版本号在 <h2>/<h3> 里混着平台后缀（8u511 / jdk-27.0.1），正则很难稳定切干净；
    - 这个 API 是官方给 java.com 下载页用的同一份数据，结构化、字段齐全，
      一次请求就能同时拿到版本号 + LTS 标记 + 发布日期 + 发行说明链接。

    注意 SSL：部分环境握手会被中断（UNEXPECTED_EOF），故用不校验证书的 context 重试。
    """
    import json as _json
    import ssl

    api = product.get('java_api') or 'https://java.oraclecloud.com/javaReleases'
    # 只保留用户关注的版本线（产品配置里给出），API 里还有 17/11/8-perf 等
    wanted = [str(x) for x in (product.get('java_lines') or [])]

    headers = {
        'User-Agent': UA,
        'Accept': 'application/json, text/plain, */*',
    }

    payload = None
    last_err = None
    for verify in (True, False):
        try:
            req = urllib.request.Request(api, headers=headers)
            if verify:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    payload = _json.loads(resp.read().decode('utf-8', errors='ignore'))
            else:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
                    payload = _json.loads(resp.read().decode('utf-8', errors='ignore'))
            break
        except Exception as e:
            last_err = e
    if payload is None:
        print(f"  ⚠️ Java API错误: {last_err}")
        # 版本用配置里的固定值兜底（主版本行不随 LTS 补丁跳动）；
        # 子版本清单由上层沿用上次数据（否则 API 抽风一次，展开列表整块消失）
        return (product.get('version', ''), product.get('download_url', ''),
                product.get('download_url', ''), 0, '', '')

    # 按版本线归类：同一版本线会有多条记录（CPU 补丁 + 功能版），
    # 取 releaseDate 最新、且 releaseType 为 CPU 的那条（正式发布版）
    by_line = {}
    for item in (payload.get('items') or []):
        jd = item.get('jdkDetails') or {}
        line = str(jd.get('jdkVersion') or '')
        if line not in wanted:
            continue
        if item.get('releaseType') != 'CPU':
            continue
        rel_date = (item.get('releaseDate') or '')[:10]
        cur = by_line.get(line)
        if cur is None or rel_date > cur['date']:
            by_line[line] = {
                'date': rel_date,
                'version': jd.get('latestReleaseVersion') or item.get('releaseVersion') or '',
                'lts': bool(jd.get('isLts')),
                'notes': item.get('releaseNotesUrl') or '',
            }

    # 站点配置：每条版本线自己的发行说明页（官网固定路径）与下载锚点
    line_cfg = product.get('java_line_cfg') or {}
    variants = []
    for line in wanted:
        info = by_line.get(line)
        if not info:
            continue
        cfg = line_cfg.get(line) or {}
        variants.append({
            'name': f"Java SE Development Kit {_java_display_version(line, info['version'])}",
            'version': _java_display_version(line, info['version']),
            'tag': _java_version_tag(info['lts']),
            'official_site': cfg.get('official_site', ''),
            'download_url': cfg.get('download_url', ''),
        })

    if not variants:
        print("  ⚠️ Java API未取到目标版本线")
        return (product.get('version', ''), product.get('download_url', ''),
                product.get('download_url', ''), 0, '', '')

    # 主版本 = 配置里优先级最高的版本线（java_lines 已按 27/25/21/8 降序排列），
    # 不能按"发布日期最新"选：否则某条 LTS 线先发补丁时，主版本会从 27.0.1
    # 跳成 25.0.6（数值变小），被防降级机制判成回滚而拦掉。
    main_line = None
    for line in wanted:
        if line in by_line:
            main_line = line
            break
    if main_line is None:
        print("  ⚠️ Java API未取到目标版本线")
        return (product.get('version', ''), product.get('download_url', ''),
                product.get('download_url', ''), 0, '', '')

    # 发布日期取所有版本线里最新的一个（任一条线发补丁都算 Java 有更新）
    main_date = max((by_line[l]['date'] for l in by_line), default='')

    main_version = by_line[main_line]['version']
    display_version = _java_display_version(main_line, main_version)
    # 主下载地址用产品配置的统一下载页（不带锚点）；
    # 各版本线自己的锚点下载链接放在 version_list 里，由前端展开后逐条展示
    main_download = product.get('download_url', '')

    _java_versions[product['name']] = variants

    print(f"  Java API版本: 主 {display_version} ({main_date}), 共 {len(variants)} 条版本线")
    for v in variants:
        print(f"    └─ {v['version']} ({v['tag']})")

    return display_version, main_download, main_download, 0, main_date, ''


def detect_edge_api(product):
    """Microsoft Edge CDP API探测：获取最新stable x64版本和官方离线包直链"""
    import json as _json
    appid = "msedge-stable-win-x64"
    ua = "Microsoft Edge Update/1.3.183.29;winhttp"
    headers = {"User-Agent": ua, "Content-Type": "application/json"}

    try:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        # Step 1: 获取最新版本
        url1 = f"https://msedge.api.cdp.microsoft.com/api/v2/contents/Browser/namespaces/Default/names/{appid}/versions/latest?action=select"
        body1 = _json.dumps({"targetingAttributes": {"IsInternalUser": True, "Updater": "MicrosoftEdgeUpdate", "UpdaterVersion": "1.3.183.29"}}).encode()
        req = urllib.request.Request(url1, data=body1, headers=headers)
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            data1 = _json.loads(resp.read().decode())
        version = data1.get("ContentId", {}).get("Version", product.get("version", ""))
        print(f"  Edge API版本: {version}")

        # Step 2: 获取下载链接
        url2 = f"https://msedge.api.cdp.microsoft.com/api/v1.1/internal/contents/Browser/namespaces/Default/names/{appid}/versions/{version}/files?action=GenerateDownloadInfo"
        req = urllib.request.Request(url2, data=b'', headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            files = _json.loads(resp.read().decode())

        # 按大小排序取最大的离线包
        files.sort(key=lambda x: x.get("SizeInBytes", 0), reverse=True)
        if not files:
            raise Exception("No files returned")
        download_url = files[0].get("Url", "")
        size = files[0].get("SizeInBytes", 0)
        # http->https
        download_url = download_url.replace("http://msedge.b", "https://msedge.sb")

        # 获取日期
        date = ""
        if download_url:
            _, lm = _curl_get_headers(download_url)
            if lm:
                date = parse_date(lm)

        print(f"  Edge离线包: {size/1024/1024:.0f}MB, {date}")
        return version, download_url, download_url, size, date, ''
    except Exception as e:
        print(f"  ⚠️ Edge API错误: {e}")
        return product.get('version', ''), product.get('download_url', ''), product.get('download_url', ''), 0, '', ''


def detect_yandex(product):
    """Yandex Disk 公开分享目录检测：获取最新修改的文件作为版本
    配置:
      public_url: Yandex网盘分享链接
      version_from: 'modified' 用文件修改日期作为版本号
    """
    try:
        public_url = product['public_url']
        api_url = f"https://cloud-api.yandex.net/v1/disk/public/resources?public_key={urllib.parse.quote(public_url)}&limit=500"
        req = urllib.request.Request(api_url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())

        items = data.get('_embedded', {}).get('items', [])
        if not items:
            print("  ⚠️ Yandex网盘无文件")
            return product.get('version', ''), public_url, public_url, 0, '', ''

        # 按修改时间排序，取最新
        items.sort(key=lambda x: x.get('modified', ''), reverse=True)
        latest = items[0]
        modified = latest.get('modified', '')[:10]
        filename = latest.get('name', '')
        print(f"  最新文件: {filename[:60]} | {modified}")

        # 版本号：用日期格式 YYYY.MM.DD
        version = modified.replace('-', '.') if modified else product.get('version', '')
        download_url = latest.get('file', public_url)
        if not download_url or download_url == public_url:
            download_url = public_url

        # 大小不写（用户要求）
        size = 0
        return version, public_url, public_url, size, modified, ''

    except Exception as e:
        print(f"  ⚠️ Yandex API失败: {e}")
        return (product.get('version', ''),
                product.get('download_url', ''),
                product.get('download_url', ''),
                product.get('size', 0),
                product.get('date', ''), '')


# 资源站（monkrus/downtopc 等）当天更新的文章清单，按产品名存放：
# {'产品名': [{'title': 标题, 'url': 文章链接}, ...]}
_site_items = {}


def _fetch_rss_entries(rss_url, max_items=100, page_size=25, max_pages=4,
                       retries=3, pause=1.5):
    """抓取 Blogger RSS 文章条目，返回 [(datetime, title, url), ...]
    单页 max-results 上限 25，故按 start-index 翻页，直到取满 max_items 或没有更多。
    Blogger 对短时间连续请求会掐断 TLS（SSL UNEXPECTED_EOF），故每页加重试与间隔。
    """
    entries = []
    seen = set()
    for page in range(max_pages):
        start = page * page_size + 1
        sep = '&' if '?' in rss_url else '?'
        page_url = f'{rss_url}{sep}max-results={page_size}&start-index={start}'

        xml = ''
        for attempt in range(retries):
            try:
                req = urllib.request.Request(page_url, headers={'User-Agent': UA})
                with urllib.request.urlopen(req, timeout=25) as resp:
                    xml = resp.read().decode('utf-8', errors='ignore')
                break
            except Exception as e:
                if attempt == retries - 1:
                    print(f"  ⚠️ monkrus RSS 第 {page + 1} 页失败: {e}")
                else:
                    time.sleep(pause * (attempt + 1))
        if not xml:
            break

        # 按 <item> 切块（Blogger RSS 的 CDATA 里嵌套尖括号，正则易踩坑）
        blocks = xml.split('<item>')[1:]
        if not blocks:
            break

        for blk in blocks:
            t = re.search(r'<title>(.*?)</title>', blk, re.S)
            d = re.search(r'<pubDate>(.*?)</pubDate>', blk, re.S)
            l = re.search(r'<link>(.*?)</link>', blk, re.S)
            title = html.unescape(t.group(1)).strip() if t else ''
            pub = d.group(1).strip() if d else ''
            link = html.unescape(l.group(1).strip()) if l else ''
            if not title or title in seen:
                continue
            seen.add(title)
            entries.append((_parse_rfc822(pub), title, link))

        if len(entries) >= max_items or len(blocks) < page_size:
            break
        if page < max_pages - 1:
            time.sleep(pause)

    return entries[:max_items]


def detect_monkrus(product):
    """monkrus 资源站检测：Blogspot RSS 取最新更新日期当天的全部软件文章
    配置:
      check_url: RSS 地址（默认 https://w18.monkrus.ws/feeds/posts/default?alt=rss）
      download_url: 固定站点地址
      max_items: 抓取的文章上限（分页累积），确保当天文章不被截断
    文章清单写入 _monkrus_items，每项为 {'title': 标题, 'url': 文章链接}，
    前端把链接填进"版本/大小"两列的空白区域（资源站无版本号和体积）。
    """
    rss_url = product.get('check_url', 'https://w18.monkrus.ws/feeds/posts/default?alt=rss')
    site_url = product.get('download_url', 'https://w18.monkrus.ws/')

    try:
        entries = _fetch_rss_entries(
            rss_url, max_items=product.get('max_items', 100))

        if not entries:
            print("  ⚠️ monkrus RSS 无文章")
            return product.get('version', ''), site_url, site_url, 0, '', ''

        # 按时间倒序；"当天"只比日期部分（datetime 带时分秒，直接比会漏掉同一天的其他文章）
        entries.sort(key=lambda x: x[0], reverse=True)
        latest_day = entries[0][0].date()

        # 只取"最新更新日期当天"的软件文章（当天全部输出，不限条数）
        todays = [e for e in entries if e[0].date() == latest_day]

        # 过滤非软件文章：求助帖/广告帖/公告类
        skip_re = re.compile(
            r'КОМПЬЮТЕРНАЯ|ПОМОЩЬ|DONATE|ALIEXPRESS|REKLAM|ADVERT|'
            r'WARNING|BLOG-POST|КУПИТЬ|ПРОДАЖ|СКАЧАТЬ\s*$',
            re.I)
        soft = [e for e in todays if not skip_re.search(e[1])]

        if not soft:
            # 当天全是非软件文章，则回退取最近一篇软件文章
            soft = [e for e in entries if not skip_re.search(e[1])][:1]
            if not soft:
                print("  ⚠️ monkrus 未找到软件文章")
                return product.get('version', ''), site_url, site_url, 0, '', ''
            latest_day = soft[0][0].date()

        items = [{'title': t, 'url': u} for _, t, u in soft]
        date_str = latest_day.strftime('%Y-%m-%d')
        version = date_str  # 版本号即更新日期

        print(f"  monkrus 更新: {date_str} 共 {len(items)} 篇")
        for it in items:
            print(f"    └─ {it['title'][:70]}")

        _site_items[product['name']] = items
        return version, site_url, site_url, 0, date_str, ''

    except Exception as e:
        print(f"  ⚠️ monkrus 错误: {e}")
        return product.get('version', ''), site_url, site_url, 0, '', ''


def _parse_rfc822(s):
    """把 RFC822 日期（Tue, 06 Oct 2026 05:09:00 +0000）解析成 datetime"""
    for fmt in ('%a, %d %b %Y %H:%M:%S %z', '%a, %d %b %Y %H:%M:%S'):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return datetime.min


def _match_key(s):
    """归一化字符串用于软件名匹配：转小写，非字母数字换成空格，压缩空格。
    例：'IObit Uninstaller' -> 'iobit uninstaller'；'7-Zip' -> '7 zip'。
    用空格保留词边界，避免 'Thunder' 误命中 'Thunderbird' 这种包含关系。"""
    s = re.sub(r'[^0-9a-z]+', ' ', str(s).lower())
    return re.sub(r'\s+', ' ', s).strip()


def _build_match_keys():
    """从 PRODUCTS 抽取「已添加软件名」的归一化匹配键。
    跳过资源站自身（monkrus/downtopc），否则站点公告帖会命中自己的站名；
    只保留去空格后长度 >= 4 的名字，避免 YY 这类过短名字大面积误命中。"""
    keys = []
    for p in PRODUCTS:
        if p.get('category') == '资源站':
            continue
        k = _match_key(p.get('name', ''))
        if len(k.replace(' ', '')) >= 4:
            keys.append(k)
    return keys


def _title_hits_product(title, keys):
    """文章标题是否包含某个软件名（按词边界整词包含）"""
    norm = ' ' + _match_key(title) + ' '
    for k in keys:
        if f' {k} ' in norm:
            return True, k
    return False, ''


_SITE_HEADERS = {
    'User-Agent': UA,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}


def _fetch_site_html(url, timeout=15, retries=2, pause=1.0, deadline=None):
    """通用资源站页面抓取（downtopc / nsane 等）。返回 HTML；失败返回 ''。

    这些站点有 Mod_Security 或 Cloudflare 等防护，需带完整浏览器头（否则 403/406/挑战页）；
    连续请求也会被掐断，故加重试与间隔。

    deadline: 本轮探测的绝对截止时间（time.time() 时间戳）。一旦到点就不再重试，
    直接放弃——避免把整个产品的预算耗在一个抽风的 URL 上。这是"站点抽风"下
    仍能快速返回并交出部分结果的关键。
    """
    last_err = ''
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=_SITE_HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode('utf-8', errors='ignore')
        except Exception as e:
            last_err = e
            if attempt == retries - 1 or (deadline is not None and time.time() >= deadline):
                break
            wait = pause * (attempt + 1)  # 指数退避：1s、2s…
            if deadline is not None:
                wait = min(wait, max(0.0, deadline - time.time()))
            if wait > 0:
                time.sleep(wait)
    print(f"  ⚠️ 页面抓取失败 {url}: {last_err}")
    return ''


def detect_downtopc(product):
    """downtopc 资源站检测：取站点「最新更新日期当天」的全部文章，
    标题命中已添加软件名的才输出（没命中的跳过）。
    配置:
      check_url:     RSS 地址（用于确定最新更新日期），默认 .../software/rss.xml
      download_url:  固定站点地址
      detect_timeout / allow_no_size: 资源站通用
    命中文章写入 _site_items[product['name']]，前端按 monkrus 样式渲染。
    """
    rss_url = product.get('check_url', 'https://downtopc.com/software/rss.xml')
    site_url = product.get('download_url', 'https://downtopc.com/software/')
    max_pages = product.get('max_pages', 6)
    deadline = time.time() + SITE_DETECT_BUDGET
    keys = _build_match_keys()

    try:
        # 1) 用 RSS 的全部 pubDate 取最新日期（RSS 只给 10 条，但按时间倒序）
        rss = _fetch_site_html(rss_url, deadline=deadline)
        cands = [_parse_rfc822(s.strip())
                 for s in re.findall(r'<pubDate>(.*?)</pubDate>', rss, re.S)]
        cands = [d for d in cands if d != datetime.min]
        if cands:
            latest = max(cands, key=lambda d: d.timestamp())
        else:
            latest = datetime.now()
        print(f"  downtopc 最新更新日期: {latest.strftime('%Y-%m-%d')}")

        # 2) 抓该日期归档页；当天没文章（如周末）则往前找，最多回退 3 天。
        #    某天归档页抓不通就跳过、继续往前找；一个都没抓通才判定为站点抽风。
        date_str = ''
        articles = None          # None = 一个归档页都没抓通
        for offset in range(4):
            if time.time() >= deadline:
                break
            day = latest - timedelta(days=offset)
            base = f"https://downtopc.com/{day.strftime('%Y/%m/%d')}/"
            got = _fetch_downtopc_articles(base, max_pages, deadline=deadline)
            if got is None:
                continue
            if articles is None:
                articles = []
            articles.extend(got)
            if got:
                date_str = day.strftime('%Y-%m-%d')
                break
        if articles is None:
            # 站点整轮无响应 → 返回空版本，交给 detect_one 沿用旧数据（不清空清单）
            print("  ⚠️ downtopc 站点无响应，本轮跳过")
            return '', site_url, site_url, 0, '', ''

        # 3) 标题匹配已添加软件名，命中才输出
        matched = []
        seen = set()
        for title, url in articles:
            if url in seen:
                continue
            seen.add(url)
            ok, key = _title_hits_product(title, keys)
            if ok:
                matched.append({'title': title, 'url': url})
                print(f"    ✓ [{key}] {title[:70]}")

        if not date_str:
            date_str = latest.strftime('%Y-%m-%d')
        # 抓通了但一篇都没命中「已添加软件」→ 不算更新（同 nsane）
        if not matched:
            print(f"  downtopc {date_str}: 当天无命中文章（共 {len(articles)} 篇），本轮不更新")
            return '', site_url, site_url, 0, '', ''

        _site_items[product['name']] = matched
        print(f"  downtopc 更新: {date_str} 共 {len(articles)} 篇，命中 {len(matched)} 篇")
        return date_str, site_url, site_url, 0, date_str, ''

    except Exception as e:
        print(f"  ⚠️ downtopc 错误: {e}")
        return '', site_url, site_url, 0, '', ''


def _fetch_downtopc_articles(base_url, max_pages=6, deadline=None):
    """抓某个日期归档 URL 下全部文章，返回 [(标题, 链接), ...]；
    第 1 页抓不通时返回 None（区别于"页面正常但当天没文章"的空列表）。
    DLE 归档页分页在 <div class="pagination">，从第 1 页即可读出总页数。"""
    articles = []
    html_text = _fetch_site_html(base_url, deadline=deadline)
    if not html_text:
        return None

    total_pages = 1
    pm = re.search(r'class="pagination"(.*?)</div>', html_text, re.S)
    if pm:
        nums = [int(n) for n in re.findall(r'/page/(\d+)/', pm.group(1))]
        if nums:
            total_pages = min(max(nums), max_pages)

    for page in range(1, total_pages + 1):
        if page > 1 and deadline is not None and time.time() >= deadline:
            break
        text = html_text if page == 1 else _fetch_site_html(f"{base_url}page/{page}/", deadline=deadline)
        if not text:
            break
        for url, raw_title in re.findall(
                r'<h3>\s*<a\s+href="(https://downtopc\.com/[^"]+)"[^>]*>(.*?)</a>\s*</h3>',
                text, re.S):
            title = html.unescape(re.sub(r'<[^>]+>', '', raw_title)).strip()
            if title:
                articles.append((title, url))
    return articles


def _nsane_today():
    """nsane 站点时间戳是 UTC（...Z），但前端和全站日期口径都是北京时间（UTC+8），
    所以「今日」必须按北京时间算。否则北京时间凌晨（≈UTC 前一天下午）发布的帖子
    会被判成「昨日」而漏检（实测 v25.0.1007 帖：UTC 10-08 18:33 = 北京 10-09 02:33）。"""
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime('%Y-%m-%d')


def _nsane_forum_topics(list_url, deadline=None):
    """抓 nsane 论坛板块列表页，返回 [(标题, 链接, 发帖日期, 最后回复日期), ...]；
    页面抓不通时返回 None（区别于"页面正常但无主题"的空列表）。
    列表页每行是 <li data-rowID='NNN' data-controller='forums.front.forum.topicRow'>，
    行内有两个 <time>：第一个是发帖时间，最后一个（stats 列）是最后回复时间。
    注意：主题正文要登录，但列表页匿名可读，标题/时间都够用。

    ⚠️ 「今天有没有软件更新」要按**发帖时间**判，不能按最后回复时间：
    老帖被回复会被顶起来（最后回复=今天），但软件并没有更新，例如 8/17 发的帖
    今天只是有人讨论。板块惯例是「一个软件更新开一个新帖」，所以发帖==今天才是真更新。"""
    html_text = _fetch_site_html(list_url, deadline=deadline)
    if not html_text:
        return None
    out = []
    parts = re.split(
        r"<li[^>]*data-rowID='\d+'[^>]*data-controller='forums\.front\.forum\.topicRow'",
        html_text)
    for body in parts[1:]:
        am = re.search(
            r"<a href='(https://nsaneforums\.com/topic/[^']+)'[^>]*title='([^']*)'", body)
        if not am:
            continue
        url = am.group(1)
        title = html.unescape(am.group(2)).strip()
        times = re.findall(r"<time datetime='([^']+)'", body)
        # <time> 里是 UTC 时间戳（...Z），先统一转成北京日期，再和「北京今日」比
        created = parse_date(times[0]) if times else ''
        last = parse_date(times[-1]) if times else ''
        if title:
            out.append((title, url, created, last))
    return out


def _nsane_frontpage_items(page_url, deadline=None):
    """抓 nsane.down 前台「FrontPage Latest Update」小部件，返回 [(标题, 链接, 日期), ...]；
    页面抓不通时返回 None。"""
    html_text = _fetch_site_html(page_url, deadline=deadline)
    if not html_text:
        return None
    out = []
    chunks = re.split(r'<h3', html_text)
    seg = next((c for c in chunks if 'FrontPage Latest Update' in c[:300]), '')
    for block in re.split(r'<li class="ipsDataItem', seg)[1:]:
        am = re.search(
            r"<a href='(https://nsaneforums\.com/topic/[^']+)'\s*>\s*([^<]+?)\s*</a>", block, re.S)
        if not am:
            continue
        url = am.group(1)
        title = html.unescape(am.group(2)).strip()
        tm = re.search(r"<time datetime='([^']+)'", block)
        # 同上：时间戳为 UTC，转成北京日期再用于「今日」判定
        day = parse_date(tm.group(1)) if tm else ''
        if title:
            out.append((title, url, day))
    return out


def detect_nsane(product):
    """nsane 论坛资源站检测：抓指定板块「今天发布的」软件更新帖，
    标题命中已添加软件名才输出（没命中的跳过）。
    数据源均匿名可读（主题正文需登录，但不需要正文）：
      nsane_forums:   论坛板块列表页 URL 列表（按「发帖时间==今天」判定今日新帖）
      nsane_frontpage: nsane.down 前台 FrontPage Latest Update 小部件 URL
    命中项写入 _site_items[product['name']]，前端按 downtopc/monkrus 样式渲染。

    ⚠️ 「今日更新」按**发帖时间**判定，不用最后回复时间：老帖被回复会被顶起
    （最后回复=今天）但软件并未更新，会造成"推了个 8/17 的老帖"这类误报。
    板块惯例是一个软件更新开一个新帖；前台 widget 的 Latest Update 也是同一个口径。

    健壮性：每个源独立抓取、失败/超时只跳过该源；命中项「边抓边匹配」即时累积，
    即使后面某个源抽风，前面已抓到的结果也不会丢。
    """
    today = _nsane_today()
    site_url = product.get('download_url', 'https://nsaneforums.com/nsane.down/')
    deadline = time.time() + SITE_DETECT_BUDGET
    keys = _build_match_keys()
    matched, seen = [], set()
    fetched_ok = False   # 是否至少有一个源抓通

    def _collect(pairs):
        """已确认「今日更新」的 (标题, 链接) 列表，匹配命中就地追加
        （便于抽风时提交部分结果）"""
        for title, url in pairs:
            if url in seen:
                continue
            seen.add(url)
            ok, key = _title_hits_product(title, keys)
            if ok:
                matched.append({'title': title, 'url': url})
                print(f"    ✓ [{key}] {title[:70]}")

    try:
        for slug, url in product.get('nsane_forums', []):
            if time.time() >= deadline:
                print(f"  nsane/{slug}: 跳过（本轮时间预算已用完）")
                break
            try:
                got = _nsane_forum_topics(url, deadline=deadline)
            except Exception as e:
                print(f"  ⚠️ nsane/{slug} 抓取异常: {e}")
                continue
            if got is None:
                continue
            fetched_ok = True
            # 只认「今天发的帖」（= 今天的软件更新）；老帖被回复顶起的不算
            today_items = [(t, u) for (t, u, created, _last) in got if created == today]
            print(f"  nsane/{slug}: 列表 {len(got)} 帖，今日新帖 {len(today_items)} 帖")
            _collect(today_items)
            time.sleep(1.0)  # 板块之间留间隔，避免被反爬掐断

        fp = product.get('nsane_frontpage')
        if fp and time.time() < deadline:
            try:
                items = _nsane_frontpage_items(fp, deadline=deadline)
            except Exception as e:
                print(f"  ⚠️ nsane/前台 抓取异常: {e}")
                items = None
            if items is not None:
                fetched_ok = True
                fp_today = [(t, u) for (t, u, day) in items if day == today]
                print(f"  nsane/前台: 条目 {len(items)}，今日 {len(fp_today)}")
                _collect(fp_today)

        if not fetched_ok:
            # 所有源都没抓通（站点抽风）→ 返回空版本，交给 detect_one 沿用旧数据
            print("  ⚠️ nsane 站点无响应，本轮跳过")
            return '', site_url, site_url, 0, '', ''

        # 抓通了，但今天没有命中「已添加软件」的新帖 → 不算更新。
        # 返回空版本交给 detect_one 沿用旧数据，避免「无任何文章也把前端日期刷成今天」。
        if not matched:
            print(f"  nsane {today}: 今日无命中文章，本轮不更新（沿用上次数据）")
            return '', site_url, site_url, 0, '', ''

        _site_items[product['name']] = matched
        print(f"  nsane 更新: {today} 候选 {len(seen)} 帖，命中 {len(matched)} 篇")
        return today, site_url, site_url, 0, today, ''

    except Exception as e:
        print(f"  ⚠️ nsane 错误: {e}")
        if matched:  # 抽风/异常时也别把已命中的部分结果丢掉
            _site_items[product['name']] = matched
        return '', site_url, site_url, 0, '', ''


def detect_discourse(product):
    """Discourse 论坛 JSON API 检测：从分类页获取最新版本帖子
    配置:
      check_url: 分类页 .json URL (如 .../c/xxx/122.json)
      version_title_pattern: 帖子标题版本正则 (如 r'Topaz Video (\\d+\\.\\d+\\.\\d+)')
      download_url_template: 下载地址模板，{version} 替换为版本号
    """
    try:
        req = urllib.request.Request(product['check_url'], headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode('utf-8'))

        topics = data.get('topic_list', {}).get('topics', [])
        title_pattern = product.get('version_title_pattern', r'(\d+\.\d+\.\d+)')

        for t in topics:
            title = t.get('title', '')
            m = re.search(title_pattern, title, re.I)
            if m:
                # 提取所有版本号，取最后一个（处理 "v1.3.5 - v1.3.6" 这种）
                all_versions = re.findall(r'(\d+\.\d+\.\d+)', title)
                version = all_versions[-1] if all_versions else m.group(1)
                created = t.get('created_at', '')
                date = parse_date(created) if created else ''
                print(f"  Discourse版本: {version} | 日期: {date}")

                # 构造下载地址
                dl_template = product.get('download_url_template', '')
                if dl_template:
                    download_url = dl_template.replace('{version}', version)
                    # 检测文件大小
                    size = 0
                    try:
                        exists, size, _ = check_url_follow(download_url)
                        if not exists:
                            size = 0
                    except Exception:
                        pass
                    print(f"  下载地址: {download_url[:80]}...")
                    return version, download_url, download_url, size, date, ''

                # 从帖子内容获取下载链接
                topic_id = t.get('id')
                if topic_id:
                    try:
                        post_url = f"https://community.topazlabs.com/t/{topic_id}.json"
                        req2 = urllib.request.Request(post_url, headers={'User-Agent': UA})
                        with urllib.request.urlopen(req2, timeout=15) as resp2:
                            post_data = json.loads(resp2.read().decode('utf-8'))
                        cooked = post_data['post_stream']['posts'][0]['cooked']
                        links = re.findall(r'href="(https://downloads\.topazlabs\.com/[^"]+\.msi[^"]*)"', cooked)
                        if links:
                            download_url = links[0].replace('&amp;', '&')
                            size = 0
                            try:
                                exists, size, _ = check_url_follow(download_url)
                                if not exists:
                                    size = 0
                            except Exception:
                                pass
                            print(f"  帖子下载地址: {download_url[:80]}...")
                            return version, download_url, download_url, size, date, ''
                    except Exception as e:
                        print(f"  ⚠️ 获取帖子内容失败: {e}")

                return version, product.get('download_url', ''), product.get('download_url', ''), 0, date, ''

        print("  ⚠️ Discourse未找到版本帖")
    except Exception as e:
        print(f"  ⚠️ Discourse API失败: {e}")

    return (product.get('version', ''),
            product.get('download_url', ''),
            product.get('download_url', ''),
            product.get('size', 0),
            product.get('date', ''), '')


# ===== Boris FX Hub 官方下载清单 API =====
# Hub 客户端启动时拉取的清单接口，一条请求同时给出「版本号 + 官方直链 + 发布日期」。
# Vegas Pro / Sound Forge / Acid Pro 的安装包文件名带构建时间戳
# （Vegas_Pro_2027.0.0.31_x64_RELEASE_261020_132721.exe），递增猜文件名永远追不上，
# 官网与论坛发布贴都不暴露直链，只有这个接口稳定且权威。
_BORISFX_HUB_API = 'https://borisfx.com/api/1/downloads'
_borisfx_hub_cache = {}
_borisfx_hub_lock = threading.Lock()


def fetch_borisfx_hub_items(api_url=None):
    """拉取并缓存 Hub 下载清单（进程内缓存 1 小时，多个 Boris FX 产品共用一次请求）"""
    url = api_url or _BORISFX_HUB_API
    with _borisfx_hub_lock:
        hit = _borisfx_hub_cache.get(url)
    if hit and (time.time() - hit[0]) < WINGET_CACHE_TTL:
        return hit[1]
    req = urllib.request.Request(url, headers={
        'User-Agent': 'BorisFXHub/2.0.9',
        'Accept': 'application/json',
        'Accept-Encoding': 'gzip',
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
    if raw[:2] == b'\x1f\x8b':
        import gzip
        raw = gzip.decompress(raw)
    items = json.loads(raw.decode('utf-8', errors='ignore'))
    with _borisfx_hub_lock:
        _borisfx_hub_cache[url] = (time.time(), items)
    return items


def detect_borisfx_hub(product):
    """Boris FX 系列专用：官方 Hub 清单 API 一次给出版本 + 直链 + 发布日期

    匹配条件：product_name（Vegas Pro / Sound Forge / Acid Pro）+ product 前缀
    （Vegas Pro 2027 与 Vegas Pro 2026 是两条版本线，用前缀区分）+ Windows 平台。
    同一产品有多条历史记录时按 display_version 取最新。
    """
    api_url = product.get('hub_api_url')
    want_name = (product.get('hub_product_name') or '').lower()
    want_prefix = (product.get('hub_product_prefix') or '').lower()
    platform = (product.get('hub_platform') or 'windows').lower()
    fallback_url = product.get('download_url', '')
    fallback_ver = product.get('version', '')

    try:
        items = fetch_borisfx_hub_items(api_url)
    except Exception as e:
        print(f"  ⚠️ Hub 清单获取失败: {e}")
        return fallback_ver, fallback_url, fallback_url, 0, product.get('date', ''), ''

    best = None
    for it in items:
        pname = str(it.get('product_name') or '').lower()
        prod = str(it.get('product') or '').lower()
        plat = str(it.get('platform') or '').lower()
        url = it.get('download_url') or ''
        if want_name and pname != want_name:
            continue
        if want_prefix and not prod.startswith(want_prefix):
            continue
        if platform and platform not in plat:
            continue
        # 只要真正的离线安装包，不要 Hub 启动器 zip / 附加内容下载器
        if not url.lower().endswith(('.exe', '.msi')):
            continue
        ver = str(it.get('display_version') or it.get('version') or '')
        if not ver:
            continue
        if best is None or _ver_newer(ver, best[0]):
            best = (ver, url, str(it.get('date') or ''))

    if not best:
        print(f"  ⚠️ Hub 清单未匹配到 {product.get('hub_product_prefix') or want_name}")
        return fallback_ver, fallback_url, fallback_url, 0, product.get('date', ''), ''

    version, full_url, api_date = best
    # 清单里的 date 是产品挂牌日，常早于实际发布（如 Vegas Pro 2027 挂牌 09-22、
    # 实际 10-21 才上传），按铁律用 HTTP Last-Modified 优先，清单日期只作兜底。
    date = ''
    size = 0
    exists, size, lm = check_url_follow(full_url)
    if exists:
        if lm:
            date = parse_date(lm)
        if not date and api_date:
            date = parse_date(api_date)
    elif api_date:
        date = parse_date(api_date)
    if not exists:
        size = 0
    print(f"  Hub 版本: {version} | {full_url[:70]}...")
    return version, full_url, full_url, size, date, ''


def find_latest(product):
    """根据检测类型分发"""
    detect_type = product.get('detect_type', 'increment')

    if detect_type == 'redirect':
        version, full_url, param_url, size, date, md5 = detect_redirect(product)
    elif detect_type == 'fixed':
        version, full_url, param_url, size, date, md5 = detect_fixed(product)
    elif detect_type == 'cyberlink':
        version, full_url, param_url, size, date, md5 = detect_cyberlink(product)
    elif detect_type == 'scrape':
        version, full_url, param_url, size, date, md5 = detect_scrape(product)
    elif detect_type == 'github_release':
        version, full_url, param_url, size, date, md5 = detect_github_release(product)
    elif detect_type == 'gitlab_release':
        version, full_url, param_url, size, date, md5 = detect_gitlab_release(product)
    elif detect_type == 'lanzou':
        version, full_url, param_url, size, date, md5 = detect_lanzou(product)
    elif detect_type == '189pan':
        version, full_url, param_url, size, date, md5 = detect_189pan(product)
    elif detect_type == 'luminar_api':
        version, full_url, param_url, size, date, md5 = detect_luminar_api(product)
    elif detect_type == 'discourse':
        version, full_url, param_url, size, date, md5 = detect_discourse(product)
    elif detect_type == 'yandex':
        version, full_url, param_url, size, date, md5 = detect_yandex(product)
    elif detect_type == 'chrome_api':
        version, full_url, param_url, size, date, md5 = detect_chrome_api(product)
    elif detect_type == 'edge_api':
        version, full_url, param_url, size, date, md5 = detect_edge_api(product)
    elif detect_type == 'hexhub_api':
        version, full_url, param_url, size, date, md5 = detect_hexhub_api(product)
    elif detect_type == 'java_api':
        version, full_url, param_url, size, date, md5 = detect_java_api(product)
    elif detect_type == 'startallback':
        version, full_url, param_url, size, date, md5 = detect_startallback(product)
    elif detect_type == 'bwcx':
        version, full_url, param_url, size, date, md5 = detect_bwcx(product)
    elif detect_type == 'monkrus':
        version, full_url, param_url, size, date, md5 = detect_monkrus(product)
    elif detect_type == 'downtopc':
        version, full_url, param_url, size, date, md5 = detect_downtopc(product)
    elif detect_type == 'nsane':
        version, full_url, param_url, size, date, md5 = detect_nsane(product)
    elif detect_type == 'borisfx_hub':
        version, full_url, param_url, size, date, md5 = detect_borisfx_hub(product)
    else:
        version, full_url, param_url, size, date, md5 = detect_increment(product)

    # 版本号显示逻辑（用 _ver_newer 判断"是否更新"，而非简单不等）：
    # - 检测到比 base_version 更新的版本 → 用检测到的版本号
    # - 与 base_version 相同或更旧 → 用 version_display 兜底（更详细的版本号如 4.1.13.65），
    #   避免探测异常回退到旧值时把 data.json 里的版本号"降级"
    base_ver = product.get('base_version', '')
    if base_ver and _ver_newer(version, base_ver):
        display_version = version
    else:
        display_version = product.get('version_display', version)

    # version_format转换：将探测用的build号转换为显示版本号
    vfmt = product.get('version_format', '')
    if vfmt == 'adobe_build' and re.match(r'^\d{10}$', display_version):
        # 2600221931 -> 2026.002.21931
        display_version = '20' + display_version[:2] + '.' + display_version[2:5] + '.' + display_version[5:]
    if vfmt == 'idm_build' and '.' in display_version:
        # 6.43.0.11 -> 6.43 Build 11
        parts = display_version.split('.')
        if len(parts) >= 4:
            display_version = f"{parts[0]}.{parts[1]} Build {parts[3]}"

    # 日期处理：优先使用检测到的日期，为空时用配置的固定日期兜底
    if not date:
        date = product.get('date', '')

    result = {
        'name': product['name'],
        'name_cn': product['name_cn'],
        'alias': product.get('alias', ''),
        'icon': product.get('icon', ''),
        'icon_color': product.get('icon_color', ''),
        'category': product.get('category', '其他'),
        'version': display_version,
        'download_url': full_url,
        'download_url_with_params': param_url,
        'downloads': product.get('downloads', []),
        'size': size,
        'size_mb': round(size / 1024 / 1024, 1) if size else 0,
        'last_modified': date,
        'md5': md5,
        'official_site': product.get('official_site', ''),
        'update_items': _site_items.get(product['name'], []),
    }
    # 多版本线条目（如 Java）：前端渲染成「点标题展开子版本列表」
    # 只在真有多版本线时才带这个键，避免给全部 113 款单版本产品塞空列表造成 diff 噪声
    _vlist = _java_versions.get(product['name'], [])
    if _vlist:
        result['version_list'] = _vlist
    return result


def detect_with_timeout(product, timeout=30):
    """带超时的检测。返回 (info, status)，status ∈ {'ok', 'timeout', 'error', 'error_msg'}。

    超时的检测线程会被放弃（daemon），主流程继续跑其他产品，
    不会因为单个软件卡住就中断整轮检测。
    区分 timeout 和 error 很重要：超时说明"慢"（该加时间或优化），
    异常说明"逻辑/网络报错"（该修代码），两者的处理策略不同。
    """
    result = [None]
    err = ['']

    def worker():
        try:
            result[0] = find_latest(product)
        except Exception as e:
            err[0] = str(e)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return None, 'timeout'
    if result[0] is None:
        return None, ('error', err[0]) if err[0] else 'error'
    return result[0], 'ok'


def _detect_priority(product):
    """自动推断产品检测优先级（未显式配置 detect_priority 时使用）：
      fast      github_release/chrome_api/edge_api/redirect/luminar_api/yandex/bwcx （API/重定向 <1s/款）
      normal    scrape/fixed/cyberlink/startallback （网页抓取/HEAD 1-3s/款）
      slow      increment （多重试/MD5/大文件 HEAD 10-60s/款）
      resource  资源站（nsane/downtopc/monkrus/discourse/lanzou/189pan 等，整轮扫描）
    产品可显式配置 detect_priority='fast|normal|slow|resource' 覆盖推断。"""
    explicit = product.get('detect_priority')
    if explicit in ('fast', 'normal', 'slow', 'resource'):
        return explicit
    dt = product.get('detect_type', 'increment')
    cat = product.get('category', '')
    if cat == '资源站' or dt in ('nsane', 'downtopc', 'monkrus', 'discourse', 'lanzou', '189pan'):
        return 'resource'
    if dt in ('github_release', 'chrome_api', 'edge_api', 'redirect',
              'luminar_api', 'yandex', 'bwcx', 'hexhub_api', 'java_api',
              'borisfx_hub'):
        return 'fast'
    if dt == 'increment':
        return 'slow'
    return 'normal'


def main():
    import sys
    import argparse

    parser = argparse.ArgumentParser(description='软件版本检测')
    parser.add_argument('--only', help='只检测指定软件名称')
    parser.add_argument('--priority', default='all',
                        help='按优先级筛选，逗号可组合：fast,normal,slow,resource；'
                             '别名 all=不过滤、hourly=fast,normal')
    parser.add_argument('--parallel', type=int, default=DEFAULT_PARALLEL, help='并行检测线程数')
    parser.add_argument('--retry', type=int, default=DEFAULT_RETRY, help='检测失败重试次数')
    parser.add_argument('--no-save', action='store_true', help='不保存到data.json（仅检测）')
    parser.add_argument('--allow-remove', default='',
                        help='显式声明本轮允许从线上结果中移除的产品名（逗号分隔）；'
                             '故意下线某个产品时用它绕过产品数量守卫')
    args = parser.parse_args()

    # 读取上次成功数据，用于检测失败时保留
    old_data = {}
    try:
        with open(DATA_JSON, 'r', encoding='utf-8') as f:
            old = json.load(f)
            for p in old.get('products', []):
                old_data[p['name']] = p
    except Exception:
        pass

    # 线上版本喂给 increment 探测当起点（base_version 只当最低基线，防止配置落后）
    for _n, _p in old_data.items():
        _v = str(_p.get('version') or '')
        if _v:
            _LIVE_VERSIONS[_n] = _v

    # 筛选要检测的软件
    products_to_check = PRODUCTS
    if args.only:
        products_to_check = [p for p in PRODUCTS if p['name'] == args.only or p['name_cn'] == args.only]
        if not products_to_check:
            print(f"未找到软件: {args.only}")
            sys.exit(1)
    # 按优先级过滤（支持逗号组合：fast,normal,slow,resource）
    #   hourly = fast+normal（历史别名）；all = 不过滤（四个都跑）
    # 资源站请求重、易被限流，单独分层后可只并进每小时那轮，不跟着全量高频跑。
    if args.priority != 'all' and not args.only:
        raw = 'fast,normal' if args.priority == 'hourly' else str(args.priority)
        want = {x.strip() for x in raw.split(',') if x.strip()}
        valid = {'fast', 'normal', 'slow', 'resource'}
        unknown = want - valid
        if unknown:
            print(f"未知优先级: {', '.join(sorted(unknown))}"
                  f"（可选 fast/normal/slow/resource，或 all/hourly）")
            sys.exit(2)
        products_to_check = [p for p in PRODUCTS if _detect_priority(p) in want]
        labels = {'fast': '快源', 'normal': '常规', 'slow': '重探测', 'resource': '资源站'}
        shown = '+'.join(labels[x] for x in ('fast', 'normal', 'slow', 'resource') if x in want)
        print(f"🎯 优先级筛选: {shown} → {len(products_to_check)}/{len(PRODUCTS)} 款")

    # 检测统计（多线程共享，用锁保护自增避免竞态丢计数）
    stats = {'success': 0, 'retry': 0, 'timeout': 0, 'failed': 0, 'fallback': 0}
    stats_lock = threading.Lock()
    # 问题清单：多线程 print 会交错，事后统一按软件名归类输出，便于定位
    problems = []
    problems_lock = threading.Lock()
    timings = []   # (耗时秒, 产品名)，用于输出"最慢产品"便于持续优化

    def _bump(key, n=1):
        with stats_lock:
            stats[key] = stats.get(key, 0) + n

    def _note(name, kind, detail=''):
        with problems_lock:
            problems.append((name, kind, detail))

    def detect_one(product):
        """检测单个软件：产品级超时 + 可选重试 + 失败保留旧数据。

        关键点：**超时不重试**（重试只会把耗时翻倍，且大概率还是超时）；
        只有「快速失败」（拿到了结果但体积为 0）才重试。
        """
        name = product['name']
        print(f"检测 {product['name_cn']} ({name}) [{product.get('detect_type', 'increment')}]...")
        t0 = time.time()
        timeout = product.get('detect_timeout', DEFAULT_DETECT_TIMEOUT)
        info, status = detect_with_timeout(product, timeout=timeout)
        elapsed = time.time() - t0
        with problems_lock:
            timings.append((elapsed, name))

        if status == 'timeout':
            _bump('timeout')
            _note(name, '超时', f'{timeout}s')
        elif status == 'error':
            _bump('failed')
            detail = status[1] if isinstance(status, tuple) else ''
            _note(name, '异常', detail)

        allow_no_size = product.get('allow_no_size', False)

        # 资源站类：站点抽风（一个源都没抓通）或当天没有命中文章时，检测函数返回空版本
        # → 沿用旧数据，既不清空清单，也不把前端日期刷成今天（无文章不该显示"有更新"）。
        if allow_no_size and info is not None and not info.get('version') and name in old_data:
            info = old_data[name].copy()
            _bump('fallback')
            _note(name, '资源站无本轮数据', f"沿用 {info.get('last_modified', '')}")
            print(f"  ⚠️ 资源站本轮无有效数据（未抓通或无新内容），沿用上次数据: {info.get('last_modified', '')}")

        # 多版本线条目（如 Java）：本轮没取到子版本清单（API 抽风/解析失败）→ 沿用上次的。
        # 否则前端展开列表整块消失、日期被清空，等于把线上数据打回原点。
        if info is not None and name in old_data and not info.get('version_list'):
            old_vl = old_data[name].get('version_list') or []
            if old_vl:
                info['version_list'] = old_vl
                if not info.get('last_modified'):
                    info['last_modified'] = old_data[name].get('last_modified', '')
                print(f"  ⚠️ 本轮无子版本清单，沿用上次: {len(old_vl)} 条")

        # 有结果但拿不到体积 → 快速失败，允许重试一次
        # 资源站类（如 monkrus）本身就是站点、没有安装包，配置 allow_no_size 后跳过该判定
        if info is not None and info.get('size_mb', 0) <= 0 and args.retry > 0 and not allow_no_size:
            print(f"  重试...")
            time.sleep(1)
            info2, _st2 = detect_with_timeout(product, timeout=timeout)
            if info2 and info2.get('size_mb', 0) > 0:
                info = info2
                _bump('retry')

        # 检测失败时保留上次数据（allow_no_size 的资源站本身就没体积，不算失败）
        no_size_ok = info is not None and allow_no_size
        if not no_size_ok and (info is None or (info.get('size_mb', 0) == 0 and name in old_data and old_data[name].get('size_mb', 0) > 0)):
            if name in old_data:
                info = old_data[name].copy()
                _bump('fallback')
                if status == 'ok':
                    _note(name, '无体积', f"沿用 v{info['version']}")
                print(f"  ⚠️ 保留上次数据: v{info['version']}, {info['size_mb']}MB")
            elif status != 'timeout':
                _bump('failed')

        # 防版本降级：本轮探测出的版本号比 data.json 里的旧值更小 → 判定为探测降级
        # （PE/NSIS 解析偶发失败、官网页面临时异常等），保留旧值，避免前端版本号来回跳
        # 例外：产品声明了 version_authority（如微信=nsis）且本轮正是权威源命中 →
        #       说明新值来自安装包内部真实版本，与旧值（可能是 PE 占位 build）不可比，
        #       此时放行，避免权威值被数值更大的占位值永久顶掉。
        if info and name in old_data and (info.get('size_mb', 0) > 0 or allow_no_size):
            old_v = old_data[name].get('version', '')
            new_v = info.get('version', '')
            # 空版本兜底：本轮探测没拿到版本号（PE 限流 / 官网页面抽风），
            # 绝不能把线上已有的版本号覆盖成空字符串，只保留旧值。
            if old_v and not new_v:
                print(f"  ⚠️ 本轮版本号为空，沿用旧值: {old_v}")
                info['version'] = old_v
                new_v = old_v
            auth = product.get('version_authority')
            from_authority = bool(auth) and _VER_SOURCE.get(name) == auth
            if old_v and new_v and not from_authority and _ver_tuple(new_v) < _ver_tuple(old_v):
                print(f"  ⚠️ 探测版本 {new_v} 低于已有 {old_v}，判定为降级，保留旧值")
                _note(name, '版本降级已拦截', f"{new_v} -> {old_v}")
                info['version'] = old_v
                # 降级说明这一轮探测整体不可信（页面返回了旧包/旧列表），
                # 只回退 version 会把同轮的坏体积、坏日期、坏直链带进线上。
                # 这些字段一并沿用旧值，只有 update_items（独立来源）保留本轮结果。
                for _f in ('size', 'size_mb', 'last_modified', 'md5',
                           'download_url', 'download_url_with_params'):
                    if _f in old_data[name]:
                        info[_f] = old_data[name][_f]
            elif from_authority and old_v and new_v and _ver_tuple(new_v) < _ver_tuple(old_v):
                print(f"  ℹ️ 权威源({auth})版本 {new_v} 低于旧值 {old_v}，按权威值放行（旧值疑为占位 build）")

        if info and (info.get('size_mb', 0) > 0 or allow_no_size):
            _bump('success')
            if allow_no_size:
                cnt = len(info.get('update_items') or [])
                print(f"  ✅ {info['version']}, 当天更新 {cnt} 款软件")
            else:
                print(f"  ✅ {info['version']}, {info['size_mb']} MB")
        return info

    # 并行检测
    from concurrent.futures import as_completed
    results_dict = {}
    print(f"🚀 开始全量检测: {len(products_to_check)} 个软件, 并行 {args.parallel} 线程\n")
    t_start = time.time()
    with ThreadPoolExecutor(max_workers=args.parallel) as executor:
        future_to_name = {executor.submit(detect_one, p): p['name'] for p in products_to_check}
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                results_dict[name] = future.result()
            except Exception as e:
                # 单个产品抛异常绝不影响整轮：记录 + 用旧数据兜底
                print(f"  ⚠️ {name} 检测异常: {e}")
                _bump('failed')
                if name in old_data:
                    results_dict[name] = old_data[name].copy()
                    _bump('fallback')

    # 按PRODUCTS顺序排序，确保所有产品都有结果
    results = []
    changed = []
    for p in PRODUCTS:
        if p['name'] in results_dict and results_dict[p['name']] is not None:
            info = results_dict[p['name']]
        elif p['name'] in old_data:
            info = old_data[p['name']].copy()
            _bump('fallback')
        else:
            continue
        results.append(info)
        # 检测是否有变化（新增产品也视为变化）
        is_changed = False
        if p['name'] in old_data:
            old = old_data[p['name']]
            # 资源站的"更新"只体现在 update_items（当天文章清单），版本/日期可能不变，
            # 所以清单变化也必须算变化 —— 否则 CI 判定"无变化"，前端不会重新生成，
            # 会一直显示旧文章（如 nsane 已下掉的旧帖仍挂在前端）。
            old_items = old.get('update_items') or []
            new_items = info.get('update_items') or []
            # 多版本线条目（如 Java）：主版本不变、但某条子版本线更新时，
            # 也必须算变化 —— 否则 CI 判定"无变化"，前端展开列表会一直停在旧版本。
            old_vlist = old.get('version_list') or []
            new_vlist = info.get('version_list') or []
            if (old.get('version') != info.get('version')
                    or old.get('size_mb') != info.get('size_mb')
                    or old.get('last_modified') != info.get('last_modified')
                    or old.get('download_url') != info.get('download_url')
                    or old_items != new_items
                    or old_vlist != new_vlist):
                change_detail = []
                if old.get('version') != info.get('version'):
                    change_detail.append(f"版本 {old.get('version')}->{info.get('version')}")
                if old.get('size_mb') != info.get('size_mb'):
                    change_detail.append(f"大小 {old.get('size_mb')}->{info.get('size_mb')}MB")
                if old.get('last_modified') != info.get('last_modified'):
                    change_detail.append(f"日期 {old.get('last_modified')}->{info.get('last_modified')}")
                if old_items != new_items:
                    change_detail.append(f"更新清单 {len(old_items)}->{len(new_items)} 篇")
                if old_vlist != new_vlist:
                    change_detail.append(f"子版本列表 {len(old_vlist)}->{len(new_vlist)} 条")
                changed.append(f"{p['name_cn']}: {', '.join(change_detail)}")
                is_changed = True
        else:
            changed.append(f"{p['name_cn']}: 新增 -> {info.get('version')}")
            is_changed = True
        # 检测到版本变化时，保持软件真实发布日期不变（last_modified由探测逻辑获取）

    # ===== 产品数量守卫 =====
    # 误改 PRODUCTS（漏配一条、name 写错、删掉一个条目）会让本轮结果比线上少，
    # 写回 data.json 就等于静默截断线上数据。这里在写盘前拦下并明确报出少了谁。
    allow_remove = {x.strip() for x in args.allow_remove.split(',') if x.strip()}
    result_names = {r.get('name') for r in results}
    # 允许用英文名 name 或中文名 name_cn 声明下线
    lost_all = [n for n in old_data if n not in result_names]
    lost = [n for n in lost_all
            if n not in allow_remove and old_data[n].get('name_cn', '') not in allow_remove]
    if lost:
        print(f"\n❌ 产品数量守卫：线上有 {len(lost)} 款产品在本次结果中消失")
        for n in lost:
            print(f"   - {n}（{old_data[n].get('name_cn', '')}）")
        print("   可能是误改 PRODUCTS（漏配/name 写错/误删）。请先修好，"
              "确认要下线某产品则用 --allow-remove \"产品名\" 显式声明。")
        if args.no_save:
            print("   本轮为 --no-save 演练，不写盘，仅提示。")
        else:
            print("   本轮不写 data.json，线上数据保持原样。")
            sys.exit(3)
    allowed_lost = [n for n in lost_all if n not in lost]
    if allowed_lost:
        print(f"\nℹ️ 已声明允许移除 {len(allowed_lost)} 款产品: "
              f"{', '.join(old_data[n].get('name_cn', n) for n in allowed_lost)}")
    # 新增产品本轮没探到（无历史数据可回退）不算截断，但要提醒
    missing_new = [p['name'] for p in PRODUCTS
                   if p['name'] not in result_names and p['name'] not in old_data]
    if missing_new:
        print(f"\n⚠️ 新增产品本轮未产出结果（不写入线上）: {', '.join(missing_new)}")

    data = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'products': results,
    }

    if not args.no_save:
        with open(DATA_JSON, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # 检测结果汇总
    elapsed = time.time() - t_start
    print(f"\n{'='*50}")
    print(f"📊 检测汇总: 成功{stats['success']} | 重试成功{stats['retry']} | 超时{stats['timeout']} | 失败{stats['failed']} | 保留旧数据{stats['fallback']}")
    print(f"📦 产品总数: {len(results)}/{len(PRODUCTS)}")
    print(f"⏱️ 总耗时: {elapsed:.1f} 秒")
    if problems:
        print(f"\n⚠️ 本轮问题清单（{len(problems)} 项）:")
        for pname, kind, detail in sorted(problems):
            cn = next((p['name_cn'] for p in PRODUCTS if p['name'] == pname), pname)
            print(f"   - {cn}: {kind} {detail}".rstrip())
    if timings:
        top = sorted(timings, reverse=True)[:5]
        print(f"\n🐢 最慢产品 Top5（用于定位优化点）:")
        for sec, pname in top:
            cn = next((p['name_cn'] for p in PRODUCTS if p['name'] == pname), pname)
            print(f"   - {cn}: {sec:.1f}s")
    print(f"⏰ 更新时间: {data['updated_at']}")
    if changed:
        print(f"🔄 版本变化: {', '.join(changed)}")
        print("CHANGED=true")
    else:
        print("无版本变化")
        print("CHANGED=false")
    print(f"{'='*50}")


if __name__ == '__main__':
    main()




