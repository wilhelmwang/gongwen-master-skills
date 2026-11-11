#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FTS5 虚表重建（v6.9.0 P1-1）：articles → jieba 分词物化 → articles_fts
用法：python rebuild_fts.py [--force]
由 rebuild_all.py 调度；articles_fts 已存在且行数一致时跳过（--force 强制重建）。
"""
import os, sqlite3, sys, time

QS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, QS)
from qiushi_engine import tokenize, DB_PATH


def rebuild(force=False):
    conn = sqlite3.connect(DB_PATH)
    exists = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='articles_fts'").fetchone()
    total = conn.execute("SELECT COUNT(*) FROM articles WHERE content IS NOT NULL AND length(content)>100").fetchone()[0]
    if exists and not force:
        n = conn.execute("SELECT COUNT(*) FROM articles_fts").fetchone()[0]
        if n == total:
            print(f'articles_fts 已在位（{n} 行 = 库 {total}），跳过（--force 强制重建）')
            conn.close(); return 0
    if exists:
        conn.execute('DROP TABLE articles_fts')
    conn.execute("CREATE VIRTUAL TABLE articles_fts USING fts5(article_id UNINDEXED, title_t, body_t, tokenize='unicode61')")
    t0 = time.time()
    rows = conn.execute("SELECT id, title, substr(content,1,3000) FROM articles WHERE content IS NOT NULL AND length(content)>100").fetchall()
    batch, done = [], 0
    for aid, title, content in rows:
        tt = tokenize(title or '')
        bt = tokenize((title or '') + ' ' + (title or '') + ' ' + (content or ''))
        batch.append((aid, tt, bt))
        if len(batch) >= 200:
            conn.execute('BEGIN'); conn.executemany('INSERT INTO articles_fts VALUES (?,?,?)', batch); conn.commit()
            done += len(batch); batch = []
    if batch:
        conn.execute('BEGIN'); conn.executemany('INSERT INTO articles_fts VALUES (?,?,?)', batch); conn.commit()
        done += len(batch)
    # 触发器：articles 增量时提示需重建（不做自动同步，保持 rebuild 显式化）
    print(f'articles_fts 重建完成: {done} 行 / {time.time()-t0:.1f}s')
    ok = conn.execute('PRAGMA integrity_check').fetchone()[0]
    print('integrity:', ok)
    conn.close()
    return 0 if ok == 'ok' else 1


def incremental():
    """增量同步（v6.9.0）：articles 中不在 articles_fts 的新文章补录 FTS 行。
    幂等：按 article_id 差集计算；无新增时零操作。"""
    conn = sqlite3.connect(DB_PATH)
    has_fts = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='articles_fts'").fetchone()
    if not has_fts:
        conn.close()
        return rebuild(force=True)
    todo = conn.execute(
        '''SELECT a.id, a.title, substr(a.content,1,3000) FROM articles a
           WHERE a.content IS NOT NULL AND length(a.content) > 100
             AND a.id NOT IN (SELECT article_id FROM articles_fts)''').fetchall()
    if not todo:
        print('FTS 增量：无新增，跳过')
        conn.close(); return 0
    batch, done = [], 0
    for aid, title, content in todo:
        tt = tokenize(title or '')
        bt = tokenize((title or '') + ' ' + (title or '') + ' ' + (content or ''))
        batch.append((aid, tt, bt))
        if len(batch) >= 200:
            conn.execute('BEGIN'); conn.executemany('INSERT INTO articles_fts VALUES (?,?,?)', batch); conn.commit()
            done += len(batch); batch = []
    if batch:
        conn.execute('BEGIN'); conn.executemany('INSERT INTO articles_fts VALUES (?,?,?)', batch); conn.commit()
        done += len(batch)
    n = conn.execute('SELECT COUNT(*) FROM articles_fts').fetchone()[0]
    print(f'FTS 增量：补录 {done} 行，总计 {n}')
    conn.close()
    return 0


if __name__ == '__main__':
    if '--incremental' in sys.argv:
        sys.exit(incremental())
    sys.exit(rebuild(force='--force' in sys.argv))
