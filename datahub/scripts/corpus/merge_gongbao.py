#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公报/政策文件语料并入主库（gongbao.db / zhengce_*.db → articles · v7.7.0 起）

把公报或政策文件库的全文并入主库 `articles` 表，使 hybrid3 检索
（TF-IDF/BM25/FTS）可以命中这些内容。

⚠️ **2026-09-16 实测：政策文件四库并入后应回退**（公报那次是成功的，两次结论不同）
--------------------------------------------------------------------------------
| | 并之前 | 并四库之后 |
|---|---|---|
| `eval` gold_hit@3（冻结的 104 条回归线） | 74% | **68.3%（跌破 72% 地板 → 门禁 FAIL）** |
| 热查询 p50 延迟 | 1.21 s | **2.34 s** |
| 政策用例（`datahub/eval/run_policy_eval.py --channel unified`） | 0/22 | 仅 **3/22** |

机制：四库是**短篇、关键词密集**的部门/地方文件（中位 1.4–1.9 千字），进 47k 语料后
在 top-3 里挤掉了求是/公报——而「写作引证要出权威源」正是主库的产品定位。
而**专通道 `datahub/scripts/zc/search_zhengce.py` 同批用例拿 20/22**，性价比高得多。
结论按项目红线「eval 基线不许降」办理：**回退**（定向删除并入的行，保留期间新采的求是/红旗）。
要重开此议，先做**来源分级的排序**（让政策文件可被检索但不压过权威源）或**默认关、按需开**，
两条都需要先写用例再调参，不能靠调权重把指标"调回去"。

四铁律对应
----------
- ④ 写前快照：由调用方先跑 `gongwen_tool.py snapshot`（本脚本不自作主张）
- ③ 显式事务分批：每 500 行一个事务，避免大事务损坏 FTS（交接文档 §6.2 已知坑）
- ② schema 三同步：**本操作不加列不改表**——articles 现有列完全够用，
  data_source 用新枚举值（`--source` 指定）与既有来源区分；
  ⚠️ 政策文件的**文号没有独立列**，它出现在正文首部（`search_zhengce.py --wenhao` 走的是源库字段）；
  故并入后「按文号查」仍应走专通道，不要指望主库。
  故 schema 注册表与 DDL 均无需变更。
- ① WAL 不回退：只 INSERT 不 UPDATE/DELETE，不触碰 WAL 归档。
  （回退是**另一件事**，见上：定向 DELETE + 重建 FTS/索引，且须留有快照。）

字段映射
--------
  articles.title        ← gongbao.title
  articles.author       ← 从标题抽取发文机关（"国务院关于…"→"国务院"），兜底＝`--source` 的标签
  articles.source       ← `--source`（默认「国务院公报」）
  articles.publish_date ← pubtime 'YYYY.MM.DD' → 'YYYY-MM-DD'
  articles.issue_year   ← 年份（BETWEEN 1900 AND 2100 校验）
  articles.url          ← url（唯一索引自动去重，OR IGNORE）
  articles.content      ← content
  articles.word_count   ← word_count
  articles.data_source  ← `--source`
  articles.genre        ← gongbao.doc_type（制度规定/通知/意见…）

用法
----
  python merge_gongbao.py --dry-run                          # 只统计，不写
  python merge_gongbao.py                                    # 公报（默认源）
  python merge_gongbao.py --db <zhengce_gw.db> --source 国务院文件   # 政策库四库之一
"""
import argparse
import datetime
import re
import sqlite3
import sys
import os

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(BASE, 'datahub'))
from paths import db_path  # noqa: E402

BATCH = 500

#: 发文机关抽取：标题里位于动作词之前的机构名序列
_AGENCY_STOP = re.compile(
    r'(?:关于|印发|印发《|颁布|公布|令|任免|同意|批复|转发|决定：|决定$)')


def extract_agency(title, fallback='国务院公报'):
    """从标题抽取发文机关。失败兜底 fallback。

    例：『国务院关于…的通知』→ 国务院；『教育部关于…』→ 教育部；
        『中共中央办公厅 国务院办公厅印发…』→ 中共中央办公厅 国务院办公厅
    """
    t = (title or '').strip()
    cut = _AGENCY_STOP.split(t, 1)[0].strip()
    cut = re.sub(r'\s*《.*$', '', cut).strip()
    if 2 <= len(cut) <= 30 and re.search(r'(?:院|部|委|办|厅|局|会|署|行|行|公署|办公室)$', cut):
        return cut
    return fallback


def norm_date(pub):
    m = re.match(r'(\d{4})[.年/-](\d{1,2})[.月/-](\d{1,2})', pub or '')
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1900 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f'{y:04d}-{mo:02d}-{d:02d}'


def main():
    ap = argparse.ArgumentParser(description='公报/政策文件语料并入主库 articles')
    ap.add_argument('--dry-run', action='store_true', help='只统计，不写库')
    ap.add_argument('--db', default=None, help='源库路径（默认 DATA_ROOT/gongbao.db）')
    ap.add_argument('--source', default='国务院公报',
                    help='source / data_source 标签（默认「国务院公报」）。'
                         '四库各用一标签：中央文件｜国务院文件｜部门文件｜其他文件——'
                         '与既有「逐来源一标签」的约定一致（求是杂志/红旗文稿/部委政策…）')
    a = ap.parse_args()

    gongbao_path = a.db or os.path.join(os.path.dirname(db_path()), 'gongbao.db')
    if not os.path.exists(gongbao_path):
        print(f'❌ 找不到 {gongbao_path}')
        return 2
    label = a.source

    src = sqlite3.connect(gongbao_path)
    rows = src.execute('SELECT title, url, content, word_count, pubtime, doc_type '
                   'FROM gongbao WHERE content IS NOT NULL AND length(trim(content)) > 0').fetchall()
    src.close()
    print(f'源（有正文）: {len(rows)} 篇 ｜ 标签「{label}」')

    dst = sqlite3.connect(db_path())
    existing = {u for (u,) in dst.execute('SELECT url FROM articles')}
    todo = [r for r in rows if r[1] not in existing]
    print(f'主库现有        : {dst.execute("SELECT COUNT(*) FROM articles").fetchone()[0]} 篇'
          f'（URL 重叠 {len(rows) - len(todo)}，跳过）')
    print(f'待并入          : {len(todo)} 篇')
    if a.dry_run:
        import collections
        ag = collections.Counter(extract_agency(t, label) for t, *_ in todo)
        yr = collections.Counter(norm_date(p)[:4] for _t, _u, _c, _w, p, _d in todo if norm_date(p))
        print('  机关 Top8:', ' ｜ '.join(f'{k} {n}' for k, n in ag.most_common(8)))
        print('  年份跨度 :', min(yr), '-', max(yr))
        dst.close()
        return 0

    now = datetime.datetime.now().isoformat(timespec='seconds')
    ins = 0
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        with dst:                               # 显式分批事务（四铁律③）
            for title, url, content, wc, pub, dtype in batch:
                dst.execute('''INSERT OR IGNORE INTO articles
                    (title, author, source, publish_date, issue_year, issue_num,
                     url, content, keywords, word_count, crawl_time,
                     data_source, genre)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (title, extract_agency(title, label), label,
                     norm_date(pub),
                     int(pub[:4]) if re.match(r'\d{4}', pub or '') else None,
                     None, url, content, '', wc or len(content), now,
                     label, dtype))
        ins += len(batch)
        print(f'  … 已写 {ins}/{len(todo)}', flush=True)

    n = dst.execute('SELECT COUNT(*) FROM articles').fetchone()[0]
    got = dst.execute('SELECT COUNT(*) FROM articles WHERE data_source=?',
                      (label,)).fetchone()[0]
    dst.close()
    print(f'✅ 合并完成：主库 {n} 篇（其中「{label}」{got} 篇）')
    print('  后续必须：①重建 articles_fts ②重建 TF-IDF/BM25 索引 ③复跑 eval（再基线）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
