#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
site-report.py — 网站访问日志分析器（combined / JSON 两种 nginx 格式）

替代宝塔「网站监控报表」核心能力的云端分析工具：
  概览（PV / 页面PV / UV(去重IP) / 总流量 / 状态码构成）
  小时趋势、搜索引擎蜘蛛抓取、设备/系统分布、
  Top IP / 页面 / 入口来源、攻击扫描识别、高频 404 监控

用法：
  python3 site-report.py access.log(.gz) [access2.log.gz ...]
      [--top 30] [--out report.html] [--title "站点名"]
  cat a.log | python3 site-report.py - --out r.html

零依赖（仅标准库），生成自包含 HTML，浏览器直接打开。
"""
import argparse
import gzip
import html
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime

# ---------- 解析 ----------
CLF_RE = re.compile(
    r'^(?P<ip>\S+)\s+\S+\s+\S+\s+\[(?P<time>[^\]]+)\]\s+'
    r'"(?P<method>\S+)\s+(?P<path>\S+)\s+(?P<proto>[^"]*)"\s+'
    r'(?P<status>\d{3})\s+(?P<size>\S+)'
    r'(?:\s+"(?P<ref>[^"]*)"\s+"(?P<ua>[^"]*)")?'
)
STATIC_RE = re.compile(
    r'\.(?:css|js|mjs|png|jpe?g|gif|ico|woff2?|ttf|svg|webp|map|bmp|cur|mp[34]|avi|mov|exe|zip|rar|7z|apk|dmg|iso|gz|tar|bin|font)$',
    re.I)
FEED_RE = re.compile(r'/(?:feed|rss|atom|wp-json|xmlrpc\.php|.*sitemap.*\.xml|robots\.txt|favicon\.ico)', re.I)

SPIDERS = [
    # (UA 关键字, 展示名)
    ("Baiduspider-render", "百度渲染"), ("Baiduspider", "百度"),
    ("Googlebot", "Google"), ("Mediapartners-Google", "Google-AdSense"),
    ("AdsBot-Google", "Google-Ads"),
    ("bingbot", "必应"), ("360Spider", "360"), ("HaosouSpider", "360好搜"),
    ("Sogou", "搜狗"), ("Bytespider", "字节/抖音"), ("YisouSpider", "神马UC"),
    ("PetalBot", "华为花瓣"), ("YandexBot", "Yandex"), ("DuckDuckBot", "DuckDuckGo"),
    ("Applebot", "Apple"), ("Qwantify", "Qwant"),
    ("GPTBot", "GPTBot"), ("OAI-SearchBot", "OpenAI搜索"), ("ClaudeBot", "Claude"),
    ("Claude-Web", "Claude"), ("PerplexityBot", "Perplexity"),
    ("AhrefsBot", "Ahrefs"), ("SemrushBot", "Semrush"), ("MJ12bot", "MJ12"),
    ("DotBot", "DotBot"), ("BLEXBot", "BLEX"), ("SEMrush", "Semrush"),
    ("facebookexternalhit", "Facebook"), ("Twitterbot", "Twitter/X"),
    ("LinkedInBot", "LinkedIn"), ("TelegramBot", "Telegram"),
    ("ia_archiver", "Alexa"), ("Discordbot", "Discord"),
]
SCANNERS = [
    "Censys", "zgrab", "masscan", "nmap", "sqlmap", "Nikto", "Nuclei",
    "Acunetix", "wpscan", "dirbuster", "gobuster", "python-requests",
    "Go-http-client", "curl/", "Wget/", "libwww-perl", "okhttp",
    "ModatScanner", "InternetMeasurement", "NetSystemsResearch",
    "Shodan", "AlphaVantage", "bbot", "fuzz", "CensysInspect",
    "HeadlessChrome", "wp_is", "cortex",
]
PROBE_PATH_RE = re.compile(
    r'/(?:wp-admin|wp-login|xmlrpc\.php|wp-content/plugins|wp-includes|\.env|\.git|'
    r'phpmyadmin|pma|adminer|\.aws|\.ssh|vendor/|node_modules/|cgi-bin/|owa/|'
    r'jenkins|solr|actuator|druid|\.well-known/security|config\.php|shell|cmd|'
    r'boaform|setup\.cgi|HNAP1|fcgi-bin|phpinfo)', re.I)


def classify_ua(ua):
    """返回 (类别, 名称)。类别: spider / scanner / browser / other"""
    u = ua or ""
    for kw, name in SPIDERS:
        if kw.lower() in u.lower():
            return "spider", name
    for kw in SCANNERS:
        if kw.lower() in u.lower():
            return "scanner", kw
    if re.search(r'(Mozilla|Chrome|Safari|Firefox|Edge|MiuiBrowser|UCBrowser|Quark)', u, re.I):
        return "browser", ""
    return "other", ""


def device_of(ua):
    u = (ua or "").lower()
    if re.search(r'(android|iphone|ipad|ipod|harmony|mobile|miui|quark/)', u):
        return "移动端"
    if re.search(r'(windows nt|macintosh|x11|cros)|mac os x', u):
        return "PC端"
    return "其他"


def open_log(path):
    if path == "-":
        return sys.stdin
    op = gzip.open if path.endswith(".gz") else open
    return op(path, "rt", errors="replace")


def parse_line(line):
    line = line.rstrip("\n")
    if line.startswith("{"):
        try:
            d = json.loads(line)
            return {
                "ip": d.get("remote_addr") or d.get("cf_connecting_ip") or "-",
                "time": d.get("time_local", ""),
                "method": d.get("method", "-"),
                "path": d.get("uri", "-"),
                "status": str(d.get("status", "000")),
                "size": int(d.get("body_bytes_sent", 0) or 0),
                "ref": d.get("referer", "-") or "-",
                "ua": d.get("user_agent", "-") or "-",
            }
        except Exception:
            return None
    m = CLF_RE.match(line)
    if not m:
        return None
    d = m.groupdict()
    try:
        size = int(d["size"]) if d["size"] not in (None, "-", "") else 0
    except ValueError:
        size = 0
    return {
        "ip": d["ip"], "time": d["time"], "method": d["method"],
        "path": d["path"], "status": d["status"], "size": size,
        "ref": d.get("ref") or "-", "ua": d.get("ua") or "-",
    }


def hour_of(timestr):
    # 01/Oct/2026:13:00:01 +0800
    m = re.search(r':(\d{2}):\d{2}:\d{2}', timestr)
    return int(m.group(1)) if m else -1


def date_of(timestr):
    m = re.match(r'\d{2}/\w{3}/\d{4}', timestr)
    return m.group(0) if m else "?"


def path_key(path):
    # 去掉 query，合并同类页面
    return path.split("?", 1)[0]


# ---------- 聚合 ----------
def aggregate(paths, top_n):
    total = parsed = 0
    ips = Counter()
    pages = Counter()
    status_all = Counter()
    status_class = Counter()
    methods = Counter()
    refs = Counter()
    uas = Counter()
    spiders = Counter()
    scanners = Counter()
    devices = Counter()
    hour_pv = Counter()
    hour_uv = defaultdict(set)
    spider_hour = Counter()
    bytes_total = 0
    page_bytes = 0
    page_pv = 0
    browser_ips = set()
    spider_ips = set()
    scanner_ips = set()
    probe_paths = Counter()
    status404_ip = Counter()
    wp_post = 0
    wp_get = 0
    wp_ok = 0
    wp_ips = Counter()
    wp_register = 0
    dates = Counter()
    errors5xx = Counter()

    for path in paths:
        with open_log(path) as f:
            for line in f:
                total += 1
                d = parse_line(line)
                if not d:
                    continue
                parsed += 1
                ip, ua, ref = d["ip"], d["ua"], d["ref"]
                p = path_key(d["path"])
                st = d["status"]
                h = hour_of(d["time"])
                dates[date_of(d["time"])] += 1

                ips[ip] += 1
                status_all[st] += 1
                status_class[f"{st[0]}xx"] += 1
                methods[d["method"]] += 1
                bytes_total += d["size"]
                if h >= 0:
                    hour_pv[h] += 1
                    hour_uv[h].add(ip)
                uas[ua[:120]] += 1

                cat, sname = classify_ua(ua)
                if cat == "spider":
                    spiders[sname] += 1
                    spider_ips.add(ip)
                    if h >= 0:
                        spider_hour[h] += 1
                elif cat == "scanner":
                    scanners[ip] += 1
                    scanner_ips.add(ip)
                else:
                    if cat == "browser":
                        browser_ips.add(ip)
                        devices[device_of(ua)] += 1

                is_static = bool(STATIC_RE.search(p))
                is_feed = bool(FEED_RE.search(p))
                if not is_static and not is_feed and d["method"] in ("GET", "POST"):
                    pages[p] += 1
                    page_pv += 1
                    page_bytes += d["size"]

                if ref and ref != "-" and not ref.startswith("-"):
                    refs[ref[:180]] += 1

                if PROBE_PATH_RE.search(p):
                    probe_paths[p] += 1
                if st == "404":
                    status404_ip[ip] += 1
                if st.startswith("5"):
                    errors5xx[p] += 1
                # WordPress 登录爆破专题
                if p.startswith("/wp-login.php"):
                    if d["method"] == "POST":
                        wp_post += 1
                        wp_ips[ip] += 1
                        if st == "200":
                            wp_ok += 1
                    elif d["method"] == "GET":
                        wp_get += 1
                    if "action=register" in d["path"]:
                        wp_register += 1

    return {
        "total": total, "parsed": parsed,
        "pv": parsed, "page_pv": page_pv,
        "uv": len(ips), "browser_uv": len(browser_ips),
        "spider_uv": len(spider_ips), "scanner_uv": len(scanner_ips),
        "bytes_total": bytes_total, "page_bytes": page_bytes,
        "ips": ips, "pages": pages, "status_all": status_all,
        "status_class": status_class, "methods": methods,
        "refs": refs, "uas": uas, "spiders": spiders,
        "scanners": scanners, "devices": devices,
        "hour_pv": hour_pv, "hour_uv": hour_uv, "spider_hour": spider_hour,
        "probes": probe_paths, "status404_ip": status404_ip,
        "errors5xx": errors5xx, "dates": dates,
        "wp_post": wp_post, "wp_get": wp_get, "wp_ok": wp_ok,
        "wp_ips": wp_ips, "wp_register": wp_register,
    }


def human_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024
    return f"{n:.1f}PB"


def bar_rows(counter, total, top_n):
    rows = []
    mx = max((v for _, v in counter.most_common(top_n)), default=1) or 1
    for k, v in counter.most_common(top_n):
        pct = 100.0 * v / total if total else 0
        width = max(1, int(100 * v / mx))
        rows.append((html.escape(str(k)[:110]), v, pct, width))
    return rows


# ---------- HTML ----------
CSS = """
body{font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;margin:0;background:#f4f6fa;color:#222}
.wrap{max-width:1080px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:24px;margin:0 0 4px} .sub{color:#888;font-size:13px;margin-bottom:22px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:22px}
.card{background:#fff;border-radius:10px;padding:16px;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.card .v{font-size:26px;font-weight:700;color:#1a56db} .card .l{font-size:12px;color:#888;margin-top:4px}
.card.warn .v{color:#d97706} .card.bad .v{color:#dc2626} .card.ok .v{color:#059669}
section{background:#fff;border-radius:10px;padding:18px 20px;margin-bottom:18px;box-shadow:0 1px 3px rgba(0,0,0,.06)}
h2{font-size:16px;margin:0 0 14px;border-left:4px solid #1a56db;padding-left:10px}
table{width:100%;border-collapse:collapse;font-size:13px}
td,th{padding:6px 8px;border-bottom:1px solid #eef0f4;text-align:left;vertical-align:middle}
th{color:#999;font-weight:500} .num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.track{background:#eef2ff;height:14px;border-radius:7px;overflow:hidden;min-width:90px}
.fill{background:linear-gradient(90deg,#3b82f6,#1a56db);height:100%;border-radius:7px}
.spider .fill{background:linear-gradient(90deg,#34d399,#059669)}
.probe .fill{background:linear-gradient(90deg,#fbbf24,#d97706)}
.bad .fill{background:linear-gradient(90deg,#f87171,#dc2626)}
tr:hover{background:#f8fafc}
.hours{display:flex;align-items:flex-end;gap:3px;height:130px;padding-top:10px}
.hb{flex:1;background:#dbeafe;border-top:3px solid #1a56db;position:relative;min-height:2px;border-radius:2px 2px 0 0}
.hb:hover{background:#bfdbfe}
.hb span{display:none;position:absolute;bottom:100%;left:50%;transform:translateX(-50%);background:#111827;color:#fff;padding:3px 6px;border-radius:4px;font-size:11px;white-space:nowrap;z-index:2}
.hb:hover span{display:block}
.hlabels{display:flex;gap:3px;font-size:10px;color:#999;margin-top:4px} .hlabels div{flex:1;text-align:center}
.legend{font-size:12px;color:#666;margin-top:8px} .dot{display:inline-block;width:9px;height:9px;border-radius:2px;margin:0 4px 0 12px}
.tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:10px;background:#eef2ff;color:#1a56db;margin-left:6px}
"""


def table(rows, headers, klass="", value_col=1):
    out = [f'<table class="{klass}">', "<tr>"]
    for h in headers:
        out.append(f"<th>{h}</th>")
    out.append("</tr>")
    for label, v, pct, width in rows:
        out.append(
            f'<tr><td>{label}</td>'
            f'<td class="num">{v:,}</td>'
            f'<td style="width:45%"><div class="track"><div class="fill" style="width:{width}%"></div></div></td>'
            f'<td class="num" style="color:#888">{pct:.1f}%</td></tr>')
    out.append("</table>")
    return "\n".join(out)


def render_html(a, title, top_n):
    pv, ppv = a["pv"], a["page_pv"]
    date_range = ", ".join(f"{k}({v:,}行)" for k, v in sorted(a["dates"].items()))
    parts = [f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} - 访问分析报告</title><style>{CSS}</style></head><body><div class="wrap">
<h1>{html.escape(title)} · 访问分析报告</h1>
<div class="sub">数据时间：{html.escape(date_range)} ｜ 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')} ｜ 日志解析率 {a['parsed']/max(a['total'],1)*100:.1f}%</div>

<div class="cards">
  <div class="card"><div class="v">{pv:,}</div><div class="l">总请求 PV</div></div>
  <div class="card ok"><div class="v">{ppv:,}</div><div class="l">页面请求 PV（剔除静态/feed）</div></div>
  <div class="card"><div class="v">{a['uv']:,}</div><div class="l">UV（去重IP）</div></div>
  <div class="card"><div class="v">{a['browser_uv']:,}</div><div class="l">真实浏览器 UV</div></div>
  <div class="card ok"><div class="v">{a['spider_uv']:,}</div><div class="l">蜘蛛 IP 数</div></div>
  <div class="card {'bad' if a['scanner_uv'] else ''}"><div class="v">{a['scanner_uv']:,}</div><div class="l">扫描器 IP 数</div></div>
  <div class="card"><div class="v">{human_bytes(a['bytes_total'])}</div><div class="l">总流量</div></div>
  <div class="card"><div class="v">{100*a['status_class'].get('2xx',0)/max(pv,1):.1f}%</div><div class="l">2xx 成功率</div></div>
</div>
"""]

    # 小时趋势
    maxh = max((a["hour_pv"].get(h, 0) for h in range(24)), default=1) or 1
    parts.append('<section><h2>24 小时访问趋势</h2><div class="hours">')
    for h in range(24):
        v = a["hour_pv"].get(h, 0)
        uv = len(a["hour_uv"].get(h, ()))
        sp = a["spider_hour"].get(h, 0)
        hgt = max(2, int(100 * v / maxh))
        parts.append(f'<div class="hb" style="height:{hgt}%"><span>{h:02d}时 PV {v:,} / UV {uv:,} / 蜘蛛 {sp:,}</span></div>')
    parts.append('</div><div class="hlabels">')
    for h in range(24):
        parts.append(f"<div>{h:02d}</div>")
    parts.append('</div>')
    parts.append('<div class="legend"><span class="dot" style="background:#1a56db"></span>每小时总请求（悬停看 PV/UV/蜘蛛明细）</div></section>')

    # 状态码
    parts.append('<section><h2>HTTP 状态码分布</h2><table><tr><th>类别</th><th></th><th></th><th></th></tr>')
    for cls in ("2xx", "3xx", "4xx", "5xx"):
        v = a["status_class"].get(cls, 0)
        pct = 100 * v / max(pv, 1)
        w = int(pct)
        color = "#059669" if cls == "2xx" else "#1a56db" if cls == "3xx" else "#d97706" if cls == "4xx" else "#dc2626"
        parts.append(f'<tr><td>{cls}</td><td class="num">{v:,}</td>'
                     f'<td style="width:45%"><div class="track"><div class="fill" style="width:{w}%;background:{color}"></div></div></td>'
                     f'<td class="num" style="color:#888">{pct:.2f}%</td></tr>')
    parts.append('</table>')
    parts.append('<div style="margin-top:14px"><strong style="font-size:13px">Top 状态码明细</strong>')
    parts.append(table(bar_rows(a["status_all"], pv, 10), ["状态码", "次数", "", "占比"]))
    parts.append('</div></section>')

    # 蜘蛛
    sp_total = sum(a["spiders"].values())
    parts.append(f'<section><h2>搜索引擎蜘蛛抓取（共 {sp_total:,} 次）</h2>')
    if sp_total:
        parts.append(table(bar_rows(a["spiders"], sp_total, top_n), ["蜘蛛", "抓取次数", "", "占比"], "spider"))
    else:
        parts.append('<p style="color:#888">未识别到蜘蛛</p>')
    parts.append('</section>')

    # 设备
    if a["devices"]:
        dv = sum(a["devices"].values())
        parts.append(f'<section><h2>访客设备分布（真实浏览器请求 {dv:,}）</h2>')
        parts.append(table(bar_rows(a["devices"], dv, 5), ["设备", "请求数", "", "占比"]))
        parts.append('</section>')

    # Top 页面
    parts.append(f'<section><h2>热门页面 Top {top_n}</h2>')
    parts.append(table(bar_rows(a["pages"], a["page_pv"], top_n), ["URL 路径", "PV", "", "占页面PV比"]))
    parts.append('</section>')

    # Top IP
    parts.append(f'<section><h2>Top IP（{a["uv"]:,} 个去重 IP）</h2>')
    rows = bar_rows(a["ips"], pv, top_n)
    parts.append(table(rows, ["IP", "请求数", "", "占比"]))
    parts.append('</section>')

    # Referer
    parts.append(f'<section><h2>入口来源 Referer Top {min(top_n,20)}</h2>')
    if a["refs"]:
        parts.append(table(bar_rows(a["refs"], sum(a["refs"].values()), min(top_n, 20)), ["来源 URL", "次数", "", "占比"]))
    else:
        parts.append('<p style="color:#888">无 Referer 数据（多为直接访问/APP/隐私模式）</p>')
    parts.append('</section>')

    # 扫描探测
    parts.append('<section class="probe"><h2>安全：扫描/探测请求</h2>')
    if a["wp_post"] > 50:
        parts.append(
            '<div style="background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:12px 16px;margin-bottom:16px">'
            f'<div style="color:#dc2626;font-weight:700;font-size:14px">⚠ WordPress 登录爆破告警</div>'
            f'<div style="font-size:13px;margin-top:6px;color:#444">'
            f'POST /wp-login.php 登录提交 <b>{a["wp_post"]:,}</b> 次，来自 <b>{len(a["wp_ips"]):,}</b> 个 IP，'
            f'其中返回 200（到达登录程序）<b>{a["wp_ok"]:,}</b> 次；GET 登录页 {a["wp_get"]:,} 次'
            + (f'；注册页 action=register 被访问 <b>{a["wp_register"]:,}</b> 次' if a["wp_register"] else '')
            + '。建议：限制 wp-login 访问、启用强口令+二步验证、检查 WAF 规则。'
            '</div></div>')
        parts.append('<div style="margin-bottom:14px"><strong style="font-size:13px">爆破最频繁的 IP：</strong></div>')
        parts.append(table(bar_rows(a["wp_ips"], a["wp_post"], 15), ["IP", "POST次数", "", ""], "probe"))
    if a["probes"]:
        parts.append(f'<p style="font-size:13px">识别到 <b style="color:#d97706">{sum(a["probes"].values()):,}</b> 次针对敏感路径的请求，Top 路径：</p>')
        parts.append(table(bar_rows(a["probes"], sum(a["probes"].values()), 15), ["被探测路径", "次数", "", ""], "probe"))
    else:
        parts.append('<p style="color:#059669">未发现典型扫描路径请求</p>')
    if a["scanners"]:
        parts.append(f'<p style="font-size:13px;margin-top:14px">高频扫描器 IP Top：</p>')
        parts.append(table(bar_rows(a["scanners"], sum(a["scanners"].values()), 15), ["扫描器 IP", "请求数", "", ""], "probe"))
    if a["status404_ip"]:
        parts.append(f'<p style="font-size:13px;margin-top:14px">404 最多的 IP（可能在爆破路径）：</p>')
        parts.append(table(bar_rows(a["status404_ip"], sum(a["status404_ip"].values()), 10), ["IP", "404次数", "", ""], "probe"))
    parts.append('</section>')

    # 5xx
    if a["errors5xx"]:
        parts.append('<section class="bad"><h2>5xx 服务器错误页面</h2>')
        parts.append(table(bar_rows(a["errors5xx"], sum(a["errors5xx"].values()), 15), ["URL", "5xx次数", "", ""], "bad"))
        parts.append('</section>')

    # Top UA
    parts.append(f'<section><h2>User-Agent Top 10</h2>')
    parts.append(table(bar_rows(a["uas"], pv, 10), ["UA", "次数", "", "占比"]))
    parts.append('</section>')

    parts.append('<div class="sub">由 site-report.py 生成 · UV 为日志去重 IP 近似值（CDN/NAT 场景会偏低）· 页面PV 已剔除静态资源与 feed 请求</div>')
    parts.append('</div></body></html>')
    return "".join(parts)


def console_summary(a, title):
    print(f"\n===== {title} =====")
    print(f"解析 {a['parsed']:,}/{a['total']:,} 行")
    print(f"PV={a['pv']:,}  页面PV={a['page_pv']:,}  UV(IP)={a['uv']:,}  "
          f"浏览器UV={a['browser_uv']:,}  蜘蛛IP={a['spider_uv']:,}  扫描器IP={a['scanner_uv']:,}")
    print(f"流量={human_bytes(a['bytes_total'])}  状态码={dict(a['status_class'])}")
    print("蜘蛛 Top5:", a["spiders"].most_common(5))
    print("热门页面 Top5:", a["pages"].most_common(5))
    print("Top IP5:", a["ips"].most_common(5))
    print("探测请求:", sum(a["probes"].values()), " 5xx页面:", sum(a["errors5xx"].values()))
    if a["wp_post"] > 50:
        print(f"⚠ wp-login 爆破: POST {a['wp_post']:,} 次 / {len(a['wp_ips']):,} IP, 返回200 {a['wp_ok']:,} 次, register访问 {a['wp_register']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--out", default="")
    ap.add_argument("--title", default="网站")
    args = ap.parse_args()

    a = aggregate(args.logs, args.top)
    if a["parsed"] == 0:
        print("ERROR: 没有解析到任何日志行（格式是否为 nginx combined / JSON）", file=sys.stderr)
        sys.exit(1)
    console_summary(a, args.title)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(render_html(a, args.title, args.top))
        print(f"HTML report -> {args.out}")


if __name__ == "__main__":
    main()
