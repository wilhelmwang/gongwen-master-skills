#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""范本池分层入库器（L0 原始层 / L1 治理层 / L2 审核台账）

为什么分三层：清洗判据一定会改（本项目已改三轮：把「短行」误当网页残留一次、
把 CMS 元数据误当名单体一次、把站群导航块漏在正文里一次）。
只存清洗结果，判据一改就只能在半成品上再洗一遍；留下原文才能整层重洗。

  L0 raw_pages    采集原样：raw_text（清洗前正文）+ raw_sha256 + 判据版本。只增不改
  L1 samples      治理层：由 L0 按**当前**判据重算 content/skel，可整层重建
  L2 review_state 审核台账：哪篇判过、判了哪档、need_full 补没补全文复核

设计要点
--------
· JSONL（collected.jsonl）是唯一事实源，本库是派生物 —— 任何时候可整库重建
· **不并入主库检索**：主库用于写作引证，混入县区级范本会让引文出处变成基层文件
· 老数据（14,701 篇）没有 L0，clean_version 标 `legacy_no_raw`、raw_ref 为 NULL。
  这是永久性数据缺陷，如实标注，不假装可回溯
· 所有 SQL 一律参数绑定；DDL 用字面量而非变量，避免静态分析无法判定来源

用法
----
  python build_samples_db.py --dry-run          # 只统计，不写库
  python build_samples_db.py                    # 全量重建（先自动快照）
  python build_samples_db.py --incremental      # 只补库里没有的 url
"""
import argparse
import datetime
import hashlib
import json
import os
import sqlite3
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'quality'))
import sweep_columns as sw           # noqa: E402  提供 OUT_DIR
import export_review as er           # noqa: E402  复用清洗与骨架指纹，保证口径一致
import clean_boundary as cb          # noqa: E402  正文定界（通用规则，见其模块 docstring）
import snapshot as snap              # noqa: E402  写前快照 + 轮转（四铁律④）

POOL = os.path.join(sw.OUT_DIR, 'collected.jsonl')
DB_PATH = os.path.join(sw.OUT_DIR, 'gongwen_samples.db')
BATCH = 300


def sha16(s):
    return hashlib.sha256(s.encode('utf-8', 'replace')).hexdigest()[:16]


def ensure_schema(con):
    """建表。DDL 全部是字面量，不经变量传入 execute。"""
    con.execute('''CREATE TABLE IF NOT EXISTS raw_pages (
         id INTEGER PRIMARY KEY,
         url TEXT NOT NULL UNIQUE,
         source_key TEXT,
         doc_type TEXT,
         fetched_at TEXT,
         raw_text TEXT NOT NULL,
         raw_sha256 TEXT,
         clean_version TEXT)''')
    con.execute('''CREATE TABLE IF NOT EXISTS samples (
         id INTEGER PRIMARY KEY,
         url TEXT NOT NULL UNIQUE,
         raw_ref INTEGER,
         title TEXT,
         doc_type TEXT,
         source_key TEXT,
         pub_date TEXT,
         content TEXT NOT NULL,
         chars INTEGER,
         skel TEXT,
         txt_hash TEXT,
         clean_version TEXT)''')
    con.execute('CREATE INDEX IF NOT EXISTS ix_samples_type'
                ' ON samples(doc_type, clean_version)')
    con.execute('CREATE INDEX IF NOT EXISTS ix_samples_skel ON samples(skel)')
    con.execute('''CREATE TABLE IF NOT EXISTS review_state (
         url TEXT PRIMARY KEY,
         batch_id TEXT,
         tier TEXT,
         scores_json TEXT,
         why TEXT,
         need_full INTEGER DEFAULT 0,
         reviewed_at TEXT,
         full_reviewed_at TEXT,
         reviewer TEXT)''')
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS samples_fts USING fts5("
                "title, content, content='samples', content_rowid='id',"
                " tokenize='trigram')")
    con.execute('CREATE TABLE IF NOT EXISTS samples_meta (k TEXT PRIMARY KEY, v TEXT)')


def load_pool():
    recs = {}
    if not os.path.exists(POOL):
        return recs
    with open(POOL, 'rb') as f:
        for line in f:
            try:
                r = json.loads(line.decode('utf-8', 'replace'))
            except Exception:
                continue
            u = r.get('url')
            if u and u not in recs:
                recs[u] = r
    return recs


def load_l0():
    """从库内 L0 读原文，供池子里没有 raw_text 的存量记录兜底。

    存量 14,701 篇采于采集器改造之前，原文没存；2026-09-14 用 refetch_raw.py
    按 URL 重抓补回了其中 99%。池子仍是文章集合与元数据的事实源，
    L0 是补回来的原文层——两者合作，不互相取代。
    """
    out = {}
    if not os.path.exists(DB_PATH):
        return out
    try:
        con = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)
        for u, raw, sh, cv in con.execute(
                'SELECT url, raw_text, raw_sha256, clean_version FROM raw_pages'):
            out[u] = (raw, sh, cv)
        con.close()
    except Exception:
        pass
    return out


def derive(rec, l0):
    """由一条池记录算出 (L0 行, L1 行)。

    原文来源优先级：池子里的 raw_text（新采集器会写）→ 库内 L0（重抓补的）。

    **护栏**：原文按定义必然长于治理后正文。若原文比库内正文还短（实测 821 篇
    重抓抽取不足），说明这次抓取没取全，**不采用**，退回库内正文——
    宁可留着旧的网页残留，也不能把正文截掉一截。
    """
    url = rec.get('url')
    title = (rec.get('title') or '').strip()
    stored = rec.get('content') or ''
    src = rec.get('source') or rec.get('key') or ''
    raw = rec.get('raw_text')
    cver = rec.get('clean_version') or ''
    if not raw and url in l0:
        raw, _sh, cv0 = l0[url]
        cver = cv0 or cver
    if raw and len(raw) < len(stored) * 0.75:
        raw = None                      # 重抓没取全，护栏拦下
        cver = ''
    if raw:
        # 先**定界**再清洗。这一步是本项目 2026-09-15 的关键修正：
        # 此前三轮清洗都在扩词表（把站点框架特征词一条条加进 BOILER_PAT），
        # 抽样复核实测"5 篇里 4 篇开头仍是纯站点框架"。子 agent 归纳后指出根因判断错了——
        # **问题不是"词表清不掉"，而是"从来没做定界"**：政务 CMS 的页面结构是
        # 标题→元数据行→导航→面包屑→标题再现→正文…→页脚，只要把头尾切出来，
        # 框架自然全没了。实测：定界后短行占比中位 0.43 → 0.00，触发率 89%。
        body, bdiag = cb.boundary(raw, title)
        src_text = body if body is not None else raw     # 定界失败则退回原文（不清比切错安全）
        ls, _meta = er.cleaned_lines({'content': src_text, 'title': title})
        content = '\n'.join(ls)
        cver = 'v2_boundary' if body is not None else (cver or 'v1')
        r0 = (url, src, rec.get('doc_type'), rec.get('fetched_at'),
              raw, rec.get('raw_sha256') or sha16(raw), cver)
    else:
        # 无原文（或重抓原文过短被护栏拦下）：**先试对已清洗文本定界，再退回"只清洗"**。
        #
        # 为什么可行（2026-09-16 实测，不是推测）：这批的 `stored` 是**旧清洗规则**的产物，
        # 旧规则弱，头部导航/元数据行、尾部页脚**仍在里面**；而定界器的两条判据是纯形态的
        # ——「头＝第一条 ≥25 字且含标点的行」「尾＝最后一个含句末标点的行」——**不要求输入是原始 HTML**。
        # 抽样 6 例核对：切掉的头部是站名+导航+面包屑、尾部是 ICP+网站地图，切后首句都是正文起句、
        # 末句都正常收束，**无一例过度删除**。实测 1,203 篇里 847 篇可切（切后长度比中位 0.49）。
        # 另两批（v1 1,040 / refetch_v1 808）可切 0 与 6 ——它们的 stored 已被清洗过，无框架可切，故不适用。
        body, bdiag = cb.boundary(stored, title)
        if body is not None and not bdiag.get('no_cut'):
            ls, _meta = er.cleaned_lines({'content': body, 'title': title})
            content = '\n'.join(ls)
            # 标签区分来源：规则同 v2，但输入是**已清洗文本**（无原文可回溯）——
            # 不标成 v2_boundary，否则日后没人分得清这批的定界是基于什么切的。
            cver = 'v2_boundary_stored'
        else:
            # 既无原文、定界也不适用 → 套用**当前**清洗规则。
            # clean_version 标 legacy_no_raw 是如实声明"无法回溯到原文"，
            # 不等于"沿用旧结果不再治理"（L1 是派生层、可整层重建）。
            ls, _meta = er.cleaned_lines({'content': stored, 'title': title})
            content = '\n'.join(ls)
            cver = 'legacy_no_raw'
        r0 = None
    ls2 = [x for x in content.split('\n') if x.strip()]
    r1 = (url, title, rec.get('doc_type'), src, rec.get('pub_date') or '',
          content, len(content), er.skel_hash(ls2) if ls2 else '', sha16(content), cver)
    return r0, r1


def main():
    ap = argparse.ArgumentParser(description='范本池分层入库器')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--incremental', action='store_true', help='只补库里没有的 url')
    ap.add_argument('--no-snapshot', action='store_true')
    ap.add_argument('--keep', type=int, default=1,
                    help='写前快照保留份数（默认 1，0=不留；-1=不轮转）')
    a = ap.parse_args()

    pool = load_pool()
    if not pool:
        print('池子读不到:', POOL)
        return 2
    print(f'池子去重 {len(pool)} 篇 ｜ 库 {DB_PATH}')

    have = set()
    if os.path.exists(DB_PATH):
        try:
            c = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)
            have = {r[0] for r in c.execute('SELECT url FROM samples')}
            c.close()
        except Exception:
            have = set()
    todo = [r for u, r in pool.items() if u not in have]
    with_raw = sum(1 for r in todo if r.get('raw_text'))
    mode = '增量（只补缺）' if a.incremental else '全量（按 url 覆盖更新）'
    print(f'库内已有 {len(have)} ｜ 待入库 {len(todo)} ｜ 其中含原文(L0) {with_raw} ｜ {mode}')

    l0 = load_l0()
    print(f'库内 L0 原文 {len(l0):,} 篇可用作兜底')
    rows = [derive(r, l0) for r in (todo if a.incremental else pool.values())]
    l0 = [r[0] for r in rows if r[0]]
    l1 = [r[1] for r in rows]
    legacy = sum(1 for r in l1 if r[9] == 'legacy_no_raw')
    print(f'本次计算：L0 {len(l0)} 行 ｜ L1 {len(l1)} 行 ｜ 其中无原文(legacy) {legacy}')
    skels = {}
    for r in l1:
        key = (r[2], r[7])
        skels[key] = skels.get(key, 0) + 1
    dup = sum(v - 1 for v in skels.values() if v > 1)
    print(f'跨批同源同骨架近重复：{dup} 篇（同 doc_type + skel 只应留 1 篇）')

    if a.dry_run:
        print('\n--dry-run：未写库。')
        return 0

    if not a.no_snapshot:
        snap.take(DB_PATH, keep=getattr(a, 'keep', 1))

    con = sqlite3.connect(DB_PATH)
    con.execute('PRAGMA journal_mode=WAL')
    ensure_schema(con)
    con.commit()

    t0 = datetime.datetime.now().isoformat(timespec='seconds')
    n0 = n1 = 0
    # 去重标记是**另一层的结论**（dedup_samples.py 算出来的），重建 L1 时必须原样带过去。
    # ⚠️ 2026-09-17 实测踩到：INSERT 列表里没有 dup_of/dup_kind，一次重建就把 1,294 条精确重复
    # + 90 条近重复的标记全部冲成 NULL——消费方按 `dup_of IS NULL` 取唯一集，会瞬间多出 1,384 篇。
    marks = {u: (d, k) for u, d, k in
             con.execute('SELECT url, dup_of, dup_kind FROM samples')}
    print(f'沿用既有去重标记 {sum(1 for v in marks.values() if v[0])} 篇')
    try:
        con.execute('BEGIN')
        for i in range(0, len(l0), BATCH):
            con.executemany(
                'INSERT OR REPLACE INTO raw_pages'
                '(url,source_key,doc_type,fetched_at,raw_text,raw_sha256,clean_version)'
                ' VALUES(?,?,?,?,?,?,?)', l0[i:i + BATCH])
            n0 += len(l0[i:i + BATCH])
        con.execute('COMMIT')
        con.execute('BEGIN')
        for i in range(0, len(l1), BATCH):
            chunk = l1[i:i + BATCH]
            con.executemany(
                'INSERT OR REPLACE INTO samples'
                '(url,raw_ref,title,doc_type,source_key,pub_date,content,chars,skel,'
                ' txt_hash,clean_version,dup_of,dup_kind) VALUES(?,'
                '(SELECT id FROM raw_pages WHERE url=?),?,?,?,?,?,?,?,?,?,?,?)',
                [(c[0], c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[7], c[8], c[9],
                  marks.get(c[0], (None, None))[0], marks.get(c[0], (None, None))[1])
                 for c in chunk])
            n1 += len(chunk)
        con.execute('COMMIT')
        con.execute('BEGIN')
        con.execute("INSERT INTO samples_fts(samples_fts) VALUES('rebuild')")
        con.execute('COMMIT')
    except Exception as e:
        con.execute('ROLLBACK')
        con.close()
        print('写库失败，已回滚:', type(e).__name__, e)
        return 1

    con.execute('INSERT OR REPLACE INTO samples_meta(k,v) VALUES(?,?)', ('built_at', t0))
    con.execute('INSERT OR REPLACE INTO samples_meta(k,v) VALUES(?,?)',
                ('note', 'JSONL 为唯一事实源，本库为派生物；不并入主库检索'))
    con.commit()
    tot = con.execute('SELECT count(*) FROM samples').fetchone()[0]
    tot0 = con.execute('SELECT count(*) FROM raw_pages').fetchone()[0]
    print(f'\n入库完成：L0 {n0} 行（库内 {tot0}）｜ L1 {n1} 行（库内 {tot}）')
    for r in con.execute('SELECT doc_type, clean_version, count(*) FROM samples'
                         ' GROUP BY doc_type, clean_version ORDER BY 3 DESC'):
        print(f'   {r[0]:6s} {r[1]:14s} {r[2]:>6,}')
    con.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
