# -*- coding: utf-8 -*-
"""按需获取外部语料（不随仓库分发）。

本工具只从公开页面抓取，不内含任何第三方正文。抓取所得仅写入本地数据库，
供个人学习与研究参考；不得再分发，不得用于商业用途。

用法：
    python tools/fetch_corpus.py --plan           # 只列出待抓期次，不联网写入
    python tools/fetch_corpus.py --journal        # 抓取理论刊物（求是 / 红旗文稿）
    python tools/fetch_corpus.py --journal --rebuild   # 抓取后重建全文索引
    python tools/fetch_corpus.py --status         # 查看当前库内语料构成
"""
import argparse
import os
import subprocess
import sys
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'datahub', 'sqlite', 'gongwen_corpus.db')
DATAHUB = os.path.join(ROOT, 'datahub')
QS = os.path.join(DATAHUB, 'scripts', 'qs')

BANNER = """
────────────────────────────────────────────────────────────
 外部语料获取 · 仅供个人学习研究参考
 抓取内容版权归原刊物与原作者所有，仓库不提供、不授权、不再分发。
 使用者须自行遵守目标站点服务条款与所在地法律。
────────────────────────────────────────────────────────────
"""


def _env():
    e = dict(os.environ)
    e['PYTHONPATH'] = DATAHUB + (os.pathsep + e['PYTHONPATH'] if e.get('PYTHONPATH') else '')
    return e


def run(script, args=()):
    cmd = [sys.executable, os.path.join(QS, script)] + list(args)
    print('  →', ' '.join([script] + list(args)))
    return subprocess.call(cmd, cwd=ROOT, env=_env())


def status():
    if not os.path.exists(DB):
        print('[提示] 数据库不存在，请先运行: python tools/unpack_data.py')
        return 1
    con = sqlite3.connect('file:%s?mode=ro' % DB.replace('\\', '/'), uri=True)
    rows = con.execute(
        'SELECT source, COUNT(*) FROM articles GROUP BY 1 ORDER BY 2 DESC').fetchall()
    total = con.execute('SELECT COUNT(*) FROM articles').fetchone()[0]
    con.close()
    print('当前库内文章 %s 篇：' % format(total, ','))
    for s, n in rows[:12]:
        print('  %-28s %s' % (str(s)[:28], format(n, ',')))
    print('\n提示：仅国务院公报等中央级公开文件为仓库随包数据；')
    print('      其余来源若存在，均为你本地抓取所得，不在仓库分发范围内。')
    return 0


def main():
    ap = argparse.ArgumentParser(description='按需获取外部语料（不随仓库分发）')
    ap.add_argument('--journal', action='store_true', help='抓取理论刊物（求是 + 红旗文稿）')
    ap.add_argument('--plan', action='store_true', help='仅列出待抓期次')
    ap.add_argument('--rebuild', action='store_true', help='抓取后重建全文索引')
    ap.add_argument('--status', action='store_true', help='查看库内语料构成')
    a = ap.parse_args()

    print(BANNER)

    if a.status:
        return status()

    if not (a.journal or a.plan):
        ap.print_help()
        return 0

    if a.plan:
        rc = run('crawl_qiushi_incremental.py', ['--plan'])
        rc |= run('crawl_hqwg.py', ['--plan'])
        return rc

    rc = run('crawl_qiushi_incremental.py', ['--rebuild'] if a.rebuild else [])
    rc |= run('crawl_hqwg.py', ['--rebuild'] if a.rebuild else [])

    print('\n完成。')
    print('  论断与金句抽取: python datahub/scripts/qs/extract_statements.py')
    print('  重建全文索引  : python datahub/scripts/qs/rebuild_fts.py full')
    print('  查看语料构成  : python tools/fetch_corpus.py --status')
    print('\n抓到的内容仅存于本地，请勿随包再分发。')
    return rc


if __name__ == '__main__':
    sys.exit(main())
