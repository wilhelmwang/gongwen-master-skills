#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门户栏目直扫器（v1.0 · 政府工作报告 / 工作总结）

「发现器」要先抓首页再从导航里找栏目，对**政府工作报告**这种位置固定的栏目反而绕远：
省级门户十有八九把它放在 `/zwgk/zfgzbg/` 或 `/zfxxgk/zfgzbg/` 这类固定路径上
（extra4 已实测命中 15 站）。这里直接按模板打，命中即按页深扫。

域名取三类：`probe_targets.PROVINCIAL`（31 省级）、`mined_domains.txt` 里的
二级域名（省市门户）、以及 `probe_targets` 的地市清单。

用法
----
  python sweep_portals.py --type 工作报告 --pages 40
  python sweep_portals.py --all --pages 30
  python sweep_portals.py --type 工作总结 --dry     # 只看命中不采
"""
import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_columns as sw

try:
    from probe_targets import PROVINCIAL, GUIZHOU_CITY, XINJIANG_CITY
except ImportError:
    PROVINCIAL, GUIZHOU_CITY, XINJIANG_CITY = [], [], []

MINED_TXT = os.path.join(sw.OUT_DIR, 'mined_domains.txt')

#: 政府工作报告：位置最固定的栏目，模板覆盖已验证 + 常见变体
T_REPORT = [
    '/zwgk/zfgzbg/', '/zfxxgk/zfgzbg/', '/xxgk/zfgzbg/', '/zfgzbg/',
    '/zwgk/ghjh/zfgzbg/', '/xxgk/ghjh/zfgzbg/',
    '/zwgk/fdzdgknr/ghjh/zfgzbg/', '/xxgk/fdzdgknr/ghjh/zfgzbg/',
    '/zwgk/zdgk/ghjh/zfgzbg/', '/zfxxgkml/fdzdgknr/qtfdxx/zfgzbg/',
    '/zwgk/ghjh/zfgzbg/index.html', '/zwgk/zfgzbg/index.html',
]

#: 工作总结：厅局与市县的门户常放在「规划计划」族下
T_SUMMARY = [
    '/zwgk/gzzj/', '/xxgk/gzzj/', '/zwgk/ndzj/', '/xxgk/ndzj/',
    '/zwgk/zfxxgk/fdzdgknr/ghjh/', '/zwgk/fdzdgknr/ghjh/',
    '/zwgk/ghjh/', '/xxgk/ghjh/', '/zfxxgk/fdzdgknr/ghjh/',
    '/zwgk/zfxxgk/zfxxgknb/', '/zwgk/xxgknb/', '/xxgk/xxgknb/',
]

#: 调研报告：人大 / 政协 / 政研室 / 统计
T_RESEARCH = [
    '/dybg/', '/dcyj/', '/gzyj/', '/llyj/', '/scdy/', '/dyyj/', '/dycg/',
    '/zwgk/dybg/', '/xxgk/dybg/', '/jcyj/',
    '/zwgk/fdzdgknr/ghjh/dybg/', '/xxgk/fdzdgknr/ghjh/dybg/',
]

TPL = {'工作报告': T_REPORT, '工作总结': T_SUMMARY, '调研报告': T_RESEARCH}
KW = {'工作报告': ['工作报告'], '工作总结': ['总结'], '调研报告': ['调研', '研究', '视察']}


def load_ports():
    """省市门户域名（二级域），部门子站不参与——它们不登政府工作报告"""
    out = []
    for d in PROVINCIAL + GUIZHOU_CITY + XINJIANG_CITY:
        if d not in out:
            out.append(d)
    if os.path.exists(MINED_TXT):
        for line in open(MINED_TXT, encoding='utf-8', errors='replace'):
            d = line.strip().lower()
            if re.match(r'^[a-z0-9\-]{2,16}\.gov\.cn$', d) and d not in out:
                out.append(d)
    return out


def probe(url, kws, timeout):
    try:
        _s, h = sw.cgs.fetch(url, timeout=timeout, retries=2)
    except Exception as e:
        return 0, f'{type(e).__name__}: {str(e)[:50]}'
    if not h or len(h) < 600:
        return 0, 'short'
    try:
        items = sw.detect_items(h, url, kws)
    except Exception:
        return 0, 'parse'
    if not items:
        return 0, ''
    ex = next(iter(items.items()))
    return len(items), f'{ex[1][:26]} → {ex[0][:52]}'


def main():
    ap = argparse.ArgumentParser(description='门户栏目直扫器')
    ap.add_argument('--type', action='append', default=[])
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--pages', type=int, default=30)
    ap.add_argument('--delay', type=float, default=0.7)
    ap.add_argument('--workers', type=int, default=20)
    ap.add_argument('--timeout', type=float, default=12.0)
    ap.add_argument('--min-links', type=int, default=3)
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()

    types = a.type if a.type else (list(TPL) if a.all else [])
    if not types:
        print('指定 --type 或 --all')
        return 2

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

    ports = load_ports()
    if a.limit:
        ports = ports[:a.limit]
    t0 = time.time()
    verified, stats = [], {'req': 0, 'err': 0, 'errs': {}}
    tasks = [(dt, p, t) for dt in types for p in ports for t in TPL[dt]]
    print(f'=== 直扫 {len(tasks)} 个 (域名 × 模板) 组合 ｜ {len(ports)} 域 '
          f'｜ {a.workers} 并发 ===', flush=True)

    def work(item):
        dt, dom, tpl = item
        for base in (f'https://www.{dom}', f'https://{dom}'):
            u = base + tpl
            stats['req'] += 1
            n, msg = probe(u, KW[dt], a.timeout)
            if n >= a.min_links:
                return (dt, u, n, msg)
        return None

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(work, it): it for it in tasks}
        done = 0
        for fu in as_completed(futs):
            done += 1
            it = futs[fu]
            try:
                r = fu.result()
            except Exception as e:
                r = None
                stats['err'] += 1
                tag = f'{type(e).__name__}: {str(e)[:50]}'
                stats['errs'][tag] = stats['errs'].get(tag, 0) + 1
            if r:
                verified.append(r)
                print(f'  HIT\t{r[0]}\t{r[2]:3d}\t{r[1]}\t{r[3]}', flush=True)
            if done % 200 == 0:
                print(f'  .. {done}/{len(tasks)} ｜ 请求 {stats["req"]} '
                      f'｜ 命中 {len(verified)} ｜ {time.time()-t0:.0f}s', flush=True)

    # 同一域名只保留链接数最多的那个模板，避免同栏目换路径重复采
    best = {}
    for dt, u, n, msg in verified:
        dom = u.split('//')[-1].split('/')[0]
        k = (dt, dom)
        if k not in best or n > best[k][2]:
            best[k] = (dt, u, n, msg)
    picks = sorted(best.values(), key=lambda x: -x[2])
    print(f'\n=== 命中 {len(verified)} 个 ｜ 去重后 {len(picks)} 个栏目 '
          f'｜ 请求 {stats["req"]} ｜ 用时 {time.time()-t0:.0f}s ===', flush=True)
    for dt, u, n, _m in picks:
        print(f'  {dt}\t{n:3d}\t{u}', flush=True)
    if a.dry:
        return 0

    total = 0
    for dt, u, _n, _m in picks:
        key = 'pt_' + re.sub(r'\W+', '', u.split('//')[-1])[:28]
        try:
            got, failed, fails = sw.sweep_one(key, dt, u, KW[dt], a.pages, a.delay, seen)
        except Exception as e:
            print(f'  [{key}] 采集异常 {type(e).__name__}: {e}', flush=True)
            continue
        total += got
        print(f'  [{key}] +{got}（失败 {failed}）', flush=True)
        for why, n in fails.most_common(2):
            print(f'        ↳ {n:3d} × {why}', flush=True)
    print(f'\n=== 直扫采集合计: +{total} 篇 ===', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
