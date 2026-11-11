#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""县区域名挖掘器（只读，输出到 stdout）

为什么单独写一个
----------------
`mine_domains.py --level 2` 走「省级 → 地市 → 县区」，但贵州几个市州门户的县区导航是
JS 渲染的，那一层几乎没挖到（全库二级门户只有 41 个）。

换的路子：**县级门户的站群导航通常把同平台的所有兄弟县都列出来**——
贵州系站点底部/顶部有「贵州省人大网站群：遵义 | 六盘水 | 安顺 …」这类整列，
挖一个县就能带出一片兄弟县。Xinjiang / Hunan 系同理。

种子取：已知全部二级门户 + 已挖到的县区域名 + probe_targets 的地市清单。
判据：域名级数 == 2 且是 gov.cn → 县区门户；≥3 级 → 部门子站（另计）。

⚠️ 挖域名时**不按 `www.` 前缀过滤**——县级门户全是 `www.xxx.gov.cn`（这个错犯过）。

用法
----
  python mine_counties.py --workers 24 > counties.log 2>&1
  # 抽取：grep '^NEWCOUNTY' counties.log | cut -f2
"""
import argparse
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_columns as sw

try:
    from probe_targets import PROVINCIAL, GUIZHOU_CITY, GUIZHOU_COUNTY, XINJIANG_CITY
except ImportError:
    PROVINCIAL = GUIZHOU_CITY = GUIZHOU_COUNTY = XINJIANG_CITY = []

MINED_TXT = os.path.join(sw.OUT_DIR, 'mined_domains.txt')
COUNTY_TXT = os.path.join(sw.OUT_DIR, 'guizhou_county.txt')

NAV_PATHS = ['/', '/syqt/wzdt/', '/wzdt/', '/gywm/', '/zj/', '/xwzx/', '/zwgk/']

BAD = ('beian.', 'liuyan.', 'mail.', 'sso.', 'zwfw.', 'search.', 'data.', 'app.',
       'static.', 'cdn.', 'jyzx.', 'job.', 'www.gov.cn', '.mee.gov.cn',
       '.stats.gov.cn', '.npc.gov.cn', '.cppcc.gov.cn', '.moe.gov.cn')
_S = {'fetch': 0, 'err': 0}
_L = threading.Lock()


def get(url, timeout):
    with _L:
        _S['fetch'] += 1
    try:
        u = quote(url, safe=':/?&=#%+~!$\'()*;,[]@')
        _s, h = sw.cgs.fetch(u, timeout=timeout, retries=1)
        return h or ''
    except Exception:
        with _L:
            _S['err'] += 1
        return ''


def hosts_in(html):
    return {m.group(1).lower()
            for m in re.finditer(r'https?://([a-z0-9\-]+(?:\.[a-z0-9\-]+)*\.gov\.cn)',
                                 html, re.I)}


def read_lines(p):
    out = []
    if os.path.exists(p):
        for line in open(p, encoding='utf-8', errors='replace'):
            d = line.strip().lower()
            if d:
                out.append(d)
    return out


def seeds():
    s = set(PROVINCIAL) | set(GUIZHOU_CITY) | set(GUIZHOU_COUNTY) | set(XINJIANG_CITY)
    s |= set(read_lines(COUNTY_TXT))
    # 全部已知二级门户（含省级、地市、县区）都当种子
    for d in read_lines(MINED_TXT):
        if d.count('.') == 2:
            s.add(d)
    return sorted(d for d in s if d.endswith('.gov.cn'))


def scan(host, timeout):
    got, pages = set(), 0
    for p in NAV_PATHS:
        h = get(f'https://{host}{p}', timeout)
        if h and len(h) > 1200:
            pages += 1
            got |= hosts_in(h)
    return got, pages


def main():
    ap = argparse.ArgumentParser(description='县区域名挖掘器（只读）')
    ap.add_argument('--workers', type=int, default=24)
    ap.add_argument('--timeout', type=float, default=14.0)
    a = ap.parse_args()

    known = set(read_lines(MINED_TXT)) | set(read_lines(COUNTY_TXT))
    known |= set(PROVINCIAL) | set(GUIZHOU_CITY) | set(GUIZHOU_COUNTY) | set(XINJIANG_CITY)
    sd = seeds()
    print(f'已知域名 {len(known):,} ｜ 种子门户 {len(sd):,}', flush=True)

    newc, newd = [], []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(scan, h, a.timeout): h for h in sd}
        done = 0
        for fu in as_completed(futs):
            h = futs[fu]
            done += 1
            found, pages = fu.result()
            c = d = 0
            for x in sorted(found):
                if x in known or any(b in x for b in BAD):
                    continue
                known.add(x)
                if x.count('.') == 2:
                    print(f'NEWCOUNTY\t{x}\t来自 {h}', flush=True)
                    newc.append(x)
                    c += 1
                else:
                    print(f'NEWDEPT\t{x}\t来自 {h}', flush=True)
                    newd.append(x)
                    d += 1
            if c or d:
                print(f'  {h:26s} 页 {pages} ｜ 县区 +{c} 部门 +{d}', flush=True)
            if done % 30 == 0:
                print(f'  .. {done}/{len(sd)} ｜ 县区 {len(newc)} 部门 {len(newd)} ｜ '
                      f'{time.time()-t0:.0f}s', flush=True)

    print(f'\n=== 挖掘结束：新县区门户 {len(newc)} ｜ 新部门子站 {len(newd)} '
          f'｜ 请求 {_S["fetch"]} 失败 {_S["err"]} ｜ 用时 {time.time()-t0:.0f}s ===',
          flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
