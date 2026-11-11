#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""认知层统计（L3–L5）：站位、弹药、分寸（cognition-stats v1.0.0）

用途：从**本机自己的语料库**跑出认知层的量级，供 `references/cognition-layers.md` 引用。

为什么不直接搬外部参考工程的数字
--------------------------------
外部参考工程（`lieflat-gongwen`）的认知层统计跑在 226 篇内部工作材料上，
其原始语料因版权不随包分发 ⇒ **本机无法复算那些百分比**。
按 `references/param-guardrails.md` 第二纪律（抽样区间不得直接当验收线），
不可复算的数字不能当合格线。故本脚本的存在意义是：**给出本机可复算的那一份**，
并明确标出「本机语料覆盖不到哪一层」。

只读，不写库
------------
只跑 SELECT。不建库、不改库、不联网。库路径经 `--db` 指定，默认取环境变量
`GONGWEN_DATA_ROOT` 下的 `gongwen/gongwen_corpus.db`。

统计口径（五个维度）
--------------------
- **L3 站位**：取正文开头 120 字，按「哪一类信号最早出现」分类（不是出现最多）。
- **L4 引用层级**：T1 习近平 / T2 党中央·全会 / T3 国务院 / T4 省委·部委 / T5 法律法规 / T8 古语典故，各计出现次数与覆盖篇数。
- **L4 数据位置**：带单位的数字按全文十分位统计落点（「前半篇密集、建议段几乎无数据」是可核验的职能分工）。
- **L5 力度词**：必须/建议/希望/要求/切实/严禁/不得 的每千字频次。
- **L5 收尾**：末 130 字的程式匹配（上行谦辞 / 下行落款 / 讲话号召 / 自然收束）。

用法
----
  python cognition_stats.py                      # 跑默认表（articles）
  python cognition_stats.py --table jhsjk_articles
  python cognition_stats.py --limit 3000         # 限额采样（快跑）
  python cognition_stats.py --json
"""
import argparse
import json
import os
import re
import sqlite3
import sys

# ---------- 站位分类（L3）----------
# 顺序即优先级：命中越靠前的信号，越说明「开篇最早给了什么」。
STANCES = [
    ('A 国家战略/全局定位', re.compile(
        r'习近平|新时代|二十大|二十届|党中央|国家战略|全局|大局|中国式现代化|'
        r'民族复兴|战略高度|根本遵循|重要论述')),
    ('B 政策依据/受命行文', re.compile(
        r'根据|依据|按照|贯彻落实|为深入|为认真|为贯彻|遵照|经.{0,6}(研究|批准|同意)|收悉')),
    ('E 群众感受/一线场景', re.compile(
        r'走访|调研|座谈|实地|现场|入户|面对面|群众反映|一线')),
    ('D 现实问题/形势警示', re.compile(
        r'存在|问题|不足|短板|薄弱|差距|风险|隐患|亟待|面临')),
    ('F 个人经历/白描叙事', re.compile(r'^我|^我们|本人')),
    ('C 制度缺陷', re.compile(r'制度(不|缺)|机制(不|缺)|体制(不|缺)|法制(不|缺)')),
]

# ---------- 引用层级（L4）----------
CITES = [
    ('T1 习近平总书记', re.compile(r'习近平总书记|习近平同志|习近平')),
    ('T2 党中央/全会/党代会', re.compile(r'党中央|中央委员会|全会|党代会|全国代表大会')),
    ('T3 国务院/国家级文件', re.compile(r'国务院|中央人民政府')),
    ('T4 省委省政府/部委党组', re.compile(r'省委|省政府|部党组|部委|省人民政府')),
    ('T5 法律法规', re.compile(r'《[^》]{0,40}(?:法|条例|规定|办法)》')),
    ('T8 古语典故/国际比较', re.compile(r'古人云|所谓|正所谓|《史记|《论语|《孟子|国际经验')),
]

# ---------- 力度词（L5）----------
FORCE = {
    '必须': re.compile(r'必须'),
    '切实': re.compile(r'切实'),
    '要求': re.compile(r'要求'),
    '建议': re.compile(r'建议'),
    '希望': re.compile(r'希望'),
    '严禁/不得': re.compile(r'严禁|不得'),
}

# ---------- 收尾程式（L5）----------
CLOSINGS = [
    ('上行·谦辞在结尾', re.compile(r'妥否.{0,4}请批示|请予批准|以上请示|请审阅|特此报告')),
    ('上行·供参考（开篇式谦辞）', re.compile(r'供.{0,6}(参阅|参考)')),
    ('下行·落款式/督查问责', re.compile(r'严肃追责|考核结果|评先评优|贯彻执行中的问题')),
    ('讲话·程序语', re.compile(r'谢谢大家|我就讲这些|散会|谢谢')),
    ('讲话·号召口号', re.compile(r'作出新的更大贡献|再上新台阶|一定能|必将')),
    ('经验材料·留余地', re.compile(r'初步|假以时日')),
]

# 带单位的数字（用于数据位置分布）
NUM_UNIT = re.compile(r'\d+(?:\.\d+)?\s*(?:%|％|个|项|人|户|家|次|条|万|亿|元|万元|亿元|'
                      r'平方公里|公里|吨|亩|平方米|台|辆|所|篇|份)')
SENT_END = re.compile(r'[。！？；]')


def _db_path(explicit=None):
    if explicit:
        return explicit
    root = os.environ.get('GONGWEN_DATA_ROOT')
    if root:
        p = os.path.join(root, 'gongwen', 'gongwen_corpus.db')
        if os.path.exists(p):
            return p
    return None


def _plain(text):
    """去掉版式噪声：Markdown 标记、页码行、多余空白。"""
    t = re.sub(r'^\s*#{1,6}\s*', '', text, flags=re.M)
    t = re.sub(r'^\s*\d{1,4}\s*$', '', t, flags=re.M)          # 独立成行的页码
    t = re.sub(r'[ \t\u3000]+', '', t)
    return re.sub(r'\n{2,}', '\n', t)


def classify_stance(text, head_chars=120):
    head = text[:head_chars]
    for name, pat in STANCES:
        if pat.search(head):
            return name
    return 'G 其他/无显著信号'


def digit_deciles(text):
    """带单位数字在全文的十分位落点（返回 10 桶计数）。"""
    buckets = [0] * 10
    n = len(text)
    if n < 100:
        return buckets
    for m in NUM_UNIT.finditer(text):
        buckets[min(9, int(10 * m.start() / n))] += 1
    return buckets


def closing_of(text, tail_chars=130):
    tail = text[-tail_chars:]
    hits = [name for name, pat in CLOSINGS if pat.search(tail)]
    return hits or ['自然收束/无程式化结语']


def run(db, table, content_col='content', title_col='title', limit=None):
    con = sqlite3.connect(db)
    con.text_factory = lambda b: b.decode('utf-8', 'replace')
    q = f'SELECT {title_col}, {content_col} FROM {table} WHERE {content_col} IS NOT NULL'
    if limit:
        q += f' LIMIT {int(limit)}'
    rows = con.execute(q).fetchall()
    con.close()

    stance = {}
    cite_hits, cite_cov = {}, {}
    force = {k: 0 for k in FORCE}
    closings = {}
    deciles = [0] * 10
    total_chars = 0
    n = 0

    for _title, raw in rows:
        if not raw:
            continue
        text = _plain(raw)
        if len(text) < 200:
            continue
        n += 1
        total_chars += len(text)

        stance[classify_stance(text)] = stance.get(classify_stance(text), 0) + 1

        for name, pat in CITES:
            hits = len(pat.findall(text))
            if hits:
                cite_hits[name] = cite_hits.get(name, 0) + hits
                cite_cov[name] = cite_cov.get(name, 0) + 1

        for k, pat in FORCE.items():
            force[k] += len(pat.findall(text))

        for c in closing_of(text):
            closings[c] = closings.get(c, 0) + 1

        b = digit_deciles(text)
        deciles = [a + x for a, x in zip(deciles, b)]

    per_k = {k: round(1000.0 * v / total_chars, 2) if total_chars else 0.0
             for k, v in force.items()}
    return {
        'table': table, 'n': n, 'chars': total_chars,
        'stance': stance, 'cite_hits': cite_hits, 'cite_cover': cite_cov,
        'force_per_k': per_k, 'force_raw': force,
        'closings': closings, 'digit_deciles': deciles,
    }


def report(r):
    L = []
    L.append(f'表 {r["table"]} ｜ 参与统计 {r["n"]} 篇 ｜ 正文 {r["chars"]:,} 字')
    L.append('')
    L.append('=== L3 站位（开篇 120 字，取最早出现的信号）===')
    for k, v in sorted(r['stance'].items(), key=lambda x: -x[1]):
        L.append(f'  {k:<28} {v:>6} 篇  {100.0 * v / max(1, r["n"]):>5.1f}%')
    L.append('')
    L.append('=== L4 引用层级（出现次数 / 覆盖篇数）===')
    for k, _ in CITES:
        h, c = r['cite_hits'].get(k, 0), r['cite_cover'].get(k, 0)
        L.append(f'  {k:<28} {h:>7} 次  {c:>6} 篇  {100.0 * c / max(1, r["n"]):>5.1f}%')
    L.append('')
    L.append('=== L4 带单位数字的十分位落点 ===')
    tot = sum(r['digit_deciles']) or 1
    for i, v in enumerate(r['digit_deciles']):
        L.append(f'  {i * 10:>3}-{(i + 1) * 10:>3}%  {v:>7} 个  {100.0 * v / tot:>5.1f}%')
    L.append('')
    L.append('=== L5 力度词（每千字次数）===')
    for k, v in sorted(r['force_per_k'].items(), key=lambda x: -x[1]):
        L.append(f'  {k:<10} {v:>6} 次/千字  （合计 {r["force_raw"][k]} 次）')
    L.append('')
    L.append('=== L5 收尾程式（末 130 字；可多重命中）===')
    for k, v in sorted(r['closings'].items(), key=lambda x: -x[1]):
        L.append(f'  {k:<28} {v:>6} 篇  {100.0 * v / max(1, r["n"]):>5.1f}%')
    return '\n'.join(L)


def main():
    ap = argparse.ArgumentParser(description='认知层统计（L3–L5，只读本机语料库）')
    ap.add_argument('--db', default=None, help='语料库路径（默认取 GONGWEN_DATA_ROOT）')
    ap.add_argument('--table', default='articles', help='统计表（articles / jhsjk_articles）')
    ap.add_argument('--limit', type=int, default=None, help='限额采样（快跑）')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()

    db = _db_path(a.db)
    if not db:
        print('未找到语料库：请用 --db 指定，或设置 GONGWEN_DATA_ROOT。', file=sys.stderr)
        return 2
    if not os.path.exists(db):
        print(f'语料库不存在: {db}', file=sys.stderr)
        return 2

    r = run(db, a.table, limit=a.limit)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(report(r))
    print()
    print('⚠ 口径声明：以上数值只覆盖本表实际收录的文体。'
          '若本表不含「调研报告/领导讲话/工作意见/经验材料/经验总结」这些内部工作材料，'
          '则这些数值**不能**套用到那些文种上——引用时必须写明统计来源表与篇数。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
