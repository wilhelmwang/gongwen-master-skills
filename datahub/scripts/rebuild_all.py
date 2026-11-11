#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据重建单入口（v1.0 · 2026-09-03）
用法：
  python rebuild_all.py --all            # 全量：embed → extract → reindex
  python rebuild_all.py embed            # 向量全量（需 venv+bge）
  python rebuild_all.py embed-inc        # 向量增量（新文章差集）
  python rebuild_all.py extract          # 论断库重抽
  python rebuild_all.py reindex          # TF-IDF/BM25 索引重建
  python rebuild_all.py fts              # FTS5 快路虚表（v6.9.0，冷启动毫秒级）
  python rebuild_all.py hs-sync          # 地方联动（占位，pipeline 驱动）
"""
import os, subprocess, sys

QS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'qs')

def run(name, script, args=()):
    print(f'⟳ {name} ...')
    r = subprocess.run([sys.executable, os.path.join(QS, script), *args], capture_output=True,
                       text=True, encoding='utf-8', errors='replace')
    print(r.stdout[-400:] if r.stdout else r.stderr[-400:])
    print(f'✓ {name} 完成' if r.returncode == 0 else f'✗ {name} 失败 rc={r.returncode}')

STEPS = {
    'embed': ('embed_qiushi_vec.py', ()),
    'embed-inc': ('embed_incremental.py', ()),
    'extract': ('extract_statements.py', ()),
    'reindex': ('qiushi_engine.py', ('reindex',)),
    'fts': ('rebuild_fts.py', ()),   # v6.9.0 P1-1：FTS5 快路虚表
}

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    if args[0] == '--all':
        for k in ('embed', 'extract', 'reindex', 'fts'):
            s, a = STEPS[k]
            run(k, s, a)
        return
    if args[0] == 'hs-sync':
        print('地方同步由 42 pipeline 驱动（数据随包分发）；hs.db 结构见 schema/ddls/hs.sql')
        return
    if args[0] in STEPS:
        s, a = STEPS[args[0]]
        run(args[0], s, a)
        return
    print(__doc__)

if __name__ == '__main__':
    main()
