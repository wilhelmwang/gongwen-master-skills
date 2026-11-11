#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""字段分离小样验证器（只读，结果打 stdout）

背景：库里正文是一整块纯文本——标题、正文、发文机关、成文日期、附件说明全混在
一个 `content` 字段里。排版时要先解析一遍，每次生成都做一次脆弱的正则。
本器验证「把字段拆出来」这件事在现有语料上能做到什么程度。

抽的字段与判据
--------------
  issuer        发文机关署名：末尾若干行里，独立成行、无句号、以 机关类型词结尾的短行
  doc_number    发文字号：`××〔20XX〕N号` 形态
  sign_date     成文日期：独立成行的 `20XX年X月X日`
  attachments   附件说明：行首「附件」+ 序号/冒号
  paragraphs    正文段落数组：去掉上述构件后的正文行

**只读**：不写任何文件，命中率与失败样例打在 stdout，供人工判断能否继续。

用法
----
  python extract_fields.py --limit 20
  python extract_fields.py --type 工作报告 --limit 10 --show-miss
"""
import argparse
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import export_review as er   # noqa: E402

DB = os.path.join(er.sw.OUT_DIR, 'gongwen_samples.db')

#: 机关类型结尾词——署名行的判据
ORG_TAIL = re.compile(
    r'(省|市|县|区|自治县|州|旗|镇|乡|街道)?'
    r'(人民政府|人民政府办公室|委员会|办公厅|办公室|管理局|管理局|局|厅|部|委|'
    r'法院|检察院|政协|人大|团体|联合会|协会|中心|公司|学校|医院|支行|分行)$')
#: 发文字号：××〔20XX〕N号 / ××发〔20XX〕N号
DOCNUM = re.compile(r'[\u4e00-\u9fa5A-Za-z]{1,12}[〔\[]\s*20\d{2}\s*[〕\]]\s*第?\s*\d{1,5}\s*号')
#: 成文日期（独立成行）
SIGNDATE = re.compile(r'^\s*20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*$')
#: 附件说明
ATTACH = re.compile(r'^\s*附件\s*[:：]?\s*\d*\s*[:：]?\s*\S')
#: 明显的正文句特征（含句号或够长）——用来把署名行与正文区分开
SENT = re.compile(r'[。；：！？]$')


def extract(content):
    lines = [x.strip() for x in (content or '').split('\n')]
    lines = [x for x in lines if x]
    got = {'issuer': '', 'doc_number': '', 'sign_date': '', 'attachments': [],
           'paragraphs': []}
    body, tail_i = [], len(lines)
    # 从尾部往前扫，连续命中构件就继续，遇到正文即停（构件总在末尾）
    for i in range(len(lines) - 1, max(-1, len(lines) - 12), -1):
        x = lines[i]
        if not got['sign_date'] and SIGNDATE.match(x):
            got['sign_date'] = x
            continue
        if not got['issuer'] and 2 <= len(x) <= 24 and not SENT.search(x) \
                and ORG_TAIL.search(x):
            got['issuer'] = x
            continue
        if len(x) > 30 or SENT.search(x):
            tail_i = i + 1
            break
        tail_i = i
    body = lines[:tail_i]
    for x in lines:
        if not got['doc_number']:
            m = DOCNUM.search(x)
            if m:
                got['doc_number'] = m.group(0)
        if ATTACH.match(x) and len(x) <= 40:
            got['attachments'].append(x)
    got['paragraphs'] = [x for x in body if x not in got['attachments']]
    return got


def main():
    ap = argparse.ArgumentParser(description='字段分离小样验证（只读）')
    ap.add_argument('--limit', type=int, default=20)
    ap.add_argument('--type', default='')
    ap.add_argument('--show-miss', action='store_true')
    a = ap.parse_args()

    if not os.path.exists(DB):
        print('库不存在:', DB)
        return 2
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    q = ('SELECT url, title, doc_type, content FROM samples WHERE chars >= ?'
         + (' AND doc_type = ?' if a.type else '')
         + ' ORDER BY url LIMIT ?')
    args = (600, a.type, a.limit) if a.type else (600, a.limit)
    rows = list(con.execute(q, args))
    con.close()
    if not rows:
        print('没取到样本')
        return 0

    stat = {'doc_number': 0, 'sign_date': 0, 'issuer': 0, 'attachments': 0}
    miss = []
    print(f'样本 {len(rows)} 篇'
          + (f'（{a.type}）' if a.type else '')
          + f' ｜ 库 {os.path.basename(DB)}\n')
    for url, title, dt, content in rows:
        g = extract(content)
        for k in stat:
            if g[k]:
                stat[k] += 1
        hit = sum(1 for k in stat if g[k])
        line = (f'[{(dt or ""):5s}] {(title or "")[:34]:34s} '
                + ' '.join(f'{k[:4]}={"✓" if g[k] else "·"}' for k in stat)
                + f' 段{len(g["paragraphs"])}')
        print(line)
        if hit == 0:
            miss.append((title, g))

    n = len(rows)
    print(f'\n=== 命中率（{n} 篇）===')
    for k, v in stat.items():
        print(f'  {k:12s} {v:3d}/{n}  {v * 100 // n:3d}%')
    any_hit = sum(1 for _, t, _, c in rows if any(extract(c).values()))
    print(f'  至少命中一个构件: {any_hit}/{n}  {any_hit * 100 // n}%')
    if a.show_miss and miss:
        print(f'\n=== 零命中样例（{len(miss)} 篇）===')
        for t, g in miss[:5]:
            print(f'  {(t or "")[:50]} → 段数 {len(g["paragraphs"])}')
    print('\n注：doc_number / sign_date 在网页版公文里常常本就不存在——'
          '命中率低不等于抽取器差，要先看「原文是否带这个字段」。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
