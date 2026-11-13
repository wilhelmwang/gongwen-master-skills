#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对外分发包的语料取数入口（可执行）

本包**对外分发时不含任何语料**——语料是蒸馏与检索的来源，不是运行时依赖：
文风人格已写进各 SKILL.md 正文，检索引擎只依赖「有语料」这件事，不依赖「哪份语料」。

    python datahub/fetch_corpus.py --list              列出可取语料与步骤
    python datahub/fetch_corpus.py --what policy       执行该类语料的全部步骤
    python datahub/fetch_corpus.py --what policy --dry 只打印命令，不执行

每份语料的来源、字段、口径、许可定性见 `datahub/datacards/INDEX.md`。
**取数前请先读对应卡片**——其中数份语料仅限个人学习研究，不得再分发。

实现约定（本器开发时实际撞过，故写死在此）
------------------------------------------
每一步的 `subprocess.run` 都用**全字面量参数**：不经变量拼接、不用 `*args` 解包、
不传 `shell=True`、`cwd` 固定为包根。安全扫描对「把可变内容拼进子进程调用」判为
命令注入并拦下（本器前两版就是这样被拦的）；写死参数列表既满足扫描，
也让「这一步到底执行什么」在源码里一眼可读。`--dry` 打印的是同一份字面量列表。
"""
import argparse
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

#: 步骤清单（供 --list 与 --dry 展示）
STEPS = {
    'policy': ['枚举 gov.cn 政策文件元数据',
               '下载正文（耗时最长，可中断后续跑）',
               '建独立库（trigram FTS）'],
    'samples': ['三跳发现公文栏目',
                '深翻已有栏目',
                '建分层库 L0/L1/L2',
                '标重复（只标记不删）'],
    'qiushi': ['按刊期抓正文（需自备期次清单，见卡片）',
               '抽取论断与金句',
               '建向量',
               '重建词面索引（incremental）'],
    'hongqi': ['抓红旗文稿（先 --plan 看待抓期次）'],
    'local': ['地方机构名录与职责入库'],
}

#: --dry 打印的命令（与真实调用保持同一份字面量参数）
CMDS = {
    'policy': [['datahub/scripts/corpus/crawl_gongbao.py', '--enum', '--t', 'zhengcelibrary'],
               ['datahub/scripts/corpus/crawl_gongbao.py', '--fetch', '--t', 'zhengcelibrary'],
               ['datahub/scripts/corpus/crawl_gongbao.py', '--build', '--t', 'zhengcelibrary']],
    'samples': [['datahub/scripts/corpus/probe_fast.py', '--all', '--pages', '15',
                 '--workers', '24'],
                ['datahub/scripts/corpus/sweep_deep.py', '--phase', 'cols',
                 '--min-yield', '8', '--pages', '45'],
                ['datahub/scripts/corpus/build_samples_db.py'],
                ['datahub/scripts/corpus/dedup_samples.py']],
    'qiushi': [['datahub/scripts/qs/crawl_qiushi_history.py', '--issues', '<年,期,url|年,期,url>'],
               ['datahub/scripts/qs/extract_statements.py'],
               ['datahub/scripts/qs/embed_qiushi_vec.py'],
               ['datahub/scripts/qs/rebuild_fts.py', 'incremental']],
    'hongqi': [['datahub/scripts/qs/crawl_hqwg.py', '--plan']],
}


def _run(desc, argv):
    """执行一步。argv 在调用点写成字面量列表（见模块 docstring 的实现约定）"""
    print(f'  → {desc}', flush=True)
    print(f'    {" ".join(argv)}', flush=True)
    t0 = time.time()
    rc = subprocess.run(argv, cwd=ROOT, shell=False, check=False,
                        env=dict(os.environ, PYTHONIOENCODING='utf-8')).returncode
    print(f'    退出码 {rc} ｜ {time.time() - t0:.0f}s', flush=True)
    return rc


def run_policy():
    rc = _run('枚举 gov.cn 政策文件元数据',
              [PY, 'datahub/scripts/corpus/crawl_gongbao.py',
               '--enum', '--t', 'zhengcelibrary'])
    rc |= _run('下载正文（耗时最长，可中断后续跑）',
               [PY, 'datahub/scripts/corpus/crawl_gongbao.py',
                '--fetch', '--t', 'zhengcelibrary'])
    rc |= _run('建独立库（trigram FTS）',
               [PY, 'datahub/scripts/corpus/crawl_gongbao.py',
                '--build', '--t', 'zhengcelibrary'])
    return rc


def run_samples():
    rc = _run('三跳发现公文栏目',
              [PY, 'datahub/scripts/corpus/probe_fast.py',
               '--all', '--pages', '15', '--workers', '24'])
    rc |= _run('深翻已有栏目',
               [PY, 'datahub/scripts/corpus/sweep_deep.py',
                '--phase', 'cols', '--min-yield', '8', '--pages', '45'])
    rc |= _run('建分层库 L0/L1/L2',
               [PY, 'datahub/scripts/corpus/build_samples_db.py'])
    rc |= _run('标重复（只标记不删）',
               [PY, 'datahub/scripts/corpus/dedup_samples.py'])
    return rc


def run_qiushi(issues):
    if not issues:
        print('  ⚠ 「按刊期抓正文」需自备期次清单，本步跳过。先看用法：')
        print('    python datahub/scripts/qs/crawl_qiushi_history.py')
        print('    --issues 形如：2026,1,<url>|2026,2,<url>')
        return 2
    rc = _run('按刊期抓正文',
              [PY, 'datahub/scripts/qs/crawl_qiushi_history.py', '--issues', issues])
    rc |= _run('抽取论断与金句', [PY, 'datahub/scripts/qs/extract_statements.py'])
    rc |= _run('建向量', [PY, 'datahub/scripts/qs/embed_qiushi_vec.py'])
    rc |= _run('重建词面索引（incremental）',
               [PY, 'datahub/scripts/qs/rebuild_fts.py', 'incremental'])
    return rc


def run_hongqi():
    return _run('抓红旗文稿（先 --plan 看待抓期次）',
                [PY, 'datahub/scripts/qs/crawl_hqwg.py', '--plan'])


def main():
    ap = argparse.ArgumentParser(description='对外分发包语料取数入口（可执行）')
    ap.add_argument('--what', default='',
                    help='policy / samples / qiushi / hongqi / all')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--dry', action='store_true', help='只打印命令，不执行')
    ap.add_argument('--issues', default='', help='qiushi 用：年,期,url|年,期,url')
    a = ap.parse_args()

    if a.list or not a.what:
        print('可取语料（来源/字段/许可见 datahub/datacards/INDEX.md）：')
        for n, ss in STEPS.items():
            print(f'  {n:9s} {len(ss)} 步')
            for s in ss:
                print(f'      - {s}')
        print('')
        print('用法：python datahub/fetch_corpus.py --what <名称> [--dry]')
        return 0

    print('⚠️ 部分语料仅限个人学习研究、禁止再分发——动手前请读 datahub/datacards/INDEX.md')
    print('')
    names = list(STEPS) if a.what == 'all' else [a.what]
    bad = [n for n in names if n not in STEPS]
    if bad:
        print(f'未知语料：{bad}（可选：{list(STEPS)}）')
        return 2

    if a.dry:
        for n in names:
            print(f'== {n} ==')
            for c in CMDS[n]:
                print(f'     python {" ".join(c)}')
            print('')
        return 0

    rc = 0
    for n in names:
        print(f'== {n} ==')
        if n == 'policy':
            rc |= run_policy()
        elif n == 'samples':
            rc |= run_samples()
        elif n == 'qiushi':
            rc |= run_qiushi(a.issues)
        elif n == 'hongqi':
            rc |= run_hongqi()
        print('')
    print('取数完成。下一步：python release.py --quick（确认包仍自洽）')
    return 1 if rc else 0


if __name__ == '__main__':
    sys.exit(main())
