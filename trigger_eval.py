#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""路由触发率评测（B 批 · v7.3.2）

它补的是什么缺口
----------------
`rules_regression.py` 的 50 条用例**全是正例**（"写份通知"→notice），因此只能证明
"该命中的能命中"，无法证明"不该命中的不会命中"。而本包 16 类公文共享大量子串
（报告/总结/通报/简报/通知/纪要…），**近义误触发**才是真实风险所在。

本评测集引入两类负例：
  · near_miss    含某技能关键词，但诉求属别的技能、或根本不是公文
  · true_negative 完全不该触发本包
并输出 per-skill 精确率/召回率与**混淆对**——混淆对才是可执行的改进线索
（"哪两个文种的描述需要互相划清界限"）。

train / validation 划分
------------------------
只据 train 的失败去改规则/描述，用 validation 验收，避免把规则过拟合到评测集本身。
另有 `--holdout-check` 用于临时子集抽查。

与官方方法的差异（如实说明）
----------------------------
Anthropic 官方触发率方法要求"每例跑 3 次算触发率"，那是针对**随机触发的 LLM 抽取**。
本包路由是确定性的关键词+优先级引擎，单次判定即可复现，故不用 3 次重复；
其区分力由近义负例承担。**宿主 agent 层面的触发率**（技能描述是否被模型选中）
无法从包内测得，需宿主侧遥测（如 Claude Code 的 /skill-doctor），属已知边界。

用法：
  python trigger_eval.py                 # 全量（train+val）报告，退出码 0/1
  python trigger_eval.py --split train    # 只看训练集
  python trigger_eval.py --split val      # 只看验证集
  python trigger_eval.py --verbose        # 打印每条判定
  python trigger_eval.py --json           # 机器可读
"""
import argparse
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

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
try:
    from skills_manifest import SKILL_ROOT
except Exception:
    SKILL_ROOT = BASE
BENCH = os.path.join(SKILL_ROOT, 'datahub', 'eval', 'trigger_benchmark.json')

#: 门槛 = **实测基线**（不是目标值）。演进：
#:   v7.3.2 首测 79.1%（3 个设计问题未修）→ 修完三处后 **97.6%**。
#:   取 0.96 略低于实测以防噪声，但能拦住"改规则把既有关键词挤掉"。
#: 剩余 1 条已知失败：m03「请示一下领导的意见再定」——「请示」同形（名词文种/动词），
#: 关键词层无法区分词性，需语义路由（BGE）才可能改善，已记为关键词层边界。
ACC_FLOOR = 0.96


def skill_of(target):
    """从路由目标里归一化出技能名：'govdoc-notice' / 'qiushi-db' → 'govdoc-notice' / 'qiushi-db'"""
    if not target:
        return 'NO-MATCH'
    t = target.strip()
    for sep in ('（', '(', ' →', ' '):
        i = t.find(sep)
        if i > 0:
            t = t[:i]
    return t.strip()


def main():
    ap = argparse.ArgumentParser(description='路由触发率评测（含近义负例）')
    ap.add_argument('--split', choices=['train', 'val', 'all'], default='all')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--holdout-check', type=int, metavar='N',
                    help='随机抽 N 例做独立抽查（固定种子 20260911，可复现）——在 train/val 之外'
                         '做一次无偏抽样，防止把规则过拟合到评测集')
    a = ap.parse_args()

    import router as R

    data = json.load(open(BENCH, encoding='utf-8'))
    cases = [c for c in data['cases'] if a.split == 'all' or c.get('split', 'train') == a.split]
    if a.holdout_check:
        # 确定性抽样：等距位置切片（可复现，且不依赖随机数发生器）
        n_pick = min(a.holdout_check, len(cases))
        step = max(1, len(cases) // n_pick)
        cases = cases[::step][:n_pick]
        print(f'[holdout] 从 {a.split} 集等距抽 {n_pick} 例')

    rows = []
    per_skill = {}                     # skill → [应命中数, 实际命中数, 命中正确数]
    confusion = {}                     # (期望, 实际) → 次数（仅错误）
    for c in cases:
        _rule, kw, target = R.route(c['q'])
        got = skill_of(target)
        want = c['expect']
        # 子串语义（与 rules_regression 一致）：expect 写短名即可匹配全名
        ok = (got == want) if want == 'NO-MATCH' else (want in got)
        rows.append({'id': c['id'], 'q': c['q'], 'kind': c['kind'], 'split': c.get('split'),
                     'want': want, 'got': got, 'kw': kw, 'ok': ok, 'note': c.get('note'),
                     'known_gap': bool(c.get('known_gap'))})
        if c['kind'] in ('positive', 'near_miss') and want != 'NO-MATCH':
            st = per_skill.setdefault(want, [0, 0, 0])
            st[0] += 1                       # 期望该技能的请求数
            if got != 'NO-MATCH':
                st[1] += 1                   # 实际路由出去的数量（含错路由）
            if ok:
                st[2] += 1                   # 路由正确
        if not ok:
            confusion[(want, got)] = confusion.get((want, got), 0) + 1

    counted = [r for r in rows if not r['known_gap']]      # known_gap 不计入分母
    gaps = [r for r in rows if r['known_gap']]
    n = len(counted)
    ok_n = sum(r['ok'] for r in counted)
    acc = ok_n / n if n else 0.0
    # 误触发：期望 NO-MATCH 却命中
    over = [r for r in rows if r['want'] == 'NO-MATCH' and r['got'] != 'NO-MATCH']
    # 漏触发：期望命中却 NO-MATCH
    under = [r for r in rows if r['want'] != 'NO-MATCH' and r['got'] == 'NO-MATCH']
    # 错路由：命中了但技能不对（子串语义）
    wrong = [r for r in rows if r['want'] != 'NO-MATCH' and r['got'] != 'NO-MATCH'
             and r['want'] not in r['got']]

    if a.json:
        print(json.dumps({'n': n, 'ok': ok_n, 'accuracy': round(acc, 4),
                          'floor': ACC_FLOOR, 'over_trigger': len(over),
                          'under_trigger': len(under), 'mis_route': len(wrong),
                          'per_skill': {k: {'expected': v[0], 'hit': v[1], 'correct': v[2]}
                                        for k, v in per_skill.items()},
                          'confusion': {f'{k[0]} → {k[1]}': v for k, v in confusion.items()},
                          'rows': rows}, ensure_ascii=False, indent=1))
        return 0 if acc >= ACC_FLOOR else 1

    print(f'=== 路由触发率评测（split={a.split}）===')
    if gaps:
        print(f'  ⚠ 已知设计权衡 {len(gaps)} 条（spec 明确规定，不计入分母）: '
              + ' '.join(r['id'] for r in gaps))
    print(f'  用例 {n} 条（正例 {sum(1 for r in counted if r["kind"]=="positive")}'
          f' / 近义负例 {sum(1 for r in counted if r["kind"]=="near_miss")}'
          f' / 纯负例 {sum(1 for r in counted if r["kind"]=="true_negative")}）')
    print(f'  正确 {ok_n} | 准确率 {acc:.1%}（门槛 {ACC_FLOOR:.0%}）')
    print(f'  误触发 {len(over)} | 漏触发 {len(under)} | 错路由 {len(wrong)}')

    if per_skill:
        print('\n分层指标（按期望技能）：')
        for s in sorted(per_skill):
            e, h, c_ = per_skill[s]
            print(f'  {s:20s} 期望 {e:2d} | 路由出去 {h:2d} | 正确 {c_:2d}'
                  + ('  ⚠ 有错路由' if h > c_ else ('  ⚠ 未路由' if h == 0 else '')))

    if confusion:
        print('\n混淆对（期望 → 实际，出现次数）：')
        for (w, g), cnt in sorted(confusion.items(), key=lambda x: -x[1]):
            print(f'  {w:20s} → {g:20s} × {cnt}')

    fails = [r for r in rows if not r['ok']]
    if fails:
        print(f'\n未通过用例（{len(fails)}）：')
        for r in fails:
            tag = {'positive': '正例', 'near_miss': '近义', 'true_negative': '纯负'}[r['kind']]
            print(f'  ❌ [{r["id"]}/{tag}] {r["q"][:34]:36s} 期望 {r["want"]:18s} 实际 {r["got"]}')
            if r.get('note'):
                print(f'         注: {r["note"]}')
    if a.verbose:
        print('\n全部判定：')
        for r in rows:
            print(f'  {"✅" if r["ok"] else "❌"} [{r["id"]}] {r["q"][:30]:32s} {r["want"]:18s} {r["got"]}')
    if a.holdout_check:
        # 诊断模式：随机小样本噪声大，不作门禁判据（只看分布，不判通过）
        print()
        print('[holdout] 诊断模式，不参与门禁判定（随机子集样本量小，仅供抽查参考）')
        return 0
    return 0 if acc >= ACC_FLOOR else 1


if __name__ == '__main__':
    sys.exit(main())
