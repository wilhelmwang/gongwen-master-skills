import os

def _find_root():
    """包根探测：向上找含 VERSION 的目录（目录改名/跨机部署自适应）"""
    import os
    p = os.path.dirname(os.path.abspath(__file__))
    while not os.path.exists(os.path.join(p, 'VERSION')) and os.path.dirname(p) != p:
        p = os.path.dirname(p)
    return p

_DATA_ROOT = os.path.join(_find_root(), 'datahub')
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核心论断库抽取 v1.0（C-求是，2026-09-01）
规则抽取：每篇取 2-4 条论断句（判断句特征：是/必须/要/坚持/根本/关键/本质/一定/始终 等 + 长度 18-80 字）
→ references/素材库/求是文章/statements.json（主题索引：标题词 + jieba 高频词）
用法: python extract_statements.py
"""
import sqlite3, os, re, json, sys
from collections import Counter

# 数据路径：统一经 datahub/paths.py 解析（v7.3.0 单一事实源）
# 此前指向包内 datahub/sqlite/qs_articles.db —— 该库自 2026-09-09 起为 0 字节占位，重抽会读空库。
sys.path.insert(0, _DATA_ROOT)
from paths import db_path, statements_path
DB = db_path()
OUT = statements_path()

MARK = re.compile(r'(是|必须|要|坚持|根本|关键|本质|一定|始终|更加|着力|不断|全面|进一步)')
SENT = re.compile(r'([^。！？]*?(?:是|必须|要|坚持|根本|关键|本质) [^。！？]{8,60}[。！？])')
STOP = re.compile(r'(编者按|本报|本刊|网址|扫一扫|二维码|版权|来源|预览|摘要)')

def split_sents(text):
    return [s.strip() for s in re.split(r'[。！？]', text) if s.strip()]

def main():
    conn = sqlite3.connect(DB)
    rows = conn.execute('SELECT id, title, content FROM articles WHERE content IS NOT NULL AND length(content) > 1000').fetchall()
    conn.close()
    print(f'候选文章: {len(rows)}')

    try:
        import jieba
    except ImportError:
        jieba = None

    statements = []
    picked = 0
    for aid, title, content in rows:
        sents = split_sents(content)
        cands = []
        for s in sents[:40]:  # 只看前 40 句（开头论断区）
            if not (12 <= len(s) <= 90):
                continue
            if STOP.search(s):
                continue
            if MARK.search(s) and s[0] not in '“「（—':
                cands.append(s)
            if len(cands) >= 6:
                break
        if not cands:
            continue
        # 主题关键词：标题词 + 首句高频词
        keys = set()
        keys.update([w for w in re.findall(r'[\u4e00-\u9fa5]{2,4}', title or '') if w not in ('我们', '中国', '人民', '发展', '建设', '推进') ][:4])
        if jieba:
            top = [w for w, _ in Counter(
                w for w in jieba.lcut(cands[0]) if len(w) >= 2 and w not in ('我们', '中国', '一个', '这个', '对于', '进行', '以及', '可以')
            ).most_common(4)]
            keys.update(top)
        for s in cands[:4]:
            statements.append({
                'id': aid, 'title': title, 'statement': s,
                'keywords': list(keys)[:6],
            })
        picked += 1

    from pathlib import Path as _P
    _P(OUT).write_text(json.dumps({'count': len(statements), 'articles_picked': picked,
                                   'items': statements}, ensure_ascii=False), encoding='utf-8')
    size = os.path.getsize(OUT) / 1024 / 1024
    print(f'论断库: {len(statements)} 条 / 覆盖文章 {picked} 篇 / {size:.1f}MB → {OUT}')

if __name__ == '__main__':
    main()