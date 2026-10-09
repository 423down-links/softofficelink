#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将 data.json 数据嵌入到 index.html 的 __EMBEDDED_DATA__ 占位符中
"""

import json
import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_JSON = os.path.join(BASE_DIR, 'data.json')
INDEX_HTML = os.path.join(BASE_DIR, 'index.html')

def main():
    with open(DATA_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)

    with open(INDEX_HTML, 'r', encoding='utf-8') as f:
        html = f.read()

    embedded = json.dumps(data, ensure_ascii=False)

    if '__EMBEDDED_DATA__' in html:
        html = html.replace('__EMBEDDED_DATA__', embedded)
    else:
        pattern = r'const EMBEDDED_DATA = \{.*?\};\n'
        replacement = 'const EMBEDDED_DATA = ' + embedded + ';\n'
        html = re.sub(pattern, replacement, html, flags=re.DOTALL)

    with open(INDEX_HTML, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"已嵌入 {len(data['products'])} 个产品数据到 index.html")

if __name__ == '__main__':
    main()
