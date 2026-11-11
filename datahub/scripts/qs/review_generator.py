#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定题综述生成器 v1.0（D-求是，2026-09-01）
输入主题 → 检索（hybrid3 三路优先，无向量则 hybrid）→ 论断库补充 → 按年聚类 →
输出《主题_权威说法手册.md》：跨年表述汇编 + 金句 + 来源
用法: python review_generator.py "人工智能治理" [--top 15] [--out 目录]
"""
import os, sys, json, re, argparse, sqlite3
def _find_root():
    """包根探测：向上找含 VERSION 的目录（目录改名/跨机部署自适应）"""
    import os
    p = os.path.dirname(os.path.abspath(__file__))
    while not os.path.exists(os.path.join(p, 'VERSION')) and os.path.dirname(p) != p:
        p = os.path.dirname(p)
    return p

_DATA_ROOT = os.path.join(_find_root(), 'datahub')

from collections import defaultdict

# 数据路径：统一经 datahub/paths.py 解析（v7.3.0 单一事实源）
# 此前指向包内 datahub/sqlite/qs_articles.db —— 该库自 2026-09-09 起为 0 字节占位。
sys.path.insert(0, _DATA_ROOT)
from paths import db_path, statements_path, statements_denoised_path
DB = db_path()
# 论断库取**去噪版**（剔除图片署名/截断片段/章节小标题共 885 条）；
# 去噪版缺失时 statements_denoised_path() 自动回退原版，故此处无需判存在性。
STATEMENTS = statements_denoised_path()
# 综述产物属生成件（非注册资产），仍落包内 derived/
OUTDIR = os.path.join(_DATA_ROOT, 'derived', 'qs_reviews')

# 展示用统计（写进手册头部）：原先写死「求是 5,761 篇（三源）」与「生成：2026-09-01」，
# 已偏离实库（求是系 5,823 篇），且日期恒为常量（手册重生成后日期不变，不可信）。
_QS_SOURCES = ('求是杂志', '红旗文稿', '求是图书', '求是网采集', '求是-转载',
               '任仲平专项采集', '贺词采集')


def _corpus_line(outdir):
    """手册头部数据行：篇数与日期均现算；查库失败则回退为不计数的占位描述。"""
    import datetime
    today = datetime.date.today().isoformat()
    try:
        conn = sqlite3.connect(DB)
        marks = ','.join('?' * len(_QS_SOURCES))
        n_qs = conn.execute(f'SELECT COUNT(*) FROM articles WHERE data_source IN ({marks})',
                            _QS_SOURCES).fetchone()[0]
        n_all = conn.execute('SELECT COUNT(*) FROM articles').fetchone()[0]
        conn.close()
        corpus = f'求是系 {n_qs:,} 篇（七源）+ 全库 {n_all:,} 篇' if n_qs else f'全库 {n_all:,} 篇'
    except Exception:
        corpus = '语料篇数未计入（库不可读）'
    return f'> 生成：{today} ｜ 语料：{corpus} ｜ 检索模式：词面+向量混合（hybrid3）'

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('topic', help='综述主题')
    ap.add_argument('--top', type=int, default=15)
    ap.add_argument('--out', help='输出目录（默认 derived/qs_reviews）')
    args = ap.parse_args()

    # 同目录即 qiushi_engine 所在处；显式插入以保证任意 cwd 下均可导入
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from qiushi_engine import search_database
    import sqlite3

    outdir = args.out or OUTDIR
    os.makedirs(outdir, exist_ok=True)
    results = search_database(args.topic, top_n=args.top, use_semantic=True)
    print(f'检索命中: {len(results)} 篇')

    # 论断库按关键词快筛（主题 jieba 分词 + 核心词去泛词）
    stat_hits = {}
    if os.path.exists(STATEMENTS):
        try:
            import jieba
            jieba.setLogLevel(60)
            cand = [w for w in jieba.cut(args.topic) if len(w) >= 2
                    and w not in ('发展', '建设', '推进', '工作', '治理', '全面', '深化', '高质量', '中国', '我们')]
            core = cand or [args.topic]
        except Exception:
            core = [args.topic]
        stats = json.load(open(STATEMENTS, encoding='utf-8'))
        # 落盘结构为 list（每条 {type, content, article, author}），非 dict['items']
        items = stats if isinstance(stats, list) else stats.get('items', [])
        for item in items:
            _content = item.get('content') or item.get('statement') or ''
            if any(k in _content[:80] for k in core[:2]):
                stat_hits.setdefault(item.get('article') or item.get('title') or '—',
                                     []).append(_content[:120])
    print(f'论断库补充: {len(stat_hits)} 篇')

    conn = sqlite3.connect(DB)
    lines = [f'# 《关于「{args.topic}」的权威说法手册》', '',
             _corpus_line(outdir), '']

    by_year = defaultdict(list)
    for r in results:
        by_year[r.get('publish_date', '')[:4] or '未知'].append(r)

    lines.append('## 一、核心论断速查（Top 论断库命中）')
    n = 0
    for title, ss in sorted(stat_hits.items(), key=lambda x: -len(x[1]))[:8]:
        if title and title != '—':
            lines.append(f'- **{title[:40]}**')
        else:
            # 论断库约 4% 条目 article 与 author 皆空（原库 2,088 条 → 去噪版 1,269 条）。
            # 原先只跳打印标题、条目仍输出，结果是一串顶格无归属的 snippet。
            lines.append('- **（来源未标注）**')
        for s in ss[:2]:
            lines.append(f'  - 「{s}…」')
        n += 1
    if n == 0:
        lines.append('（本主题论断库命中较少，以下按年度原文检索）')

    lines.append('')
    lines.append('## 二、跨年度表述汇编（按年）')
    # 正文常带行尾图片说明（「…。 新华社记者 某某/摄」），展示前剥离；判据不确时原样保留。
    from strip_credit import strip_credit_tail_regex
    n_credit = 0
    for year in sorted(by_year.keys(), reverse=True):
        lines.append(f'### {year}年（{len(by_year[year])} 篇）')
        for r in by_year[year]:
            title = r.get('title', '') or ''
            lines.append(f'- 《{title[:50] if len(title) > 50 else title}》——{r.get("author", "—")}（{r.get("publish_date", "")}）')
            # 先在完整 snippet 上剥离行尾图片说明，再截断展示——
            # 若先截断，署名会被切在中间而无法识别（图集类文章尤其明显）。
            snip, k = strip_credit_tail_regex(r.get('snippet') or '')
            n_credit += k
            snip = snip[:110]
            if snip:
                lines.append(f'  - {snip}')

    from pathlib import Path as _P
    fname = re.sub(r'[\\/:*?"<>|]', '', args.topic)[:30]
    out = os.path.join(outdir, f'{fname}_权威说法手册.md')
    _P(out).write_text('\n'.join(lines), encoding='utf-8')
    print(f'手册已生成: {out}')
    print(f'内容: 论断速查 {n} 组 + 跨年 {len(by_year)} 年 / {len(results)} 篇'
          + (f' ｜ 剥离图片说明 {n_credit} 处' if n_credit else ''))

if __name__ == '__main__':
    main()