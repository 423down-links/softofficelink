#!/usr/bin/env python3
"""版本集体倒退熔断（审计项2）：比对两份 data.json 的逐产品版本。

场景：沙箱旧快照整棵回滚 / 探测器集体抽风时，一次提交会把大量产品版本
打回旧值——产品数量守卫只看条数，看不见版本倒退。这里按 _ver_tuple 数值
元组逐产品比较，倒退数达阈值即拒绝（exit 1）并点名报出倒退了谁。

用法：
  check_no_rollback.py <旧data.json> <新data.json> [--threshold N] [--allow 名1,名2]

被 tools/push_main.sh（推送前）和 data-guard.yml（push 触发校验）复用。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from check_versions import _ver_tuple  # noqa: E402  与检测端同口径的版本比较


def load_versions(path):
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    return {x['name']: str(x.get('version') or '')
            for x in (data.get('products') or [])}


def main():
    ap = argparse.ArgumentParser(description='版本集体倒退熔断')
    ap.add_argument('old', help='旧 data.json（对照基准）')
    ap.add_argument('new', help='新 data.json（待检查）')
    ap.add_argument('--threshold', type=int, default=3,
                    help='倒退产品数达到该值即拒绝（默认 3）')
    ap.add_argument('--allow', default='',
                    help='显式放行的产品名（逗号分隔，口径切换场景）')
    a = ap.parse_args()

    old = load_versions(a.old)
    new = load_versions(a.new)
    allow = {x.strip() for x in a.allow.split(',') if x.strip()}

    down = []
    for name, ov in old.items():
        nv = new.get(name)
        if not ov or not nv or name in allow:
            continue
        if _ver_tuple(nv) < _ver_tuple(ov):
            down.append(f"{name}: {ov} -> {nv}")

    if len(down) >= a.threshold:
        print(f"❌ 版本集体倒退熔断：{len(down)} 款产品版本倒退（阈值 {a.threshold}）")
        for s in down:
            print(f"   - {s}")
        print("   疑似旧快照回滚 / 探测器集体异常；确属口径切换用 --allow \"产品名\" 放行。")
        return 1
    if down:
        print(f"ℹ️ {len(down)} 款版本数值变小（未达阈值 {a.threshold}）: {'; '.join(down)}")
    print(f"✅ 版本倒退检查通过（对照 {len(old)} 款）")
    return 0


if __name__ == '__main__':
    sys.exit(main())
