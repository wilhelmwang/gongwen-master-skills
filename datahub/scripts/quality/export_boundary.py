#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定界与字段分离小样导出器（只读，stdout 由调用方重定向）

给子 agent 的每篇包含**清洗前原文与清洗后正文的对照窗口**：
  raw_head   原文前 600 字——看正文真正的起点在哪（导航常在开头）
  raw_tail   原文后 400 字——看署名、成文日期，以及站点页脚
  cur_head/cur_tail  现有治理结果的首尾——看清洗删对了没有

为什么必须给原文：实测发现**导航与公文正文会在同一行**
（「…政府信息公开年报 政府工作报告 （2021年1月25日…」），
按行判据分不开，只有语义判断能分。只给清洗后的文本，子 agent 也返不回原文。

用法
----
  python export_boundary.py --limit 34 --offset 0 > batch_p1.jsonl
"""
import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import export_review as er   # noqa: E402

DB = os.path.join(er.sw.OUT_DIR, 'gongwen_samples.db')


def window(text, head, tail):
    t = text or ''
    if len(t) <= head + tail:
        return t, ''
    return t[:head], t[-tail:]


def main():
    ap = argparse.ArgumentParser(description='定界小样导出（只读）')
    ap.add_argument('--limit', type=int, default=34)
    ap.add_argument('--offset', type=int, default=0)
    ap.add_argument('--min-chars', type=int, default=600)
    a = ap.parse_args()

    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    rows = list(con.execute(
        'SELECT s.url, s.title, s.doc_type, s.source_key, s.chars, s.content,'
        ' r.raw_text FROM samples s LEFT JOIN raw_pages r ON r.url = s.url'
        ' WHERE s.chars >= ? AND r.raw_text IS NOT NULL'
        ' ORDER BY s.doc_type, s.url LIMIT ? OFFSET ?',
        (a.min_chars, a.limit, a.offset)))
    con.close()

    for url, title, dt, src, chars, content, raw in rows:
        rh, rt = window(raw, 600, 400)
        ch, ct = window(content, 400, 300)
        rec = {'url': url, 'type': dt, 'src': src or '', 'chars': chars,
               'title': title or '',
               'raw_head': rh.replace('\n', ' ⏎ '), 'raw_tail': rt.replace('\n', ' ⏎ '),
               'cur_head': ch.replace('\n', ' ⏎ '), 'cur_tail': ct.replace('\n', ' ⏎ ')}
        print(json.dumps(rec, ensure_ascii=False), flush=True)
    print(f'# 导出 {len(rows)} 篇', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
