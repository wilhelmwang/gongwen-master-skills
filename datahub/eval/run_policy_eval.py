#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""政策原文定向评测（方案 B 的「能力线」，2026-09-16）

它和 `run_eval.py` 的分工
-------------------------
| | `run_eval.py`（104 条） | 本器（16 条） |
|---|---|---|
| gold 怎么来 | `build_gold.py` 从 `articles` 表**按标题批量派生** | **手工指定具体文档**（URL 精确） |
| gold 密度 | 34.6%（单条查询动辄几百篇） | 每条 1~2 篇 |
| 量的是什么 | 主库检索整体质量（回归线） | **政策原文能否被定位**（能力线） |
| 四库并入前后的可比性 | **不可比**——并入后重派生 gold，单条从 276 涨到 4,428，指标因判据变松而虚涨 | **可比**——gold 是外部指定的文档，不受语料变化影响 |

所以「四库要不要并进主库检索」这个问题，只能由本器回答。命令：

    python datahub/eval/run_policy_eval.py                  # 走政策四库通道（现状）
    python datahub/eval/run_policy_eval.py --channel unified # 走 hybrid3 统一检索（并入前后的"前"）

`--channel unified` 现在**预期全部落空**（四库不在 articles 里、索引也没它们），
这是如实测量——它就是「并之前」的基线。将来真并入后重跑同一条命令，差值才是可信增量。

退出码：0 = 达标；1 = 低于地板；2 = 环境不可用（四库缺失）
"""
import argparse
import io
import json
import os
import sys


def _stdout_encoding_guard():
    """非交互流强制 UTF-8，交互控制台保 locale 只降级不可编码字符。

    Windows 上 CPython 对 pipe/重定向用 locale 编码（cp936），遇 ✅⚠✓ 等符号抛
    UnicodeEncodeError 中断脚本；agent 调脚本时 stdout 恒为管道 ⇒ 必崩。
    真控制台不能改 encoding（字节流仍按控制台代码页渲染，会中文乱码）。
    """
    try:
        for _st in (sys.stdout, sys.stderr):
            if _st is None or not hasattr(_st, 'reconfigure'):
                continue
            if _st.isatty():
                _st.reconfigure(errors='replace')
            else:
                _st.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


_stdout_encoding_guard()

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CASES = os.path.join(BASE, 'datahub', 'eval', 'policy_cases.json')
ZC = os.path.join(BASE, 'datahub', 'scripts', 'zc')

#: 地板（2026-09-16 首测后据实测设定；**下调须说明理由**）
FLOOR_HIT = 0.90         # hit@5
FLOOR_MRR = 0.70


def _load_zc():
    """按需导入政策检索器（同包内脚本，直接复用其口径，不另写一套检索）"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'search_zhengce', os.path.join(ZC, 'search_zhengce.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _urls_zc(zc, case, per):
    """政策四库通道：返回 {库: [url…]}。

    ⚠️ **必须按库分别判名次**，不能把四库结果拼成一条表：工具的输出本来就是
    按库分列的（用户看到的是"中央文件 5 条 / 国务院文件 5 条 / …"），
    拼表会把第二个库的第 1 名算成总表第 6 名 → 明明排第一却记 MISS。
    首版就踩了这个（p11/p12/p14 全被误判为未命中，实为各自库内 rank 1/1/3）。

    wenhao 类走文号查（工具为该场景提供的模式），结果归入 'wenhao' 一档。
    """
    out = {}
    if case.get('kind') == 'wenhao':
        out['wenhao'] = [r[6] for _s, r in zc.search_wenhao(case['q'], per)]
        return out
    for short, _name, _p, form in zc.policy_libs():
        if form is None:
            continue
        rows, _how = zc.search_one(short, case['q'], per)
        out[short] = [r[6] for r in (rows or [])]
    return out


def _urls_unified(case, per):
    """hybrid3 统一检索通道（并入四库后的对照通道）"""
    sys.path.insert(0, os.path.join(BASE, 'datahub', 'scripts', 'qs'))
    from qiushi_engine import search_database
    res = search_database(case['q'], top_n=per, use_semantic=True)
    out = []
    for r in (res or []):
        u = r.get('url') if isinstance(r, dict) else None
        if u:
            out.append(u)
    return out


def main():
    ap = argparse.ArgumentParser(description='政策原文定向评测（能力线）')
    ap.add_argument('--channel', default='zc', choices=('zc', 'unified'),
                    help='zc = 政策四库通道（现状）；unified = hybrid3 统一检索（并入前后对照）')
    ap.add_argument('--per', type=int, default=5, help='取前 N 条判定 hit@N（默认 5）')
    ap.add_argument('--json', action='store_true', help='机器可读输出')
    a = ap.parse_args()

    data = json.load(io.open(CASES, encoding='utf-8'))
    cases = data['cases']

    zc = None
    if a.channel == 'zc':
        zc = _load_zc()
        have = [f for _s, _n, _p, f in zc.policy_libs() if f]
        if not have:
            print('政策四库全部缺失（形态 C 或未采到）——本器需要这四库，无法评测。')
            return 2
        print(f'通道：政策四库（{len(have)} 库在位）｜ 取前 {a.per} 条')
    else:
        print(f'通道：hybrid3 统一检索 ｜ 取前 {a.per} 条')

    rows, hits, rr_sum = [], 0, 0.0
    by_diff = {}
    for c in cases:
        try:
            if a.channel == 'zc':
                per_lib = _urls_zc(zc, c, a.per)
            else:
                per_lib = {'unified': _urls_unified(c, a.per)}
        except Exception as e:
            per_lib = {}
            c['_err'] = f'{type(e).__name__}: {str(e)[:60]}'
        gold = set(c['gold'])
        # 每条候选列内取 gold 的最优名次（按列判，不跨列拼接）
        rank = 0
        for urls in per_lib.values():
            i = next((k + 1 for k, u in enumerate(urls) if u in gold), 0)
            if i and (not rank or i < rank):
                rank = i
        # ⚠️ 按 top-N 截断判定（标准 cutoff）：超出 N 名即未命中，MRR 按 0 计。
        # 不截断的话"排第 14 也算命中"，指标虚高——首版踩过。
        if rank > a.per:
            rank = 0
        if rank:
            hits += 1
            rr_sum += 1.0 / rank
        diff = c.get('difficulty', 'core')
        by_diff.setdefault(diff, []).append(rank)
        rows.append((c['id'], c['kind'], rank, diff, c.get('_err', '')))

    n = max(len(cases), 1)
    hit_rate = hits / n
    mrr = rr_sum / n
    if a.json:
        print(json.dumps({'channel': a.channel, 'n': len(cases),
                          'hit_rate': round(hit_rate, 4), 'mrr': round(mrr, 4),
                          'per': a.per,
                          'rows': [{'id': i, 'kind': k, 'rank': r,
                                    'difficulty': d, 'err': e}
                                   for i, k, r, d, e in rows]},
                         ensure_ascii=False, indent=2))
    else:
        for i, k, r, d, e in rows:
            mark = f'rank {r}' if r else 'MISS'
            flag = '★' if d == 'hard' else ' '
            print(f'  {flag}{"✓" if r else "✗"} {i} [{k:8s}] {mark}'
                  f'{"  " + e if e else ""}')
        print(f'\nhit@{a.per} {hits}/{len(cases)} = {hit_rate:.1%}'
              f' ｜ MRR {mrr:.3f}')
        # 分组只报数、**不分开设地板**——分开设等于把难点藏起来
        for d, ranks in sorted(by_diff.items()):
            h = sum(1 for x in ranks if x)
            m = sum(1.0 / x for x in ranks if x) / max(len(ranks), 1)
            print(f'  {d:5s}（{len(ranks)} 条）：hit@{a.per} {h}/{len(ranks)}'
                  f' = {h / len(ranks):.1%} ｜ MRR {m:.3f}')
        print(f'地板（整体）：hit@{a.per} ≥{FLOOR_HIT:.0%} ｜ MRR ≥{FLOOR_MRR:.2f}')

    ok = hit_rate >= FLOOR_HIT and mrr >= FLOOR_MRR
    if not a.json:
        print('✅ 达标' if ok else '❌ 低于地板')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
