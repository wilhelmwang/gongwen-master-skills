#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""深翻 + 家族复制采集器（v1.0）

两件事，分开跑、串行写，避免两个进程同时追加 `collected.jsonl`。

**phase=cols｜深翻已验证栏目**
已有 183 个栏目里，一批高产的页限设得很浅（横州总结 4 页得 78 篇、古田 3 页得 44 篇、
广州人大调研 2 页得 21 篇）——`page_yield = 产量 / 页限` 高就说明还没翻到底。
本阶段按产量降序深翻，页深可调，翻到底（列表页取不到新条目）自然停。

**phase=family｜家族复制**
政府网站的路径是模板化的：同一套平台把栏目挂在同一批路径词下。
`probe_targets.py` 里的域名来自**站群导航实测**（不是拼音猜域名），
按家族套路径模板，命中一个就吃一片。

用法
----
  python sweep_deep.py --phase cols   --min-yield 8 --pages 60 --delay 0.35
  python sweep_deep.py --phase family --pages 30 --delay 0.5
  python sweep_deep.py --phase family --family gz_report --dry
"""
import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_columns as sw

try:
    from probe_targets import (PROVINCIAL, GUIZHOU_CITY, GUIZHOU_COUNTY,
                               XINJIANG_CITY, ZUNYI_DEPT, XINJIANG_DEPT)
except ImportError:
    PROVINCIAL = GUIZHOU_CITY = GUIZHOU_COUNTY = XINJIANG_CITY = []
    ZUNYI_DEPT = XINJIANG_DEPT = []

MINED_TXT = os.path.join(sw.OUT_DIR, 'mined_domains.txt')
COUNTY_TXT = os.path.join(sw.OUT_DIR, 'guizhou_county.txt')


def gz_county_domains():
    """从市州门户首页内联的县区导航挖出的县级门户（`title="××县"` 那批）。

    ⚠️ 挖域名时**不能过滤 `www.` 前缀**——县级门户几乎全是 `www.xxx.gov.cn`，
    按 `d.startswith('www.')` 跳过等于把目标全滤掉（这个错犯过一次）。
    """
    out = []
    if os.path.exists(COUNTY_TXT):
        for line in open(COUNTY_TXT, encoding='utf-8', errors='replace'):
            d = line.strip().lower()
            if re.match(r'^[a-z0-9.\-]+\.gov\.cn$', d):
                out.append(d)
    return out

#: 区县聚合总结栏——一个栏目吃几十个部门的年度总结，实测命中率最高的路径词
AGG_SUM = ['/zwgk/ghjh/bmjhzj/', '/zwgk/ghjh/ndgzjhhzj/', '/zwgk/ghjh/ndgzjhhz/',
           '/zwgk/fdzdgknr/ghjh/', '/zwgk/zfxxgk/fdzdgknr/ghjh/',
           '/zwgk/gzzj/', '/xxgk/gzzj/', '/zwgk/ghjh/NDJH/']

FAMILIES = {
    # 贵州县区系：全省统一平台，`/zwgk/zfgzbg/` 已在 24 个已验证站点全部命中
    'gz_report': dict(
        domains=lambda: GUIZHOU_CITY + GUIZHOU_COUNTY + gz_county_domains(),
        templates=['/zwgk/zfgzbg/', '/zwgk/ghjh/zfgzbg/', '/zfxxgk/zfgzbg/'],
        doc_type='工作报告', kws=['工作报告']),
    # 贵州县区系的总结栏
    'gz_summary': dict(
        domains=lambda: GUIZHOU_CITY + GUIZHOU_COUNTY + gz_county_domains(),
        templates=AGG_SUM, doc_type='工作总结', kws=['总结']),
    # 新疆地州系
    'xj_report': dict(
        domains=lambda: XINJIANG_CITY,
        templates=['/zwgk/zfgzbg/', '/zfxxgk/zfgzbg/', '/zwgk/ghjh/zfgzbg/'],
        doc_type='工作报告', kws=['工作报告']),
    'xj_summary': dict(
        domains=lambda: XINJIANG_CITY,
        templates=AGG_SUM, doc_type='工作总结', kws=['总结']),
    # 厅局子站系：聚合总结栏（遵义 33 局 + 新疆 17 厅局）
    'dept_summary': dict(
        domains=lambda: ZUNYI_DEPT + XINJIANG_DEPT,
        templates=AGG_SUM, doc_type='工作总结', kws=['总结']),
    # 消息类：要闻栏目路径最统一，且**不该用标题关键词过滤**（消息没有可区分的标题特征）。
    # kws=None 让 detect_items 改走"按链接形态启发"——接受栏目内所有文章形态链接。
    'news_all': dict(
        domains=lambda: portals_2nd(),
        templates=['/xwdt/', '/zwdt/', '/ywdt/', '/xwzx/', '/xwdt/zwyw/',
                   '/zwgk/zwdt/', '/news/', '/xwzx/gzdt/'],
        doc_type='消息', kws=None),
    # 总结类：改用**二级门户直扫**（94 个市/县级门户）。
    # 前三条通道已证伪——县区挖掘 202 种子只 +6 县、部门子站 4,459 域 × 8 路径词只 +14、
    # 三跳发现 112 栏目只 +30。本路新增两类栏目源：
    #   ① 规划计划族（`ghjh` 下的年度总结/部门总结聚合栏）
    #   ② **政府信息公开年报**（`zfxxgknb` / `xxgknb`）——每个单位每年一份、路径高度统一，
    #      正文即年度工作回顾，属总结体例，且此前从未系统扫过。
    'summary_all': dict(
        domains=lambda: portals_2nd(),
        # 第二轮扩词（2026-09-15）：首轮 10 个路径词只命中 10 个栏目，但命中的
        # **全是政府信息公开年报**（`zfxxgknb`），且多栏产量封顶——说明这条通道有存货、
        # 只是路径词没铺够。故把年报族的变体铺全，并补"年度报告/总结"族。
        templates=[
            # —— 年报族（首轮验证有效，铺全变体）——
            '/zwgk/zfxxgk/zfxxgknb/', '/zfxxgk/zfxxgknb/', '/xxgk/zfxxgknb/',
            '/zwgk/xxgknb/', '/xxgk/xxgknb/', '/zwgk/zfxxgkml/zfxxgknb/',
            '/zwgk/xxgkml/zfxxgknb/', '/zwgk/ndbg/', '/xxgk/ndbg/',
            '/zwgk/ndgzbg/', '/xxgk/ndgzbg/', '/zwgk/gzbg/', '/xxgk/gzbg/',
            # —— 总结族 ——
            '/zwgk/ghjh/', '/xxgk/ghjh/', '/zwgk/fdzdgknr/ghjh/',
            '/zwgk/zfxxgk/fdzdgknr/ghjh/', '/zwgk/gzzj/', '/xxgk/gzzj/',
            '/zwgk/ghjh/bmjhzj/', '/xxgk/ghjh/bmjhzj/', '/zwgk/gzjh/', '/xxgk/gzjh/',
            '/zwgk/zjbg/', '/xxgk/zjbg/', '/zwgk/fdzdgknr/gzbg/'],
        doc_type='工作总结', kws=['总结', '年度报告', '年报']),
    # 省级门户系：政府工作报告位置最固定
    'prov_report': dict(
        domains=lambda: PROVINCIAL,
        templates=['/zwgk/zfgzbg/', '/zfxxgk/zfgzbg/', '/xxgk/zfgzbg/',
                   '/zwgk/ghjh/zfgzbg/', '/xxgk/ghjh/zfgzbg/'],
        doc_type='工作报告', kws=['工作报告']),
}


def portals_2nd():
    """已知二级门户（省/市/县）——要闻栏目家族用它们，不限于贵州"""
    out = []
    if os.path.exists(MINED_TXT):
        for line in open(MINED_TXT, encoding='utf-8', errors='replace'):
            d = line.strip().lower()
            if d.count('.') == 2 and re.match(r'^[a-z0-9.\-]+\.gov\.cn$', d):
                out.append(d)
    if os.path.exists(COUNTY_TXT):
        for line in open(COUNTY_TXT, encoding='utf-8', errors='replace'):
            d = line.strip().lower()
            if d and d not in out:
                out.append(d)
    for d in PROVINCIAL + XINJIANG_CITY:
        if d not in out:
            out.append(d)
    return out


def mined_dept_domains():
    """挖出的省级部门子站（三级域名）——聚合总结栏最可能挂在这类站上"""
    out = []
    if os.path.exists(MINED_TXT):
        for line in open(MINED_TXT, encoding='utf-8', errors='replace'):
            d = line.strip().lower()
            if d.count('.') >= 3 and re.match(r'^[a-z0-9.\-]+\.gov\.cn$', d):
                out.append(d)
    return out


def load_seen():
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
    return seen


def key_of(prefix, u):
    return prefix + re.sub(r'\W+', '', u.split('//')[-1])[:30]


def sweep_all(todos, pages, delay, seen, t0, max_n=0):
    """todos: [(key, doc_type, list_url, kws)]，串行采集并打印进度"""
    total = 0
    for i, (k, dt, u, kws) in enumerate(todos, 1):
        try:
            got, failed, fails = sw.sweep_one(k, dt, u, kws, pages, delay, seen, max_n)
        except Exception as e:
            print(f'  [{k}] 异常 {type(e).__name__}: {str(e)[:70]}', flush=True)
            continue
        total += got
        el = time.time() - t0
        print(f'  [{i}/{len(todos)}] [{k}] +{got}（失败 {failed}）'
              f'｜池 {len(seen)}｜{el:.0f}s', flush=True)
        for why, n in fails.most_common(2):
            print(f'        ↳ {n:3d} × {why}', flush=True)
    return total


def phase_cols(a):
    """深翻已验证栏目：按产量降序，跳过零产量的（它们多半是软 404 或站点改版）"""
    seen = load_seen()
    fp = os.path.join(sw.OUT_DIR, 'collected.jsonl')
    import collections
    yield_by_key = collections.Counter()
    for l in open(fp, 'rb'):
        try:
            r = json.loads(l.decode('utf-8', 'replace'))
            if r.get('key'):
                yield_by_key[r['key']] += 1
        except Exception:
            pass
    rows = [(yield_by_key.get(k, 0), k, dt, u, kws, pg)
            for k, dt, u, kws, pg in sw.COLUMNS]
    if a.type:
        rows = [r for r in rows if r[2] in a.type]
    rows = [r for r in rows if r[0] >= a.min_yield]
    rows.sort(reverse=True)
    if a.top:
        rows = rows[:a.top]
    print(f'=== 深翻 {len(rows)} 个栏目（原产量 ≥{a.min_yield}）｜页深 {a.pages} '
          f'｜池 {len(seen)} ===', flush=True)
    print(f'{"原产量":>5s} {"原页限":>5s} {"页/篇":>5s}  key', flush=True)
    for n, k, dt, u, kws, pg in rows[:20]:
        print(f'{n:5d} {pg:5d} {pg/max(n,1):5.2f}  {k}', flush=True)
    todos = [(k, dt, u, kws) for _n, k, dt, u, kws, _pg in rows]
    return sweep_all(todos, a.pages, a.delay, seen, time.time(), a.max_per_column)


def phase_family(a):
    seen = load_seen()
    names = [a.family] if a.family else list(FAMILIES)
    todos, plan = [], []
    for name in names:
        f = FAMILIES[name]
        doms = f['domains']()
        if name.startswith('dept'):
            doms = doms + mined_dept_domains()
        doms = [d for d in dict.fromkeys(doms)]
        plan.append((name, len(doms), len(f['templates'])))
        for d in doms:
            # 主机形态：三级及以上子站不能加 www 前缀——`www.czj.zunyi.gov.cn` 不存在。
            # 这里踩过：家族阶段整批用 www 形态 → 6,608 个部门站单元全部 DNS 失败。
            forms = ([f'https://{d}'] if (d.count('.') >= 3 or d.startswith('www.'))
                     else [f'https://{d}', f'https://www.{d}'])
            for t in f['templates']:
                for base in forms:
                    todos.append((key_of('fm_', base + t), f['doc_type'],
                                  base + t, f['kws']))
    print('=== 家族复制计划 ===', flush=True)
    for name, nd, nt in plan:
        print(f'   {name:14s} {nd:4d} 域 × {nt} 模板 = {nd*nt:5d} 采集单元', flush=True)
    print(f'合计 {len(todos)} 个采集单元 ｜ 页深 {a.pages} ｜ 池 {len(seen)}', flush=True)
    if a.dry:
        for k, dt, u, _kw in todos[:40]:
            print(f'   {dt:6s} {u}')
        return 0

    # 先并发探（只读，不写池），再串行采命中项——几千个单元串行探要跑两小时，
    # 而探测天然可并发；采集保持单进程，不出现两个进程追加同一份 JSONL。
    from concurrent.futures import ThreadPoolExecutor, as_completed
    hits, stat = [], {'req': 0, 'err': 0}

    def probe(item):
        k, dt, u, kws = item
        try:
            _s, h = sw.cgs.fetch(u, timeout=a.timeout, retries=1)
        except Exception:
            stat['err'] += 1
            return None
        stat['req'] += 1
        if not h or len(h) < 600:
            return None
        try:
            items = sw.detect_items(h, u, kws)
        except Exception:
            return None
        return item if len(items) >= a.min_links else None

    print(f'--- 并发探测（{a.workers} 并发）---', flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(probe, it) for it in todos]
        done = 0
        for fu in as_completed(futs):
            done += 1
            r = fu.result()
            if r:
                hits.append(r)
                print(f'  HIT\t{r[2]}', flush=True)
            if done % 500 == 0:
                print(f'  .. {done}/{len(todos)} ｜ 请求 {stat["req"]} '
                      f'｜ 命中 {len(hits)} ｜ {time.time()-t0:.0f}s', flush=True)
    print(f'--- 探测完：请求 {stat["req"]} ｜ 异常 {stat["err"]} ｜ '
          f'命中 {len(hits)} 个栏目 ｜ {time.time()-t0:.0f}s ---', flush=True)
    if not hits:
        return 0
    # 同域同文种只留一个栏目（模板常互为别名，如 /zwgk/zfgzbg/ 与 .../index.html）
    best = {}
    for k, dt, u, kws in hits:
        dom = u.split('//')[-1].split('/')[0]
        best.setdefault((dt, dom), (k, dt, u, kws))
    picks = list(best.values())
    print(f'--- 去重后 {len(picks)} 个栏目，开始串行采集 ---', flush=True)
    return sweep_all(picks, a.pages, a.delay, seen, time.time(), a.max_per_column)


def main():
    ap = argparse.ArgumentParser(description='深翻 + 家族复制采集器')
    ap.add_argument('--phase', choices=['cols', 'family'], required=True)
    ap.add_argument('--family', default='', help='只跑某个家族')
    ap.add_argument('--type', action='append', default=[], help='只深翻某文种（可重复）')
    ap.add_argument('--pages', type=int, default=60)
    ap.add_argument('--delay', type=float, default=0.4)
    ap.add_argument('--min-yield', type=int, default=8)
    ap.add_argument('--top', type=int, default=0)
    ap.add_argument('--workers', type=int, default=24)
    ap.add_argument('--timeout', type=float, default=12.0)
    ap.add_argument('--min-links', type=int, default=3)
    ap.add_argument('--max-per-column', type=int, default=0,
                    help='单栏最多下载多少篇（0=不限）。要闻栏目类必须设，否则单栏能跑几小时')
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()
    t0 = time.time()
    n = phase_cols(a) if a.phase == 'cols' else phase_family(a)
    print(f'\n=== {a.phase} 阶段完成: +{n} 篇 ｜ 用时 {time.time()-t0:.0f}s ===', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
