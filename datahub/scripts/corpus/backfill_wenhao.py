#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""政策文件文号回填（2026-09-15）

背景
----
政策文件四库 + 公报合计 41,665 篇，`wenhao`（文号）字段**100% 为空**——
而文号明明写在正文首部（抽样见「国函〔2026〕89号」「财金〔2026〕88号」）。
后果：**按文号检索完全不可用**。

只在前 300 字里找
-----------------
实测国务院文件 5,998 篇中 3,690 篇（61%）正文含文号、其中 **99% 出现在前 200 字**。
**必须限制在首部**——正文中后部出现的〔XXXX〕号是**引用他文**（这条早前在调研报告
上验证过：那批 〔XXXX〕号全是引用国办发/黔府办发等别的文件，不是本文文号）。
不限制就会把引用当作文号写进字段，比留空更糟。

两种形态都要认
--------------
  A 机关代字式：`国函〔2026〕89号` `国办发〔2026〕24号` `财金〔2026〕88号`
  B 令体      ：`国务院令 第843号` `xx部令 第12号`（无〔年份〕）

提不到就留空，不猜。
"""
import argparse
import os
import re
import sqlite3
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
import sweep_columns as sw          # noqa: E402
import snapshot as snap             # noqa: E402  写前快照 + 轮转（四铁律④）

ROOT = sw.OUT_DIR and os.path.dirname(sw.OUT_DIR) or '.'
DB_DIR = os.path.dirname(sw.OUT_DIR)     # 数据根（govdoc_samples 的上一级）

#: 只扫首部这么多个字
HEAD_CHARS = 300
#: A 机关代字式（全角/半角括号、可省"第"、字号可含"-"）
RE_A = re.compile(r'[\u4e00-\u9fa5]{1,14}\s*[〔\[（(]\s*20\d{2}\s*[〕\]）)]'
                  r'\s*第?\s*\d{1,5}\s*[-—]?\s*\d{0,3}\s*号')
#: B 令体（无年份）
RE_B = re.compile(r'[\u4e00-\u9fa5]{2,14}令\s*第\s*\d{1,5}\s*号')
#: 排除：明显是"引用他文"的引导语（出现在文号前 20 字内即判引用）
#: ⚠️ 2026-09-16 修正：原词表里有**单字 `见`**，而 `意见` 含 `见` → 凡标题以
#: 「…的意见」结尾的公文，文号前的 20 字内必含"见"，**被判成引用他文而丢弃**。
#: `意见` 恰是高发文种（仅 gw 库就 999 篇）。实测：去掉这个单字后
#: 四库可提取量 12,250 → 14,372（**+2,122**：gw +890 / bm +1,136 / other +96）。
#: 已验证新增的命中位置中位 32 字（紧跟标题）= 本文文号，不是正文里的引用。
#: 残余误报约 4%（98 篇）：**「答记者问 / 解读」类**文档本身无文号，其括注里写的是
#: 被解读文件的号。已试过两种收紧判据都不成立——括注判据会误伤基线 766 篇、
#: 标题判据只切掉 38 篇却误伤 394 篇，故此残余**有意保留**（留空比填错更"干净"，
#: 但 98/27,352 的错误率换取 2,122 篇正确回填，这个交换是划算的）。
RE_CITE = re.compile(r'根据|按照|依据|参见|详见|另见|印发|转发|批转|执行|落实')


def extract(head):
    """返回 (文号, 形态) 或 (None, None)"""
    for pat, tag in ((RE_A, 'A'), (RE_B, 'B')):
        for m in pat.finditer(head):
            lead = head[max(0, m.start() - 20):m.start()]
            if RE_CITE.search(lead):
                continue                    # 前文是"根据/按照…"→ 引用他文，不是本文文号
            return re.sub(r'\s+', '', m.group(0)), tag
    return None, None


def main():
    ap = argparse.ArgumentParser(description='政策文件文号回填')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--no-snapshot', action='store_true')
    ap.add_argument('--overwrite', action='store_true',
                    help='连已有值一起覆盖（默认只填空；覆盖前请先看 --dry-run 的差异）')
    ap.add_argument('--keep', type=int, default=1,
                    help='写前快照保留份数（每份 170~240MB，不轮转会白占上 GB）')
    ap.add_argument('--only', default='', help='只处理指定库，逗号分隔（如 zhengce_gw.db）')
    a = ap.parse_args()

    dbs = ['gongbao.db', 'zhengce_gw.db', 'zhengce_bm.db',
           'zhengce_other.db', 'zhengce_zy.db']
    if a.only:
        want = {x.strip() for x in a.only.split(',') if x.strip()}
        dbs = [d for d in dbs if d in want]
        if not dbs:
            print(f'--only 未匹配到库：{sorted(want)}')
            return 2
    total_upd = total_n = 0
    for name in dbs:
        p = os.path.join(DB_DIR, name)
        if not os.path.exists(p):
            print(f'  跳过（不存在）{name}')
            continue
        c = sqlite3.connect(p)
        c.execute('PRAGMA journal_mode=WAL')
        rows = list(c.execute('SELECT rowid, content FROM gongbao'))
        upd = []
        forms = {'A': 0, 'B': 0}
        for rid, ct in rows:
            num, tag = extract((ct or '')[:HEAD_CHARS])
            if num:
                upd.append((num, rid))
                forms[tag] += 1
        print(f'  {name:18s} {len(rows):>6,} 篇 → 提取到文号 {len(upd):>6,}'
              f'（{len(upd)*100//max(len(rows),1)}%）｜ 代字式 {forms["A"]:,} 令体 {forms["B"]:,}')
        if a.dry_run or not upd:
            total_n += len(rows); total_upd += len(upd)
            c.close(); continue
        if not a.no_snapshot:
            # 经 snapshot.py（四铁律④的唯一实现处）——它同时做轮转：
            # 四库每份 170~540MB，不轮转的话跑几次就白占上 GB。
            snap.take(p, keep=getattr(a, 'keep', 1))
        try:
            c.execute('BEGIN')
            for i in range(0, len(upd), 500):
                if a.overwrite:
                    c.executemany('UPDATE gongbao SET wenhao=? WHERE rowid=?',
                                  upd[i:i + 500])
                else:
                    # **默认只填空、不覆盖**（2026-09-16 改）。依据：
                    # ① 现有值的行数恰好等于旧口径的提取数，说明现有值就是这个抽取器写的，
                    #    不是接口给的原值——但新旧口径在 214 行上不一致（旧口径会把被"见"
                    #    挡住的首个候选跳过、退到更靠后的候选，那个候选更可能是正文里的引用）。
                    # ② 两种口径谁对无法逐行判定 → **不动它们**；而"只填空"能拿到全部增量
                    #    （口径之外的每一行本就是空的），风险为零。
                    c.executemany(
                        'UPDATE gongbao SET wenhao=? WHERE rowid=?'
                        " AND (wenhao IS NULL OR wenhao='')", upd[i:i + 500])
            c.execute('COMMIT')
        except Exception as e:
            c.execute('ROLLBACK'); c.close()
            print(f'      回填失败已回滚: {type(e).__name__} {e}')
            continue
        got = c.execute("SELECT COUNT(*) FROM gongbao WHERE wenhao IS NOT NULL"
                        " AND trim(wenhao)<>''").fetchone()[0]
        print(f'      回填后库内文号非空 {got:,} 篇')
        c.close()
        total_n += len(rows); total_upd += len(upd)
    print(f'\n合计 {total_n:,} 篇 ｜ 提取到文号 {total_upd:,}'
          f'（{total_upd*100//max(total_n,1)}%）')
    if a.dry_run:
        print('--dry-run：未写库。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
