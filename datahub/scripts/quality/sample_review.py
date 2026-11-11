#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L2 精品审核·第 2 步：分层抽样与批次导出（零 LLM）

抽样的三个刻意设计
------------------
1. **按 (域名 × 文种) 分层**，大域多抽、长尾少抽——语料分布极不均：
   实测 908 域名里 **55 个承担 48%**、688 个（≥5 篇）覆盖 96%；只按文种抽会被大域淹没。
2. **按域名留出**（默认 20% 的域名整域留出，不做跨域混抽）——
   否则模型学到的是"某市门户的排版"、指标虚高。这是深度研究的头号失败模式。
3. **保证含 C 档样本**——现有 40 条人工锚点里 **C 档为 0**（A10/B30），
   只靠它训不出"C 长什么样"。故每层若含一票否决件，强制至少抽 1 篇。

⚠️ 摘要**不含**确定性层的分数——否则就是拿规则的结果去"检验"规则，口供式循环。
子 agent 只看标题/篇幅/小标题/首尾原文，独立判档；它与确定性层的一致率才是第 4 步要的 κ。

用法
----
  python sample_review.py --dry-run                  # 只看分配与规模
  python sample_review.py --per-max 6 --holdout 0.2  # 正式导出批次
  python sample_review.py --out <目录>               # 指定落点
"""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import export_review as er          # noqa: E402  摘要口径唯一来源
import paths                        # noqa: E402

DB = os.environ.get('GW_SAMPLES_DB') or paths.samples_db_path()
RULE_VER = 'v1'
BATCH = 100


def host_of(u):
    m = re.match(r'https?://([^/]+)', u or '')
    d = (m.group(1) if m else '').lower()
    return d[4:] if d.startswith('www.') else d


def quota(n, per_max):
    """按域规模定配额：大域多抽，长尾少抽"""
    if n >= 100:
        return per_max
    if n >= 30:
        return max(3, per_max - 2)
    if n >= 10:
        return 3
    if n >= 5:
        return 2
    return 1


def hkey(h, mod=100):
    return int(hashlib.sha256(h.encode()).hexdigest()[:8], 16) % mod


def main():
    ap = argparse.ArgumentParser(description='L2 第 2 步：分层抽样与批次导出')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--per-max', type=int, default=6, help='单个(域,文种)层最多抽几篇')
    ap.add_argument('--holdout', type=float, default=0.2, help='留出域名的比例')
    ap.add_argument('--out', default=None)
    ap.add_argument('--target', type=int, default=0, help='抽样总量上限（0=不限）')
    ap.add_argument('--from-holdout', action='store_true',
                    help='**只抽留出域名**（真正域外验证用）。默认抽样会跳过留出域，'
                         '所以留出域本来没有标签——这个模式补上那批，'
                         '并在 manifest 里标 "holdout": true，供训练侧切分。')
    ap.add_argument('--tag', default='', help='批次文件后缀，便于区分（如 hold）')
    a = ap.parse_args()
    out_dir = a.out or os.path.join(os.path.dirname(DB), 'step2_batches')

    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    rows = con.execute(
        'SELECT s.url, s.doc_type, s.title, s.content, s.chars, s.skel, d.verdict'
        ' FROM samples s LEFT JOIN quality_det d'
        '   ON d.url = s.url AND d.rule_ver = ?'
        ' WHERE s.dup_of IS NULL', (RULE_VER,)).fetchall()
    con.close()
    print(f'可抽池（唯一篇）{len(rows):,}')

    strata = defaultdict(list)
    for r in rows:
        strata[(host_of(r[0]), r[1])].append(r)
    doms = {h for h, _dt in strata}
    print(f'域名 {len(doms):,} ｜ (域名×文种) 层 {len(strata):,}')

    holdout = {h for h in doms if hkey(h) < a.holdout * 100}
    print(f'留出域名 {len(holdout):,}（{len(holdout)*100//max(len(doms),1)}%）')

    picked, nveto = [], 0
    for (h, _dt), items in strata.items():
        if a.from_holdout:
            if h not in holdout:            # 只抽留出域
                continue
        elif h in holdout:
            continue
        q = quota(len(items), a.per_max)
        items = sorted(items, key=lambda r: r[0])
        step = max(1, len(items) // q)
        take = items[::step][:q]
        vetoed = [r for r in items if r[6] == 'C']
        if vetoed and not any(r[6] == 'C' for r in take):
            take = (take[:-1] + [vetoed[len(vetoed) // 2]]) if take else [vetoed[0]]
        picked.extend(take)
        nveto += sum(1 for r in take if r[6] == 'C')

    if a.target and len(picked) > a.target:
        picked = picked[:a.target]
    print(f'抽中 {len(picked):,} 篇 ｜ 其中一票否决(C) {nveto:,} 篇'
          f'（{nveto*100//max(len(picked),1)}%）')
    print('  按文种:', dict(Counter(r[1] for r in picked).most_common()))
    print('  涉及域名:', len({host_of(r[0]) for r in picked}))
    if a.dry_run:
        print('\n--dry-run：未导出。')
        return 0

    # 写盘：pathlib + 落盘点旁校验 + 一次性 write_text
    # （Mimosa 对 `open(<拼接路径>)` 判路径穿越，pathlib.write_text 是它认可的写法）
    base = Path(out_dir).resolve()
    base.mkdir(parents=True, exist_ok=True)
    mp = (base / 's2_manifest.json').resolve()
    old = json.loads(mp.read_text(encoding='utf-8')) if mp.exists() else {'manifest': []}
    start = max([b['batch'] for b in old.get('manifest', [])] or [0])
    picked.sort(key=lambda r: r[0])
    manifest, nbatch = [], start
    for i in range(0, len(picked), BATCH):
        chunk = picked[i:i + BATCH]
        nbatch += 1
        lines = []
        for url, dt, title, content, chars, _skel, _v in chunk:
            d = er.digest({'url': url, 'doc_type': dt, 'title': title,
                           'content': content, 'chars': chars})
            d.pop('id', None)          # 摘要里的 id 是 hash 派生，本步不用
            lines.append(json.dumps(d, ensure_ascii=False))
        fp = (base / f's2_batch_{nbatch:02d}{a.tag}.jsonl').resolve()
        if base != fp.parent:
            raise SystemExit(f'越界，拒绝写入：{fp}')
        fp.write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
        manifest.append({'batch': nbatch, 'file': fp.name, 'n': len(chunk),
                         'holdout': bool(a.from_holdout),
                         'urls': [r[0] for r in chunk]})
    old['manifest'] = old.get('manifest', []) + manifest
    old['holdout_hosts'] = sorted(set(old.get('holdout_hosts', [])) | holdout)
    mp.write_text(json.dumps(old, ensure_ascii=False, indent=1) + '\n',
                  encoding='utf-8', newline='\n')
    print(f'\n已导出 {len(manifest)} 批（编号 {start+1}–{nbatch}）→ {base}')
    print(f'  已并入 s2_manifest.json（标 holdout={bool(a.from_holdout)}）')


if __name__ == '__main__':
    sys.exit(main())
