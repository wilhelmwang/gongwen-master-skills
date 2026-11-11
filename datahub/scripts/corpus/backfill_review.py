#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""审核台账回填（L2 review_state）

把已有的子 agent 评审产物收进台账。两类产物、两种绑定方式：

  boundary（定界与字段分离）：产物直接带 url，按 url 绑定
  tier（精品三档）           ：产物只有 id，而 id 曾用内置 hash() 生成（按进程随机化），
                              重跑对不上。改用依据文件里的 (标题 + 来源站) 从库中反查 url。
                              ⚠️ 该缺陷已在 export_review.py 修掉（改 sha256 并补 url 字段），
                              这是对既有产物的补救绑定，不是常规路径。

台账结构：review_state 增加 `review_kind` 与 `payload_json` 两列——
tier 与 boundary 是两种不同评审，混用一个 tier 字段会掩盖区别。
原始评审 JSON 整份存进 payload_json，不丢信息。

只读写 review_state，不动 samples。

用法
----
  python backfill_review.py --dry-run
  python backfill_review.py
  python backfill_review.py --report
"""
import argparse
import datetime
import json
import os
import sqlite3
import sys
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import sweep_columns as sw          # noqa: E402

D = sw.OUT_DIR
DB = os.path.join(D, 'gongwen_samples.db')

#: (产物文件, 依据文件, 评审种类)
JOBS = [
    ('pilot_out_p1.json', None, 'boundary'),
    ('pilot_out_p2.json', None, 'boundary'),
    ('rev_out_jiyao_1.json', 'rev_jiyao_1.jsonl', 'tier'),
    ('rev_out_jiyao_2.json', 'rev_jiyao_1.jsonl', 'tier'),
]


def load_json_docs(path):
    """一个文件里可能有「数组 + 尾部一个对象」（子 agent 按约定在数组后附 batch_summary）"""
    raw = open(path, encoding='utf-8-sig').read()
    dec = json.JSONDecoder()
    docs, i = [], 0
    while i < len(raw):
        while i < len(raw) and raw[i] in ' \r\n\t':
            i += 1
        if i >= len(raw):
            break
        o, i = dec.raw_decode(raw, i)
        docs.append(o)
    return docs


def host_of(url):
    m = __import__('re').match(r'https?://([^/]+)', url or '')
    return m.group(1) if m else ''


def main():
    ap = argparse.ArgumentParser(description='审核台账回填')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--report', action='store_true')
    a = ap.parse_args()

    con = sqlite3.connect(DB)
    con.execute('PRAGMA journal_mode=WAL')
    cols = [r[1] for r in con.execute('PRAGMA table_info(review_state)')]
    if 'review_kind' not in cols:
        con.execute('ALTER TABLE review_state ADD COLUMN review_kind TEXT')
    if 'payload_json' not in cols:
        con.execute('ALTER TABLE review_state ADD COLUMN payload_json TEXT')
    con.commit()

    if a.report:
        tot = con.execute('SELECT count(*) FROM review_state').fetchone()[0]
        print(f'台账共 {tot:,} 条')
        for r in con.execute('SELECT review_kind, count(*) FROM review_state'
                             ' GROUP BY review_kind'):
            print(f'   {r[0]:10s} {r[1]:>6,}')
        for r in con.execute("SELECT tier, count(*) FROM review_state"
                             " WHERE review_kind='tier' GROUP BY tier"):
            print(f'   档位 {r[0]}: {r[1]:,}')
        con.close()
        return 0

    rows = list(con.execute('SELECT url, title FROM samples'))
    by_url = {u for u, _t in rows}
    by_title_host = defaultdict(list)
    for u, t in rows:
        if t:
            by_title_host[(t.strip(), host_of(u))].append(u)

    # id → (title, src_host)：从依据文件建。tier 产物只带 id，
    # 而 id 的哈希段不可复现（内置 hash 随进程随机化），故不能重算，只能查依据文件。
    # 依据文件按行读成列表：tier 产物只带 id，而 id 的哈希段不可复现
    # （内置 hash 随进程随机化，且依据文件重导出过），故按**位置**绑定。
    # 位置绑定前已验证：依据第 N 行与产物第 N 条的 key 前缀 40/40 一致。
    src_lines = {}
    for _out, srcfile, _k in JOBS:
        if not srcfile:
            continue
        sp = os.path.join(D, srcfile)
        if not os.path.exists(sp):
            continue
        rows_s = []
        for line in open(sp, encoding='utf-8', errors='replace'):
            line = line.strip()
            if line:
                try:
                    rows_s.append(json.loads(line))
                except Exception:
                    pass
        src_lines[srcfile] = rows_s
    print(f'依据文件行数: ' + ', '.join(f'{k}={len(v)}' for k, v in src_lines.items()))

    total, bound, unbound = 0, 0, []
    recs = []
    for outfile, srcfile, kind in JOBS:
        p = os.path.join(D, outfile)
        if not os.path.exists(p):
            print(f'跳过（不存在）{outfile}')
            continue
        docs = load_json_docs(p)
        items = docs[0] if docs and isinstance(docs[0], list) else []
        b = 0
        for idx, it in enumerate(items):
            total += 1
            url = it.get('url')
            if not url:
                # tier 类：按位置回依据文件取 (标题, 来源站)，再查库反推 url
                base_rows = src_lines.get(srcfile) or []
                if idx < len(base_rows):
                    it = dict(it)
                    it['title'] = base_rows[idx].get('title')
                    it['src_host'] = base_rows[idx].get('src_host')
                t = (it.get('title') or '').strip()
                h = it.get('src_host') or ''
                cand = by_title_host.get((t, h)) or []
                if len(cand) == 1:
                    url = cand[0]
                elif len(cand) > 1:
                    url = sorted(cand)[0]
            if not url or url not in by_url:
                unbound.append((outfile, it.get('id') or it.get('title') or '?'))
                continue
            b += 1
            bound += 1
            payload = json.dumps(it, ensure_ascii=False)
            if kind == 'tier':
                tier = it.get('tier')
                scores = json.dumps(it.get('scores') or {}, ensure_ascii=False)
                need = 1 if it.get('need_full') else 0
            else:
                tier = 'article' if it.get('is_article') else 'not_article'
                scores = json.dumps({'clean_ok': it.get('clean_ok'),
                                     'confidence': it.get('confidence')},
                                    ensure_ascii=False)
                need = 0
            # batch_id 用**产物文件名**标识评审轮次；原先填依据文件名，
            # 而同一批的两轮评审共用同一个依据文件，看不出是第几轮。
            recs.append((url, outfile, tier, scores, it.get('why') or '',
                         need, datetime.datetime.now().isoformat(timespec='seconds'),
                         'subagent', kind, payload))
        print(f'{outfile:24s} {len(items):3d} 条 ｜ 绑定 {b} ｜ 种类 {kind}')

    print(f'\n合计 {total} 条 ｜ 绑定成功 {bound} ｜ 未绑定 {len(unbound)}')
    for f, k in unbound[:6]:
        print(f'   未绑定 [{f}] {str(k)[:60]}')
    if a.dry_run:
        print('--dry-run：未写库。')
        con.close()
        return 0

    try:
        con.execute('BEGIN')
        con.executemany(
            'INSERT OR REPLACE INTO review_state'
            '(url,batch_id,tier,scores_json,why,need_full,reviewed_at,reviewer,'
            ' review_kind,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?)', recs)
        con.execute('COMMIT')
    except Exception as e:
        con.execute('ROLLBACK')
        con.close()
        print('回填失败，已回滚:', type(e).__name__, e)
        return 1
    print(f'\n已写台账 {len(recs):,} 条')
    con.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
