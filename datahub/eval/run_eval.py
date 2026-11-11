# -*- coding: utf-8 -*-
"""检索质量评测器（v1.1 · 2026-09-11）
用法：python run_eval.py [--top N] [--tier term|paraphrase|topic|hard] [--mrr-hard] [--json]
判定：TOP-N 中标题/摘要含 expected 任一关键词即命中（N@N 命中率）

v1.2 变更（B 批 · v7.4.0）：
  · 接入 **gold 文档集**（`datahub/eval/gold_ids.json`，由 build_gold.py 级联推导）：
    新增 gold_hit@k / MRR@first-gold（全量）+ precision@k / recall@k（仅 tight 子集，
    因宽 gold 下 precision 天然很低、报了没意义）。旧的关键词子串判据保留，
    以便与历史基线（99%/MRR 0.946）连续对比。
  · 新增**延迟指标**：冷启动（首查询，含索引加载）与热查询 mean/p50/p95 分开报——
    冷启动 3.6s 与热查询 1.5ms 是同一条命令里的两个数量级，混在一起没有意义。
v1.1 变更：
  · 实现 `--mrr-hard`（v1.0 的 print 里建议用该参数，但从未实现 —— ghost 参数）
  · 新增**分层指标**：整体命中率会掩盖 hard 层的退化，故按 tier 分别给出 n/命中/MRR
  · 新增 `--json`（供 release 流水线与 CI 消费，免去正则解析）

退出码：命中率 ≥0.6 且无检索异常 → 0；否则 1。
注意：release 门禁按「整体 ≥98% / MRR ≥0.935 / gold ≥72%」卡基线（与 release_gates.json 的地板一致），比本脚本自身阈值严得多；开向量路实测 99% / 0.974 / gold 74.0%（2026-09-28，20,680 篇语料）。
"""
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
sys.path.insert(0, os.path.join(BASE, 'datahub', 'scripts', 'qs'))
GOLD_PATH = os.path.join(BASE, 'datahub', 'eval', 'gold_ids.json')


def _load_gold():
    """载入 gold 文档集；缺失时返回 None（新指标跳过，旧判据照常）"""
    try:
        d = json.load(open(GOLD_PATH, encoding='utf-8'))
        return {r['idx']: r for r in d['queries']}
    except Exception:
        return None


def _opt(args, name, default=None):
    return args[args.index(name) + 1] if name in args else default


def main():
    args = sys.argv[1:]
    top = int(_opt(args, '--top', 3))
    tier = _opt(args, '--tier')
    only_hard = '--mrr-hard' in args
    as_json = '--json' in args

    from qiushi_engine import SemanticSearch
    ss = SemanticSearch()
    data = json.load(open(os.path.join(BASE, 'datahub', 'eval', 'benchmark_queries.json'),
                          encoding='utf-8'))
    qs = [x for x in data['queries'] if tier is None or x['tier'] == tier]

    import time as _t
    gold_all = _load_gold()
    hit = miss = 0
    mrr_sum = 0.0
    search_fail = 0
    per_tier = {}                                   # tier → [n, hit, mrr_sum]
    lat = []                                        # 每查询耗时(ms)
    g_hit = g_mrr = g_n = 0                         # gold：命中数 / MRR 累加 / 参与数
    p_sum = r_sum = p_n = 0                         # precision/recall（仅 tight 子集）
    for _qi, item in enumerate(qs):
        _t0 = _t.perf_counter()
        try:
            r = ss.search(item['q'], top_n=top, mode='hybrid3')
        except Exception as e:
            # v6.8.1 修复（P0-1 延伸）：原裸 except 静默吞异常，向量路失效无感知。
            # 现改为记录并计数，评测结束时显式汇报，防止"降级模式"假成绩。
            r = []
            search_fail += 1
            print(f"  ⚠ 检索异常 [{item['q'][:18]}]: {type(e).__name__}: {e}")
        lat.append((_t.perf_counter() - _t0) * 1000)

        # ---- gold 指标（若 gold 集可用）----
        gi = gold_all.get(_qi) if gold_all else None
        if gi and gi.get('gold'):
            gset = set(gi['gold'])
            got_ids = [x.get('id') for x in r[:top]]
            ranks = [i for i, aid in enumerate(got_ids, 1) if aid in gset]
            g_n += 1
            inter = len([a for a in got_ids if a in gset])
            if ranks:
                g_hit += 1
                g_mrr += 1.0 / ranks[0]
            if gi.get('tight'):
                # tight 子集统计**全部**紧查询（未命中记 0），
                # 否则会把"命中率"混进 precision 的分母（曾误算成 25/41 只取命中者）
                p_n += 1
                p_sum += inter / max(1, min(top, len(got_ids)))
                r_sum += inter / min(len(gset), top)

        mrr_n = None
        for rank, x in enumerate(r[:top], 1):
            text = (x.get('title') or '') + ' ' + (x.get('snippet') or '')
            if any(k in text for k in item['expected']):
                mrr_n = rank
                break
        t = item.get('tier', 'unknown')
        st = per_tier.setdefault(t, [0, 0, 0.0])
        st[0] += 1
        if mrr_n:
            hit += 1
            mrr_sum += 1.0 / mrr_n
            st[1] += 1
            st[2] += 1.0 / mrr_n
        else:
            miss += 1
            print(f"  ✗ [{item['tier']}] {item['q'][:22]} 期望 {item['expected']}")

    n = len(qs)
    mrr = mrr_sum / n
    # —— 整体行（格式保持稳定：release 门禁按本行解析基线）——
    print(f'\n评测集 {n} 条 | N@{top} 命中 {hit} | 未命中 {miss} | 命中率 {hit/n:.0%} | MRR {mrr:.3f} | 最佳位 中位/均值见下')
    if search_fail:
        print(f'⚠ 检索异常 {search_fail} 条（向量路/索引故障，结果不可信，请先修复）')

    # —— 分层指标：整体 99% 会掩盖 hard 层退化 ——
    tiers = {t: (v[0], v[1], v[2] / v[0] if v[0] else 0.0) for t, v in per_tier.items()}
    if len(tiers) > 1 or tier is None:
        print('分层结果（整体命中率会掩盖难层退化，故单列）：')
        for t in sorted(tiers):
            tn, th, tm = tiers[t]
            print(f'  {t:11s} n={tn:3d}  命中 {th}/{tn}  命中率 {th/tn:.0%}  MRR {tm:.3f}')

    # ---- gold 指标与延迟（v1.2）----
    if g_n:
        print(f'gold 指标（gold 集 {g_n} 条有效）：'
              f'  gold_hit@{top} {g_hit}/{g_n} = {g_hit/g_n:.1%} ｜ MRR@first-gold {g_mrr/g_n:.3f}')
        if p_n:
            print(f'  tight 子集（AND_T 且 ≤20 篇，{p_n} 条）: '
                  f'precision@{top} {p_sum/p_n:.3f} ｜ recall@{top} {r_sum/p_n:.3f}')
        else:
            print('  （无 tight 子集，未报 precision/recall——宽 gold 下该指标无意义）')
    else:
        print('gold 指标: 未接入（缺 gold_ids.json；跑 `python build_gold.py` 生成）')

    if lat:
        warm = sorted(lat[1:]) or lat                # 首条含索引加载，单列为冷启动
        def _pct(a, p):
            return a[min(len(a) - 1, int(len(a) * p))] if a else 0.0
        print(f'延迟: 冷启动(首查询) {lat[0]:.0f}ms ｜ 热查询 mean {sum(warm)/len(warm):.1f}ms'
              f' / p50 {_pct(warm, 0.5):.1f}ms / p95 {_pct(warm, 0.95):.1f}ms（n={len(warm)}）')

    if only_hard:
        if 'hard' in tiers:
            tn, th, tm = tiers['hard']
            print(f'\n>>> Hard 层（--mrr-hard）: n={tn} 命中 {th}/{tn} ({th/tn:.0%}) MRR={tm:.3f}')
        else:
            print('\n>>> Hard 层（--mrr-hard）: 本次评测集不含 hard 层'
                  f'（当前 tier 过滤={tier!r}）')

    if as_json:
        print(json.dumps({'n': n, 'top': top, 'tier_filter': tier, 'hit': hit, 'miss': miss,
                          'hit_rate': hit / n, 'mrr': mrr, 'search_fail': search_fail,
                          'per_tier': {t: {'n': v[0], 'hit': v[1], 'mrr': v[2]}
                                       for t, v in tiers.items()},
                          'gold': {'n': g_n, 'hit': g_hit,
                                   'hit_rate': (g_hit / g_n) if g_n else None,
                                   'mrr': (g_mrr / g_n) if g_n else None,
                                   'tight_n': p_n,
                                   'precision': (p_sum / p_n) if p_n else None,
                                   'recall': (r_sum / p_n) if p_n else None},
                          'latency_ms': {'cold': lat[0] if lat else None,
                                         'warm_mean': (sum(lat[1:]) / len(lat[1:])) if len(lat) > 1 else None}},
                         ensure_ascii=False))

    return 0 if (hit / n >= 0.6 and search_fail == 0) else 1


if __name__ == '__main__':
    sys.exit(main())
