#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L2 精品审核·第 2 步收尾：批次标签汇总入库 + 逐批一致性体检（零 LLM）

做三件事：
  ① **对账**：每批 `s2_out_NN.jsonl` 的行数与 url 集合必须与 `s2_manifest.json` 完全一致
     （url 是唯一绑定键；对不上就报错退出，不猜）
  ② **体检**：逐批 A 率、type_mismatch 率、need_full 数、五维分布、降档情况——
     不同子 agent 之间的口径漂移只能这样看出来（实测前三批 A 率 19%/35%/23%）
  ③ **入库**：写入 `quality_llm`（主键 `(url, batch_id)`）
     ⚠️ 不写 `review_state`：那张表主键只有 url，2026-09-17 已因此覆盖过 108 条台账；
     且多轮标注需要并存，url 单列主键放不下。

用法
----
  python ingest_labels.py --check      # 只对账与体检，不写库
  python ingest_labels.py              # 对账通过后入库
"""
import argparse
import glob
import io
import json
import os
import sqlite3
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))          # datahub/
import paths                        # noqa: E402

DB = os.environ.get('GW_SAMPLES_DB') or paths.samples_db_path()
BATCH_DIR = os.environ.get('GW_BATCHES') or os.path.join(
    os.path.dirname(DB), 'step2_batches')
DIMS = ('体例', '内容', '语言', '完整', '价值')


def load_manifest():
    p = os.path.join(BATCH_DIR, 's2_manifest.json')
    with io.open(p, encoding='utf-8') as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(description='批次标签汇总入库 + 体检')
    ap.add_argument('--check', action='store_true', help='只对账与体检，不写库')
    a = ap.parse_args()

    man = load_manifest()
    expect = {b['batch']: b for b in man['manifest']}
    files = sorted(glob.glob(os.path.join(BATCH_DIR, 's2_out_*.jsonl')))
    if not files:
        print('未找到任何 s2_out_*.jsonl')
        return 2

    rows, bad = [], []
    for fp in files:
        n = int(os.path.basename(fp).split('_')[-1].split('.')[0])
        exp = expect.get(n)
        recs = []
        with io.open(fp, encoding='utf-8') as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception as e:
                    bad.append(f'{os.path.basename(fp)}:{i} JSON 坏行 {e}')
                    continue
                miss = [k for k in ('url', 'tier') + DIMS if k not in d]
                if miss:
                    bad.append(f'{os.path.basename(fp)}:{i} 缺字段 {miss}')
                    continue
                recs.append(d)
        if exp is None:
            bad.append(f'{os.path.basename(fp)} 不在 manifest 里')
            continue
        if len(recs) != exp['n']:
            bad.append(f'批 {n}: 条数 {len(recs)} ≠ manifest {exp["n"]}')
        got, want = {r['url'] for r in recs}, set(exp['urls'])
        if got != want:
            bad.append(f'批 {n}: url 集合不一致（缺 {len(want-got)} / 多 {len(got-want)}）')
        # 体检
        t = Counter(r['tier'] for r in recs)
        n_ar = t['A']
        tm = sum(1 for r in recs if r.get('type_mismatch'))
        nf = sum(1 for r in recs if r.get('need_full'))
        print(f'批 {n:02d}  {len(recs):3d} 条 ｜ A {t["A"]:3d} / B {t["B"]:3d} / C '
              f'{t["C"]:3d} ｜ A 率 {n_ar*100//max(len(recs),1):3d}% '
              f'｜ type_mismatch {tm:3d} ｜ need_full {nf}')
        for r in recs:
            rows.append((n, r))

    if bad:
        print(f'\n❌ 对账失败 {len(bad)} 项，**不写库**：')
        for b in bad[:12]:
            print('   -', b)
        return 1
    print(f'\n✅ 对账通过：{len(files)} 批 / {len(rows)} 条')

    tot = Counter(r['tier'] for _n, r in rows)
    n = max(len(rows), 1)
    print(f'\n合计 A {tot["A"]} / B {tot["B"]} / C {tot["C"]}'
          f' ｜ A 率 {tot["A"]*100//n}% ｜ type_mismatch '
          f'{sum(1 for _n, r in rows if r.get("type_mismatch"))*100//n}%')

    # 与确定性层的一致率（第 4 步 κ 的预览）
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    det = {u: v for u, v in con.execute(
        "SELECT url, verdict FROM quality_det WHERE rule_ver='v1'")}
    con.close()
    cm = Counter()
    for _n, r in rows:
        dv = det.get(r['url'])
        llm_c = (r['tier'] == 'C')
        det_c = (dv == 'C')
        cm[(det_c, llm_c)] += 1
    both = cm[(True, True)]
    only_det = cm[(True, False)]
    only_llm = cm[(False, True)]
    agree = cm[(True, True)] + cm[(False, False)]
    print(f'\n与确定性层（一票否决 vs LLM 判 C）对照：')
    print(f'   两方都判 C {both} ｜ 仅规则判 C {only_det} ｜ 仅 LLM 判 C {only_llm}')
    print(f'   一致率 {agree*100//n}%（{agree}/{n}）')

    if a.check:
        print('\n--check：未写库。')
        return 0

    con = sqlite3.connect(DB)
    con.execute('PRAGMA journal_mode=WAL')
    import datetime
    ts = datetime.datetime.now().isoformat(timespec='seconds')
    try:
        con.execute('BEGIN')
        con.executemany(
            'INSERT OR REPLACE INTO quality_llm'
            '(url,batch_id,tili,neirong,yuyan,wanzheng,jiazhi,tier,'
            ' need_full,type_mismatch,why,labeled_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            [(r['url'], f's2_batch_{n_:02d}', r['体例'], r['内容'], r['语言'],
              r['完整'], r['价值'], r['tier'], 1 if r.get('need_full') else 0,
              1 if r.get('type_mismatch') else 0, (r.get('why') or '')[:120], ts)
             for n_, r in rows])
        con.execute('COMMIT')
    except Exception as e:
        con.execute('ROLLBACK')
        print('写库失败，已回滚:', type(e).__name__, e)
        con.close()
        return 1
    k = con.execute('SELECT count(*) FROM quality_llm').fetchone()[0]
    print(f'\n已落 quality_llm：{k:,} 条')
    con.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
