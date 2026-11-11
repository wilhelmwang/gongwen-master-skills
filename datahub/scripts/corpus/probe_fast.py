#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""栏目发现器（v2.0 · 从站点自身发现，不猜路径）

v1.0 猜路径模板，实测对两个主要站群都不成立：
  - 贵州厅局是四层嵌套 `/zwgk/zfxxgk/fdzdgknr/ghjh/`（比模板多一层 zfxxgk）
  - 新疆厅局是 TRS 数字频道 `/xjnynct/c113556/zwgk.shtml`（路径里带频道 ID，无法猜）
12 域 × 17 模板 = 204 次请求，命中 0——猜路径这条路的期望值已经测出来了。

v2.0 换成两跳发现：
  跳 1  抓域名首页，取**锚文本含栏目关键词**的链接（政务公开 / 规划计划 / 总结 / 报告 …）
  跳 2  抓这些候选栏目页，用 `detect_items` 数标题含文种关键词的静态详情链接，≥3 即命中

这样站群把栏目挂在哪一层、用什么路径名都不影响——路径是从页面里读出来的，不是猜的。

用法
----
  python probe_fast.py --type 工作总结 --workers 24
  python probe_fast.py --all --pages 12          # 命中即采（默认行为）
  python probe_fast.py --type 调研报告 --limit 100 --dry
"""
import argparse
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse, quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_columns as sw

try:
    from probe_targets import PORTALS as _PORTALS, DEPTS as _DEPTS
except ImportError:
    _PORTALS, _DEPTS = [], []

MINED_TXT = os.path.join(sw.OUT_DIR, 'mined_domains.txt')

#: 跳 1 的栏目锚文本线索（越靠前越优先探）
NAV_KW = ['政务公开', '信息公开', '规划计划', '规划', '年度', '总结', '报告',
          '调研', '参阅', '决策', '研究成果', '统计', '专题', '数据', '公开']

#: 跳 2 的口径：标题含这些词才算目标文种的详情链接
KW = {'工作总结': ['总结'], '工作报告': ['工作报告'], '调研报告': ['调研', '研究', '视察'],
      '会议纪要': ['常务会议', '办公会议', '会议纪要', '议定事项']}

#: 栏目链接打分用的路径词（命中的栏目多半长这样）
PATH_HINT = {
    '工作总结': ['gzzj', 'ndzj', 'jhzj', 'gzjh', 'ndbg', 'ghjh', 'fdzdgknr', 'zwgk', 'xxgk'],
    '工作报告': ['zfgzbg', 'gzbg', 'ghjh', 'fdzdgknr', 'zwgk', 'xxgk'],
    '调研报告': ['dybg', 'dcyj', 'gzyj', 'llyj', 'scdy', 'dyyj', 'jcyj', 'dycg', 'zwgk', 'xxgk'],
    '会议纪要': ['zfcwhy', 'cwhy', 'zfhy', 'zdhyxx', 'hyxx', 'hyjy', 'cwh', 'zwgk', 'xxgk'],
}

#: 跳 3 的子栏目锚文本线索（目标栏目常挂在「政务公开」落地页的下一层）
SUB_NAV = {
    '工作总结': ['工作总结', '年度总结', '总结', '年度工作', '工作要点', '计划总结'],
    '工作报告': ['政府工作报告', '工作报告', '年度报告', '报告'],
    '调研报告': ['调研报告', '调研', '参阅', '研究成果', '决策参考', '考察'],
    '会议纪要': ['常务会议', '政府会议', '会议纪要', '办公会议', '议定事项', '政府常务'],
}

_LOCK = threading.Lock()
_STAT = {'req': 0, 'err': 0, 'errs': {}}


def _bump(tag=None):
    with _LOCK:
        if tag is None:
            _STAT['req'] += 1
        else:
            _STAT['err'] += 1
            _STAT['errs'][tag] = _STAT['errs'].get(tag, 0) + 1


def get(url, timeout):
    _bump()
    try:
        # href 里可能带中文（如 /zwgk/工作总结/），urllib 拼请求行时按 ASCII 编码会直接抛
        # UnicodeEncodeError。先做百分号编码再发。
        u = quote(url, safe=':/?&=#%+~!$&\'()*;,[]@')
        st, h = sw.cgs.fetch(u, timeout=timeout, retries=2)
        return h or ''
    except Exception as e:
        _bump(f'{type(e).__name__}: {str(e)[:56]}')
        return ''


def host_forms(dom):
    """三级及以上子站不加 www 前缀——`www.czj.zunyi.gov.cn` 不存在，白打 204 次"""
    if dom.count('.') >= 3 or dom.startswith('www.'):
        return ['https://' + dom]
    return ['https://' + dom, 'https://www.' + dom]


def nav_candidates(html, base, dtype):
    """从首页取栏目候选链接，按路径线索与锚文本打分排序"""
    out, seen = [], set()
    hints = PATH_HINT.get(dtype, [])
    for m in re.finditer(r'<a\s[^>]*href="([^"#]+)"[^>]*>(.*?)</a>', html, re.I | re.S):
        href, anchor = m.group(1), re.sub(r'<[^>]+>|\s+', '', m.group(2))
        if not anchor or len(anchor) > 20 or not href:
            continue
        if href.startswith(('javascript:', 'mailto:', 'tel:')):
            continue
        u = urljoin(base, href)
        if urlparse(u).netloc != urlparse(base).netloc:
            continue
        if u in seen:
            continue
        score = 0
        for i, k in enumerate(NAV_KW):
            if k in anchor:
                score += (len(NAV_KW) - i) * 2
                break
        low = u.lower()
        for j, p in enumerate(hints):
            if p in low:
                score += len(hints) - j
                break
        if score <= 0:
            continue
        if re.search(r'\.(pdf|doc|docx|xls|xlsx|jpg|png|zip|rar)$', low):
            continue
        seen.add(u)
        out.append((score, u))
    out.sort(key=lambda x: -x[0])
    return [u for _s, u in out[:14]]


def sub_links(html, base, sub_kw):
    """从栏目页里取下一层子栏目链接（锚文本命中子栏目线索词）"""
    out, seen = [], set()
    for m in re.finditer(r'<a\s[^>]*href="([^"#]+)"[^>]*>(.*?)</a>', html, re.I | re.S):
        href, anchor = m.group(1), re.sub(r'<[^>]+>|\s+', '', m.group(2))
        if not anchor or len(anchor) > 16 or not href:
            continue
        if href.startswith(('javascript:', 'mailto:', 'tel:')):
            continue
        if not any(k in anchor for k in sub_kw):
            continue
        u = urljoin(base, href)
        if urlparse(u).netloc != urlparse(base).netloc or u in seen:
            continue
        if re.search(r'\.(pdf|doc|docx|xls|xlsx|jpg|png|zip|rar)$', u.lower()):
            continue
        seen.add(u)
        out.append(u)
    return out[:6]


def discover_domain(dom, dtype, timeout, min_links):
    """三跳发现：首页 → 栏目候选 → 子栏目。返回 (命中URL, 链接数, 示例) 或 None"""
    kws = KW[dtype]
    sub_kw = SUB_NAV[dtype]
    for base in host_forms(dom):
        home = get(base + '/', timeout)
        if not home:
            continue
        subs = []
        for cu in nav_candidates(home, base + '/', dtype):
            h = get(cu, timeout)
            if not h or len(h) < 800:
                continue
            try:
                items = sw.detect_items(h, cu, kws)
            except Exception:
                items = {}
            if len(items) >= min_links:
                ex = next(iter(items.items()))
                return (cu, len(items), f'{ex[1][:26]} → {ex[0][:52]}')
            subs += sub_links(h, cu, sub_kw)
        for su in subs[:6]:
            h = get(su, timeout)
            if not h or len(h) < 800:
                continue
            try:
                items = sw.detect_items(h, su, kws)
            except Exception:
                continue
            if len(items) >= min_links:
                ex = next(iter(items.items()))
                return (su, len(items), f'{ex[1][:26]} → {ex[0][:52]}')
        return None                      # 首页可达但无目标栏目，不再试别的 host 形态
    return None


def load_domains(dtype):
    doms = []
    if os.path.exists(MINED_TXT):
        for line in open(MINED_TXT, encoding='utf-8', errors='replace'):
            d = line.strip().lower()
            if d and re.match(r'^[a-z0-9.\-]+\.gov\.cn$', d):
                doms.append(d)
    for d in (_PORTALS + (_DEPTS if dtype == '工作总结' else [])):
        if d not in doms:
            doms.append(d)
    return doms


def main():
    ap = argparse.ArgumentParser(description='栏目发现器（两跳）')
    ap.add_argument('--type', action='append', default=[])
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--workers', type=int, default=24)
    ap.add_argument('--timeout', type=float, default=12.0)
    ap.add_argument('--min-links', type=int, default=3)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--pages', type=int, default=12)
    ap.add_argument('--delay', type=float, default=0.6)
    a = ap.parse_args()

    types = a.type if a.type else (list(KW) if a.all else [])
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

    t0 = time.time()
    verified = []
    for dtype in types:
        doms = load_domains(dtype)
        if a.limit:
            doms = doms[:a.limit]
        print(f'\n=== 发现 {dtype}：{len(doms)} 域 ｜ {a.workers} 并发 ===', flush=True)
        done = 0
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            futs = {ex.submit(discover_domain, d, dtype, a.timeout, a.min_links): d
                    for d in doms}
            for fu in as_completed(futs):
                d = futs[fu]
                done += 1
                try:
                    r = fu.result()
                except Exception as e:
                    _bump(f'{type(e).__name__}: {str(e)[:56]}')
                    r = None
                if r:
                    cu, n, ex_ = r
                    verified.append((dtype, cu, n))
                    print(f'  HIT\t{dtype}\t{n:3d}\t{cu}\t{ex_[:52]}', flush=True)
                if done % 50 == 0:
                    print(f'  .. {done}/{len(doms)} 域 ｜ 请求 {_STAT["req"]} '
                          f'｜ 命中 {len(verified)} ｜ {time.time()-t0:.0f}s', flush=True)

    print(f'\n=== 命中 {len(verified)} 个栏目 ｜ 请求 {_STAT["req"]} 次 '
          f'｜ 异常 {_STAT["err"]} 次 ｜ 用时 {time.time()-t0:.0f}s ===', flush=True)
    for k, v in sorted(_STAT['errs'].items(), key=lambda x: -x[1])[:5]:
        print(f'    异常 {v:5d} × {k}', flush=True)
    for dtype, cu, n in verified:
        print(f'  {dtype}\t{n:3d}\t{cu}', flush=True)
    if a.dry:
        return 0

    total = 0
    for dtype, cu, _n in verified:
        key = 'fd_' + re.sub(r'\W+', '', cu.split('//')[-1])[:26]
        try:
            got, failed, fails = sw.sweep_one(key, dtype, cu, KW[dtype], a.pages, a.delay, seen)
        except Exception as e:
            print(f'  [{key}] 采集异常 {type(e).__name__}: {e}', flush=True)
            continue
        total += got
        print(f'  [{key}] +{got}（失败 {failed}）', flush=True)
        for why, n in fails.most_common(3):
            print(f'        ↳ {n:3d} × {why}', flush=True)
    print(f'\n=== 发现器采集合计: +{total} 篇 ===', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
