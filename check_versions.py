#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
常用软件最新版离线安装包自动检测脚本
支持四种检测模式：
  increment - 从基础版本递增检测（默认）
  redirect  - 访问固定地址，从 302 Location 头提取版本号和完整下载链接
  fixed     - 固定下载地址，版本号手动维护，只检测文件可用性
  scrape    - 从官网页面抓取版本号，固定下载地址，计算MD5校验
"""

import hashlib
import json
import os
import re
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_JSON = os.path.join(BASE_DIR, 'data.json')

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

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
        'url_pattern': 'https://down.sandai.net/thunder_pc/ThunderSetup{ver}up.exe',
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
        'nsis_version': True,
        'pe_version': True,
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
        'detect_type': 'increment',
        'base_version': '9.59.0.0',
        'pe_version': True,
        'url_pattern': 'https://dl-limit.yystatic.com/4/setup/YYSetup-{ver}-zh-CN.exe',
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
        'check_url': 'https://www.xyplorer.com/',
        'version_regex': r'version\s*\((\d+\.\d+\.\d+\.\d+)',
        'version': '28.30.2600',
        'date': '2026-09-13',
        'download_url': 'https://www.xyplorer.com/download/xyplorer64_full_noinstall.zip',
        'official_site': 'https://www.xyplorer.com/',
    },
    {
        'name': 'Microsoft Edge',
        'name_cn': 'Microsoft Edge',
        'icon': 'E',
        'icon_color': 'linear-gradient(135deg, #0078d4, #00bcf2)',
        'category': '浏览器',
        'detect_type': 'scrape',
        'check_url': 'https://raw.githubusercontent.com/Bush2021/edge_installer/main/readme.md',
        'version_regex': r'\*\*x64\*\*\s*\|\s*`(\d+\.\d+\.\d+\.\d+)',
        'download_url_regex': r'\*\*x64\*\*.*?\]\((https://[^)]+)\)',
        'version': '153.0.4234.32',
        'download_url': 'https://github.com/Bush2021/edge_installer/releases',
        'official_site': 'https://github.com/Bush2021/edge_installer',
    },
    {
        'name': 'Google Chrome',
        'name_cn': 'Google Chrome',
        'icon': 'C',
        'icon_color': 'linear-gradient(135deg, #4285f4, #34a853)',
        'category': '浏览器',
        'detect_type': 'scrape',
        'check_url': 'https://raw.githubusercontent.com/Bush2021/chrome_installer/main/readme.md',
        'version_regex': r'\*\*x64\*\*\s*\|\s*`(\d+\.\d+\.\d+\.\d+)',
        'download_url_regex': r'\*\*x64\*\*.*?\]\((https://[^)]+)\)',
        'prefer_scraped_version': True,
        'version': '153.0.8010.48',
        'download_url': 'https://github.com/Bush2021/chrome_installer/releases',
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
        'detect_type': 'increment',
        'base_version': '17.1.1036',
        'pe_version': True,
        'url_pattern': 'https://sedl.360tpcdn.com/se/360se{ver}.64.exe',
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
        'detect_type': 'increment',
        'base_version': '23.1.1253',
        'pe_version': True,
        'url_pattern': 'https://sedl.360tpcdn.com/cse/360csex_{ver}.64.exe',
        'param_format': '',
        'channel': '',
        'official_site': 'https://chromex.360.cn/',
    },
    {
        'name': 'Topaz Photo',
        'name_cn': 'Topaz Photo',
        'icon': 'P',
        'icon_color': 'linear-gradient(135deg, #ff6b35, #f7931e)',
        'category': '图像处理',
        'detect_type': 'scrape',
        'check_url': 'https://community.topazlabs.com/c/topaz-photo/topaz-photo-releases/117',
        'detail_url_regex': r'https://community\.topazlabs\.com/t/[a-z0-9-]+/[0-9]+',
        'detail_url_index': 2,
        'version_regex': r'v(\d+\.\d+\.\d+)',
        'date_regex': r'article:published_time" content="([^"]+)"',
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
        'detect_type': 'scrape',
        'check_url': 'https://community.topazlabs.com/c/topaz-gigapixel/topaz-gigapixel-releases/128',
        'detail_url_regex': r'https://community\.topazlabs\.com/t/[a-z0-9-]+/[0-9]+',
        'detail_url_index': 2,
        'version_regex': r'v(\d+\.\d+\.\d+)',
        'date_regex': r'article:published_time" content="([^"]+)"',
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
        'detect_type': 'scrape',
        'check_url': 'https://community.topazlabs.com/c/topaz-video/topaz-video-releases/122',
        'detail_url_regex': r'https://community\.topazlabs\.com/t/[a-z0-9-]+/[0-9]+',
        'detail_url_index': 2,
        'version_regex': r'v(\d+\.\d+\.\d+)',
        'date_regex': r'article:published_time" content="([^"]+)"',
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
        'detect_type': 'increment',
        'base_version': '6.3.2',
        'url_pattern': 'https://www.ntwind.com/files/WinSnap_{ver}-setup.exe',
        'param_format': '',
        'channel': '',
        'date': '2026-09-14',
        'official_site': 'https://www.ntwind.com/blog',
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
        'version_regex': r'(\d+\.\d+\.\d+)',
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
        'version_regex': r'(\d+\.\d+\.\d+)',
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
        'detect_type': 'github_release',
        'repo': 'Open-Shell/Open-Shell-Menu',
        'version_regex': r'v?(\d+\.\d+\.\d+)',
        'include_prerelease': True,
        'version': '4.4.201',
        'date': '2026-09-15',
        'download_url': 'https://github.com/Open-Shell/Open-Shell-Menu/releases',
        'official_site': 'https://github.com/Open-Shell/Open-Shell-Menu/releases',
    },
    {
        'name': 'PowerDirector',
        'name_cn': 'PowerDirector 365',
        'icon': 'PD',
        'icon_color': 'linear-gradient(135deg, #2c3e50, #f39c12)',
        'category': '视频编辑',
        'detect_type': 'fixed',
        'version': '25.0.0.0904.0',
        'size': 691 * 1024 * 1024,
        'date': '2026-09-14',
        'md5': 'be7750903c07baa523c0ab0328a1b27a',
        'download_url': 'https://build.cyberlink.com/Retail/PowerDirector/CGQC8ZH75VM6/PowerDirector_DirectorSuite365.exe',
        'official_site': 'https://www.cyberlink.com/products/powerdirector-video-editing-software/features_en_US.html',
    },
    {
        'name': 'PhotoDirector',
        'name_cn': 'PhotoDirector 365',
        'icon': 'PhD',
        'icon_color': 'linear-gradient(135deg, #8e44ad, #3498db)',
        'category': '图像处理',
        'detect_type': 'fixed',
        'version': '18.0.8.0908.0',
        'size': 639 * 1024 * 1024,
        'date': '2026-09-08',
        'md5': '02769dcdca897ea1574c2de844c4d76e',
        'download_url': 'https://build.cyberlink.com/Retail/PhotoDirector/Y2QIW32JB74CH/PhotoDirector_DirectorSuite365.exe',
        'official_site': 'https://www.cyberlink.com/products/photodirector/features_en_US.html',
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


def check_url(url, referer=None):
    """检测URL是否存在，返回 (exists, size, last_modified)
    不跟随重定向：302/301（如CDN跳转404页）视为文件不存在
    HEAD无Content-Length时用GET探测
    """
    headers = {'User-Agent': UA}
    if referer:
        headers['Referer'] = referer
    try:
        req = urllib.request.Request(url, method='HEAD', headers=headers)
        with _no_redirect_opener.open(req, timeout=10) as resp:
            size = resp.headers.get('Content-Length', '0')
            last_modified = resp.headers.get('Last-Modified', '')
            if resp.status == 200 and (not size or int(size) == 0):
                # HEAD无Content-Length，用GET探测
                try:
                    req2 = urllib.request.Request(url, headers=headers)
                    with _no_redirect_opener.open(req2, timeout=15) as resp2:
                        size = resp2.headers.get('Content-Length', '0')
                        if not size or int(size) == 0:
                            # 分块传输，读取实际大小
                            total = 0
                            while True:
                                chunk = resp2.read(65536)
                                if not chunk:
                                    break
                                total += len(chunk)
                            size = str(total)
                except Exception:
                    pass
            return resp.status == 200, int(size) if size and size.isdigit() else 0, last_modified
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
            size = resp.headers.get('Content-Length', '0')
            last_modified = resp.headers.get('Last-Modified', '')
            if resp.status == 200 and (not size or int(size) == 0):
                try:
                    req2 = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req2, timeout=20) as resp2:
                        size = resp2.headers.get('Content-Length', '0')
                        if not size or int(size) == 0:
                            total = 0
                            while True:
                                chunk = resp2.read(65536)
                                if not chunk:
                                    break
                                total += len(chunk)
                            size = str(total)
                except Exception:
                    pass
            # urllib返回200但size=0时，尝试curl兜底
            if resp.status == 200 and (not size or int(size) == 0):
                curl_size, curl_date = _curl_get_headers(url, referer)
                if curl_size > 0:
                    return True, curl_size, curl_date or last_modified
            return resp.status == 200, int(size) if size and size.isdigit() else 0, last_modified
    except urllib.error.HTTPError as e:
        if e.code == 403:
            # 403时尝试curl兜底（Cloudflare可能拦截urllib但允许curl）
            curl_size, curl_date = _curl_get_headers(url, referer)
            if curl_size > 0:
                return True, curl_size, curl_date
            return True, 0, ''
        size = e.headers.get('Content-Length', '0') if e.headers else '0'
        return False, int(size) if size.isdigit() else 0, ''
    except Exception:
        # urllib失败（超时/Cloudflare拦截），用curl兜底
        curl_size, curl_date = _curl_get_headers(url, referer)
        if curl_size > 0:
            return True, curl_size, curl_date
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
    """解析多种日期格式为 YYYY-MM-DD"""
    date_str = date_str.strip()
    # ISO格式: 2026-08-27T17:23:08+00:00
    m = re.match(r'(20\d{2}-\d{2}-\d{2})T', date_str)
    if m:
        return m.group(1)
    # 英文月份: September 9, 2026
    months = {'january':'01','february':'02','march':'03','april':'04','may':'05','june':'06',
              'july':'07','august':'08','september':'09','october':'10','november':'11','december':'12',
              'jan':'01','feb':'02','mar':'03','apr':'04','jun':'06','jul':'07','aug':'08','sep':'09','oct':'10','nov':'11','dec':'12'}
    m = re.match(r'([A-Za-z]+)\s+(\d{1,2}),?\s*(20\d{2})', date_str)
    if m:
        mon = months.get(m.group(1).lower(), '01')
        return f"{m.group(3)}-{mon}-{m.group(2).zfill(2)}"
    # 中文格式: 2026年09月09日
    date_str = date_str.replace('年', '-').replace('月', '-').replace('日', '')
    # 斜杠格式
    date_str = date_str.replace('/', '-')
    return date_str


def increment_version(version):
    """递增版本号的最后一段，支持任意段数"""
    parts = version.split('.')
    parts[-1] = str(int(parts[-1]) + 1)
    return '.'.join(parts)


def carry_version(version):
    """进位到上一段：将上一段+1，后面所有段重置为0
    例如 25.1.13.1636 -> 25.1.14.0
         4.1.15 -> 4.2.0
    """
    parts = version.split('.')
    if len(parts) < 2:
        return increment_version(version)
    # 找到倒数第二段，+1，后面全部置0
    parts[-2] = str(int(parts[-2]) + 1)
    for i in range(-1, -len(parts), -1):
        if i == -2:
            break
        parts[i] = '0'
    return '.'.join(parts)


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
    return version


def detect_increment(product):
    """递增检测模式：多级进位探测
    第1层：递增最后一段（build号），遇到不存在的版本跳过（最多5个）
    第2层：连续5个404后进位到上一段（如25.1.13.1636 -> 25.1.14.0），重置后段为0
    第3层：最多进位2次，确保能探测到跨小版本（25.1.15、25.2.0）
    第4层：检测到最新版本后，探测四段小版本号（NSIS/PE）
    第5层：获取安装包大小、更新日期、MD5
    """
    current = product['base_version']
    latest = current
    latest_size = 0
    latest_date = ''
    referer = product.get('referer')
    MAX_SKIP = 5  # 最多跳过5个不存在的版本
    MAX_CARRY = 2  # 最多进位2次（防止无限探测）
    MD5_SIZE_LIMIT = 100 * 1024 * 1024  # 超过100MB不计算MD5

    # 检测基础版本是否存在
    url = product['url_pattern'].format(ver=_url_ver(current, product))
    exists, size, date = check_url(url, referer=referer)
    if exists:
        latest = current
        latest_size = size
        latest_date = date
    else:
        print(f"  ⚠️ 警告: 基础版本 {current} 不存在，可能已下架或网络异常")

    # 多级进位递增探测
    carry_count = 0
    skip_count = 0
    for _ in range(MAX_INCREMENT * (MAX_CARRY + 1)):
        next_ver = increment_version(current)
        url = product['url_pattern'].format(ver=_url_ver(next_ver, product))
        exists, size, date = check_url(url, referer=referer)
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
                # 连续5个404，尝试进位到上一段
                if carry_count < MAX_CARRY:
                    carry_ver = carry_version(current)
                    print(f"  🔄 连续{MAX_SKIP}个404，进位探测: {current} -> {carry_ver}")
                    current = carry_ver
                    skip_count = 0
                    carry_count += 1
                    # 检测进位后的版本是否存在
                    url = product['url_pattern'].format(ver=_url_ver(current, product))
                    exists, size, date = check_url(url, referer=referer)
                    if exists:
                        latest = current
                        latest_size = size
                        latest_date = date
                        print(f"  ✓ 进位版本存在: {current}")
                    time.sleep(0.3)
                    continue
                else:
                    print(f"  ⏹ 已进位{MAX_CARRY}次，停止探测")
                    break
            current = next_ver
            time.sleep(0.2)

    # 第2层：多源版本号探测
    # NSIS版本优先（安装包内部真实版本，最精确）
    # PE版本与increment版本取最高的作为兜底
    display_version = latest  # increment探测到的大版本
    nsis_ver = None
    pe_ver = None
    parts = latest.split('.')
    if len(parts) == 3:
        full_url_tmp = product['url_pattern'].format(ver=_url_ver(latest, product))
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

    # 版本号比较函数
    def version_key(v):
        nums = re.findall(r'\d+', str(v))
        return [int(n) for n in nums] if nums else [0]

    # NSIS版本优先（最精确的真实版本），否则PE与increment取最高
    if nsis_ver:
        display_version = nsis_ver
        print(f"  采用NSIS精确版本: {display_version}")
    elif pe_ver:
        # PE版本与increment版本取最高的
        display_version = max([latest, pe_ver], key=version_key)
        if display_version != latest:
            print(f"  PE版本更高，采用: {display_version} (increment={latest})")
    else:
        display_version = latest

    # 第3层：MD5计算（小于100MB才计算）
    md5 = ''
    full_url = product['url_pattern'].format(ver=_url_ver(latest, product))
    if latest_size > 0 and latest_size < MD5_SIZE_LIMIT:
        print(f"  计算MD5 ({latest_size/1024/1024:.1f}MB)...")
        md5 = get_file_md5(full_url, referer=referer)
        if md5:
            print(f"  MD5: {md5}")
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
    is_webpage = url.endswith('/') or '#' in url or '.html' in url or 'pages.dev' in url or 'update-history' in url
    size = product.get('size', 0)
    date = product.get('date', '')
    md5 = product.get('md5', '')
    if is_webpage:
        size = 0
        date = ''
    else:
        # 检测文件可用性，如果检测到大小则用检测值，否则用配置值
        exists, detected_size, detected_date = check_url_follow(url)
        if exists and detected_size > 0:
            size = detected_size
            if detected_date:
                date = detected_date
        elif not exists:
            print(f"  ⚠️ 警告: 固定地址不可用，可能链接已失效（使用配置值）")
    version = product.get('version', '最新版')
    return version, url, url, size, date, md5


def get_pe_version(url, referer=None):
    """从PE文件的.rsrc段读取FileVersion（四段版本号），只下载PE头和资源段，不需要下载整个文件。
    返回版本号字符串，失败返回空字符串。
    """
    import struct
    import re
    headers = {'User-Agent': UA}
    if referer:
        headers['Referer'] = referer

    def download_range(start, end):
        req = urllib.request.Request(url, headers={**headers, 'Range': f'bytes={start}-{end}'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()

    try:
        # 1. 下载PE头（前1KB）
        head = download_range(0, 1024)
        pe_offset = struct.unpack_from('<I', head, 0x3C)[0]

        # 2. 下载PE header + section headers
        pe_data = download_range(pe_offset, pe_offset + 4096)
        num_sections = struct.unpack_from('<H', pe_data, 6)[0]
        opt_header_size = struct.unpack_from('<H', pe_data, 20)[0]

        # 3. 找.rsrc段
        section_offset = 24 + opt_header_size
        for i in range(num_sections):
            off = section_offset + i * 40
            name = pe_data[off:off+8].rstrip(b'\x00').decode('ascii', errors='replace')
            if name == '.rsrc':
                raw_offset = struct.unpack_from('<I', pe_data, off+20)[0]
                raw_size = struct.unpack_from('<I', pe_data, off+16)[0]
                # 4. 下载.rsrc段（最多2MB）
                rsrc = download_range(raw_offset, raw_offset + min(raw_size, 2*1024*1024))
                # 5. 解析版本信息（UTF-16LE编码）
                text = rsrc.decode('utf-16-le', errors='replace')
                # 找FileVersion后面的版本号
                match = re.search(r'FileVersion\s*(\d+\.\d+\.\d+\.\d+)', text)
                if match:
                    return match.group(1)
                # 兜底：找所有四段版本号，取出现最多的
                versions = re.findall(r'\d+\.\d+\.\d+\.\d+', text)
                if versions:
                    from collections import Counter
                    return Counter(versions).most_common(1)[0][0]
                break
    except Exception as e:
        print(f"  PE版本解析失败: {e}")
    return ''


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
        req = urllib.request.Request(url, headers={**headers, 'Range': f'bytes={start}-{end}'})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()

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
            # 尝试多个7z可执行文件名（包括项目目录）
            import os
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
                print(f"  未找到7z命令，跳过NSIS版本解析")
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
            import re
            versions = re.findall(r'(\d+\.\d+\.\d+\.\d+)', result.stdout)
            if versions:
                print(f"  NSIS install版本号(兜底): {versions[0]}")
                return versions[0]
        finally:
            os.unlink(tmp_path)

    except Exception as e:
        print(f"  NSIS版本解析失败: {e}")
    return ''


def get_file_md5(url, max_retries=3, max_size_mb=500, referer=None):
    """下载文件并计算MD5，返回md5十六进制字符串。支持重试。
    超过 max_size_mb 的文件跳过MD5计算（避免大文件下载过慢）
    """
    headers = {'User-Agent': UA}
    if referer:
        headers['Referer'] = referer
    # 先 HEAD 请求获取文件大小
    try:
        req = urllib.request.Request(url, headers=headers, method='HEAD')
        with urllib.request.urlopen(req, timeout=15) as resp:
            size = int(resp.headers.get('Content-Length', '0'))
            if size > max_size_mb * 1024 * 1024:
                print(f"  文件过大({size/1024/1024:.0f}MB)，跳过MD5计算")
                return ''
    except Exception:
        pass

    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=180) as resp:
                md5 = hashlib.md5()
                total = 0
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    md5.update(chunk)
                    total += len(chunk)
                if total > 0:
                    return md5.hexdigest()
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"  MD5下载重试 ({attempt+1}/{max_retries}): {e}")
                time.sleep(2)
            else:
                print(f"  ⚠️ MD5计算失败: {e}")
    return ''


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
        req = urllib.request.Request(api_url, headers={'User-Agent': UA, 'Accept': 'application/vnd.github.v3+json'})
        with urllib.request.urlopen(req, timeout=20) as resp:
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

        # 计算所有asset的总大小
        assets = latest_release.get('assets', [])
        total_size = sum(a.get('size', 0) for a in assets)
        print(f"  分卷: {len(assets)}个, 总大小: {total_size/1024/1024:.0f}MB")

        # 日期转换
        date = ''
        if published:
            try:
                from datetime import datetime, timezone, timedelta
                dt = datetime.fromisoformat(published.replace('Z', '+00:00'))
                dt = dt.astimezone(timezone(timedelta(hours=8)))
                date = dt.strftime('%Y-%m-%d')
            except Exception:
                date = published[:10]

        return version, html_url, html_url, total_size, date, ''

    except Exception as e:
        print(f"  ⚠️ GitHub API失败: {e}")
        # API失败时保留配置的默认值（版本、下载地址、大小、日期）
        return (product.get('version', '未知'),
                product.get('download_url', ''),
                product.get('download_url', ''),
                product.get('size', 0),
                product.get('date', ''), '')


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

    # 从官网抓取版本号、发布日期、下载链接
    try:
        req = urllib.request.Request(product['check_url'], headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=20) as resp:
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
                scraped_date = parse_date(m.group(1))
                print(f"  发布日期: {scraped_date}")

        # 抓取下载链接
        dl_regex = product.get('download_url_regex')
        if dl_regex:
            m = re.search(dl_regex, html, re.I)
            if m:
                scraped_download_url = m.group(1)
                print(f"  抓取下载链接: {scraped_download_url[:80]}...")
    except Exception as e:
        print(f"  ⚠️ 官网抓取失败: {e}")

    # 版本号决策：默认优先使用配置的默认版本号，配置prefer_scraped_version时优先使用抓取版本
    prefer_scraped = product.get('prefer_scraped_version', False)
    if prefer_scraped and scraped_version:
        version = scraped_version
        if default_version and default_version != scraped_version:
            print(f"  ℹ️ 使用官网抓取版本: {scraped_version} (配置版本: {default_version})")
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
    if product.get('url_pattern'):
        url = product['url_pattern'].format(ver=_url_ver(version, product))
        print(f"  动态构造URL: {url}")
    else:
        url = scraped_download_url or product['download_url']

    # 获取文件信息（仅当下载地址是文件时）
    is_webpage = url.endswith('.html') or url.endswith('/') or 'download.html' in url or 'update-history' in url or 'pages.dev' in url
    size = 0
    date = ''
    md5 = ''

    if is_webpage:
        date = scraped_date or ''
        print(f"  下载地址为网页，大小不适用")
    else:
        exists, size, date = check_url_follow(url)
        if not exists and size == 0:
            print(f"  ⚠️ 下载地址不可用")
        if exists:
            # MD5计算：小于100MB且未配置skip_md5才计算
            if not product.get('skip_md5') and size > 0 and size < 100 * 1024 * 1024:
                md5 = get_file_md5(url)
                if md5:
                    print(f"  MD5: {md5}")
            else:
                print(f"  跳过MD5计算 (skip_md5={product.get('skip_md5', False)}, size={size/1024/1024:.0f}MB)")

    if scraped_date and not date:
        date = scraped_date

    # 配置的固定日期优先（当抓取不到时）
    if not date and product.get('date'):
        date = product['date']

    # PE版本探测：当下载地址是exe文件且配置了pe_version时
    if not is_webpage and product.get('pe_version') and url.endswith('.exe'):
        print(f"  解析PE文件版本信息...")
        pe_ver = get_pe_version(url)
        if pe_ver:
            print(f"  PE版本: {pe_ver}")
            version = pe_ver

    return version, url, url, size, date, md5


def find_latest(product):
    """根据检测类型分发"""
    detect_type = product.get('detect_type', 'increment')

    if detect_type == 'redirect':
        version, full_url, param_url, size, date, md5 = detect_redirect(product)
    elif detect_type == 'fixed':
        version, full_url, param_url, size, date, md5 = detect_fixed(product)
    elif detect_type == 'scrape':
        version, full_url, param_url, size, date, md5 = detect_scrape(product)
    elif detect_type == 'github_release':
        version, full_url, param_url, size, date, md5 = detect_github_release(product)
    else:
        version, full_url, param_url, size, date, md5 = detect_increment(product)

    # 版本号显示逻辑：
    # - 如果检测到新版本（与base_version不同），使用检测到的版本号
    # - 如果未检测到新版本，且配置了version_display，使用version_display（更详细的版本号如4.1.13.65）
    base_ver = product.get('base_version', '')
    if version != base_ver and base_ver:
        display_version = version  # 检测到新版本，使用检测到的版本号
    else:
        display_version = product.get('version_display', version)

    # 日期处理：优先使用检测到的日期，为空时用配置的固定日期兜底
    if not date:
        date = product.get('date', '')

    return {
        'name': product['name'],
        'name_cn': product['name_cn'],
        'icon': product.get('icon', ''),
        'icon_color': product.get('icon_color', ''),
        'category': product.get('category', '其他'),
        'version': display_version,
        'download_url': full_url,
        'download_url_with_params': param_url,
        'size': size,
        'size_mb': round(size / 1024 / 1024, 1) if size else 0,
        'last_modified': date,
        'md5': md5,
        'official_site': product.get('official_site', ''),
    }


def detect_with_timeout(product, timeout=45):
    """带超时的检测，超时返回None"""
    import threading
    result = [None]
    def worker():
        try:
            result[0] = find_latest(product)
        except Exception as e:
            print(f"  ⚠️ 检测异常: {e}")
            result[0] = None
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        print(f"  ⚠️ 检测超时({timeout}s)，保留上次数据")
        return None
    return result[0]


def main():
    import sys
    import argparse

    parser = argparse.ArgumentParser(description='软件版本检测')
    parser.add_argument('--only', help='只检测指定软件名称')
    parser.add_argument('--parallel', type=int, default=4, help='并行检测线程数')
    parser.add_argument('--no-save', action='store_true', help='不保存到data.json（仅检测）')
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

    # 筛选要检测的软件
    products_to_check = PRODUCTS
    if args.only:
        products_to_check = [p for p in PRODUCTS if p['name'] == args.only or p['name_cn'] == args.only]
        if not products_to_check:
            print(f"未找到软件: {args.only}")
            sys.exit(1)

    def detect_one(product):
        """检测单个软件，带超时和重试"""
        name = product['name']
        print(f"检测 {product['name_cn']} ({name}) [{product.get('detect_type', 'increment')}]...")
        info = None
        for attempt in range(2):
            info = detect_with_timeout(product, timeout=45)
            if info and info.get('size_mb', 0) > 0:
                break
            if attempt == 0:
                print(f"  重试第2次...")
                time.sleep(2)
        if info is None or (info.get('size_mb', 0) == 0 and name in old_data and old_data[name].get('size_mb', 0) > 0):
            if name in old_data:
                old = old_data[name]
                info = old.copy()
                print(f"  ⚠️ 检测异常，保留上次数据: v{old['version']}, {old['size_mb']}MB")
            elif info is None:
                info = find_latest(product)
        if info:
            print(f"  最新版: {info['version']}, 大小: {info['size_mb']} MB")
        return info

    # 并行检测
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results_dict = {}
    with ThreadPoolExecutor(max_workers=args.parallel) as executor:
        future_to_name = {executor.submit(detect_one, p): p['name'] for p in products_to_check}
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                results_dict[name] = future.result()
            except Exception as e:
                print(f"  ⚠️ {name} 检测异常: {e}")
                if name in old_data:
                    results_dict[name] = old_data[name].copy()

    # 按PRODUCTS顺序排序
    results = []
    changed = []
    for p in PRODUCTS:
        if p['name'] in results_dict:
            info = results_dict[p['name']]
            results.append(info)
            # 检测是否有变化
            if p['name'] in old_data:
                old = old_data[p['name']]
                if old.get('version') != info.get('version') or old.get('size_mb') != info.get('size_mb'):
                    changed.append(f"{p['name_cn']}: {old.get('version')} -> {info.get('version')}")

    data = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'products': results,
    }

    if not args.no_save:
        with open(DATA_JSON, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n已保存到 {DATA_JSON}")
    print(f"更新时间: {data['updated_at']}")
    print(f"共 {len(results)} 个产品")
    if changed:
        print(f"📦 版本变化: {', '.join(changed)}")
        print("CHANGED=true")
    else:
        print("无版本变化")
        print("CHANGED=false")

    failed = [p['name_cn'] for p in PRODUCTS if p['name'] in results_dict and results_dict[p['name']].get('size_mb', 0) == 0 and p['name'] in old_data and old_data[p['name']].get('size_mb', 0) > 0]
    if failed:
        print(f"⚠️ 检测异常保留旧数据: {', '.join(failed)}")


if __name__ == '__main__':
    main()
