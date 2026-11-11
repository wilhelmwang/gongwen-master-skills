#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gold 回归线守卫：当前 gold_ids.json 是否与冻结记录一致（2026-09-16）

为什么需要它
------------
`run_eval.py` 的 104 条指标之所以能当基线，前提是 **gold 判据本身不动**。
而 `build_gold.py` 会按「标题含关键词」从 `articles` 表**重新派生** gold——
实测重派生会把 gold 槽位从 7,145 放大到 35,615（104 条里 65 条变大，
最大一条 289 → 5,413，占语料 26%），**gold 占比一高指标就虚升**。
也就是说：顺手跑一次 `python build_gold.py`，评测就悄悄放宽了，而检索毫无改善。

本器把「判据变松」变成**显式动作**：哈希不符即 FAIL，逼你按
`gold_freeze.json:how_to_change` 走一遍并留痕。

用法
----
  python datahub/eval/check_gold_freeze.py              # 校验（门禁用；0 = 一致）
  python datahub/eval/check_gold_freeze.py --explain     # 顺带说明重派生会差多少
  python datahub/eval/check_gold_freeze.py --show        # 打印冻结记录全文

退出码：0 = 一致；1 = 不一致（判据被改过）；2 = 冻结记录或 gold 文件缺失
"""
import argparse
import hashlib
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
EVAL = os.path.join(BASE, 'datahub', 'eval')
FREEZE = os.path.join(EVAL, 'gold_freeze.json')
GOLD = os.path.join(EVAL, 'gold_ids.json')


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description='gold 回归线守卫')
    ap.add_argument('--explain', action='store_true', help='说明重派生会差多少')
    ap.add_argument('--show', action='store_true', help='打印冻结记录全文')
    a = ap.parse_args()

    if not os.path.exists(FREEZE):
        print(f'缺冻结记录：{FREEZE}（无法判定 gold 判据是否被动过）')
        return 2
    rec = json.load(io.open(FREEZE, encoding='utf-8'))
    if a.show:
        print(json.dumps(rec, ensure_ascii=False, indent=2))
        return 0
    if not os.path.exists(GOLD):
        print(f'缺 gold 文件：{GOLD}（跑 `python build_gold.py` 派生，再按冻结流程留痕）')
        return 2

    cur = sha256(GOLD)
    n_cur = len(json.load(io.open(GOLD, encoding='utf-8'))['queries'])
    ok = (cur == rec['sha256'])
    print(f'冻结基准 sha256 {rec["sha256"][:16]}…（{rec["n_queries"]} 条 / '
          f'{rec["slots"]:,} 槽位）')
    print(f'当前文件 sha256 {cur[:16]}…（{n_cur} 条）')
    if ok:
        print('✅ gold 判据与冻结一致——现有 104 条指标与基线可比')
        return 0

    print('❌ gold 判据已被改动，104 条指标**不再与历史基线可比**。')
    print('   常见原因：跑过 `python build_gold.py`（不带 --check）重新派生。')
    print('   重派生会让 gold 变多、指标虚升，**不代表检索变好**。')
    print('   处置：按 `gold_freeze.json` 的 `how_to_change` 走一遍——确认是刻意变更、')
    print('   更新 sha256 与 slots、并追加带日期的理由；否则用版本库回退该文件。')
    return 1


if __name__ == '__main__':
    sys.exit(main())
