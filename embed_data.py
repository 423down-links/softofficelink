#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将 data.json 数据嵌入到 index.html 的 __EMBEDDED_DATA__ 占位符中
"""

import argparse
import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_JSON = os.path.join(BASE_DIR, 'data.json')
INDEX_HTML = os.path.join(BASE_DIR, 'index.html')

# 线上页面里当前已嵌入的产品数据，用于判断本轮是否发生了截断
_EMBED_RE = re.compile(r'const EMBEDDED_DATA = ')


def _current_products(html):
    """取出 index.html 里现有 EMBEDDED_DATA 的产品列表（取不到返回 None）。"""
    m = _EMBED_RE.search(html)
    if not m:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(html[m.end():].lstrip())
    except ValueError:
        return None
    return obj.get('products') if isinstance(obj, dict) else None


def main():
    parser = argparse.ArgumentParser(description='嵌入 data.json 到 index.html')
    parser.add_argument('--allow-remove', default='',
                        help='显式声明本轮允许从线上移除的产品名（逗号分隔）')
    args = parser.parse_args()

    with open(DATA_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)

    with open(INDEX_HTML, 'r', encoding='utf-8') as f:
        html = f.read()

    products = data.get('products', [])
    new_count = len(products)

    # ===== 产品数量守卫 =====
    # index.html 就是线上页面，嵌入前的条数少于线上现有条数 = 线上产品被截断。
    # 这里拦下来并报出少了谁，确认下线则用 --allow-remove 显式声明。
    old_products = _current_products(html)
    if old_products is not None and new_count < len(old_products):
        new_names = {p.get('name_cn', '') for p in products}
        allow = {x.strip() for x in args.allow_remove.split(',') if x.strip()}
        # 丢失的产品：允许用 name（英文名）或 name_cn（中文名）声明
        lost = [p for p in old_products if p.get('name_cn', '') not in new_names]
        blocked = [p for p in lost
                   if p.get('name_cn', '') not in allow and p.get('name', '') not in allow]
        if blocked:
            print(f"❌ 产品数量守卫拦截：线上 {len(old_products)} 款 → 本轮 {new_count} 款")
            for p in blocked:
                print(f"   - {p.get('name_cn', '')}")
            print("   可能是误改 PRODUCTS（漏配/name 写错/误删）。请先修好，"
                  "确认要下线某产品则用 --allow-remove \"产品名\" 显式声明。")
            print("   本轮不改 index.html，线上页面保持原样。")
            sys.exit(3)
        allowed = [p.get('name_cn', '') for p in lost]
        print(f"ℹ️ 已声明允许移除 {len(allowed)} 款产品: {', '.join(allowed)}")

    embedded = json.dumps(data, ensure_ascii=False)

    if '__EMBEDDED_DATA__' in html:
        html = html.replace('__EMBEDDED_DATA__', embedded)
    else:
        pattern = r'const EMBEDDED_DATA = \{.*?\};\n'
        replacement = 'const EMBEDDED_DATA = ' + embedded + ';\n'
        html = re.sub(pattern, replacement, html, flags=re.DOTALL)

    with open(INDEX_HTML, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"已嵌入 {new_count} 个产品数据到 index.html")

if __name__ == '__main__':
    main()
