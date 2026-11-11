#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""存量数据重抓补原始层（L0）

背景：存量 14,701 篇采于采集器改造之前，只存了清洗后正文，`raw_text` 没有，
所以 `raw_pages` 至今为 0 行。后果是分不清某处网页残留是采集器漏的还是治理规则漏的
——两个环节的产物混在一起，无法隔离定位。

但 URL 全在库里，**重抓一遍即可补回原始层**。政务文档内容极少变动，
且本器只补 L0（不改 L1 正文），风险低。

口径
----
· 只对 `raw_pages` 里还没有的 url 抓，逐条落 `raw_text` + `raw_sha256`
· 抓回后与库内 `chars` 比对，**明显变短/变长都记进 stdout**（可能就是当初抽取不全的证据）
· 不碰 L1 `samples` 表：正文仍由 build_samples_db.py 从 L0 重算，保持单一入口

用法
----
  python refetch_raw.py --limit 200            # 小样验证
  python refetch_raw.py --workers 16           # 全量补
  python refetch_raw.py --dry-run              # 只列待补数量
"""
import argparse
import datetime
import hashlib
import os
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import sweep_columns as sw                      # noqa: E402
import crawl_govdoc_samples as cgs              # noqa: E402  复用 fetch/html_to_text/extract_body

DB = os.path.join(sw.OUT_DIR, 'gongwen_samples.db')
BATCH = 200
_LOCK = threading.Lock()
_STAT = {'ok': 0, 'fail': 0, 'reasons': {}}


def bump(reason=None):
    with _LOCK:
        if reason:
            _STAT['fail'] += 1
            _STAT['reasons'][reason[:40]] = _STAT['reasons'].get(reason[:40], 0) + 1
        else:
            _STAT['ok'] += 1


def guess_cfg(url):
    """按 URL 猜一个正文抽取配置——重抓只需要 body 区，不比配置名精确"""
    return {'body_re': None} if False else {}


def fetch_one(url, timeout):
    """返回 (url, raw_text, raw_sha256) 或 (url, None, 失败原因)"""
    try:
        st, html = cgs.fetch(url, timeout=timeout, retries=1)
    except Exception as e:
        return url, None, f'{type(e).__name__}: {str(e)[:34]}'
    if not html:
        return url, None, '空响应'
    # 复用同一套抽取：先按通用正则取正文容器，退化到整页文本
    try:
        txt = cgs.html_to_text(html)
        m = re.search(r'(?is)<div[^>]+(?:id|class)="[^"]*(?:UCAP-CONTENT|zoom|'
                      r'TRS_Editor|article|content|conTxt|wznr)[^"]*"[^>]*>(.*?)</div>',
                      html)
        if m:
            inner = cgs.html_to_text(m.group(1))
            if len(inner) > 120:
                txt = inner
    except Exception:
        txt = html
    txt = txt or ''
    if len(txt) < 100:
        return url, None, f'正文过短({len(txt)}字)'
    return url, txt, hashlib.sha256(txt.encode('utf-8', 'replace')).hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser(description='存量重抓补原始层（只写 L0）')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--workers', type=int, default=16)
    ap.add_argument('--timeout', type=float, default=15.0)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    if not os.path.exists(DB):
        print('库不存在:', DB)
        return 2
    con = sqlite3.connect(DB)
    con.execute('PRAGMA journal_mode=WAL')
    have = {r[0] for r in con.execute('SELECT url FROM raw_pages')}
    todo = [(u, c, t) for u, c, t in
            con.execute('SELECT url, chars, title FROM samples') if u not in have]
    print(f'库内 {con.execute("SELECT count(*) FROM samples").fetchone()[0]:,} 篇 ｜ '
          f'已有原始层 {len(have):,} ｜ 待补 {len(todo):,}')
    if a.limit:
        todo = todo[:a.limit]
        print(f'本次上限 {len(todo)}')
    if a.dry_run or not todo:
        con.close()
        print('--dry-run：未抓取。' if a.dry_run else '无需补。')
        return 0

    t0 = time.time()
    rows, shorter, longer = [], [], []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(fetch_one, u, a.timeout): (u, c, t) for u, c, t in todo}
        done = 0
        for fu in as_completed(futs):
            u, c, t = futs[fu]
            done += 1
            try:
                _u, raw, tag = fu.result()
            except Exception as e:
                bump(f'{type(e).__name__}')
                continue
            if raw is None:
                bump(tag)
                continue
            bump()
            rows.append((u, raw, tag))
            # 与库内正文长度对比：差异大的很可能是当初抽取不全
            if c:
                if len(raw) < c * 0.75:
                    shorter.append((t, c, len(raw)))
                elif len(raw) > c * 3:
                    longer.append((t, c, len(raw)))
            if done % 100 == 0:
                print(f'  .. {done}/{len(todo)} ｜ 成功 {_STAT["ok"]} '
                      f'｜ {time.time()-t0:.0f}s', flush=True)

    print(f'\n抓取完成：成功 {_STAT["ok"]} ｜ 失败 {_STAT["fail"]} ｜ '
          f'用时 {time.time()-t0:.0f}s')
    for k, v in sorted(_STAT['reasons'].items(), key=lambda x: -x[1])[:6]:
        print(f'   失败 {v:5d} × {k}')

    if shorter:
        print(f'\n⚠ 重抓正文比库内短 25% 以上的 {len(shorter)} 篇（当初抽取可能不全）：')
        for t, c, r in shorter[:6]:
            print(f'   库内 {c:>6} → 重抓 {r:>6}  {(t or "")[:40]}')
    if longer:
        print(f'\n⚠ 重抓正文比库内长 3 倍以上的 {len(longer)} 篇（当初可能截断）：')
        for t, c, r in longer[:6]:
            print(f'   库内 {c:>6} → 重抓 {r:>6}  {(t or "")[:40]}')

    if not rows:
        con.close()
        print('无可写入数据。')
        return 1
    now = datetime.datetime.now().isoformat(timespec='seconds')
    n = 0
    try:
        con.execute('BEGIN')
        for i in range(0, len(rows), BATCH):
            chunk = [(u, raw, sh, now) for u, raw, sh in rows[i:i + BATCH]]
            con.executemany(
                'INSERT OR REPLACE INTO raw_pages'
                '(url,source_key,doc_type,fetched_at,raw_text,raw_sha256,clean_version)'
                ' VALUES(?,?,?,?,?,?,?)',
                [(u, '', '', ts, raw, sh, 'refetch_v1') for u, raw, sh, ts in chunk])
            n += len(chunk)
        con.execute('COMMIT')
    except Exception as e:
        con.execute('ROLLBACK')
        con.close()
        print('写库失败，已回滚:', type(e).__name__, e)
        return 1
    tot = con.execute('SELECT count(*) FROM raw_pages').fetchone()[0]
    con.close()
    print(f'\n原始层写入 {n} 篇 ｜ raw_pages 现有 {tot:,} 行')
    print('下一步：python build_samples_db.py   # 让 L1 正文从原文按当前规则重算')
    return 0


if __name__ == '__main__':
    sys.exit(main())
