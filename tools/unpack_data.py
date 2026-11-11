# -*- coding: utf-8 -*-
"""解压随包数据库。

用法：
    python tools/unpack_data.py            # 解压到 datahub/sqlite/gongwen_corpus.db
    python tools/unpack_data.py --force    # 覆盖已存在的库
    python tools/unpack_data.py --check    # 仅校验，不解压
"""
import argparse
import gzip
import os
import shutil
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GZ = os.path.join(ROOT, 'datahub', 'sqlite', 'gongwen_corpus.db.gz')
DB = os.path.join(ROOT, 'datahub', 'sqlite', 'gongwen_corpus.db')


def decompress(force=False, check=False):
    if not os.path.exists(GZ):
        print('[错误] 未找到压缩数据: %s' % GZ)
        return 1

    if check:
        with gzip.open(GZ, 'rb') as f:
            head = f.read(16)
        ok = head.startswith(b'SQLite format 3')
        print('[校验] %s' % ('通过' if ok else '失败：文件头不是 SQLite 数据库'))
        print('       压缩包 %.1f MB' % (os.path.getsize(GZ) / 1024 / 1024))
        return 0 if ok else 1

    if os.path.exists(DB) and not force:
        print('[跳过] 数据库已存在: %s' % DB)
        print('       如需覆盖请加 --force')
        return verify()

    print('[1/2] 解压中 ...')
    tmp = DB + '.tmp'
    with gzip.open(GZ, 'rb') as fin, open(tmp, 'wb') as fout:
        shutil.copyfileobj(fin, fout)
    os.replace(tmp, DB)
    print('      完成，%.1f MB' % (os.path.getsize(DB) / 1024 / 1024))
    return verify()


def verify():
    print('[2/2] 校验中 ...')
    try:
        con = sqlite3.connect('file:%s?mode=ro' % DB.replace('\\', '/'), uri=True)
        integrity = con.execute('PRAGMA integrity_check').fetchone()[0]
        n = con.execute('SELECT COUNT(*) FROM articles').fetchone()[0]
        src = con.execute(
            'SELECT source, COUNT(*) FROM articles GROUP BY 1 ORDER BY 2 DESC').fetchall()
        con.close()
    except Exception as e:
        print('      [失败] %s' % e)
        return 1

    print('      integrity_check: %s' % integrity)
    print('      文章总数: %s' % format(n, ','))
    for s, c in src:
        print('        - %-24s %s' % (s, format(c, ',')))
    if integrity != 'ok':
        return 1
    print('\n完成。下一步：python tools/build_fts.py 建立全文索引')
    return 0


def main():
    ap = argparse.ArgumentParser(description='解压公文大师随包数据库')
    ap.add_argument('--force', action='store_true', help='覆盖已存在的数据库')
    ap.add_argument('--check', action='store_true', help='仅校验压缩包，不解压')
    a = ap.parse_args()
    return decompress(force=a.force, check=a.check)


if __name__ == '__main__':
    sys.exit(main())
