# -*- coding: utf-8 -*-
"""建立全文索引（articles_fts）。

随包数据库未预建 FTS 索引，以控制仓库体积。首次检索前运行一次：

    python tools/build_fts.py

索引约占用 300MB 磁盘，构建耗时 1-2 分钟（14,865 篇）。
重复运行会先删除旧索引再重建。
"""
import os
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'datahub', 'sqlite', 'gongwen_corpus.db')


def main():
    if not os.path.exists(DB):
        print('[错误] 数据库不存在，请先运行: python tools/unpack_data.py')
        return 1

    t0 = time.time()
    con = sqlite3.connect(DB)
    cur = con.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='articles_fts'")
    if cur.fetchone():
        print('[1/3] 移除旧索引 ...')
        cur.execute('DROP TABLE articles_fts')
        con.commit()

    print('[2/3] 创建 FTS5 表 ...')
    cur.execute("""CREATE VIRTUAL TABLE articles_fts USING fts5(
                     article_id UNINDEXED, title_t, body_t, tokenize='unicode61')""")

    print('[3/3] 灌入正文 ...')
    total = cur.execute('SELECT COUNT(*) FROM articles').fetchone()[0]
    cur.execute("""INSERT INTO articles_fts(article_id, title_t, body_t)
                   SELECT id, COALESCE(title,''), COALESCE(content,'') FROM articles""")
    con.commit()

    n = cur.execute('SELECT COUNT(*) FROM articles_fts').fetchone()[0]
    con.execute('VACUUM')
    con.close()

    print('完成：%s / %s 篇，耗时 %.1fs' % (format(n, ','), format(total, ','), time.time() - t0))
    print('试检索: python datahub/scripts/qs/qiushi_engine.py search 高质量发展 --top 3')
    return 0


if __name__ == '__main__':
    sys.exit(main())
