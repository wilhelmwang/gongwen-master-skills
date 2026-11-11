#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""政策文件定向查询（国务院 / 部门 / 中央 / 其他文件 四库）

为什么是"定向查询"而不是"并入主库检索"
--------------------------------------
主库（`gongwen_corpus.db`）的作用是**写作引证**——里面的权威期刊与国务院公报用来学文风、
取立意；政策文件库的作用是**核依据**——某个提法出自哪份文、文号是多少、原文怎么写的。
两者混在一起，引文的出处会变成基层部门的《关于印发××的通知》。
所以四库**不并入 hybrid3**，由本器单独提供入口（与范文池不入检索同一条判断）。

四库合计 **27,352 篇**，与主库 20,931 篇按 URL 比对**重叠 0 条**：

    简称    库                篇数     内容
    zy     zhengce_zy.db       550    中央文件（行政法规 / 意见 / 制度规定）
    gw     zhengce_gw.db     5,998    国务院文件（国发 / 国办发 / 国函）
    bm     zhengce_bm.db    12,685    部门文件（各部委通知 / 公告 / 制度规定）
    other  zhengce_other.db  8,119    其他文件

检索口径
--------
- **词面检索**（trigram FTS，按相关度排序）。不走向量路——政策查询要的是**精确命中**，
  且这四库未做嵌入。
- ⚠️ trigram 分词器**要求查询串 ≥3 字**：更短的查询自动回退到 `LIKE`（全表扫，库不大可接受）。
- 多词按空白切分后**全部命中**（AND）；每词加引号使 FTS5 把它当字面短语，避免
  `-`／`*` 等被当成查询语法。

用法
----
  python search_zhengce.py "高标准农田"                 # 跨四库检索（默认每库 5 条）
  python search_zhengce.py "高标准农田" --lib gw,bm     # 只查指定库
  python search_zhengce.py "高标准农田" --per 10 --full  # 每库 10 条并打印正文片段
  python search_zhengce.py --wenhao "国办发〔2026〕"     # 按文号查（前缀匹配）
  python search_zhengce.py --show <url>                 # 看某篇全文（核原文用）
  python search_zhengce.py --stats                      # 各库篇数 / 文号覆盖 / 时间跨度

平台：Windows / macOS / Linux；Python 3.8+；只读，无网络调用。
"""
import argparse
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

try:
    from paths import policy_libs, policy_db_path, POLICY_NAMES
except ImportError:                                  # 数据层缺失时不崩在导入上
    policy_libs = policy_db_path = None
    POLICY_NAMES = {}

MIN_TRIGRAM = 3          # trigram 分词器的最小查询长度
LONG_SEG = 6             # 无空格且长于这个字数 → 当"问句"处理，先分词
SNIP = 160               # 正文片段长度


def _open(short):
    p = policy_db_path(short)
    if not (os.path.exists(p) and os.path.getsize(p) > 0):
        return None
    # 只读 URI：防误写（本器全程只读）
    return sqlite3.connect(f'file:{p}?mode=ro', uri=True)


def _quote(tok):
    """引号包裹成字面短语，避免 `-`／`*` 被 FTS5 当查询语法"""
    return '"%s"' % tok.replace('"', '""')


def _seg(text):
    """中文分词（只在长问句上按需调用；jieba 缺失则按二字滑窗退化）

    ⚠️ 为什么需要它：trigram 的短语匹配要求**连续命中**，
    而"育儿补贴每年发多少钱"这种问句在正文里从不连续出现 → 实测命中 0 条。
    用户会怎么问就得怎么支持，故长问句先切词再按"任一命中"检索。
    """
    try:
        import jieba
        return [w for w in jieba.cut(text) if w.strip()]
    except Exception:
        return [text[i:i + 2] for i in range(len(text) - 1)]


def _fts_query(text):
    """把用户输入转成 FTS5 查询串：按空白切词、全部命中的 AND 短语串"""
    toks = [t for t in re.split(r'\s+', (text or '').strip()) if t]
    return ' '.join(_quote(t) for t in toks)


def build_query(text):
    """返回 (fts 查询串, 模式标签)；模式 ∈ {'and','or','like'}

    · 短于 3 字 → 'like'（trigram 不支持，调用方走 LIKE 回退）
    · 无空格且 >6 字 → 当问句，**分词后任一命中**（'or'）
    · 其余 → 全部命中（'and'）
    """
    t = (text or '').strip()
    if len(t) < MIN_TRIGRAM:
        return None, 'like'
    toks = [x for x in re.split(r'\s+', t) if x]
    if len(toks) == 1 and len(t) > LONG_SEG:
        words = [w for w in _seg(t) if len(w.strip()) >= 2]
        if len(words) > 1:
            return ' OR '.join(_quote(w) for w in words), 'or'
    return ' '.join(_quote(x) for x in toks), 'and'


def _fts_search(con, fts_q, per):
    return con.execute(
        'SELECT g.id, g.title, g.wenhao, g.pubtime, g.doc_type,'
        ' g.word_count, g.url, bm25(gongbao_fts) AS s'
        ' FROM gongbao_fts JOIN gongbao g ON g.id = gongbao_fts.rowid'
        ' WHERE gongbao_fts MATCH ? ORDER BY s LIMIT ?',
        (fts_q, per)).fetchall()


def _like_search(con, term, per):
    like = f'%{term}%'
    # 短词无相关度可用，故给"标题命中优先、正文命中次之"一个廉价位次——
    # 否则 3.8 万字的《乡村振兴战略规划》会靠字数把精准标题顶下去（实测过）。
    return con.execute(
        'SELECT id, title, wenhao, pubtime, doc_type, word_count, url, 0.0'
        ' FROM gongbao WHERE title LIKE ? OR content LIKE ?'
        ' ORDER BY CASE WHEN title LIKE ? THEN 0 ELSE 1 END, word_count DESC'
        ' LIMIT ?',
        (like, like, like, per)).fetchall()


def _like_or(con, words, per):
    """逐词 LIKE 后在 Python 里合并去重（不拼 SQL，避免动态构造的注入面）。

    为什么要有这条退路：trigram 短语要求 **≥3 字**，而中文问句经分词后常全是二字词
    （实测「育儿补贴每年发多少钱」→ 育儿/补贴/每年/多少，一个都匹配不上）。此时
    FTS 全路尽墨，只能退回 LIKE——它没有 3 字下限。排序：标题命中在前。
    """
    merged, seen = [], set()
    for w in words:
        for row in _like_search(con, w, per):
            url = row[6]
            if url in seen:
                continue
            seen.add(url)
            merged.append(row)
    merged.sort(key=lambda r: (0 if words and words[0] in (r[1] or '') else 1,
                               -(r[5] or 0)))
    return merged[:per]


def search_one(short, text, per):
    """单库检索，返回 (rows, 模式标签)。

    模式标签是**如实标注**，不是内部细节：`and` 全部命中 / `or` 问句分词任一命中 /
    `or(fallback)` 精确无果后放宽 / `like-or(问句分词)` 退到 LIKE / `like` 短词。
    调用方据此判断结果的松紧程度，别把放宽后的结果当成精确匹配。
    """
    con = _open(short)
    if con is None:
        return None, 'missing'
    try:
        t = (text or '').strip()
        fts_q, mode = build_query(t)
        if mode == 'like':
            return _like_search(con, t, per), 'like'
        if mode == 'or':
            # ⚠️ **先试整串精确短语，再退分词**（2026-09-16 修）。
            # 无空格长串既可能是问句、也可能是一份文的标题或一段条款原文——
            # 而"长"这个条件无法区分二者。曾经的实现一律按问句分词，结果
            # 「国家水网建设规划纲要」「市场监管领域知识产权案件案由规定」这两条
            # **精确标题查询反而查不到目标文**（分词成 国家/水网/建设/… 后被大文件挤掉）。
            # 精确短语匹配既便宜（FTS 一次）又零误伤，故放在最前；不中才退分词。
            rows = _fts_search(con, _quote(t), per)
            if rows:
                return rows, 'phrase'
            rows = _fts_search(con, fts_q, per)
            if rows:
                return rows, 'or(分词)'
            words = [w.strip() for w in _seg(t) if len(w.strip()) >= 2]
            if words:
                rows2 = _like_or(con, words, per)
                if rows2:
                    return rows2, 'like-or(问句分词)'
            return rows, 'or'
        # mode == 'and'
        rows = _fts_search(con, fts_q, per)
        if rows:
            return rows, 'and'
        toks = [x.strip() for x in re.split(r'\s+', t) if x.strip()]
        if len(toks) > 1:
            rows2 = _fts_search(con, ' OR '.join(_quote(x) for x in toks), per)
            if rows2:
                return rows2, 'or(fallback)'
        return rows, 'and'
    finally:
        con.close()


#: 文号书写变体归一：去掉括号（全/半角、书名号式）、空白、「第」与口语里的「年」。
#: 为什么需要：库内文号存的是含全角括号的规范形态「国办发〔2019〕50号」，
#: 而**人不会这么打字**——实测用户敲「国办发2019年50号」时一条都查不到
#: （政策能力线 hard 用例 h04 暴露）。归一后两侧都能对上：
#:   国办发〔2019〕50号 → 国办发201950号 ｜ 国办发2019年50号 → 国办发201950号
#: 「年」必须一起去：留着它会与库内形态差一个字（实测第一次修就漏了它）。
_DROP_WH = re.compile(r'[〔\[（(【「《〕\]）)】」》\s第年]')


def _norm_wh(n):
    return _DROP_WH.sub('', (n or '').strip())


def search_wenhao(prefix, per):
    """按文号查（**容忍书写变体**：括号有无、全半角、「第」字、空格）

    粗筛 + 精比两步：先用「机关代字（必要时叠加年份）」做 LIKE 把候选缩到几十上百行，
    再在 Python 里按归一化形态精确比对。不这么做就得全表扫 4 万行，或反过来
    只按字面前缀匹配——后者正是「国办发2019年50号」查不到的根因。
    """
    key = _norm_wh(prefix)
    if not key:
        return []
    m = re.match(r'^[\u4e00-\u9fa5]{2,}', key)
    coarse = f'{m.group(0)}%' if m else '%'
    y = re.search(r'(19|20)\d{2}', key)
    if y:
        coarse = coarse[:-1] + f'%{y.group(0)}%'      # 代字 + 年份，进一步收窄
    out = []
    for short, _name, _p, form in policy_libs():
        if form is None:
            continue
        con = _open(short)
        try:
            rows = con.execute(
                'SELECT id, title, wenhao, pubtime, doc_type, word_count, url, 0.0'
                ' FROM gongbao WHERE wenhao LIKE ?'
                ' ORDER BY pubtime DESC LIMIT ?',
                (coarse, 600)).fetchall()
        finally:
            con.close()
        hits = [r for r in rows if _norm_wh(r[2]) == key]
        if not hits:                                  # 退一步：只记得前半段
            hits = [r for r in rows if _norm_wh(r[2]).startswith(key)]
        for r in hits[:per]:
            out.append((short, r))
    return out


def show(url):
    """按 url 看全文（跨库找，命中的第一个库胜出；URL 在各库唯一）"""
    for short, _name, _p, form in policy_libs():
        if form is None:
            continue
        con = _open(short)
        try:
            r = con.execute(
                'SELECT title, wenhao, pubtime, doc_type, url, content, word_count'
                ' FROM gongbao WHERE url = ?', (url,)).fetchone()
        finally:
            con.close()
        if r:
            return short, r
    return None, None


def snippet(content, text, n=SNIP):
    """取正文中第一处命中附近的窗口（trigram 的 snippet() 对中文断句不友好，手工截）"""
    c = (content or '').replace('\n', '').replace(' ', '')
    key = (text or '').strip()
    i = c.find(key) if key else -1
    if i < 0:
        return c[:n]
    a = max(0, i - n // 3)
    return ('…' if a else '') + c[a:a + n] + '…'


def cmd_search(text, libs, per, full):
    print(f'政策文件检索：{text}')
    print('=' * 72)
    total = 0
    for short, name, _p, form in policy_libs():
        if libs and short not in libs:
            continue
        if form is None:
            print(f'\n【{name} / {short}】库缺失（形态 C 或未采到）')
            continue
        rows, how = search_one(short, text, per)
        n = 0
        if rows:
            n = sum(1 for _ in rows)
        total += n
        print(f'\n【{name} / {short}】命中 {n} 条（{how}）')
        for rank, (rid, title, wenhao, pubtime, doc_type, wc, url, _s) in enumerate(rows, 1):
            print(f'  {rank}. {title}')
            print(f'     {wenhao or "（无文号）"} ｜ {pubtime or "无日期"} ｜'
                  f' {doc_type or "-"} ｜ {wc or 0} 字')
            print(f'     {url}')
            if full:
                _, r = show(url)
                if r:
                    print(f'     …{snippet(r[5], text)}')
    print(f'\n合计命中 {total} 条')
    if not libs:
        print('提示：四库为**依据出处**，与主库（写作引证）分开检索；'
              '查原文用 --show <url>。')
    return 0


def cmd_stats():
    print('政策文件库四库现状')
    print('=' * 72)
    tot = 0
    for short, name, p, form in policy_libs():
        if form is None:
            print(f'{name}（{short}）: 缺失 — 期望路径 {p}')
            continue
        con = _open(short)
        try:
            n = con.execute('SELECT count(*) FROM gongbao').fetchone()[0]
            wh = con.execute(
                'SELECT count(*) FROM gongbao WHERE wenhao IS NOT NULL'
                ' AND wenhao <> ""').fetchone()[0]
            span = con.execute(
                'SELECT min(pubtime), max(pubtime) FROM gongbao'
                ' WHERE pubtime IS NOT NULL AND pubtime <> ""').fetchone()
            dt = con.execute(
                'SELECT doc_type, count(*) FROM gongbao GROUP BY 1'
                ' ORDER BY 2 DESC LIMIT 3').fetchall()
        finally:
            con.close()
        tot += n
        s = ' / '.join(f'{a} {b}' for a, b in dt)
        print(f'{name}（{short}）: {n:,} 篇 ｜ 有文号 {wh:,}（{wh*100//max(n,1)}%）'
              f' ｜ {span[0] or "?"} ~ {span[1] or "?"}')
        print(f'    主要类型：{s}')
    forms = {f for _s, _n, _p, f in policy_libs() if f}
    print(f'\n合计 {tot:,} 篇（形态 {"/".join(sorted(forms)) or "C 无数据"}）')
    print('注意：这四库**不在** hybrid3 检索内，属"核依据"通道，与主库（写作引证）分工不同。')
    return 0


def main():
    ap = argparse.ArgumentParser(description='政策文件定向查询（四库，只读）')
    ap.add_argument('query', nargs='?', help='检索词（≥3 字走 trigram FTS，短词回退 LIKE）')
    ap.add_argument('--lib', default='', help='限定库，逗号分隔：zy,gw,bm,other（默认全部）')
    ap.add_argument('--per', type=int, default=5, help='每库返回条数（默认 5）')
    ap.add_argument('--full', action='store_true', help='附正文命中片段')
    ap.add_argument('--wenhao', default='', help='按文号前缀查，如 "国办发〔2026〕"')
    ap.add_argument('--show', default='', help='按 URL 打印全文（核原文用）')
    ap.add_argument('--stats', action='store_true', help='看四库现状')
    a = ap.parse_args()

    if policy_libs is None:
        print('数据层不可用（datahub/paths.py 导入失败）：本器无法解析政策库路径。')
        return 2

    if a.stats:
        return cmd_stats()
    if a.show:
        short, r = show(a.show)
        if not r:
            print(f'未找到该 URL：{a.show}')
            return 1
        title, wenhao, pubtime, doc_type, url, content, wc = r
        print(f'【{POLICY_NAMES.get(short, short)}】{title}')
        print(f'{wenhao or "（无文号）"} ｜ {pubtime or "无日期"} ｜ {doc_type or "-"} ｜ {wc or 0} 字')
        print(url)
        print('=' * 72)
        print(content)
        return 0
    if a.wenhao:
        rows = search_wenhao(a.wenhao, a.per)
        print(f'文号前缀「{a.wenhao}」命中 {len(rows)} 条')
        print('=' * 72)
        for short, (rid, title, wenhao, pubtime, doc_type, wc, url, _s) in rows:
            print(f'  [{POLICY_NAMES.get(short, short)}] {wenhao} ｜ {pubtime or "-"} ｜ {wc} 字')
            print(f'     {title}')
            print(f'     {url}')
        return 0
    if not a.query:
        ap.print_help()
        return 2
    libs = {s.strip() for s in a.lib.split(',') if s.strip()}
    valid = {s for s, _n, _p, _f in policy_libs()}
    bad = libs - valid
    if bad:
        print(f'未知库简称：{sorted(bad)}；可选 {sorted(valid)}')
        return 2
    return cmd_search(a.query, libs, a.per, a.full)


if __name__ == '__main__':
    sys.exit(main())
