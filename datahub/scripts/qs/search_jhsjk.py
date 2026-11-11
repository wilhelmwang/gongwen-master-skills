#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""领袖语录检索（search_jhsjk · 领袖著作要闻库 14,901 篇）

用途
----
公文写作中需要"总书记指出""总书记强调"类精确引用时，用本工具检索**原文**，
取得可核验的出处（标题 + 日期 + 来源 + 原文摘录），杜绝凭印象引述。

数据源
------
合并库 `gongwen_corpus.db` 的 `jhsjk_articles` 表（人民网领袖著作要闻库，
2012-11 ~ 2026-09，14,901 篇 / 2,222 万字）+ `jhsjk_fts` 索引（jieba 分词物化）。

> ⚠️ 领袖著作**不在** qiushi_engine 的 `articles` 表内（该表 data_source 不含领袖域），
> 故 hybrid3 检索**查不到**领袖语录，必须走本入口。

用法
----
    python search_jhsjk.py "新质生产力"                 # 全文检索
    python search_jhsjk.py "中国式现代化" --year 2024   # 限定年份
    python search_jhsjk.py "全面从严治党" --limit 20    # 条数
    python search_jhsjk.py "高质量发展" --full          # 附正文全文
    python search_jhsjk.py "新质生产力" --json          # 机器可读
    python search_jhsjk.py --show 40792917              # 按 id 读全文
    python search_jhsjk.py --stats                      # 语料规模

输出: 命中清单（标题 + 日期 + 来源 + 摘录）+ 引用规范提示。
所有 SQL 均为 execute() 处字面量，检索词一律参数绑定。
"""
import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
from paths import db_path  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qiushi_engine import tokenize  # noqa: E402

CITATION_HINT = (
    '【引用规范】领导讲话/署名文章引用须写全出处，例如：\n'
    '  「据《人民日报》YYYY年M月D日《标题》」\n'
    '  「习近平总书记在《求是》XXXX年第X期《标题》中指出…」\n'
    '  不得简写为"习近平总书记曾指出"而无出处——读者无法核验。'
)


def strip_meta(content):
    """剥离正文前的元数据头（jhsjk_articles.content 前 5-6 行以 '#' 开头的采集元信息）。"""
    if not content:
        return ''
    lines = content.splitlines()
    i = 0
    for ln in lines:                      # 跳过连续的前置 '# ...' 行与紧随的空行
        s = ln.strip()
        if s.startswith('#') or (i > 0 and not s and i < 12):
            i += 1
        else:
            break
    return '\n'.join(lines[i:]).strip()


def _db_or_none():
    p = db_path()
    return p if os.path.exists(p) else None


def search(keyword, year=None, limit=10):
    """检索领袖语录。返回 [(id, title, date, source, chars, excerpt), ...]，失败返回 None。"""
    db = _db_or_none()
    if not db:
        return None
    toks = tokenize(keyword)
    if not toks:
        return []
    conn = sqlite3.connect('file:' + db + '?mode=ro', uri=True)
    try:
        if year:
            rows = conn.execute(
                'SELECT a.id, a.title, a.publish_date, a.source, a.chars, '
                'substr(a.content, 1, 1500) '
                'FROM jhsjk_fts f JOIN jhsjk_articles a ON a.id = f.jid '
                'WHERE jhsjk_fts MATCH ? AND a.publish_date LIKE ? '
                'ORDER BY a.publish_date DESC LIMIT ?',
                (toks, str(year) + '%', limit)
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT a.id, a.title, a.publish_date, a.source, a.chars, '
                'substr(a.content, 1, 1500) '
                'FROM jhsjk_fts f JOIN jhsjk_articles a ON a.id = f.jid '
                'WHERE jhsjk_fts MATCH ? '
                'ORDER BY a.publish_date DESC LIMIT ?',
                (toks, limit)
            ).fetchall()
        # 剥离采集元数据头，摘录取正文前 400 字
        return [(r[0], r[1], r[2], r[3], r[4], strip_meta(r[5])[:400]) for r in rows]
    except sqlite3.Error as e:
        print(f'❌ 检索出错: {e}')
        return []
    finally:
        conn.close()


def show_one(aid):
    db = _db_or_none()
    if not db:
        return None
    conn = sqlite3.connect('file:' + db + '?mode=ro', uri=True)
    try:
        return conn.execute(
            'SELECT id, title, publish_date, source, content '
            'FROM jhsjk_articles WHERE id=?', (aid,)
        ).fetchone()
    finally:
        conn.close()


def stats():
    db = _db_or_none()
    if not db:
        return None
    conn = sqlite3.connect('file:' + db + '?mode=ro', uri=True)
    try:
        return {
            'articles': conn.execute('SELECT COUNT(*) FROM jhsjk_articles').fetchone()[0],
            'indexed': conn.execute('SELECT COUNT(*) FROM jhsjk_fts').fetchone()[0],
            'chars': conn.execute('SELECT SUM(chars) FROM jhsjk_articles').fetchone()[0],
            'from': conn.execute('SELECT MIN(publish_date) FROM jhsjk_articles').fetchone()[0],
            'to': conn.execute('SELECT MAX(publish_date) FROM jhsjk_articles').fetchone()[0],
        }
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description='领袖语录检索（领袖著作要闻库）')
    ap.add_argument('keywords', nargs='*', help='检索词')
    ap.add_argument('--year', type=int, help='限定年份')
    ap.add_argument('--limit', type=int, default=10, help='返回条数（默认 10）')
    ap.add_argument('--full', action='store_true', help='打印命中正文全文')
    ap.add_argument('--json', action='store_true', help='机器可读输出')
    ap.add_argument('--show', help='按 id 读全文')
    ap.add_argument('--stats', action='store_true', help='语料规模统计')
    a = ap.parse_args()

    if a.show:
        row = show_one(a.show)
        if not row:
            print(f'❌ 未找到 id={a.show}')
            return 1
        print('《%s》\n%s ｜ %s\n%s' % (row[1], row[2], row[3], '-' * 60))
        print(strip_meta(row[4]))
        return 0

    if a.stats:
        s = stats()
        if not s:
            print('❌ 数据层不可用（形态 C）')
            return 2
        print('=== 领袖著作要闻库 ===')
        print('  篇数: %s（索引 %s）' % (format(s['articles'], ','), format(s['indexed'], ',')))
        print('  字数: %s（约 %.0f 万字）' % (format(s['chars'], ','), s['chars'] / 10000))
        print('  时间: %s ~ %s' % (s['from'], s['to']))
        return 0

    if not a.keywords:
        ap.print_help()
        return 1

    query = ' '.join(a.keywords)
    rows = search(query, a.year, a.limit)
    if rows is None:
        print('❌ 数据层不可用（形态 C）')
        return 2

    if a.json:
        print(json.dumps(
            [{'id': r[0], 'title': r[1], 'date': r[2], 'source': r[3],
              'chars': r[4], 'excerpt': r[5]} for r in rows],
            ensure_ascii=False, indent=1))
        return 0

    head = '=== 领袖语录检索: %s' % query
    if a.year:
        head += ' [%d]' % a.year
    print(head + ' ===\n')

    if not rows:
        print('  无命中。')
        print('  建议：换更常见的提法（如「中国式现代化」「高质量发展」），')
        print('        或去掉 --year 放宽时间范围。')
        return 0

    print('  命中 %d 条（按日期倒序）：\n' % len(rows))
    for i, (aid, title, date, src, chars, exc) in enumerate(rows, 1):
        print('%2d. 《%s》' % (i, title))
        print('    %s ｜ %s ｜ %s 字 ｜ id=%s' % (date, src, chars, aid))
        exc1 = ' '.join((exc or '').split())[:110]
        if exc1:
            print('    摘录: %s…' % exc1)
        print()
        if a.full:
            row = show_one(aid)
            if row:
                print('    ' + '-' * 56)
                for line in strip_meta(row[4]).splitlines():
                    if line.strip():
                        print('    ' + line.strip())
                print('    ' + '-' * 56 + '\n')

    print(CITATION_HINT)
    return 0


if __name__ == '__main__':
    sys.exit(main())
