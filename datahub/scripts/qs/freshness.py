#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据新鲜度运维（v7.5.1 · C5④ 落地）

背景
----
`datahub/assets.json` 的 `ops.freshness` 登记了三条运维承诺：
  ① 每周 snapshot（gongwen_tool.py snapshot）
  ② 求是爬虫 hash 变更检测（**声称**"URL 不变内容变更可检测"）
  ③ 地方公报发布季提醒（每年 4-5 月 / 10 月）

2026-09-11 核查发现：**②是假的**——全包没有任何 hash 实现，增量爬虫只按
`if url in existing: continue` 判重，URL 不变而内容被改写（刊物线上勘误、正文替换）
永远发现不了。③也零自动化。①没有轮转（已由 `gongwen_tool.py snapshot --keep/--ttl-days` 补上）。

本模块把②做成真的，并把③变成可查询的状态，①的现状一并纳入报告：

  python freshness.py --status        # 一张表看清：主库/索引/向量/hash 覆盖/快照/年鉴季
  python freshness.py --hash-init     # 首次建立（或整表重建）内容哈希边车
  python freshness.py --hash-verify   # 比对库内正文与边车哈希 → 发现"入库后被改动"的行
  python freshness.py --hash-compare <url> <file>   # 爬虫钩子：判断某 URL 内容是否已变更
  python freshness.py --json          # 机器可读

设计取舍
--------
- 哈希存**边车**（`qs_content_hash.json`），不加库列：加列要动 749.6MB 主库的 schema 三同步
  （registry + ddls + 实库），风险与收益不成比例。边车可随时重建，不碰主库。
- 哈希算在**规范化正文**上（去空白差异），避免排版空白变化造成假阳性。
- 只报不改：`--hash-verify` 发现差异只列出，不自动改库（改数据是单独的人工决策）。
"""
import argparse
import datetime
import hashlib
import json
import os
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(BASE, 'datahub'))
from paths import (db_path, index_path, vectors_path, content_hash_path,  # noqa: E402
                   resolve_form, is_available, degradation_notice)

#: 年鉴季提醒窗口（月）——地方统计公报/年鉴集中在 4-5 月与 10 月发布
YEARBOOK_MONTHS = (4, 5, 10)


# ---------------------------------------------------------------- 哈希核心

def normalize(text):
    """规范化正文：统一空白 + 去零宽字符。哈希算在这上面，避免排版差异造成假阳性。"""
    if not text:
        return ''
    t = text.replace('\r\n', '\n').replace('\r', '\n')
    for zw in ('\u200b', '\u200c', '\u200d', '\ufeff'):
        t = t.replace(zw, '')
    return '\n'.join(line.strip() for line in t.split('\n') if line.strip())


def content_hash(text):
    return hashlib.sha256(normalize(text).encode('utf-8')).hexdigest()[:32]


def load_hashes():
    """读边车，返回 {'meta': {...}, 'hashes': {url: hash}}"""
    p = content_hash_path()
    if not os.path.exists(p):
        return {'meta': {}, 'hashes': {}}
    try:
        with open(p, encoding='utf-8') as f:
            d = json.load(f)
        d.setdefault('meta', {})
        d.setdefault('hashes', {})
        return d
    except Exception:
        return {'meta': {}, 'hashes': {}}


def save_hashes(d):
    from pathlib import Path as _P
    p = content_hash_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    _P(p).write_text(json.dumps(d, ensure_ascii=False), encoding='utf-8')
    return p


def _db_rows(only_urls=None):
    """产出 (url, content)；超大表分批读，避免一次性载入内存"""
    conn = sqlite3.connect(db_path())
    try:
        cur = conn.cursor()
        if only_urls:
            for u in only_urls:
                r = cur.execute('SELECT content FROM articles WHERE url=?', (u,)).fetchone()
                if r:
                    yield u, r[0]
        else:
            for url, content in cur.execute('SELECT url, content FROM articles ORDER BY id'):
                yield url, content
    finally:
        conn.close()


# ---------------------------------------------------------------- 子命令

def cmd_hash_init():
    """整表重建哈希边车"""
    if not is_available():
        print('❌ 数据层降级，无法建哈希。'); print(degradation_notice()); return 1
    hashes, n, empty = {}, 0, 0
    for url, content in _db_rows():
        if not url:
            continue
        if not normalize(content):
            empty += 1
            continue
        hashes[url] = content_hash(content)
        n += 1
    d = {'meta': {'built_at': datetime.datetime.now().isoformat(timespec='seconds'),
                  'rows_hashed': n, 'rows_empty_skipped': empty,
                  'algo': 'sha256(规范化正文)[:32]'},
         'hashes': hashes}
    p = save_hashes(d)
    print(f'✓ 哈希边车已建立: {os.path.relpath(p, BASE)}')
    print(f'  已哈希 {n} 行 ｜ 跳过空正文 {empty} 行')
    return 0


def cmd_hash_verify():
    """比对库内正文与边车哈希 → 列出"入库后被改动"的行（只报不改）"""
    if not is_available():
        print('❌ 数据层降级。'); return 1
    d = load_hashes()
    old = d['hashes']
    if not old:
        print('❌ 边车为空，先跑 --hash-init'); return 1
    changed, new_rows, empty, checked = [], [], 0, 0
    for url, content in _db_rows():
        if not url:
            continue
        if not normalize(content):
            empty += 1          # 空正文行本就不入边车（图表/法规栏目），非"新增"
            continue
        h = content_hash(content)
        if url not in old:
            new_rows.append(url)
        elif old[url] != h:
            changed.append(url)
        checked += 1
    print(f'=== 哈希核验（边车构建于 {d["meta"].get("built_at", "未知")}）===')
    print(f'  核验 {checked} 行 ｜ 内容变更 {len(changed)} ｜ 边车未覆盖（真新增行）{len(new_rows)}'
          f' ｜ 空正文跳过 {empty}')
    for u in changed[:20]:
        print(f'   ⚠️  内容已变更: {u[:100]}')
    for u in new_rows[:20]:
        print(f'   ＋ 边车未覆盖: {u[:100]}')
    if changed or new_rows:
        print('\n  提示：确认变更无误后重跑 --hash-init 收敛边车；本命令只报不改库。')
    return 0


def cmd_hash_compare(url, path):
    """爬虫钩子：比较"该 URL 的既有哈希"与"给定文件的正文哈希"。"""
    d = load_hashes()
    cur = d['hashes'].get(url)
    if cur is None:
        print('NEW')          # 边车无此 URL → 视为新内容
        return 0
    try:
        with open(path, encoding='utf-8') as f:
            h = content_hash(f.read())
    except Exception as e:
        print(f'ERR {e}'); return 1
    print('SAME' if h == cur else 'CHANGED')
    return 0


def _corpus_year_range():
    """语料年份窗口（求是文章的 issue_year 范围）"""
    try:
        conn = sqlite3.connect(db_path())
        # 加合理区间：库内有 issue_year=0/NULL 的行（早期抓取未解析出年份），
        # 不加过滤会把 MIN 拉到 0，报告成含义不明的 "?-2026"
        r = conn.execute('SELECT MIN(issue_year), MAX(issue_year) FROM articles '
                         'WHERE issue_year BETWEEN 1900 AND 2100').fetchone()
        conn.close()
        return (r[0] or '?', r[1] or '?')
    except Exception:
        return ('?', '?')


def cmd_phrase_age(phrase, as_json=False):
    """提法时效画像：某提法在语料中的首/末次出现年份与逐年频次（C4 轻量版）

    **红线：只提示、不判定。** 本命令不判断"某政策是否已失效"——错误标注"已失效"
    比不提示更危险（作者可能据此删掉正确引用）。它只回答"这个说法在语料里最后一次
    出现是哪一年、之后还出现过吗"，把核验决定权交回作者。
    """
    if not is_available():
        print('❌ 数据层降级。'); return 1
    like = f'%{phrase}%'
    conn = sqlite3.connect(db_path())
    try:
        rows = conn.execute(
            "SELECT issue_year, COUNT(*), MIN(publish_date), MAX(publish_date) FROM articles "
            "WHERE (title LIKE ? OR content LIKE ?) AND issue_year IS NOT NULL "
            "GROUP BY issue_year ORDER BY issue_year", (like, like)).fetchall()
        titles = conn.execute(
            "SELECT title, publish_date, issue_year FROM articles "
            "WHERE (title LIKE ? OR content LIKE ?) ORDER BY publish_date DESC LIMIT 5",
            (like, like)).fetchall()
    finally:
        conn.close()

    if not rows:
        ymin, ymax = _corpus_year_range()
        rep = {'phrase': phrase, 'found': False, 'corpus_years': f'{ymin}-{ymax}',
               'note': f'语料（{ymin}-{ymax}）中未检索到该提法——**这不能推出"该提法已失效"**。'
                       f'两个同样可能的原因：①该提法不在本语料年份窗口内'
                       f'（如更早年份的表述）②语料未覆盖该领域或用词不同。请以官方原文核对。'}
        if as_json:
            print(json.dumps(rep, ensure_ascii=False, indent=1))
        else:
            print(f'=== 提法时效画像：「{phrase}」===')
            print(f'  语料年份窗口：{ymin}-{ymax}')
            print('  语料中未检索到。')
            print('  ⚠️ 未检出 ≠ 已失效。同样可能的原因：①该提法不在语料年份窗口内'
                  '（如更早年份的表述）②语料未覆盖该领域或用词不同。请以官方原文核对。')
        return 0

    years = {y: c for y, c, _a, _b in rows}
    first_y, last_y = min(years), max(years)
    total = sum(years.values())
    cur_y = datetime.date.today().year
    gap = cur_y - last_y
    # 只提示：近 3 年未再现 → 建议核对是否有新版表述；这是提示不是判定
    hint = (f'该提法最后一次出现在 {last_y} 年，距今 {gap} 年未再出现在本语料中 —— '
            f'**建议核对是否有现行版本或新表述**（本提示只作线索，不构成"已失效"判定）。'
            if gap >= 3 else
            f'近 {gap + 1} 年内仍有出现，时效性风险较低；引用前仍应核对原文。')
    rep = {'phrase': phrase, 'found': True, 'first_year': first_y, 'last_year': last_y,
           'years_span': f'{first_y}-{last_y}', 'total_hits': total,
           'by_year': years, 'years_since_last': gap, 'hint': hint,
           'recent_titles': [{'title': t, 'date': d} for t, d, _y in titles],
           'red_line': '只提示，不判定。不得据本结果声称某政策/提法"已失效"。'}

    if as_json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 0

    ymin, ymax = _corpus_year_range()
    rep['corpus_years'] = f'{ymin}-{ymax}'
    print(f'=== 提法时效画像：「{phrase}」===')
    print(f'  语料年份窗口：{ymin}-{ymax}')
    print(f'  首见 {first_y} 年 ｜ 末见 {last_y} 年 ｜ 跨度 {first_y}-{last_y} ｜ 命中 {total} 篇')
    print('  逐年：' + ' ｜ '.join(f'{y}:{c}' for y, c in sorted(years.items())))
    print(f'  ⚠️ {hint}')
    print('  最近命中：')
    for t, d, _y in titles:
        print(f'    · [{d or "无日期"}] {t[:56]}')
    print('\n  红线：只提示、不判定 —— 不得据本结果声称某政策/提法已失效。')
    return 0


def cmd_status(as_json=False):
    """数据新鲜度总览：三条运维承诺的现状一屏看清"""
    rep = {}
    if not is_available():
        msg = degradation_notice()
        if as_json:
            print(json.dumps({'form': 'C', 'notice': msg}, ensure_ascii=False, indent=1))
        else:
            print(msg)
        return 1

    conn = sqlite3.connect(db_path())
    try:
        cur = conn.cursor()
        total = cur.execute('SELECT COUNT(*) FROM articles').fetchone()[0]
        avail = cur.execute("SELECT COUNT(*) FROM articles WHERE content IS NOT NULL AND content<>''").fetchone()[0]
        latest = cur.execute('SELECT MAX(crawl_time) FROM articles').fetchone()[0]
        newest_pub = cur.execute('SELECT MAX(publish_date) FROM articles').fetchone()[0]
    finally:
        conn.close()

    rep['articles_total'] = total
    rep['articles_searchable'] = avail
    rep['last_crawl_time'] = latest
    rep['newest_publish_date'] = newest_pub

    # 索引 / 向量覆盖
    try:
        import pickle
        with open(index_path(), 'rb') as f:
            idx = pickle.load(f)
        # 索引是 dict（键 article_ids/article_titles/...），不是对象——两种都兼容
        if isinstance(idx, dict):
            ids = idx.get('article_ids') or []
        else:
            ids = getattr(idx, 'article_ids', []) or []
        rep['index_articles'] = len(ids)
    except Exception as e:
        rep['index_articles'] = f'读取失败: {e}'
    try:
        v = json.load(open(os.path.splitext(vectors_path())[0] + '.json', encoding='utf-8'))
        rep['vector_chunks'] = v.get('n')
        rep['vector_dims'] = v.get('dim')
    except Exception:
        rep['vector_chunks'] = None

    # 哈希边车
    d = load_hashes()
    rep['hash_built_at'] = d['meta'].get('built_at')
    rep['hash_coverage'] = f"{len(d['hashes'])}/{total}"

    # 快照
    bk = os.path.join(BASE, 'datahub', 'backups')
    snaps = []
    if os.path.isdir(bk):
        for x in sorted(os.listdir(bk)):
            p = os.path.join(bk, x)
            if not os.path.isdir(p):
                continue
            sz = sum(os.path.getsize(os.path.join(r, f))
                     for r, _dd, ff in os.walk(p) for f in ff)
            snaps.append((x, sz, os.path.getmtime(p)))
    snaps.sort(key=lambda s: -s[2])
    rep['snapshots'] = [{'name': n, 'mb': round(s / 1024 / 1024),
                         'at': datetime.datetime.fromtimestamp(m).strftime('%Y-%m-%d %H:%M')}
                        for n, s, m in snaps]

    # 年鉴季
    m = datetime.date.today().month
    rep['yearbook_season'] = {'months': list(YEARBOOK_MONTHS), 'current_month': m,
                              'in_season': m in YEARBOOK_MONTHS}

    if as_json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 0

    print('=== 数据新鲜度总览（freshness.py --status）===')
    print(f'  形态        : {resolve_form()}')
    print(f'  主库文章    : {total} 篇（可检索 {avail}）')
    print(f'  最近抓取    : {latest or "未知"}')
    print(f'  最新发文日期: {newest_pub or "未知"}')
    print(f'  索引覆盖    : {rep["index_articles"]} 篇')
    print(f'  向量块      : {rep["vector_chunks"]} 块 × {rep["vector_dims"]} 维')
    print(f'  哈希边车    : {rep["hash_coverage"]}  建于 {rep["hash_built_at"] or "**尚未建立（跑 --hash-init）**"}')
    if snaps:
        tot = sum(s for _, s, _m in snaps)
        print(f'  快照        : {len(snaps)} 份 / {tot / 1024 / 1024 / 1024:.2f}GB（最新 {snaps[0][0]}）')
    else:
        print('  快照        : 无')
    flag = '⚠️ 是' if rep['yearbook_season']['in_season'] else '否'
    print(f'  年鉴季      : {flag}（提醒月 {"/".join(map(str, YEARBOOK_MONTHS))}；当前 {m} 月）')
    print()
    print('  运维承诺对应动作：')
    print('   ① 每周快照    → python gongwen_tool.py snapshot --keep 3')
    print('   ② 内容变更检测 → python freshness.py --hash-verify（边车由 --hash-init 建立）')
    print('   ③ 季度补录    → 4-5 月 / 10 月为公开数据集中发布期，可择时更新语料')
    return 0


def main():
    ap = argparse.ArgumentParser(description='数据新鲜度运维（v7.5.1 C5④）')
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--status', action='store_true', help='新鲜度总览（默认）')
    g.add_argument('--hash-init', action='store_true', help='建立/重建内容哈希边车')
    g.add_argument('--hash-verify', action='store_true', help='核验库内正文是否被改动（只报不改）')
    g.add_argument('--hash-compare', nargs=2, metavar=('URL', 'FILE'),
                   help='爬虫钩子：比较 URL 既有哈希与文件正文 → 输出 NEW/SAME/CHANGED')
    g.add_argument('--phrase-age', metavar='PHRASE',
                   help='提法时效画像：某提法的首/末次出现年份与逐年频次（C4 轻量版，只提示不判定）')
    ap.add_argument('--json', action='store_true', help='机器可读')
    a = ap.parse_args()

    if a.hash_init:
        return cmd_hash_init()
    if a.hash_verify:
        return cmd_hash_verify()
    if a.hash_compare:
        return cmd_hash_compare(*a.hash_compare)
    if a.phrase_age:
        return cmd_phrase_age(a.phrase_age, a.json)
    return cmd_status(a.json)


if __name__ == '__main__':
    sys.exit(main())
