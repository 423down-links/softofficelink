#!/usr/bin/env python3
"""Summarize an nginx / apache access log.

Usage:
    analyze-log.py <logfile> [--top 20]
    analyze-log.py -              # read from stdin

Supports plain text and .gz. Prints: total/parsed counts, top IPs, paths,
status codes, methods, referers, user-agents, and suspicious probing paths.
"""
import argparse, re, sys
from collections import Counter

# Combined Log Format: ip - - [time] "M P HTTP/x" status size "ref" "ua"
CLF = re.compile(
    r'^(?P<ip>\S+)\s+\S+\s+\S+\s+\[(?P<time>[^\]]+)\]\s+'
    r'"(?P<method>\S+)\s+(?P<path>\S+)\s+(?P<proto>[^"]+)"\s+'
    r'(?P<status>\d+)\s+(?P<size>\S+)'
    r'(?:\s+"(?P<ref>[^"]*)"\s+"(?P<ua>[^"]*)")?'
)

PROBE_PATTERNS = [
    r'/wp-admin', r'/wp-login', r'/xmlrpc\.php', r'/\.env', r'/\.git',
    r'/phpmyadmin', r'/adminer', r'\.php\?', r'/config\.php',
    r'/vendor/', r'/node_modules/', r'/owa/', r'/cgi-bin/',
    r'/\.aws', r'/\.ssh', r'/\.well-known/skip', r'/solr', r'/jenkins',
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", help="log file path, or - for stdin")
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    ips, paths, statuses, methods, refs, uas = (Counter() for _ in range(6))
    probes = Counter()
    total = parsed = 0

    opener = open
    if args.file != "-" and args.file.endswith(".gz"):
        import gzip
        opener = gzip.open

    f = sys.stdin if args.file == "-" else opener(args.file, "rt", errors="replace")
    with f:
        for line in f:
            total += 1
            m = CLF.match(line)
            if not m:
                continue
            parsed += 1
            d = m.groupdict()
            ips[d["ip"]] += 1
            paths[d["path"]] += 1
            statuses[d["status"]] += 1
            methods[d["method"]] += 1
            if d.get("ref") and d["ref"] != "-":
                refs[d["ref"]] += 1
            if d.get("ua") and d["ua"] != "-":
                uas[d["ua"][:80]] += 1
            for pat in PROBE_PATTERNS:
                if re.search(pat, d["path"], re.I):
                    probes[d["path"]] += 1
                    break

    print(f"== {args.file} ==")
    print(f"total lines: {total}, parsed: {parsed} ({100*parsed/max(total,1):.1f}%)")

    def show(name, c):
        print(f"\n-- top {name} ({len(c)} unique) --")
        for k, v in c.most_common(args.top):
            print(f"  {v:8d}  {k}")

    show("IPs", ips)
    show("paths", paths)
    show("status codes", statuses)
    show("methods", methods)
    show("referers", refs)
    show("user-agents", uas)
    show("PROBE hits", probes)


if __name__ == "__main__":
    main()
