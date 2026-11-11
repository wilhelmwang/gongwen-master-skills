#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""领袖域 FTS 重建（jhsjk_fts · jieba 分词物化）

背景（两个问题一起修）
---------------------
**问题 1 · external content 指错表**
合并库 `jhsjk_fts` 原定义为 `content='articles'`（应为 `jhsjk_articles`）：
索引数据取自 jhsjk_articles，外部内容却从 articles 读，导致
`SELECT title FROM jhsjk_fts WHERE MATCH` 返回 articles 的标题，与命中 rowid
在 jhsjk_articles 里对应的文章**不是同一篇**。

**问题 2 · unicode61 对中文等于不分词**
原 `tokenize='unicode61'` 把连续汉字整段当作**单个 token**。实测：
`'生产力'` 命中 0 条、`'发展 AND 生产力'` 命中 0 条，只有整句短语才命中。
按关键词检索领袖语录因此不可用。

本方案
------
照 `articles_fts` 的既有范式（`rebuild_fts.py`）重建为 **jieba 分词物化**结构：

    fts5(jid UNINDEXED, title_t, body_t, tokenize='unicode61')

`title_t` / `body_t` 存 jieba 分词后的空格串，unicode61 再按空格切分即得词元，
与 `articles_fts` 完全同构，检索词可直接作为 MATCH 参数（参数绑定，无拼接）。

用法
----
    python rebuild_jhsjk_fts.py            # 重建并校验
    python rebuild_jhsjk_fts.py --dry-run  # 只报告现状
    python rebuild_jhsjk_fts.py --verify   # 只校验现有表

注意：本脚本**写库**。运行前请先 `python gongwen_tool.py snapshot`（数据库铁律④）。
所有 SQL 均为 execute() 处字面量，数据值一律参数绑定。
"""
import argparse
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
from paths import db_path  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qiushi_engine import tokenize  # noqa: E402

DB = db_path()

#: 校验用样本（分词检索下应各有命中）
PROBES = ('新质生产力', '中国式现代化', '全面从严治党')


def count_fts(conn):
    try:
        return conn.execute('SELECT COUNT(*) FROM jhsjk_fts').fetchone()[0]
    except sqlite3.Error:
        return None


def count_src(conn):
    try:
        return conn.execute('SELECT COUNT(*) FROM jhsjk_articles').fetchone()[0]
    except sqlite3.Error:
        return None


def find_jhsjk(conn, keyword, limit=5):
    """按关键词检索：jieba 分词后的空格串直接作 MATCH 参数（同 articles_fts 范式）
    新表列：jid UNINDEXED / title_t / body_t；正文经 jid 回表取。"""
    return conn.execute(
        'SELECT a.id, a.title, a.publish_date, a.source '
        'FROM jhsjk_fts f JOIN jhsjk_articles a ON a.id = f.jid '
        'WHERE jhsjk_fts MATCH ? '
        'ORDER BY a.publish_date DESC LIMIT ?',
        (tokenize(keyword), limit)
    ).fetchall()


def verify(conn, quiet=False):
    ok = True
    n_fts = count_fts(conn)
    n_src = count_src(conn)
    if not quiet:
        print(f'  jhsjk_fts 行数 {n_fts} ｜ jhsjk_articles 行数 {n_src}')
    if n_fts != n_src:
        print(f'  ❌ 行数不一致（{n_fts} vs {n_src}）')
        ok = False
    for kw in PROBES:
        try:
            rows = find_jhsjk(conn, kw)
        except sqlite3.Error as e:
            print(f'  ❌ 检索失败 {kw}: {e}')
            ok = False
            continue
        if rows:
            if not quiet:
                print(f'  ✅ 「{kw}」命中（首条: {str(rows[0][1])[:36]}…）')
        else:
            print(f'  ❌ 「{kw}」无命中（分词检索不可用）')
            ok = False
    return ok


def rebuild(conn):
    print('\n[1/4] 删除旧表与遗留临时表 …')
    conn.execute('DROP TABLE IF EXISTS jhsjk_fts_bak')
    conn.execute('DROP TABLE IF EXISTS jhsjk_fts')
    conn.commit()

    print('[2/4] 建新表（jieba 分词物化，与 articles_fts 同构）…')
    conn.execute(
        "CREATE VIRTUAL TABLE jhsjk_fts USING fts5("
        "jid UNINDEXED, title_t, body_t, tokenize='unicode61')"
    )
    conn.commit()

    print('[3/4] 灌入分词物化数据 …')
    rows = conn.execute(
        'SELECT id, title, substr(content, 1, 4000) FROM jhsjk_articles '
        'WHERE content IS NOT NULL AND length(content) > 0'
    ).fetchall()
    batch, done = [], 0
    t0 = time.time()
    for jid, title, content in rows:
        tt = tokenize(title or '')
        bt = tokenize((title or '') + ' ' + (title or '') + ' ' + (content or ''))
        batch.append((jid, tt, bt))
        if len(batch) >= 200:
            conn.execute('BEGIN')
            conn.executemany(
                'INSERT INTO jhsjk_fts(jid, title_t, body_t) VALUES(?,?,?)', batch
            )
            conn.commit()
            done += len(batch)
            batch = []
    if batch:
        conn.execute('BEGIN')
        conn.executemany(
            'INSERT INTO jhsjk_fts(jid, title_t, body_t) VALUES(?,?,?)', batch
        )
        conn.commit()
        done += len(batch)
    print(f'  已物化 {done} 行 / {time.time() - t0:.1f}s')

    print('[4/4] 校验 …')
    return verify(conn)


def main():
    ap = argparse.ArgumentParser(description='领袖域 FTS 重建（jieba 分词物化）')
    ap.add_argument('--dry-run', action='store_true', help='只报告现状，不改库')
    ap.add_argument('--verify', action='store_true', help='只校验现有 jhsjk_fts')
    a = ap.parse_args()

    if not os.path.exists(DB):
        print(f'❌ 数据根主库不存在: {DB}')
        return 2
    print(f'主库: {DB}')

    conn = sqlite3.connect(DB)
    try:
        if a.verify:
            print('\n校验现有 jhsjk_fts：')
            return 0 if verify(conn) else 1

        r = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='jhsjk_fts'"
        ).fetchone()
        print('\n当前 jhsjk_fts 定义：')
        print('  ' + (r[0] if r else '(不存在)'))

        if a.dry_run:
            print('\n--dry-run：未改库。')
            return 0

        ok = rebuild(conn)
        print('\n' + ('✅ 重建完成' if ok else '❌ 重建未通过校验'))
        return 0 if ok else 1
    finally:
        conn.close()


if __name__ == '__main__':
    sys.exit(main())
