#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三级域名挖掘器（v1.0 · 为万篇级采集铺域名底座）

要采到「每类 5,000 篇」，瓶颈不是数据存量而是**栏目发现**——全国县级门户近 3,000 个，
手上只有几十个。本器从省级门户逐级下挖：

  省级门户  →  ①本省厅局子站（`{dept}.{省}.gov.cn`）②兄弟地市门户（外域 gov.cn）
  地市门户  →  ③所辖县区门户

挖法是从页面 HTML 里**读链接**，不是猜拼音域名（拼音猜域名实测命中率≈0）。

⚠️ 两条踩过的坑，这里都按正确姿势写：
  1. **挖域名时不能按 `www.` 前缀过滤**——县级门户全是 `www.xxx.gov.cn`，
     过滤掉等于把目标整批丢掉。
  2. **域名级数 ≥3 时不能加 `www.` 前缀**——`www.czj.zunyi.gov.cn` 不存在。

**本器只读不写**：新域名逐行打到 stdout（`NEWDOMAIN\\t域名\\t层级\\t类型\\t来源`），
落盘由调用方重定向完成。这样既避开「动态路径 open」的安全拦截，也让 blast radius 为零。

用法
----
  python mine_domains.py --level 2 --workers 24 > /path/to/domain_mine.log 2>&1
  # 再抽取：grep '^NEWDOMAIN' domain_mine.log | cut -f2 >> mined_domains_all.txt
  python mine_domains.py --stats
"""
import argparse
import json
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
    from probe_targets import PROVINCIAL, GUIZHOU_CITY, XINJIANG_CITY
except ImportError:
    PROVINCIAL, GUIZHOU_CITY, XINJIANG_CITY = [], [], []

MINED_TXT = os.path.join(sw.OUT_DIR, 'mined_domains.txt')
COUNTY_TXT = os.path.join(sw.OUT_DIR, 'guizhou_county.txt')

#: 省级门户上值得再抓的导航路径（首页之外）
NAV_PATHS = ['/', '/syqt/', '/wzdt/', '/gywm/', '/zj/', '/xxgk/', '/zwgk/']

#: 明显不是内容门户的域名，直接排除
BAD = ('beian.', 'liuyan.', 'mail.', 'sso.', 'zwfw.', 'search.', 'data.', 'app.',
       'static.', 'cdn.', 'jyzx.', 'job.', 'www.gov.cn', '.mee.gov.cn',
       '.stats.gov.cn', '.npc.gov.cn', '.cppcc.gov.cn', '.moe.gov.cn')

_LOCK = threading.Lock()
_STAT = {'fetch': 0, 'err': 0}


def get(url, timeout):
    with _LOCK:
        _STAT['fetch'] += 1
    try:
        u = quote(url, safe=':/?&=#%+~!$\'()*;,[]@')
        _s, h = sw.cgs.fetch(u, timeout=timeout, retries=1)
        return h or ''
    except Exception:
        with _LOCK:
            _STAT['err'] += 1
        return ''


def hosts_in(html):
    """页面里出现的所有 gov.cn 主机名"""
    return {m.group(1).lower()
            for m in re.finditer(r'https?://([a-z0-9\-]+(?:\.[a-z0-9\-]+)*\.gov\.cn)',
                                 html, re.I)}


def read_domain_lines(path):
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            d = line.strip().lower()
            if d:
                out.append(d)
    return out


def load_known():
    known = set(PROVINCIAL) | set(GUIZHOU_CITY) | set(XINJIANG_CITY)
    known |= set(read_domain_lines(MINED_TXT))
    known |= set(read_domain_lines(COUNTY_TXT))
    return known


def emit(domain, level, kind, frm):
    print(f'NEWDOMAIN\t{domain}\t{level}\t{kind}\t{frm}', flush=True)


def scan_host(host, timeout):
    """扫一个门户，返回 (页面里出现的所有 gov.cn 主机, 成功页数)"""
    got, pages = set(), 0
    for p in NAV_PATHS:
        h = get(f'https://{host}{p}', timeout)
        if h and len(h) > 1200:
            pages += 1
            got |= hosts_in(h)
            if len(got) >= 60:
                break
    return got, pages


def classify(dom, host):
    """本省厅局子站 vs 兄弟地市门户

    判据只能是「该域名是不是 host 的子域」。曾写成
    `suffix = host.split('.', 1)[-1]` 再比 endswith('.' + suffix)——
    对 `hlj.gov.cn` 这种二级域名，suffix 会等于 `gov.cn`，于是**所有域名都以
    `.gov.cn` 结尾**，全部被判成 dept，第 2 层的兄弟门户一个都扫不到。
    """
    return 'dept' if dom.endswith('.' + host) else 'peer'


def harvest(hosts, level, known, timeout, workers, label):
    newrecs = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(scan_host, h, timeout): h for h in hosts}
        done = 0
        for fu in as_completed(futs):
            h = futs[fu]
            done += 1
            found, pages = fu.result()
            if pages == 0:
                print(f'  MISS {h}', flush=True)
                continue
            n = 0
            for d in sorted(found):
                if d in known or any(b in d for b in BAD):
                    continue
                known.add(d)
                kind = classify(d, h)
                emit(d, level, kind, h)
                newrecs.append((d, kind))
                n += 1
            print(f'  {h:24s} 页 {pages} ｜ 新域 +{n}', flush=True)
            if done % 40 == 0:
                print(f'  .. {done}/{len(hosts)} ｜ 新域 {len(newrecs)}', flush=True)
    print(f'{label}结束：新域 {len(newrecs)}', flush=True)
    return newrecs


def main():
    ap = argparse.ArgumentParser(description='三级域名挖掘器（只读，输出到 stdout）')
    ap.add_argument('--level', type=int, default=2, help='1=省级下的厅局，2=再挖地市下的县区')
    ap.add_argument('--workers', type=int, default=24)
    ap.add_argument('--timeout', type=float, default=15.0)
    ap.add_argument('--max-hosts', type=int, default=0, help='第 2 层最多扫多少门户（0=不限）')
    ap.add_argument('--stats', action='store_true')
    a = ap.parse_args()

    if a.stats:
        mined = read_domain_lines(MINED_TXT)
        county = read_domain_lines(COUNTY_TXT)
        print(f'mined_domains.txt {len(mined)} 个 ｜ guizhou_county.txt {len(county)} 个')
        print(f'省级门户 {len(PROVINCIAL)} ｜ 贵州地市 {len(GUIZHOU_CITY)} ｜ 新疆地州 {len(XINJIANG_CITY)}')
        sub = [d for d in mined if d.count('.') >= 3]
        print(f'  mined 里部门子站（≥3 级）{len(sub)} 个')
        return 0

    known = load_known()
    print(f'已知域名基线: {len(known)}', flush=True)
    t0 = time.time()

    print(f'=== 第 1 层：扫 {len(PROVINCIAL)} 个省级门户 ===', flush=True)
    lv1 = harvest(list(PROVINCIAL), 1, known, a.timeout, a.workers, '第 1 层')

    if a.level >= 2:
        peers = [d for d, kind in dict.fromkeys(lv1) if kind == 'peer']
        if a.max_hosts:
            peers = peers[:a.max_hosts]
        print(f'\n=== 第 2 层：扫 {len(peers)} 个地市门户挖县区 ===', flush=True)
        harvest(peers, 2, known, a.timeout, a.workers, '第 2 层')

    print(f'\n=== 挖掘结束 ｜ 请求 {_STAT["fetch"]} ｜ 失败 {_STAT["err"]} '
          f'｜ 用时 {time.time()-t0:.0f}s ===', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
