#!/usr/bin/env python3
"""新增软件探测助手：丢 URL 进来，直接吐出可粘贴的 PRODUCTS 配置。

用法：
  python3 probe.py <url> [url2 ...]              # 自动定型（url2 可给版本历史/更新日志页）
  python3 probe.py --name "Bandizip" <url>       # 带软件名提示，配置片段更完整

定型规则（先跑脚本，再照抄，不用人肉走决策树）：
  1) github.com/<owner>/<repo>（含 /releases） → github_release，自动挑 x64 安装包资产
  2) 固定 URL 无版本号、直接返回文件        → fixed（给了历史页就附 page_version 建议）
  3) 固定 URL 301/302 跳转                   → redirect（从 Location 提版本）
  4) URL 路径里带版本号                      → increment + url_pattern 骨架
  5) 页面 URL（html / history / changelog）  → scrape
参考：仓库根目录 DETECTION_GUIDE.md。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
VER_RE = r'v?(\d+\.\d+(?:\.\d+){0,3})'
CHANGELOG_HINT = re.compile(r'(history|changelog|update|version|release|download)', re.I)
# 页面版本号候选：(匹配式, 建议 page_version_regex)，按可信度从高到低
VERSION_PATTERNS = [
    (r'\bv\.?(\d+(?:\.\d+){1,3})\b', r'v?(\d+\.\d+(?:\.\d+){0,3})'),      # v7.47 / v 7.47
    (r'[Vv]ersion[^\d<]{0,8}(\d+(?:\.\d+){1,3})', r'Version[^\d<]{0,8}(\d+\.\d+(?:\.\d+){0,3})'),
    (r'\b(\d+\.\d+\.\d+(?:\.\d+)?)\b', r'(\d+\.\d+\.\d+(?:\.\d+)?)'),       # 三段式
]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http(url, method='GET', follow=False, timeout=25):
    """返回 (status, headers, body_bytes)。默认不跟随跳转，便于识别 302。"""
    handlers = [] if follow else [_NoRedirect]
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, method=method, headers={'User-Agent': UA})
    try:
        with opener.open(req, timeout=timeout) as resp:
            body = b'' if method == 'HEAD' else resp.read(512 * 1024)
            return resp.status, dict(resp.headers), body
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), b''
    except Exception as e:
        return 0, {}, str(e).encode()


def gh_json(path):
    """走 GitHub API：优先环境变量 token，失败退回 gh CLI。"""
    token = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    if not token:
        try:
            token = subprocess.run(['gh', 'auth', 'token'], capture_output=True,
                                   text=True, timeout=10).stdout.strip()
        except Exception:
            token = ''
    if token:
        req = urllib.request.Request(
            f'https://api.github.com{path}',
            headers={'User-Agent': UA, 'Accept': 'application/vnd.github.v3+json',
                     'Authorization': f'token {token}'})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception:
            pass
    try:
        out = subprocess.run(['gh', 'api', path], capture_output=True, text=True, timeout=30)
        return json.loads(out.stdout) if out.returncode == 0 else None
    except Exception:
        return None


def pick_asset(assets):
    """启发式挑安装包：要 installer/setup + x64 + 可执行归档，躲开 arm64/x86/符号/校验文件。"""
    def score(n):
        s = 0
        if re.search(r'(installer|setup|install)', n, re.I):
            s += 3
        if re.search(r'(x64|amd64|win64)', n, re.I):
            s += 2
        if n.lower().endswith(('.exe', '.msi')):
            s += 2
        elif n.lower().endswith('.zip'):
            s += 1
        if re.search(r'(arm64|aarch64|ia32|x86[^_]|symbols|source|debug|pdb|\.sha|checksums)', n, re.I):
            s -= 5
        return s
    ranked = sorted(((score(a.get('name', '')), a) for a in assets), key=lambda x: -x[0])
    return ranked


def guess_version(html):
    """从页面提版本号：优先 vX.Y 写法，其次 Version X.Y，最后三段式。返回 (版本, 建议regex)。"""
    page = re.sub(r'<(script|style|noscript)[^>]*>.*?</\1>', ' ', html, flags=re.S | re.I)
    page = re.sub(r'<(meta|link|br|img|input)[^>]*>', ' ', page, flags=re.I)
    for pat, regex in VERSION_PATTERNS:
        m = re.search(pat, page, re.I)
        if m:
            return m.group(1), regex
    return '', ''


def asset_key(name, ver):
    """从资产名抠稳定子串做 asset_filter：先砍扩展名，再挖掉版本段，保留 x64 这类平台标记。"""
    key = re.sub(r'\.(exe|msi|zip|7z|dmg|apk|pkg|tar\.gz)$', '', name, flags=re.I)
    for v in {ver, ver.replace('.', '_')} if ver else set():
        key = key.replace(v, '')
    key = re.sub(r'\d+(?:[._-]\d+)+', '', key)          # 兜底：挖掉 1.9.2 / 4_4_202
    key = re.sub(r'[._-]{2,}', '.', key)                # 合并多余分隔符
    return key.strip('._-')


def emit(cfg, notes):
    print('\n' + '=' * 60)
    for n in notes:
        print(f'· {n}')
    print('=' * 60)
    print('# 粘到 check_versions.py 的 PRODUCTS 末尾：')
    print('{')
    for k, v in cfg.items():
        print(f"    '{k}': {v!r},")
    print('}')


def probe_github(url, name):
    m = re.search(r'github\.com/([^/]+)/([^/?#]+)', url)
    repo = f'{m.group(1)}/{m.group(2)}' if m else ''
    rels = gh_json(f'/repos/{repo}/releases?per_page=30') if repo else None
    if not rels:
        print(f'✗ 取 GitHub releases 失败（{repo}），检查仓库名/网络/token')
        return 1
    stable = [r for r in rels if not r.get('draft') and not r.get('prerelease')]
    rel = (stable or rels)[0]
    tag, published = rel.get('tag_name', ''), rel.get('published_at', '')[:10]
    ver, _ = guess_version(tag)
    assets = [a for a in rel.get('assets', []) if not a.get('name', '').lower().endswith(('.sha', '.txt', '.asc'))]
    ranked = pick_asset(assets) if assets else []
    pre = [r for r in rels if r.get('prerelease') and not r.get('draft')]
    notes = [f'GitHub: {repo}  最新 tag={tag}  版本={ver}  发布={published}']
    if not stable:
        notes.append('无稳定版，已取预发布 → 配置必须 include_prerelease=True')
    elif pre:
        notes.append(f"注意：存在更新的预发布版 {pre[0]['tag_name']}；要跟它就把 include_prerelease=True")
    notes.append(f'资产 {len(assets)} 个，按安装包启发式排序：')
    for sc, a in ranked[:4]:
        notes.append(f'   [{sc:+d}] {a["name"]}  {a["size"] / 1048576:.1f}MB')
    cfg = {'name': name or repo.split('/')[-1], 'name_cn': name or repo.split('/')[-1],
           'icon': '', 'icon_color': '', 'category': '',
           'detect_type': 'github_release', 'repo': repo, 'version_regex': r'v?(\d+\.\d+\.\d+)'}
    if not stable:
        cfg['include_prerelease'] = True
    if ranked:
        chosen = ranked[0][1]
        if len(assets) > 1:
            key = asset_key(chosen['name'], ver)   # 去掉版本段留稳定子串
            cfg['asset_filter'] = key
            cfg['use_asset_url'] = True
            notes.append(f'多资产 → asset_filter={key!r} + use_asset_url=True（只要这一支）')
        cfg['version'] = ver
        cfg['date'] = published
        cfg['download_url'] = chosen['browser_download_url']
    else:
        cfg['version'] = ver
        cfg['date'] = published
        cfg['download_url'] = rel.get('html_url', url)
        notes.append('该 release 无资产，改推发布页 URL')
    cfg['official_site'] = f'https://github.com/{repo}/releases'
    emit(cfg, notes)
    return 0


def probe_plain(urls, name, status, headers):
    url = urls[0]
    notes = [f'HEAD {url} → {status}  '
             f'len={headers.get("Content-Length", "-")}  lm={headers.get("Last-Modified", "-")[:16]}']
    ver_in_url = re.search(r'[/_\-.](v?\d+\.\d+(?:\.\d+){1,3})[/_\-.$]', url)
    if status in (301, 302, 303, 307, 308):
        loc = headers.get('Location', '')
        notes.append(f'跳转 → {loc[:110]}')
        cfg = {'name': name or '', 'detect_type': 'redirect', 'check_url': url,
               'version_regex': VER_RE, 'version': guess_version(loc), 'download_url': url}
    elif ver_in_url:
        ver = ver_in_url.group(1)
        pat = url.replace(ver, '{ver}')
        notes.append(f'URL 含版本 {ver} → increment；url_pattern 已生成')
        cfg = {'name': name or '', 'detect_type': 'increment', 'base_version': ver,
               'url_pattern': pat, 'version': ver, 'download_url': url}
    else:
        notes.append('固定地址、无版本 → fixed；版本手动维护')
        cfg = {'name': name or '', 'detect_type': 'fixed', 'version': '',
               'size': int(headers.get('Content-Length', 0) or 0),
               'download_url': url}
        for extra in urls[1:]:
            if CHANGELOG_HINT.search(extra):
                _, _, page = http(extra)
                ver, regex = guess_version(page.decode('utf-8', errors='ignore'))
                if ver:
                    cfg['page_version_url'] = extra
                    cfg['page_version_regex'] = regex or VER_RE
                    cfg['version'] = ver
                    notes.append(f'历史页首个版本 {ver} → page_version_url/regex 已生成')
                break
    cfg['official_site'] = ''
    emit(cfg, notes)
    return 0


def probe_page(url, name):
    _, _, body = http(url)
    ver, regex = guess_version(body.decode('utf-8', errors='ignore'))
    notes = [f'页面 {url}，首个版本候选={ver or "未识别"}']
    cfg = {'name': name or '', 'detect_type': 'scrape', 'check_url': url,
           'version_regex': regex or VER_RE, 'version': ver, 'download_url': url}
    if ver:
        notes.append('下载链接在页面上就再加 download_url_regex；纯版本页可不配')
    cfg['official_site'] = url
    emit(cfg, notes)
    return 0


def main():
    ap = argparse.ArgumentParser(description='新增软件探测助手')
    ap.add_argument('urls', nargs='+', help='下载地址 / 发布页 / 版本历史页')
    ap.add_argument('--name', help='软件名（写进配置片段）')
    a = ap.parse_args()
    url = a.urls[0]
    if re.search(r'github\.com/[^/]+/[^/?#]+', url):
        return probe_github(url, a.name)
    status, headers, _ = http(url, method='HEAD')
    if status in (301, 302, 303, 307, 308) or 'text/html' not in (headers.get('Content-Type') or '').lower():
        return probe_plain(a.urls, a.name, status, headers)
    return probe_page(url, a.name)


if __name__ == '__main__':
    sys.exit(main())
