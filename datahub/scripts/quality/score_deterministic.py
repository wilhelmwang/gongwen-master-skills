#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L2 精品审核·第 1 步：确定性判据层（零 LLM）

为什么先做这一层
----------------
公文里有一半判据根本不需要 LLM——**结构是否完整、格式是否规范、文本是否干净**都是
可机器判定的。把它们写成规则，等于零成本拿下一票否决层，还能进回归门禁。
（依据：深度研究结论——FineWeb-Edu/CCI3.0-HQ 都把"确定性可判"的部分留给规则，
LLM 预算只花在主观维度上；本项目 2026-09-15 的 frame_rules_pilot 也是逐站归纳，
最终被一条通用定界规则取代，说明"能通用的别逐站"。）

三档产出
--------
  veto  → `verdict='C'`：命中任一**一票否决**（见 VETO 注释），直接判不合格
  pass  → `verdict=NULL`：无否决，各维已算分，**留给第 2 步 LLM 打主观维**
  落 `quality_det`（**不是 `review_state`**）：主键 `(url, rule_ver)`，
  三维分 + `veto` 命中原因 + `evidence_json` 逐项证据。
  ⚠️ 为什么另立一张表：`review_state` 的主键只有 `url`，2026-09-17 实测按 url 写 24,031 行
  **把 108 条审核台账整片覆盖**（40 条 A/B 锚点当场丢失，靠 `backfill_review.py` 恢复）。
  且确定性分需要留多版以便消融（同一篇 × 不同 `rule_ver`），单列主键也放不下。

三维（0-100，各项扣分可解释）
----------------------------
  结构 struct：层次标记连续 40 ｜ 段落数≥3 20 ｜ 分块小标题≥2 20 ｜ 落款形态 20
  洁净 clean ：样板占比 40 ｜ 无 HTML 实体/零宽 30 ｜ 无网址残留 15 ｜ 中文占比 15
  格式 fmt   ：引号规范 40 ｜ 标点以全角为主 30 ｜ 无连续空格/控制字符 30

口径复用：`export_review.py` 的 cleaned_lines / score_boiler / outline_of / prescreen
（第 1 段已固化并被门禁覆盖，不另立一套）。

用法
----
  python score_deterministic.py --dry-run          # 只统计，不写库
  python score_deterministic.py --limit 500        # 小样
  python score_deterministic.py                    # 全量（写前自动快照）
  python score_deterministic.py --report           # 看现状与 veto 原因分布
  python score_deterministic.py --anchor-check     # 与 40 条 A/B 锚点对账（不许误杀）
"""
import argparse
import datetime
import json
import os
import re
import sqlite3
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))          # datahub/
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(_HERE)), 'corpus'))
import export_review as er          # noqa: E402  复用清洗与预筛口径
import snapshot as snap             # noqa: E402  写前快照 + 轮转（四铁律④）
import paths                        # noqa: E402  数据根单一解析器

#: 分层库路径一律经解析器（env 覆盖仅用于测试）
DB = os.environ.get('GW_SAMPLES_DB') or paths.samples_db_path()
#: 规则版本：改判据就升版本，**同一条 url 允许多版并存**（消融与迭代用）
RULE_VER = 'v3'

#: ★ v2 新增：**"实际文种"识别**。池子的 `doc_type` 是采集来源的栏目名，实测约 18–30% 与内容不符
#: （见第 2 步的 `type_mismatch` 统计），而长度下限与结构判据都是**按文种**取的——
#: 拿"调研报告 700 字"去卡一篇实为「××主任带队赴××调研」的动态稿（消息体），
#: 就会把它误判为 too_short（第 2 步对比：37 条 too_short 里多属此类，LLM 判它们 B/A）。
DYN_TITLE = re.compile(r'(率队|带队|一行|赴|到[^，。]{2,10}(?:调研|考察|视察|督导|检查)'
                       r'|视察|开展调研|调研督导|座谈|走访|慰问)')
#: 标题里的"公文/叙事词"——一个都没有且标题很短 → 多半是首页/栏目页
ARTICLE_WORDS = re.compile(
    r'关于|通知|报告|纪要|总结|意见|决定|方案|计划|批复|函|议案|提案|建议|公告|公示|通报'
    r'|会议|调研|考察|检查|视察|工作|情况|开展|推进|建设|实施|加强|贯彻|落实|学习|经验|做法'
    r'|讲话|发言|致|在[^，。]{0,8}(?:上|中|时)|为[^，。]{0,8}')

#: 一票否决阈值（依据：ChineseWebText/EvalWeb 的公开判据 + 本项目预筛）
MIN_CJK_RATIO = 0.30        # 中文字符占比下限（EvalWeb：<30% 丢弃）
MAX_SELF_REPEAT = 0.50      # 文档内 13-gram 自重复上限（EvalWeb：>50% 丢弃）
MAX_BAD_CHAR = 0.02         # 乱码/替换字符占比上限
#: HTML 实体**数量**阈值——1~2 个 `&ensp;` 是段首缩进标记的残骸（实测某纪要只有 1 个，
#: 全文干净可用），而 313 个 `&#160;` 那种是**整页没洗干净**（实测带导航残留）。
#: 拿"出现即否决"会把 18% 的干净件误杀，故只在**数量成灾**时否决，否则在洁净维扣分。
ENTITY_MANY = 10
ENTITY_RE = re.compile(r'&[a-zA-Z]{2,8};|&#\d{1,5};')
ZW_RE = re.compile(r'[\u200b-\u200f\u202a-\u202e\ufeff]')
URL_RE = re.compile(r'https?://\S+')
CJK_RE = re.compile(r'[\u4e00-\u9fff]')
BAD_RE = re.compile(r'[\ufffd\u0000-\u0008\u000b\u000c\u000e-\u001f]')
NUM_HEAD = re.compile(r'^\s*(?:[一二三四五六七八九十]{1,3}、|[（(][一二三四五六七八九十]{1,3}[)）])')
#: 其余序号形态（实测诊断：826 篇「结构_低」里有 140 篇用的是这些，只认「一、」会漏判）
NUM_ALT = re.compile(r'^\s*(?:\d{1,2}[.、]|[（(]\d{1,2}[)）]|第[一二三四五六七八九十\d]{1,3}(?:条|步|项)|——)')
INLINE_ENUM = re.compile(r'[一二三四五六七八九]是')
DATE_END = re.compile(r'20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日')
AGENCY_END = re.compile(r'(?:办公室|人民政府|委员会|管理局|厅|部|局|院|会|中心|集团)\s*$')
#: 导语形态（消息体首段）：短句且含时间/地点/主体
LEAD_RE = re.compile(r'^\s*(?:近日|日前|\d{1,2}月\d{1,2}日|20\d{2}年|\d{4}年'
                     r'|[^，。]{2,14}(?:市|县|区|省|局|委|办|公司|学校))')


def cls_layers(ls):
    """层次标记：序号是否连续不漏号不重号。返回 (命中序号数, 连续性得分0-40)

    认三类形态：中文序号（一、/（一））、其余序号（1./（1）/第X条/——）、
    以及段落内枚举「一是…二是…」（公文里常用它代替小标题，只给 20 分）。
    """
    seen, alt, inline = [], 0, 0
    for x in ls:
        m = NUM_HEAD.match(x)
        if m:
            head = m.group(0).strip('、（()） ')
            if head and (not seen or head != seen[-1]):
                seen.append(head)
            continue
        if NUM_ALT.match(x):
            alt += 1
        if INLINE_ENUM.search(x):
            inline += 1
    cn = '一二三四五六七八九十'

    def val(h):
        if h in cn:
            return cn.index(h) + 1
        if h.startswith('十') and len(h) == 2 and h[1] in cn:
            return 10 + cn.index(h[1]) + 1
        return None

    if len(seen) >= 2:
        order = [v for v in (val(h) for h in seen) if v]
        if len(order) >= 2 and (all(b == a + 1 for a, b in zip(order, order[1:]))
                               or all(b > a for a, b in zip(order, order[1:]))):
            return len(seen), 40
        return len(seen), 20
    if alt >= 2:
        return alt, 40
    if inline >= 3:
        return inline, 20          # 「一是…二是…」：是层次，但不是小标题形态
    return len(seen) or alt, 0


def self_repeat(text, k=13):
    """文档内 k-gram 自重复率（EvalWeb 判据；抓复制粘贴与模板段）"""
    s = re.sub(r'\s+', '', text or '')
    if len(s) <= k:
        return 0.0
    grams = [s[i:i + k] for i in range(len(s) - k + 1)]
    return 1 - len(set(grams)) / len(grams)


def score_one(rec, ls, boiler):
    """返回 (veto原因, 三维分 dict, 逐项证据 dict)"""
    flat = '\n'.join(ls)
    body = ''.join(ls)
    n = len(body)
    dt = rec.get('doc_type', '')
    title = rec.get('title') or ''
    et = effective_type(dt, title)      # 实际文种（v2：长度下限与结构判据都按它取）
    ev = {'doc_type': dt, 'eff_type': et}
    if et != dt:
        ev['type_corrected'] = True

    # ---------- 一票否决 ----------
    veto = []
    # 长度下限按**实际文种**判（v2）：把 doc_type 换成 et 后再走预筛，
    # 否则「实为消息的调研动态」会被调研报告 700 字的下限误杀。
    ok, why = er.prescreen(dict(rec, doc_type=et))
    if not ok:
        veto.append(why)
    heads0, _layer0 = cls_layers(ls)
    na = is_non_article(title, ls, heads0)
    if na:
        ev['non_article'] = na
        veto.append('non_article')
    cjk = len(CJK_RE.findall(body)) / max(len(re.sub(r'\s', '', body)), 1)
    ev['cjk_ratio'] = round(cjk, 3)
    if cjk < MIN_CJK_RATIO:
        veto.append('low_cjk')
    sr = self_repeat(body)
    ev['self_repeat13'] = round(sr, 3)
    if sr > MAX_SELF_REPEAT:
        veto.append('self_repeat')
    bad = len(BAD_RE.findall(body)) / max(n, 1)
    ev['bad_char'] = round(bad, 4)
    if bad > MAX_BAD_CHAR:
        veto.append('bad_char')
    if ENTITY_RE.findall(body) and len(ENTITY_RE.findall(body)) >= ENTITY_MANY:
        ev['html_entity'] = len(ENTITY_RE.findall(body))
        veto.append('html_entity_many')

    # ---------- 结构（**按文种取判据**）----------
    # 消息体：98% 为连续正文、无小标题、无落款（见 judge_tasks 的 structure_spec 实测），
    # 用公文那一套（层次/小标题/落款）去量它，整类会被压到 20 分——实测 300 篇样本里
    # 「结构_高」只占 3.7%，正是这个口径错配造成的。
    heads, layer = cls_layers(ls)
    ev['num_heads'] = heads
    ev['layer_score'] = layer
    ev['paras'] = len(ls)
    outline_n = len(er.outline_of(ls))
    ev['outline_n'] = outline_n
    if et == '消息':
        lead = bool(LEAD_RE.match(ls[0])) if ls else False
        ev['lead'] = lead
        ends = bool(re.search(r'[。！？”]', ls[-1] if ls else ''))
        ev['ends_clean'] = ends
        s_struct = (40 if lead else 0) + (30 if len(ls) >= 3 else 0) + (30 if ends else 0)
    elif et == '会议纪要':
        # 纪要的必备构件里**没有落款**（judge_tasks 的 structure_spec 实测：纪要 required 是
        # 时间地点/主持人/出席列席/议题/议定事项，而通知类才有署名+日期）。实测 10 条 A 档
        # 纪要**全部无落款**——若照公文通用口径扣它 20 分，整类被系统性压低。
        head = ls[0] if ls else ''
        has_call = bool(re.search(r'主持|召开', head))
        ev['has_call'] = has_call
        has_attend = bool(re.search(r'参会人员|出席人员|列席人员|参加会议', flat))
        ev['has_attend'] = has_attend
        n_topics = len(re.findall(r'议题|关于[^，。]{2,20}(?:的)?(?:事宜|工作|报告|请示)', flat))
        ev['n_topics'] = n_topics
        has_verdict = bool(re.search(
            r'会议(?:通过|决定|同意|研究|听取|原则通过|审议)|研究决定|议定事项|未通过', flat))
        ev['has_verdict'] = has_verdict
        s_struct = ((20 if has_call else 0) + (20 if has_attend else 0)
                    + (20 if n_topics >= 2 else 0) + (40 if has_verdict else 0))
    else:
        s_struct = layer
        s_struct += 20 if len(ls) >= 3 else 0
        s_struct += 20 if outline_n >= 2 else 0
        tail3 = [x for x in ls[-3:] if x.strip()]
        signed = any(DATE_END.search(x) or AGENCY_END.search(x) for x in tail3)
        ev['signed'] = signed
        s_struct += 20 if signed else 0
    s_struct = min(100, s_struct)

    # ---------- 洁净 ----------
    s_clean = max(0, round(40 * (1 - min(boiler / 0.15, 1))))
    ev['boiler'] = round(boiler, 4)
    s_clean += 0 if ENTITY_RE.search(body) or ZW_RE.search(body) else 30
    ev['has_zw'] = bool(ZW_RE.search(body))
    n_url = len(URL_RE.findall(body))
    ev['urls'] = n_url
    s_clean += 15 if n_url == 0 else (8 if n_url <= 2 else 0)
    s_clean += 15 if cjk >= 0.6 else (8 if cjk >= MIN_CJK_RATIO else 0)
    s_clean = min(100, s_clean)

    # ---------- 格式 ----------
    ascii_q = len(re.findall(r'["\']', body))
    cn_q = len(re.findall(r'[“”‘’]', body))
    ev['ascii_quote'] = ascii_q
    ev['cn_quote'] = cn_q
    s_fmt = 40 if (cn_q >= ascii_q or cn_q == 0) else max(0, 40 - (ascii_q - cn_q))
    half = len(re.findall(r'[a-zA-Z0-9\u4e00-\u9fff][,;:!?][\u4e00-\u9fff]', body))
    ev['half_punct'] = half
    s_fmt += 30 if half == 0 else (15 if half <= 3 else 0)
    sp = len(re.findall(r'[^\s]  +[^\s]', body)) + len(BAD_RE.findall(body))
    ev['odd_space'] = sp
    s_fmt += 30 if sp == 0 else (15 if sp <= 2 else 0)
    s_fmt = min(100, s_fmt)

    return veto, {'结构': s_struct, '洁净': s_clean, '格式': s_fmt}, ev


def effective_type(dt, title):
    """按**内容实况**推定文种（只做有把握的一处修正）

    依据（2026-09-17 第 2 步实证）：池子 `doc_type` 来自采集栏目名，约 18–30% 与内容不符；
    其中最一致可辨的一类是「type=调研报告，标题却是『××赴××调研/视察/督导』」——
    那是**调研动态（消息体）**，不是调研报告。用调研报告的长度下限（700 字）与结构判据
    去卡它必然判错（实测 37 条 too_short 多属此类，而 LLM 把它们判成 B/A）。
    """
    if (dt or '').strip() == '调研报告' and DYN_TITLE.search(title or ''):
        return '消息'
    return dt


def is_non_article(title, ls, heads):
    """是否**非文章页**（首页/栏目页/专题页）——v2 新增

    依据（2026-09-17 第 2 步对比）：规则层 15 条盲区几乎全是这类页
    （《省退役军人事务厅》＝厅网站首页、《市本级取消调整证明事情清单》＝126 项清单、
    《优化营商环境政策集成》＝专题链接拼盘），它们字数够、样板占比也不高，老判据一概拦不住。
    两条判据（任一命中即判）：
      · 标题 ≤14 字且不含任何公文/叙事词**且正文 <3000 字** → 标题只是机构名/栏目名，正文也没内容；
      · 行数 ≥20 但**平均每行 <20 字**且无小标题 → 导航/清单式列表（真公文每段远长于此）。
    ⚠️ 第一次写这条时漏了"正文也短"这个条件，实测**误杀 216 篇**——其中
    200 多篇标题抽取失败只剩年份（《2019》《2018》…），正文是 1.8–2.1 万字的政府工作报告，
    恰恰是最值钱的一批。故：**纯数字标题直接排除在本判据之外**（那是标题抽取问题，不是页面类型问题），
    且"标题光秃"必须叠加"正文短"才成立。
    """
    t = (title or '').strip('· \u3000\t')
    n = sum(len(x) for x in ls)
    # `heads == 0` 也是必要条件：实测《国家自然资源督察西安局》标题光秃、正文 2 千余字，
    # 但内容是**机构职责规定**（第一条/第二条…，heads>0）——有层次就不是导航页。
    if (t and not t.isdigit() and len(t) <= 14 and heads == 0
            and not ARTICLE_WORDS.search(t) and n < 3000):
        return 'title_bare'
    if len(ls) >= 20 and heads == 0 and n / max(len(ls), 1) < 20:
        return 'nav_list'
    return None


def main():
    ap = argparse.ArgumentParser(description='确定性判据层（零 LLM）')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--anchor-check', action='store_true', help='与 tier 锚点对账')
    ap.add_argument('--no-snapshot', action='store_true')
    ap.add_argument('--keep', type=int, default=1)
    a = ap.parse_args()

    con = sqlite3.connect(DB)
    con.execute('PRAGMA journal_mode=WAL')
    if not con.execute("SELECT name FROM sqlite_master WHERE type='table'"
                       " AND name='quality_det'").fetchone():
        print('缺 quality_det 表。DDL 是生成物，请先：'
              'python datahub/schema/gen_ddl.py --samples（并按三同步铁律同步注册表）')
        con.close()
        return 2

    if a.report or a.anchor_check:
        rows = con.execute(
            "SELECT d.url, d.verdict, d.evidence_json, s.doc_type"
            " FROM quality_det d LEFT JOIN samples s ON s.url = d.url"
            " WHERE d.rule_ver = ?", (RULE_VER,)).fetchall()
        print(f'确定性层（rule_ver={RULE_VER}）已标 {len(rows):,} 篇')
        vl = Counter()
        n_c = 0
        for _u, verdict, pj, _dt in rows:
            if verdict == 'C':
                n_c += 1
                try:
                    for v in (json.loads(pj or '{}').get('veto') or []):
                        vl[v] += 1
                except Exception:
                    pass
        if n_c:
            print(f'  判 C（一票否决）{n_c:,} 篇（{n_c*100//max(len(rows),1)}%）')
            for k, v in vl.most_common(12):
                print(f'     {k:18s} {v:,}')
        if a.anchor_check:
            anc = con.execute(
                "SELECT r.url, r.tier, s.title FROM review_state r"
                " LEFT JOIN samples s ON s.url=r.url"
                " WHERE r.review_kind='tier'").fetchall()
            det = {u: v for u, v, _p, _d in rows}
            killed = [(u, t, ti) for u, t, ti in anc if det.get(u) == 'C']
            print(f'\n锚点对账：tier 锚点 {len(anc)} 条 ｜ 被确定性层判 C 的 {len(killed)} 条'
                  f'（**应为 0**：误杀真 A/B 说明 veto 过严）')
            for u, t, ti in killed[:10]:
                print(f'     ✗ {t} 《{(ti or "")[:34]}》')
        con.close()
        return 0

    rows = con.execute(
        "SELECT url, doc_type, title, content, chars FROM samples"
        " WHERE dup_of IS NULL").fetchall()
    if a.limit:
        rows = rows[:a.limit]
    print(f'待评分（唯一篇）{len(rows):,}')

    out, dist, vcount = [], Counter(), Counter()
    q = 0
    for url, dt, title, content, chars in rows:
        rec = {'url': url, 'doc_type': dt, 'title': title,
               'content': content, 'chars': chars}
        ls, _meta = er.cleaned_lines(rec)
        boiler = er.score_boiler(ls)
        veto, dims, ev = score_one(rec, ls, boiler)
        tier = 'C' if veto else None
        if veto:
            vcount.update(veto)
        else:
            for k, v in dims.items():
                dist[f'{k}_{"高" if v >= 80 else ("中" if v >= 50 else "低")}'] += 1
        ev['veto'] = veto
        out.append(('det_20260917', url, dims, ('C' if veto else None),
                    ','.join(veto), ev))
        q += 1
        if q % 4000 == 0:
            print(f'  … {q}/{len(rows)}', flush=True)

    print(f'\n判 C（一票否决）{sum(1 for r in out if r[3] == "C"):,} 篇')
    for k, v in vcount.most_common(12):
        print(f'   {k:14s} {v:,}')
    print('\n三维分布（非 C 篇）：')
    for k, v in sorted(dist.items()):
        print(f'   {k:10s} {v:,}')

    if a.dry_run:
        print('\n--dry-run：未写库。')
        con.close()
        return 0

    snap.take(DB, keep=a.keep)
    scored_at = datetime.datetime.now().isoformat(timespec='seconds')
    try:
        con.execute('BEGIN')
        con.executemany(
            'INSERT OR REPLACE INTO quality_det'
            '(url,rule_ver,struct,clean,fmt,verdict,veto,evidence_json,'
            ' batch_id,scored_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
            [(u, RULE_VER, d['结构'], d['洁净'], d['格式'], v, vt,
              json.dumps(ev, ensure_ascii=False), b, scored_at)
             for b, u, d, v, vt, ev in out])
        con.execute('COMMIT')
    except Exception as e:
        con.execute('ROLLBACK')
        print('写库失败，已回滚:', type(e).__name__, e)
        con.close()
        return 1
    n = con.execute('SELECT count(*) FROM quality_det WHERE rule_ver=?',
                    (RULE_VER,)).fetchone()[0]
    print(f'\n已落 quality_det：rule_ver={RULE_VER} 共 {n:,} 条')
    con.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
