#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""范文池去重：正文级重复检测（只标记，不删除）

两条口径，默认只跑第一条
------------------------
  ① 精确重复（默认）：正文 sha256 相同 → 判重。
     抽样验证过：同标题、同字数、仅 URL 协议不同（http/https），是同一篇的两个入口。
  ② 近重复（--near，默认关闭）：正文 k-gram 集合包含率 ≥ 0.93 且长度比 ≤ 1.45，
     再叠加三道闸门（正文真正切过 / 跨域 / 标题同指，逐条证据见 `TRUSTED_VERSION` 处注释）。
     **裸包含率在本语料上完全不可用**：政府公文高度模板化，不同县（佛坪县 vs 南郑区）、
     不同次（姑征补安置〔2026〕3号 vs 4号）、不同月份（昆明 5 月 vs 6 月水质报告）
     的正式文件，包含率仍达 0.93–1.00。加闸门后从 687 篇降到 90 篇，
     **逐条核对过：88 篇是同一篇稿件跨站转载，2 篇可疑**（赤水市 vs 务川县的
     「群众身边不正之风线索征集」——同一模板、由不同县各自发布，正文几乎一致）。
     ⚠️ 因此 `--near` 的结果**必须人工抽样过目**（`--sample N`）后才可信。
     ⚠️ 不加 `--near` 重跑会**把近重复标记一起清空**（writeback 先整体置 NULL 再写），
     定稿后重跑必须带上同样的参数，否则近重复标记白丢。

**只标记不删除**：给 samples 表加 `dup_of` / `dup_kind` 两列，指向保留篇的 url。
下游按 `dup_of IS NULL` 取唯一集。原文一篇不动，判断错了可撤。

用法
----
  python dedup_samples.py --dry-run            # 只统计
  python dedup_samples.py                      # 只标精确重复（默认，先自动快照）
  python dedup_samples.py --near --sample 12   # 连近重复一起标，并列 12 组供人工过目
  python dedup_samples.py --report             # 看现状
"""
import argparse
import hashlib
import os
import re
import sqlite3
import sys
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'quality'))
import sweep_columns as sw          # noqa: E402
import clean_boundary as cb          # noqa: E402  复用同一定界判据，不另立口径
import snapshot as snap              # noqa: E402  写前快照 + 轮转（四铁律④）

#: 定界判据需要原文与标题，建一次缓存供 is_trusted 查询
RAW_CACHE = {}
TITLE_CACHE = {}

DB = os.path.join(sw.OUT_DIR, 'gongwen_samples.db')

K = 3
MINHASH_N = 64
BANDS = 16
CONTAIN = 0.93
MAX_LEN_RATIO = 1.45


def norm(text):
    t = re.sub(r'[，。；：、（）()【】\[\]"“”‘’\-—…·,.!?！？]', '', text or '')
    return re.sub(r'[\s\u3000]+', '', t)


def shingles(s, k=K):
    return {s[i:i + k] for i in range(len(s) - k + 1)} if len(s) >= k else {s}


def minhash(sh, n=MINHASH_N):
    if not sh:
        return [0] * n
    out = [1 << 62] * n
    for g in sh:
        h1 = int.from_bytes(hashlib.sha256(g.encode('utf-8')).digest()[:8], 'big')
        h2 = int.from_bytes(hashlib.sha256((g + '#').encode('utf-8')).digest()[:8], 'big')
        for i in range(n):
            v = (h1 + i * h2) & ((1 << 61) - 1)
            if v < out[i]:
                out[i] = v
    return out


def candidates(sigs):
    buckets = defaultdict(set)
    per = MINHASH_N // BANDS
    for url, sig in sigs.items():
        for b in range(BANDS):
            key = (b, tuple(sig[b * per:(b + 1) * per]))
            for other in buckets[key]:
                yield (url, other) if url < other else (other, url)
            buckets[key].add(url)


def ensure_cols(con):
    cols = [r[1] for r in con.execute('PRAGMA table_info(samples)')]
    if 'dup_of' not in cols:
        con.execute('ALTER TABLE samples ADD COLUMN dup_of TEXT')
    if 'dup_kind' not in cols:
        con.execute('ALTER TABLE samples ADD COLUMN dup_kind TEXT')
    con.commit()


def exact_dups(rows):
    by_hash = defaultdict(list)
    for url, _dt, _ct, _ch, th, _cv in rows:
        by_hash[th].append(url)
    out = {}
    for th, urls in by_hash.items():
        if len(urls) > 1:
            for u in sorted(urls)[1:]:
                out[u] = (sorted(urls)[0], 'exact')
    return out, sum(1 for v in by_hash.values() if len(v) > 1)


#: 近重复的判据经 2026-09-16 全量核对后收敛为三道，缺一即为误报。前两道在
#: `is_trusted`（正文可信），后两道在 `near_dups`（跨域 + 标题同指）。列证据如下：
#:
#: ① **只比"真正切过"的正文**。定界器对「切不足 10%」和「原文过短」会判"无需切"，
#:    这类行仍带完整站点框架；实测「旗帜网·三以三促」与「提升治理效能为何要大抓党建」
#:    共享气象网框架，包含率假性 0.99 → 误报。故 `no_cut` 不算可信。
#: ② **只在跨域时判**（本条是收敛误报的主力）。全量 467 篇近重复里同域 366 /
#:    跨域 101：同域几乎全是"同模板不同期"——昆明市 5 月 vs 6 月水质报告、姑苏区
#:    征收补偿 3 号 vs 4 号、马尾区 2023 vs 2024 法治政府总结、黔东南同站各期
#:    「李强主持召开国务院常务会议」——正文包含率 0.93~1.00，但**不是同一篇文章**。
#:    根因是站点框架同域共享：同域两篇即便正文互不相干，也天然共享导航/页脚文字。
#:    跨域则相反——两个不同站点共享大段文字，只可能是同一篇稿被转载（实测跨域 101 篇
#:    里 79 篇标题前 18 字完全相同，抽样全是真转载）。
#: ③ **标题需同指**：前 18 字相同，或一方是另一方的子串（站点截断标题所致）。
#:    挡掉"跨域但讲的不是同一件事"的偶然碰撞。
TRUSTED_VERSION = 'v2_boundary'


def domain_of(url):
    m = re.match(r'https?://([^/]+)', url or '')
    d = (m.group(1) if m else '').lower()
    return d[4:] if d.startswith('www.') else d


def title_same(t1, t2):
    """标题是否指向同一篇稿（容忍站点截断：尾部长标题常被截成「…」）"""
    a, b = (t1 or '').strip(), (t2 or '').strip()
    if len(a) < 4 or len(b) < 4:
        return False
    if a[:18] == b[:18]:
        return True
    return (a in b or b in a) if min(len(a), len(b)) >= 8 else False


def is_trusted(url, cv):
    """该行是否可参与近重复比对：定界器确实切掉了头或尾"""
    if cv != TRUSTED_VERSION:
        return False
    raw = RAW_CACHE.get(url)
    if raw is None:
        return False
    _body, d = cb.boundary(raw, TITLE_CACHE.get(url, ''))
    return bool(d) and not d.get('no_cut')


def near_dups(rows, skip):
    todo = [(u, ct) for u, _dt, ct, _ch, _th, _cv in rows
            if u not in skip and is_trusted(u, _cv)]
    norms = {u: norm(ct) for u, ct in todo}
    sigs = {u: minhash(shingles(s)) for u, s in norms.items()}
    sh_cache = {u: shingles(s) for u, s in norms.items()}
    lenmap = {u: len(s) for u, s in norms.items()}
    pairs = set(candidates(sigs))
    print(f'   近重复：{len(todo):,} 篇算 MinHash，{len(pairs):,} 组候选对…')
    out = {}
    for a1, b1 in pairs:
        sa, sb = norms[a1], norms[b1]
        if not sa or not sb:
            continue
        # 跨域 + 标题同指（判据②③，见文件头的证据）
        if domain_of(a1) == domain_of(b1):
            continue
        if not title_same(TITLE_CACHE.get(a1), TITLE_CACHE.get(b1)):
            continue
        us, ub = (a1, b1) if len(sa) <= len(sb) else (b1, a1)
        if not lenmap[us] or lenmap[ub] / lenmap[us] > MAX_LEN_RATIO:
            continue
        g = sh_cache[us]
        if len(g) < 20:
            continue
        if sum(1 for x in sh_cache[ub] if x in g) / len(g) < CONTAIN:
            continue
        if us in out or ub in out:
            continue
        out[us] = (ub, 'near')
    return out


def writeback(con, marks, dry_run, snapshot, keep=1):
    if dry_run:
        print('--dry-run：未改库。')
        return 0
    if snapshot:
        snap.take(DB, keep=keep)
    batch = [(u, v[0], v[1]) for u, v in marks.items()]
    try:
        con.execute('BEGIN')
        con.execute('UPDATE samples SET dup_of=NULL, dup_kind=NULL')
        for i in range(0, len(batch), 300):
            con.executemany('UPDATE samples SET dup_of=?, dup_kind=? WHERE url=?',
                            [(b[1], b[2], b[0]) for b in batch[i:i + 300]])
        con.execute('COMMIT')
    except Exception as e:
        con.execute('ROLLBACK')
        print('标记失败，已回滚:', type(e).__name__, e)
        return 1
    e = con.execute("SELECT count(*) FROM samples WHERE dup_kind='exact'").fetchone()[0]
    n = con.execute("SELECT count(*) FROM samples WHERE dup_kind='near'").fetchone()[0]
    print(f'已标记：精确重复 {e:,} ｜ 近重复 {n:,}'
          f'（原文一篇未动，按 dup_of IS NULL 取唯一集）')
    return 0


def show_samples(rows, marks, n):
    """抽样列出判重对，供人工过目（只读，不改库）"""
    info = {u: ct for u, _dt, ct, _ch, _th, _cv in rows}
    items = sorted(marks.items())
    step = max(1, len(items) // max(n, 1))
    picked = items[::step][:n]
    print(f'\n抽样核对：{len(marks):,} 篇判重，每 {step} 篇取 1，共列 {len(picked)} 组')
    for u, (keep, kind) in picked:
        t1, t2 = TITLE_CACHE.get(u, ''), TITLE_CACHE.get(keep, '')
        c1, c2 = info.get(u, ''), info.get(keep, '')
        print(f'\n[{kind}] 判重《{t1}》{len(c1)}字  {u}')
        print(f'        保留《{t2}》{len(c2)}字  {keep}')
        print(f'        判重篇首：{c1[:90]}')
        print(f'        保留篇首：{c2[:90]}')
    return len(picked)


def main():
    ap = argparse.ArgumentParser(description='范文池去重（只标记）')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--near', action='store_true',
                    help='连近重复一起标（含跨域+标题同指闸门，仍建议配 --sample 人工过目）')
    ap.add_argument('--no-snapshot', action='store_true')
    ap.add_argument('--keep', type=int, default=1,
                    help='写前快照保留份数（默认 1；快照约 1.4 GB，不轮转会撑爆磁盘）')
    ap.add_argument('--sample', type=int, default=0,
                    help='抽样列出 N 组判重对供人工过目（配合 --dry-run 可只看不写）')
    a = ap.parse_args()

    con = sqlite3.connect(DB)
    con.execute('PRAGMA journal_mode=WAL')
    ensure_cols(con)

    if a.report:
        t = con.execute('SELECT count(*) FROM samples').fetchone()[0]
        e = con.execute("SELECT count(*) FROM samples WHERE dup_kind='exact'").fetchone()[0]
        n = con.execute("SELECT count(*) FROM samples WHERE dup_kind='near'").fetchone()[0]
        print(f'全库 {t:,} ｜ 精确重复 {e:,} ｜ 近重复 {n:,} ｜ 去重后唯一 {t - e - n:,}')
        con.close()
        return 0

    rows = list(con.execute('SELECT url, doc_type, content, chars, txt_hash, clean_version FROM samples'))
    # is_trusted 要重跑定界，故需原文与标题；只在下 --near 时才读（原文 24k 篇占内存不小）
    if a.near or a.sample:
        for u, t in con.execute('SELECT url, title FROM samples'):
            TITLE_CACHE[u] = t
    if a.near:
        for u, raw in con.execute('SELECT url, raw_text FROM raw_pages'):
            RAW_CACHE[u] = raw
        print(f'   可信集判据：读入原文 {len(RAW_CACHE):,} 篇')
    print(f'读入 {len(rows):,} 篇')
    ex, groups = exact_dups(rows)
    print(f'① 精确重复：{len(ex):,} 篇（{groups} 组）')
    marks = dict(ex)
    if a.near:
        nd = near_dups(rows, skip=ex)
        marks.update(nd)
        print(f'② 近重复：{len(nd):,} 篇')
    else:
        print('② 近重复：未启用（默认关闭；本语料上会把不同县/不同次的正式文件误判为重复）')
    print(f'\n合计判重 {len(marks):,} 篇 ｜ 去重后唯一 {len(rows) - len(marks):,} 篇')
    if a.sample:
        show_samples(rows, marks, a.sample)
    rc = writeback(con, marks, a.dry_run, not a.no_snapshot, keep=a.keep)
    con.close()
    return rc


if __name__ == '__main__':
    sys.exit(main())
