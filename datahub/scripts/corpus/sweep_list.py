#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按清单直采器（v1.0）

探测器把命中栏目打在日志里，本器把那份清单（`discovered_columns.json`，
形如 `[{"doc_type": "...", "url": "...", "links": n}]`）直接交给 `sweep_one` 采。
探测与采集分两步的好处：探测可以并发跑、可以失败重试，采集这一步保持单进程串行，
不会有两个进程同时往 `collected.jsonl` 追加。

用法
----
  python sweep_list.py --from discovered_columns.json --pages 20
  python sweep_list.py --from discovered_columns.json --type 工作总结 --dry
"""
import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_columns as sw

KW = {'工作总结': ['总结'], '工作报告': ['工作报告'], '调研报告': ['调研', '研究', '视察'],
      '会议纪要': ['会议'], '消息': ['调研', '考察', '召开', '举行']}


def main():
    ap = argparse.ArgumentParser(description='按清单直采器')
    ap.add_argument('--from', dest='src', required=True, help='栏目清单 JSON')
    ap.add_argument('--type', action='append', default=[], help='只采某类（可重复）')
    ap.add_argument('--pages', type=int, default=20)
    ap.add_argument('--delay', type=float, default=0.7)
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    rows = json.load(open(a.src, encoding='utf-8'))
    if a.type:
        rows = [r for r in rows if r.get('doc_type') in a.type]
    rows.sort(key=lambda r: -(r.get('links') or 0))
    print(f'待采 {len(rows)} 个栏目', flush=True)

    seen = set()
    fp = os.path.join(sw.OUT_DIR, 'collected.jsonl')
    if os.path.exists(fp):
        for l in open(fp, 'rb'):
            try:
                r = json.loads(l.decode('utf-8', 'replace'))
                if r.get('url'):
                    seen.add(r['url'])
            except Exception:
                pass
    print(f'去重基线: {len(seen)}', flush=True)
    if a.dry:
        for r in rows:
            print(f"  {r['doc_type']}\t{r.get('links')}\t{r['url']}")
        return 0

    t0 = time.time()
    total = 0
    for r in rows:
        dt, u = r['doc_type'], r['url']
        kws = KW.get(dt) or ['总结']
        key = 'dl_' + re.sub(r'\W+', '', u.split('//')[-1])[:28]
        try:
            got, failed, fails = sw.sweep_one(key, dt, u, kws, a.pages, a.delay, seen)
        except Exception as e:
            print(f'  [{key}] 采集异常 {type(e).__name__}: {e}', flush=True)
            continue
        total += got
        print(f'  [{key}] +{got}（失败 {failed}）｜ {u[:70]}', flush=True)
        for why, n in fails.most_common(2):
            print(f'        ↳ {n:3d} × {why}', flush=True)
    print(f'\n=== 直采合计: +{total} 篇 ｜ 用时 {time.time()-t0:.0f}s ===', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
