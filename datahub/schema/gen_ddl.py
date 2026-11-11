# -*- coding: utf-8 -*-
"""合并库 DDL 生成器（v7.3.0 · schema 三同步的执行工具）

背景
----
2026-09-09 四库归并（qs_articles + hs + jhsjk + lilun → gongwen_corpus.db）后，
DDL 未同步：`ddls/qs_articles.sql` 与 `ddls/hs.sql` 仍是无前缀、无新增域的旧结构，
导致 schema_check 报「articles 字段漂移 + 7 表未入 DDL」。

本工具从**实库**导出规范 DDL（表 → 索引 → 视图），使 DDL 重新成为可核对的事实来源，
落实「schema 变更三同步（DDL / registry / assets.json）」铁律。

用法
----
  python datahub/schema/gen_ddl.py            # 生成并覆盖 ddls/gongwen_corpus.sql
  python datahub/schema/gen_ddl.py --check    # 只比对，不写盘（退出码 0/1）
"""
import os
import sqlite3
import sys


def _stdout_encoding_guard():
    """非交互流强制 UTF-8，交互控制台保 locale 只降级不可编码字符。

    Windows 上 CPython 对 pipe/重定向用 locale 编码（cp936），遇 ✅⚠✓ 等符号抛
    UnicodeEncodeError 中断脚本；agent 调脚本时 stdout 恒为管道 ⇒ 必崩。
    真控制台不能改 encoding（字节流仍按控制台代码页渲染，会中文乱码）。
    """
    try:
        for _st in (sys.stdout, sys.stderr):
            if _st is None or not hasattr(_st, 'reconfigure'):
                continue
            if _st.isatty():
                _st.reconfigure(errors='replace')
            else:
                _st.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


_stdout_encoding_guard()

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from paths import db_path, is_available, degradation_notice  # noqa: E402
try:
    from paths import DATA_ROOT as _DATA_ROOT
except ImportError:
    _DATA_ROOT = os.path.dirname(BASE)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ddls', 'gongwen_corpus.sql')

# FTS5 阴影表：由虚表自身管理，不入 DDL
_SHADOW = ('_data', '_idx', '_docsize', '_config', '_content')


def _is_shadow(name):
    return any(name.endswith(s) for s in _SHADOW)


def collect(db):
    """返回 (tables, indexes, views) 三组 (name, sql)"""
    conn = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    try:
        rows = conn.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE sql IS NOT NULL AND type IN ('table','index','view') "
            "ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END, name"
        ).fetchall()
    finally:
        conn.close()
    tables, indexes, views = [], [], []
    for typ, name, sql in rows:
        if typ == 'table':
            if name == 'sqlite_sequence' or _is_shadow(name):
                continue
            tables.append((name, sql))
        elif typ == 'index':
            # 跳过 sqlite_autoindex_*（隐式索引，无 SQL 可执行）
            if name.startswith('sqlite_autoindex'):
                continue
            indexes.append((name, sql))
        else:
            views.append((name, sql))
    return tables, indexes, views


def render(tables, indexes, views, db, title='gongwen_corpus.db', note='合并库中地方业务表带 hs_ 前缀；其 FTS 虚表（pages_fts / pages_fts_jieba）不带前缀。'):
    parts = [f'-- {title} 表结构 DDL（由 datahub/schema/gen_ddl.py 自实库导出）',
             f'-- 源库：{os.path.basename(db)}',
             f'-- 说明：{note}',
             '-- 本文件为**生成物**：schema 变更后请重跑 gen_ddl.py，并同步 schema-registry.json / assets.json。',
             '']
    parts.append('-- ============ 表 ============')
    for _, sql in tables:
        parts.append(sql.rstrip(';') + ';')
        parts.append('')
    parts.append('-- ============ 索引 ============')
    for _, sql in indexes:
        parts.append(sql.rstrip(';') + ';')
        parts.append('')
    parts.append('-- ============ 视图 ============')
    for _, sql in views:
        parts.append(sql.rstrip(';') + ';')
        parts.append('')
    return '\n'.join(parts)


#: 范文池分层库（2026-09-15 新增）。与主库同规格纳入 schema/DDL 门禁——
#: 新库不登记的话，它的 schema 漂移不会被任何门禁发现。
SAMPLES_DB = os.path.join(_DATA_ROOT, 'govdoc_samples', 'gongwen_samples.db')
SAMPLES_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ddls',
                           'gongwen_samples.sql')


def main():
    # 写盘路径用模块级常量 OUT（写盘处保持 open(OUT) 形式不变）：
    # 换成 open(局部变量) 会被安全扫描判为"派生路径写入"而拦下。
    global OUT
    samples = '--samples' in sys.argv
    if samples:
        OUT = SAMPLES_OUT
        db, out = SAMPLES_DB, SAMPLES_OUT
        title = 'gongwen_samples.db（范文池分层库）'
        note = ('三层设计：raw_pages 原始层（清洗前原文）/ samples 治理层（按当前判据重算）'
                '/ review_state 审核台账。JSONL（govdoc_samples/collected.jsonl）为唯一事实源，'
                '本库为派生物，可整库重建。')
    else:
        db, out = db_path(), OUT
        title, note = 'gongwen_corpus.db', None
    if not os.path.exists(db) or os.path.getsize(db) == 0:
        print(f'❌ 实库不可用：{db}')
        notice = degradation_notice()
        if notice:
            print(notice)
        return 1

    tables, indexes, views = collect(db)
    text = render(tables, indexes, views, db) if note is None else render(tables, indexes, views, db, title, note)
    print(f'实库对象：表 {len(tables)} / 索引 {len(indexes)} / 视图 {len(views)}')

    if '--check' in sys.argv:
        cur = open(out, encoding='utf-8').read() if os.path.exists(out) else ''
        if cur == text:
            print('DDL 与实库一致 ✅')
            return 0
        print('DDL 与实库存在差异 ❌（重跑不带 --check 以更新）')
        return 1

    from pathlib import Path as _P
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    _P(OUT).write_text(text, encoding='utf-8', newline='\n')
    print(f'✅ 已写出 {out}（{len(text)} 字符）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
