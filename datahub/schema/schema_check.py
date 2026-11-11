# -*- coding: utf-8 -*-
"""schema 一致性检查 v3（2026-09-11）：三查——①注册表表清单 vs 实库 ②字段对比 DDL ③索引登记

v3 变更（v7.3.0 数据层自洽）
  - 物理路径不再由注册表 `path` 拼接，统一经 `datahub/paths.py` 解析（支持外置数据根与降级）
  - 适配 schema-registry v2 的 domains 分组结构与 `ddl` 列表形态
  - 地方表在合并库中带 `hs_` 前缀，而 DDL 保留逻辑名（无前缀）→ 用 `_ddl_key()` 做前缀回退匹配
  - 跳过无表清单的条目（reference_only 归档登记项）

修复 v1 假绿：只查表存在性，新增表/字段漂移无感知。
"""
import json
import os
import re
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
from paths import (db_path, is_available, degradation_notice,  # noqa: E402
                   samples_db_path)

_Q = chr(39) + chr(34)  # 单引号+双引号（正则字符类用）
RE_TABLE = re.compile(
    r"CREATE\s+(?:VIRTUAL\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[" + _Q + r"]?([\w]+)[" + _Q + r"]?\s*\(",
    re.I)
RE_COL = re.compile(
    r"[" + _Q + r"]?(\w+)[" + _Q + r"]?\s+(?:INTEGER|TEXT|REAL|BLOB|NUMERIC)", re.I)
RE_INDEX = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+\w+\s+ON\s+[" + _Q + r"]?(\w+)", re.I)


def parse_ddl_tables(ddl_text):
    """从 DDL 提取 {表名: {cols:set}}——括号平衡计数法（兼容嵌套括号/CHECK/子查询）。"""
    out = {}
    for m in RE_TABLE.finditer(ddl_text):
        t = m.group(1)
        depth, i = 1, m.end()
        while i < len(ddl_text) and depth > 0:
            if ddl_text[i] == "(":
                depth += 1
            elif ddl_text[i] == ")":
                depth -= 1
            i += 1
        body = ddl_text[m.end():i - 1]
        # 剥离 SQL 行内注释（-- …），否则注释与下一列混段导致 RE_COL 锚定失败
        body = re.sub(r"--[^\n]*", " ", body)
        cols = set()
        for line in re.split(r",", body):
            fm = RE_COL.match(line.strip())
            if fm:
                cols.add(fm.group(1))
        out[t] = {"cols": cols}
    for m in RE_INDEX.finditer(ddl_text):
        out.setdefault(m.group(1), {"cols": set()})
    return out


def _ddl_key(table, ddl_tables):
    """合并库中地方表带 hs_ 前缀，DDL 保留逻辑名 → 前缀回退匹配。

    返回 DDL 中对应的表名；找不到返回 None。
    """
    if table in ddl_tables:
        return table
    if table.startswith('hs_') and table[3:] in ddl_tables:
        return table[3:]
    return None


def _iter_conf(reg):
    """产出 (库标识, 配置, [表名...])；跳过无表清单的登记项（归档引用类）。"""
    for dbname, conf in reg.items():
        if not isinstance(conf, dict):
            continue
        tables = []
        if 'domains' in conf:
            for dom in conf['domains'].values():
                tables.extend(dom.get('tables', []))
        elif 'tables' in conf:
            tables.extend(conf['tables'])
        if not tables:
            continue  # reference_only 等仅归档登记，无实库可查
        yield dbname, conf, tables


def _resolve_db(name, conf):
    """物理路径：按库名解析（注册表不登记路径，符合 path_policy）。

    ⚠️ 默认分支回退到**主库**——新增库若不在此显式解析，门禁会拿主库去查它的表，
    报出一串"缺表"（gongwen_samples 首次登记时就是这样误报的）。
    """
    if name == 'gongwen_samples':
        return samples_db_path()
    p = conf.get('path')
    return os.path.join(BASE, p) if p else db_path()


def main():
    reg = json.load(open(os.path.join(BASE, "schema", "schema-registry.json"),
                         encoding="utf-8"))["databases"]
    bad, checked = [], 0
    for name, conf, tables in _iter_conf(reg):
        p = _resolve_db(name, conf)
        if not os.path.exists(p) or os.path.getsize(p) == 0:
            bad.append(f"{name}: 实库缺失或为空 → {p}"
                       + ('（数据层处于降级形态 C）' if not is_available() else ''))
            continue

        ddl_files = conf.get('ddl') or []
        if isinstance(ddl_files, str):
            ddl_files = [ddl_files]
        ddl_tables = {}
        for d in ddl_files:
            dp = os.path.join(BASE, d)
            if os.path.exists(dp):
                ddl_tables.update(parse_ddl_tables(open(dp, encoding="utf-8").read()))

        conn = sqlite3.connect(p)
        # 实库对象清单（表 + 视图；剔除 FTS 阴影表与内部表）
        shadow = ("_data", "_idx", "_docsize", "_config", "_content")
        real_tables, real_views = set(), set()
        for (nm, typ) in conn.execute(
                "SELECT name, type FROM sqlite_master WHERE type IN ('table','view')"):
            if typ == 'view':
                real_views.add(nm)
            elif not any(nm.endswith(s) for s in shadow) and nm != "sqlite_sequence":
                real_tables.add(nm)
        conn.close()
        real = real_tables | real_views

        declared = {t for t in tables if not t.endswith("*")}
        missing = declared - real
        if missing:
            bad.append(f"{name}: 缺表 {sorted(missing)}")
            continue

        for t in sorted(declared & real):
            if t in real_views:
                # 视图列集由定义决定（如 v_articles_corpus 跨七域聚合），不做 DDL 字段漂移比对，
                # 仅登记存在性；视图 DDL 不在 ddls/ 内属预期。
                checked += 1
                continue
            key = _ddl_key(t, ddl_tables)
            if key is None:
                bad.append(f"{name}: 表 {t} 未入 DDL（{ddl_files or '无'}）")
                continue
            checked += 1
            conn = sqlite3.connect(p)
            # 表值 pragma 函数 + 参数绑定（替代 PRAGMA 无法参数化而拼接表名的写法）
            real_cols = {r[1] for r in conn.execute('SELECT * FROM pragma_table_info(?)', (t,))}
            conn.close()
            ddl_cols = ddl_tables[key]["cols"]
            # 双向漂移检测（real 有 DDL 无 / DDL 有 real 无）
            if real_cols and ddl_cols and real_cols != ddl_cols:
                bad.append(f"{name}.{t}: 字段漂移 "
                           f"real_only={sorted(real_cols - ddl_cols)[:3]} "
                           f"ddl_only={sorted(ddl_cols - real_cols)[:3]}")

    if bad:
        print("schema diff: " + "；".join(bad))
        return 1
    notice = degradation_notice()
    if notice:
        print(notice)
    print(f"schema diff: 全部一致 ✅（表清单+字段对比，{checked} 表过检）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
