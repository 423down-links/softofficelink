#!/usr/bin/env python3
"""把带 UA 白名单的官方安装包镜像到 GitHub Release（公开仓匿名可直下）。

背景：FileZilla Pro 的 prodownload 直链只认自家 UA，浏览器点开 403；
Cloudflare（Pages Functions / Worker）fetch 该站又报 526（证书链问题），
唯一稳的免脚本方案是把官方原版包挂到公开仓 Release。

用法：python3 tools/mirror_release.py [--only NAME]
依赖：PATH 里有 gh 且已登录（Actions 用 GITHUB_TOKEN）。
"""
import json
import ssl
import subprocess
import sys
import urllib.request

REPO = '423down-links/softofficelink'

# 产品名 -> 官方直链模板 / UA / 资产文件名模板 / Release tag 模板
MIRRORS = {
    'FileZilla Pro': {
        'url': 'https://prodownload.filezilla-project.org/pro/FileZilla_Pro_{ver}_win64.zip',
        'ua': 'FileZilla',
        'asset': 'FileZilla_Pro_{ver}_win64.zip',
        'tag': 'filezilla-pro-{ver}',
    },
}


def release_exists(tag):
    return subprocess.run(
        ['gh', 'release', 'view', tag, '--repo', REPO],
        capture_output=True).returncode == 0


def download(url, ua, path):
    """官方站证书链异常，这里关校验；UA 必须匹配白名单。"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={'User-Agent': ua})
    with urllib.request.urlopen(req, timeout=180, context=ctx) as r, open(path, 'wb') as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)


def main():
    only = None
    if '--only' in sys.argv:
        only = sys.argv[sys.argv.index('--only') + 1]

    products = {p['name']: p for p in json.load(open('data.json', encoding='utf-8'))['products']}
    for name, cfg in MIRRORS.items():
        if only and name != only:
            continue
        p = products.get(name)
        if not p:
            print(f'{name}: data.json 无此产品，跳过')
            continue
        ver = p['version']
        tag = cfg['tag'].format(ver=ver)
        asset = cfg['asset'].format(ver=ver)
        if release_exists(tag):
            print(f'{name} {ver}: Release {tag} 已存在，跳过')
            continue

        path = f'/tmp/{asset}'
        print(f'{name} {ver}: 下载 {cfg["url"].format(ver=ver)}')
        download(cfg['url'].format(ver=ver), cfg['ua'], path)
        r = subprocess.run(
            ['gh', 'release', 'create', tag, path, '--repo', REPO,
             '--title', f'{name} {ver}',
             '--notes', f'官方原版安装包镜像 {ver}（UA 白名单直链浏览器不可下，故中转）'],
            capture_output=True, text=True)
        if r.returncode != 0:
            print(f'{name} {ver}: 上传失败\n{r.stderr}')
            sys.exit(r.returncode)
        print(f'{name} {ver}: 已上传 Release {tag}')


if __name__ == '__main__':
    main()
