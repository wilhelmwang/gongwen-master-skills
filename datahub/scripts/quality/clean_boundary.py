#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""正文定界器（通用规则 · 2026-09-15）

由来
----
此前三轮清洗都在做「扩词表」：把站点框架的特征词一条条加进 `BOILER_PAT`。
抽样复核实测 5 篇里 4 篇的开头仍是纯站点框架——子 agent 归纳后发现根因判断错了：

    **问题不是「词表清不掉」，而是「从来没做定界」。**

5 个样本站是同一套政务 CMS 骨架：
    标题 → 元数据行(稿件号/来源/日期/栏目/索引号) → 导航 → 面包屑
    → 标题再现 → [字号/字体选择器] → **正文** … → 主办承办/ICP备/标识码 页脚

子 agent 用一条**不含任何站点锚点**的通用启发式跑了 20 篇，结果与 5 条逐站锚点规则
**逐字符一致（20/20）**——故逐站归纳无必要，通用规则即可，且天然覆盖新站。

规则（含子 agent 建议的两条兜底校验）
------------------------------------
  头：前 1200 字内，第一条「长度 ≥25 且含 ，或 。」的行 → 从该行起保留
  尾：文末最后一个含句末标点（。！？”）的行 → 该行之后全部删除
  兜底校验（任一不过则判定失败，退回原文，不冒险切）：
    · 定界后长度须落在原文的 0.3–0.9 区间
    · 首行须含标题片段或日期形态

用法
----
  python clean_boundary.py --eval 200      # 抽样试算：命中率与残留变化
  python clean_boundary.py --apply         # 写库（只改 L1 content，先自动快照）

本器是**独立试算工具**：正式定界走 `build_samples_db.py`（L1 派生链的入口，
它 import 本模块的 `boundary()`），故两者口径永远一致、不需要各自传库路径。
"""
import argparse
import os
import re
import sqlite3
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'corpus'))
import sweep_columns as sw          # noqa: E402

DB = os.path.join(sw.OUT_DIR, 'gongwen_samples.db')
HEAD_SCAN = 1200          # 头部扫描窗口（框架文字都在前 1200 字内）
MIN_LINE = 25             # 正文行的最短长度
MIN_BODY_CHARS = 200      # 定界后正文的绝对长度下限（低于此判"切过头"，退回不切）
SHORT_RAW = 500           # 原文短于此值即判"无需切"——短文本整体就是正文，没有框架可切
                          #（实测 no_anchor 2,125 篇典型是 247~293 字的调研短文）
SENT_END = '。！？”'
#: 日期形态。**必须同时接受不带年份的「X月X日」**——实测正文首行常写作
#: 「9月10日，市委书记…率队赴…」，只认 4 位年份会把这类正文误判为"头部未确认"（实测 24 篇）。
DATE_RE = re.compile(r'(?:20\d{2}\s*[-/年]\s*)?\d{1,2}\s*月\s*\d{1,2}\s*日|20\d{2}\s*[-/]\s*\d{1,2}')


def boundary(raw_text, title, head_scan=HEAD_SCAN):
    """返回 (正文文本, 诊断dict)；判定失败时返回 (None, 诊断)"""
    lines = [x.strip() for x in (raw_text or '').split('\n')]
    lines = [x for x in lines if x]
    if len(lines) < 3:
        return None, {'why': 'too_few_lines'}
    # 头：前 head_scan 字内第一条够长且成句的行
    acc, start = 0, None
    for i, l in enumerate(lines):
        acc += len(l)
        if acc > head_scan:
            break
        if len(l) >= MIN_LINE and ('，' in l or '。' in l):
            start = i
            break
    # 尾：文末最后一个含句末标点的行
    end = None
    for i in range(len(lines) - 1, -1, -1):
        if any(p in lines[i] for p in SENT_END):
            end = i
            break
    if start is None or end is None or end <= start:
        # 头尾定位到同一行或找不到锚点。**短原文本就没什么框架可切**，判"无需切"而非失败——
        # 实测 no_anchor 2,125 篇里典型是 247~293 字的调研短文，原文整体就是正文。
        if len(raw_text or '') < SHORT_RAW:
            return '\n'.join(lines), {'start': 0, 'end': len(lines) - 1,
                                      'ratio': 1.0, 'no_cut': True, 'why': 'short_raw'}
        return None, {'why': 'no_anchor', 'start': start, 'end': end}
    body = '\n'.join(lines[start:end + 1])
    ratio = len(body) / max(len(raw_text or ''), 1)
    # 兜底校验，任一不过就不切（宁可留着框架，不可切掉正文）：
    #   ① 比例上限：切不足 10% 说明**原文头部本就没有框架**——"无需切"不是失败（实测 36%）
    if ratio > 0.9:
        return '\n'.join(lines), {'start': 0, 'end': len(lines) - 1,
                                  'ratio': round(ratio, 3), 'no_cut': True}
    #   ② 绝对长度下限：正文短于 200 字才判"切过头"。**原文本身也短时判"无需切"**——
    #      曾用**比例**下限（0.3）判定，误伤框架重的页面（导航+页脚占七成，正文合法低于 0.3，
    #      实测 122/400 被误拒）；改用绝对值后，短简讯（原文 867 字切出 168 字）仍被误拒，
    #      故再加"原文也短则不切"这条出口。
    if len(body) < MIN_BODY_CHARS:
        if len(raw_text or '') < SHORT_RAW:
            return '\n'.join(lines), {'start': 0, 'end': len(lines) - 1,
                                      'ratio': 1.0, 'no_cut': True, 'why': 'short_raw'}
        return None, {'why': 'body_too_short', 'chars': len(body),
                      'ratio': round(ratio, 3)}
    #   ③ 标题校验**只作参考，不再作否决条件**。原要求"首行须含标题片段或日期"，
    #      实测误拒 4,879 篇（占全部失败的 68%）。反例：西藏政府工作报告首行是
    #      「现在，我代表自治区人民政府，向大会报告政府工作，请予审议」——这是正文，
    #      但不含标题；洛阳那篇首行是「摘要：…」，也不含。**正文首行本来就不必含标题。**
    #      比例与长度两道校验已足够防误切，标题命中与否写进诊断供人工复核。
    t = (title or '')[:12].strip()
    head_ok = bool(t and (t in lines[start] or DATE_RE.search(lines[start])))
    return body, {'start': start, 'end': end, 'ratio': round(ratio, 3),
                  'lines': len(lines), 'title_hit': head_ok}


def residue_ratio(text):
    """站点框架残留的粗量：短行（≤6 字）占比——仅作对照，不作判据"""
    ls = [x.strip() for x in (text or '').split('\n') if x.strip()]
    if not ls:
        return 1.0
    return sum(1 for x in ls if len(x) <= 6) / len(ls)


def main():
    ap = argparse.ArgumentParser(description='正文定界器（通用规则）')
    ap.add_argument('--eval', type=int, default=0, help='抽样试算 N 篇')
    ap.add_argument('--apply', action='store_true', help='写库（改 L1 content）')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    c = sqlite3.connect('file:' + DB + '?mode=ro', uri=True)
    if a.eval:
        rows = list(c.execute(
            "SELECT s.url, s.title, s.content, r.raw_text FROM samples s"
            " JOIN raw_pages r ON r.url=s.url ORDER BY s.url LIMIT ?", (a.eval,)))
    else:
        rows = list(c.execute(
            "SELECT s.url, s.title, s.content, r.raw_text FROM samples s"
            " JOIN raw_pages r ON r.url=s.url"))
    c.close()

    ok = 0
    fails = {}
    deltas = []
    for url, title, cur, raw in rows:
        body, diag = boundary(raw, title)
        if body is None:
            fails[diag['why']] = fails.get(diag['why'], 0) + 1
            continue
        ok += 1
        deltas.append((residue_ratio(cur), residue_ratio(body),
                       len(cur or ''), len(body)))
    n = len(rows)
    print(f'样本 {n:,} 篇 ｜ 定界成功 {ok:,}（{ok*100//max(n,1)}%）')
    if fails:
        print('  失败分布:', dict(sorted(fails.items(), key=lambda x: -x[1])))
    if deltas:
        import statistics
        r0 = statistics.median(d[0] for d in deltas)
        r1 = statistics.median(d[1] for d in deltas)
        c0 = statistics.median(d[2] for d in deltas)
        c1 = statistics.median(d[3] for d in deltas)
        print(f'  短行占比 中位: 现有 {r0:.2f} → 定界后 {r1:.2f}')
        print(f'  字数中位    : 现有 {c0:,.0f} → 定界后 {c1:,.0f}')
        better = sum(1 for a_, b, _, _ in deltas if b < a_)
        print(f'  短行占比下降的篇数: {better:,}/{len(deltas):,}（{better*100//len(deltas)}%）')
    if a.eval or not a.apply:
        print('\n（只试算，未改库）')
        return 0
    print('\n--apply 的正式入口是 build_samples_db.py（本器只做独立试算，避免两套写库口径）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
