# -*- coding: utf-8 -*-
"""公文成稿参数自检器（param-check v1.0.0）

用途
----
写完一稿后，量一遍它的**数值特征**，与「参照画像」对照，只判**硬冲突**。

它不是评分器，也不判好坏。它回答三个问题：
  1. 我这稿的客观数值是多少（句长、顿号密度、力度词、层级、重心分布）？
  2. 哪些偏离是**硬冲突**（文种识别错误级，必须改）？
  3. 哪些偏离只是**与画像不同**（合法变体，可以保留，但要在稿件说明里写清）？

设计纪律（详见 ../../govdoc-corpus/references/param-guardrails.md）
--------------------------------------------------
· **只判硬冲突**。同文种内部离散度大于文种间差异，「好文章不整齐」。软项只报不判。
· **没有参照画像就不判硬冲突**。本机不内置任何语料数值——内置数字若来自
  不可分发的语料，第三方无法复核，那样出来的「合格线」是没有依据的。
  没有 `--ref` 时本脚本只输出实测值 + **与语料无关的结构性硬冲突**。
· **参照画像必须能复算**。`--ref` 只接受**本机用 `govdoc-corpus` 从自己的语料算出的**
  画像（JSON，schema 见 `--ref-template`）。别把外部工程的数值当标准。
· **词表统计先剔引号内内容**。否则自造概念（「需求分类里『必须改』『可以缓』」）
  会把力度词配额顶破。

三类数据结构（复用本包已有能力，不重复造）
------------------------------------------
· 数值指标   ← 本脚本 `analyze()`（纯统计，可复算）
· 重心分布   ← 本脚本 `section_weights()`（按一级标题切分，看是否单段独大）
· 质量与合规 ← 走 `references/govdoc-qc/scripts/quality_check.py` 与 `consistency_checker.py`
· AI 味      ← 走 `scripts/ai_flavor_detector.py`
本脚本只补「参数与重心」这一层，**不重复质检**。

用法
----
  python param_check.py 成稿.md                          # 只出实测值 + 结构硬冲突
  python param_check.py 成稿.md --ref 画像.json --genre 调研报告
  python param_check.py 成稿.md --ref 画像.json --match   # 不确定文种：列出与各文种的距离排序
  python param_check.py --ref-template                    # 打印画像 schema 示例
"""
import argparse
import json
import math
import os
import re
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

#: 计入距离的指标键（顺序即报告顺序）
KEYS = ['chars', 'sent', 'h1', 'h2', 'h3', 'yishi', 'dun', 'qz', 'yq', 'jy', 'pct', 'quote_long']

#: 中文字段名（报告用）
LABEL = {
    'chars': '字数', 'sent': '平均句长', 'h1': '一级标题', 'h2': '二级标题',
    'h3': '三级标题', 'yishi': '一是二是', 'dun': '顿号‰', 'qz': '强制词‰',
    'yq': '要求词‰', 'jy': '建议词‰', 'pct': '百分比', 'quote_long': '长引语‰',
}

#: 免参数文种：正文由制度锁定，是固定填空而非写作技法，统计参数对它没有意义
NO_PARAM = ('报告', '通知', '请示', '批复', '函', '决定', '条例', '规定', '意见', '通报', '纪要',
            '复函', '命令', '公告', '通告', '公报')

#: 避坑词（写法层面，与语料无关）
BAD_WORDS = {
    '我觉得': '改为「经研究」或直接陈述',
    '我认为': '改为「经研判」或直接陈述',
    '非常': '公文中少用程度副词，改具体程度',
    '取得了显著成效': '改具体成效与数据',
    '希望领导重视': '改为明确请求事项或请示口径',
    '问题很多': '改为分类列问题',
    '尽快': '改为明确时限',
    '相关部门': '改为具体部门名',
}

#: 元评论词（与引号剔除配合使用）
META_WORDS = re.compile(r'其实[是就]|说到底|归根到底|本质上')

#: 序次层级（与 docgen_export/mdparse.para_kind 同口径，避免两处正则漂移）
_NUM1 = re.compile(r'^\**\s*([一二三四五六七八九十百千]+)、')
_NUM2 = re.compile(r'^\**\s*（\s*[一二三四五六七八九十百千]+\s*）')
_NUM3 = re.compile(r'^\**\s*\d+[．.]\s*\D')      # \D 排除「1.5 倍」这类小数
_NUM4 = re.compile(r'^\**\s*（\s*\d+\s*）')
_ORD = '一二三四五六七八九'


# ---------- 文本提取与指标统计 ----------

def body_lines(text):
    """取正文行：剥 Markdown 标题标记但**保留标题文字**，跳过表格/分隔线/引用行。"""
    out = []
    for raw in text.split('\n'):
        ln = raw.rstrip()
        if not ln.strip():
            continue
        if re.match(r'^\s*(\||-{3,}|>|```)', ln):
            continue
        out.append(re.sub(r'^\s*#{1,6}\s*', '', ln))
    return out


def analyze(text):
    """量一稿的数值特征。所有计数都在**剔除引号内内容**之后做。"""
    lines = body_lines(text)
    plain = '\n'.join(lines)
    chars = len(re.sub(r'\s', '', plain))

    sents = [s for s in re.split(r'[。！？；]', plain) if len(s) >= 4]
    sent = round(sum(len(s) for s in sents) / len(sents), 1) if sents else 0.0

    h1 = [ln for ln in lines if _NUM1.match(ln)]
    h2 = [ln for ln in lines if _NUM2.match(ln)]
    h3 = [ln for ln in lines if _NUM3.match(ln)]
    h4 = [ln for ln in lines if _NUM4.match(ln)]

    # 占比类指标的分母：剔除引号内内容，避免自造概念顶破配额
    depunct = re.sub(r'[“"][^”"]{0,20}[”"]', '', plain)
    # 「不得不」是「只能」义，不是禁止义，须从「不得」里排除
    qz_text = depunct.replace('不得不', '\u3000\u3000\u3000')
    per_k = 1000.0 / max(1, chars)
    qz = round(per_k * sum(qz_text.count(w) for w in ('应当', '必须', '不得', '严禁')), 2)
    yq = round(per_k * sum(depunct.count(w) for w in ('要', '切实', '确保', '务必')), 2)
    jy = round(per_k * sum(depunct.count(w) for w in ('建议', '可以', '鼓励', '支持')), 2)
    dun = round(per_k * plain.count('、'), 1)
    yishi = len(re.findall(r'[%s]是[，、]?' % _ORD, plain))

    # 百分比：先剔占位符——占位符里的 % 不是真实数据
    pct = len(re.findall(r'\d+(?:\.\d+)?%', re.sub(r'【[^】]*】', '', plain)))
    # 长引语只认中文弯引号：ASCII 直角引号无法配对，会把两引号之间的正文误判为引语
    quote_long = round(per_k * len(re.findall(r'[“][^”]{9,}[”]', plain)), 1)
    dash = plain.count('——')

    return {
        'chars': chars, 'sent': sent, 'h1': len(h1), 'h2': len(h2), 'h3': len(h3),
        'h4': len(h4), 'yishi': yishi, 'dun': dun, 'qz': qz, 'yq': yq, 'jy': jy,
        'pct': pct, 'quote_long': quote_long, 'dash': dash,
        'h1_titles': [_h1_title(ln) for ln in h1],
        'lines': lines,
    }


def _h1_title(ln):
    """一级标题取标题正文（去掉序数、切到首个句读、截断 40 字）。"""
    t = _NUM1.sub('', ln).strip()
    t = re.split(r'[。；，、]|\s{2,}', t)[0]
    return t[:40]


def section_weights(lines):
    """按一级标题切分，算各段占正文字数的比重。

    为什么单列这一项：重心分布是区分「单段独大型」与「均衡型」的关键——
    参数可以全部达标而文种写错了。个体离散度大，**区间外不作为错误**。
    """
    idx = [i for i, ln in enumerate(lines) if _NUM1.match(ln)]
    if not idx:
        return []
    segs = []
    head = lines[:idx[0]]
    if head:
        segs.append(('导语', sum(len(re.sub(r'\s', '', x)) for x in head)))
    for n, i in enumerate(idx):
        j = idx[n + 1] if n + 1 < len(idx) else len(lines)
        body = lines[i + 1:j]
        segs.append((_h1_title(lines[i]) or f'第{n + 1}节',
                     sum(len(re.sub(r'\s', '', x)) for x in body)))
    tot = sum(n for _k, n in segs) or 1
    return [(k, n, round(100.0 * n / tot, 1)) for k, n in segs]


# ---------- 硬冲突：与语料无关的结构性判据 ----------

# ---------- 分层装置（与语料无关的结构判定）----------

_LEAD_TAIL = re.compile(r'^(.{6,26})。(.+)$')
#: 以序数起首的短句（一是/二是/一、/（一）/1.）不算「段首提领句」——它已属序数装置，
#: 否则同一处会被双重计数，报出虚假的「混用」
_NUM_LEAD = re.compile(r'^\**\s*(?:[一二三四五六七八九十百千]+[、是]|（[一二三四五六七八九十百千]+）|\d+[．.])')


def layer_devices(a, lines):
    """判千字材料用的是哪套分层装置：段首提领句 / 独立小标题段 / 「一是二是」。

    为何单成一类：篇幅决定装置——"一、（一）"骨架与段首提领句是**两套写法**，
    混用了就成夹生件。此项不依赖任何外部数值（不用占比当合格线），只报"实际用了哪几类"、
    "有几处"、"是否混用"。
    """
    paras = [ln for ln in lines if ln.strip() and not _NUM1.match(ln)]
    leads, subs = [], []
    for i, ln in enumerate(paras):
        t = ln.strip()
        nxt = paras[i + 1].strip() if i + 1 < len(paras) else ''
        m = _LEAD_TAIL.match(t)
        # 提领句：短句＋句号，**且句号后真有正文**（否则那是标题或首句短段）
        if (m and 8 <= len(m.group(1)) <= 26 and len(t) - len(m.group(1)) >= 20
                and not _NUM_LEAD.match(m.group(1))):
            leads.append(m.group(1))
        # 独立小标题段：无句号短段，**且不是首行（首行是篇名）、下一段有实质正文**
        elif (i > 0 and 4 <= len(t) <= 30
              and not t.endswith(('。', '；', '！', '？')) and len(nxt) >= 40):
            subs.append(t)
    devices = []
    if leads:
        devices.append(f'疑似提领句 {len(leads)} 处')
    if subs:
        devices.append(f'独立小标题段 {len(subs)} 处')
    if a.get('yishi'):
        devices.append(f'「一是二是」 {a["yishi"]} 处')
    # 只对「一是二是」与提领句/小标题段共存报警：据外部语料，提领句与小标题段是**同一构件**，
    # 二者共存只是排版选择（两者兼用占 17%），不是缺陷；真正互斥的是「一是二是」与提领句。
    warn = None
    ordinal = bool(a.get('yishi'))
    clause = bool(leads or subs)
    if ordinal and clause:
        warn = ('「一是二是」与提领句/小标题段同时出现——两者基本互斥：'
                '千字级材料用提领句（或独立小标题段）就不用「一是二是」')
    return devices, warn


def structural_conflicts(a, lines):
    """结构级硬冲突。这些不依赖任何语料统计，故无画像时也能判。"""
    out = []
    # 占位符残留：发出去就是事故
    ph = re.findall(r'【[^】]*】|X{2,}|待补|待填|〔YYYY〕|\bTODO\b', '\n'.join(lines))
    if ph:
        out.append((f'占位符残留 {len(ph)} 处', f'样例：{ph[:3]}',
                    '成稿不得含占位符；改前须逐项落实或明确标为待填并告知用户'))

    # 层级跳级：有二级无一级，或先出现三级后出现一级
    if a['h2'] and not a['h1']:
        out.append(('有二级标题但无一级标题', f"h2={a['h2']} h1=0",
                    '层级必须连续；先补一级标题或把二级标题降为正文分层'))
    first = {}
    for i, ln in enumerate(lines):
        for lv, pat in (('h1', _NUM1), ('h2', _NUM2), ('h3', _NUM3)):
            if pat.match(ln) and lv not in first:
                first[lv] = i
    if 'h3' in first and 'h1' in first and first['h3'] < first['h1']:
        out.append(('三级标题出现在一级标题之前', f"h3@{first['h3']} 早于 h1@{first['h1']}",
                    '层级必须自外向内；重排或降级'))

    # 段内序次跳号：一、二、四 —— 说明漏写或合并了段
    # 只在**全部序数都是单字**时判（含「十」「十一」的多字序数一律跳过，宁可漏报不可误报）
    nums = [_NUM1.match(ln) for ln in lines if _NUM1.match(ln)]
    if len(nums) >= 2:
        got = [_ORD.find(mm.group(1)) if len(mm.group(1)) == 1 else -1 for mm in nums]
        if all(s >= 0 for s in got) and got != list(range(got[0], got[0] + len(got))):
            out.append((f'一级序号不连续：{["一二三四五六七八九"[s] for s in got]}',
                        '序数对应绝对位置', '缺号通常是漏写了一段，检查是否合并或漏排'))
    return out


# ---------- 与画像的对照 ----------

def _ref_ok(ref):
    """画像必须能被本机复算：检查 schema 完整性与来源声明。"""
    missing = []
    if not isinstance(ref, dict) or 'genres' not in ref:
        missing.append('顶层需为 {"source": ..., "genres": {...}}')
    else:
        if not ref.get('source'):
            missing.append('缺 source 字段（画像来源，须写明由哪份语料、哪个脚本算出）')
        for g, d in ref.get('genres', {}).items():
            if not isinstance(d, dict) or 'n' not in d:
                missing.append(f'{g}: 缺样本量 n（无 n 无法判断是否具备参考价值）')
                continue
            for k in KEYS:
                v = d.get(k)
                if v is None:
                    continue
                if not (isinstance(v, dict) and 'mid' in v and 'lo' in v and 'hi' in v):
                    missing.append(f'{g}.{k}: 需为 {{lo, hi, mid}}')
    return missing


def adequacy(n):
    """样本充足度评级。**评级不足时不得把画像当依据。**"""
    if n >= 30:
        return '充足', '可作对照依据'
    if n >= 8:
        return '一般', '趋势可参考；单点偏离不宜作为硬依据'
    if n >= 3:
        return '偏薄', '仅作线索；不要据此改稿'
    return '不足', '不足以作为依据'


def distance(a, d):
    """到某文种画像的归一化距离。尺度取 max(四分位间距, 中位×0.3, 1)，避免小量纲项主导。"""
    tot = 0.0
    for k in KEYS:
        v = d.get(k)
        if not v:
            continue
        scale = max(v['hi'] - v['lo'], abs(v['mid']) * 0.3, 1)
        tot += abs(a.get(k, 0) - v['mid']) / scale
    return round(tot, 3)


def bar(val, lo, hi, slots=10):
    """位置示意条：区间内打点，区间外给箭头。"""
    span = max(1e-9, hi - lo)
    pos = (val - lo) / span
    if pos < -0.15:
        return '←低'
    if pos > 1.15:
        return '高→'
    slot = int(round(max(0.0, min(1.0, pos)) * (slots - 1)))
    return '·' * slot + '●' + '·' * (slots - 1 - slot)


def render(a, ref, genre, verbose=True):
    """出报告。返回 (硬冲突条数, 文本行列表)。"""
    L = []
    d = ref['genres'].get(genre, {}) if ref else {}
    n = d.get('n', 0)
    fails = 0

    L.append(f'=== 公文成稿参数自检 ===')
    L.append(f'  文体：{genre}' + (f'   画像样本 n={n}' if n else '   （无画像）'))
    if n:
        lvl, why = adequacy(n)
        L.append(f'  样本充足度：{lvl} —— {why}')
    L.append('')

    # 1 结构硬冲突（与语料无关）
    sc = structural_conflicts(a, a['lines'])
    L.append('【硬冲突 · 结构性（不依赖语料）】')
    if sc:
        for name, detail, fix in sc:
            L.append(f'  ✗ {name}')
            L.append(f'      实测 {detail}')
            L.append(f'      处置 {fix}')
            fails += 1
    else:
        L.append('  ✓ 通过（占位符 / 层级连续性 / 序号连续性）')
    L.append('')

    # 2 画像硬冲突（画像显式标 hard 的项才判）
    hard = [(k, v) for k, v in d.items() if isinstance(v, dict) and v.get('hard')]
    if hard:
        L.append('【硬冲突 · 按本机画像标注】')
        for k, v in hard:
            val = a.get(k)
            ok = v['lo'] <= val <= v['hi']
            L.append(f'  {"✓" if ok else "✗"} {LABEL.get(k, k)} 实测 {val}  画像 {v["mid"]}（{v["lo"]}–{v["hi"]}）')
            if not ok:
                L.append(f'      依据 {v.get("basis", "画像中标注为硬项")}')
                fails += 1
        L.append('')

    # 3 参数对照（只报不判）
    if d:
        L.append('【参数对照（偏离不等于错误）】')
        L.append(f'  {"指标":<12}{"你的":>8}{"中位":>8}{"常见区间":>14}   位置示意')
        for k in KEYS:
            v = d.get(k)
            if not v:
                continue
            val = a.get(k, 0)
            outside = val < v['lo'] or val > v['hi']
            flag = '  ⚠' if outside else ''
            L.append(f'  {LABEL.get(k, k):<12}{val:>8}{v["mid"]:>8}'
                     f'{str(v["lo"]) + "–" + str(v["hi"]):>14}   '
                     f'{bar(val, v["lo"], v["hi"])}{flag}')
        L.append('  （偏离方向连续多项一致时，说明整体节奏不对；单项偏离先问「我这一项'
                 '偏离是因为写进了什么」，答得出来就留着）')
        L.append('')

    # 4 重心分布
    sw = section_weights(a['lines'])
    if sw:
        L.append('【重心分布】')
        for name, cnt, pct in sw:
            mark = '  ←最重' if pct == max(x[2] for x in sw) else ''
            L.append(f'  {name[:24]:<26}{cnt:>6} 字  {pct:>5}%{mark}')
        L.append('  （个体离散度大，此项区间外不作为错误。单段独大 vs 均衡是文种信号）')
        L.append('')

    # 5 分层装置
    devices, dwarn = layer_devices(a, a['lines'])
    L.append('【分层装置】')
    if devices:
        L.append('  实际使用：' + ' ｜ '.join(devices))
    else:
        L.append('  实际使用：纯段落推进（未检出疑似提领句/独立小标题/「一是二是」）')
    if dwarn:
        L.append(f'  ⚠ {dwarn}')
    L.append('  （篇幅决定装置：1000–1200 字级宜用段首提领句或独立小标题段，'
             '不宜再套「一、（一）」骨架；两项计数为启发式，以「疑似」为准，供对照不作判定）')
    L.append('')

    # 6 标点与修辞
    L.append('【标点与修辞】')
    L.append(f'  正文破折号 {a["dash"]} 个（建议不超过 1 个；连用是 AI 痕迹）')
    if META_WORDS.search(re.sub(r'[“"][^”"]*[”"]', '', '\n'.join(a['lines']))):
        L.append('  ⚠ 检出元评论词（其实是/说到底/归根到底/本质上）—— 公文直陈，删')
    else:
        L.append('  未检出元评论词')
    L.append('')

    # 7 避坑词
    body = '\n'.join(a['lines'])
    hit = [(w, s) for w, s in BAD_WORDS.items() if w in body]
    if hit:
        L.append('【避坑词】')
        for w, s in hit:
            L.append(f'  ⚠ {w} → {s}')
        L.append('')

    # 8 力度词配额提示（力度词与要求词不是一回事）
    if d.get('qz'):
        v = d['qz']
        if a['qz'] > v['hi']:
            L.append(f'【力度词】强制词 {a["qz"]}‰ 高于画像 {v["hi"]}‰ —— '
                     f'一篇 {a["chars"]} 字的稿子通常 1–2 个即可；'
                     f'注意「要」属要求词、「必须/应当」属强制词，两者不是一回事')
            L.append('')

    L.append(f'  结果：硬冲突 {fails} 项')
    if not fails:
        L.append('  ✅ 无硬冲突。偏离项请结合稿件说明判断是有意还是疏漏。')
    L.append('  ℹ️  本脚本只判参数与重心，不判内容对错、不判合规。'
             '合规与一致性走 govdoc-qc，AI 味走 ai_flavor_detector.py。')
    return fails, L


REF_TEMPLATE = {
    "source": "本机语料：<目录> ｜ 脚本：govdoc-corpus/scripts/corpus_build.py ｜ 生成日期：YYYY-MM-DD",
    "genres": {
        "调研报告": {
            "n": 0,
            "chars": {"lo": 0, "hi": 0, "mid": 0, "hard": False},
            "sent": {"lo": 0, "hi": 0, "mid": 0},
            "dun": {"lo": 0, "hi": 0, "mid": 0},
            "qz": {"lo": 0, "hi": 0, "mid": 0, "hard": True,
                   "basis": "本机语料中标为硬项的依据（写清楚，否则不要标 hard）"},
            "_note": "lo/hi = p25/p75 或人工认定区间；mid = 中位数（不用均值）。"
                     "没有依据的项留空或删除，不要填占位数。"
        }
    },
}


def main():
    ap = argparse.ArgumentParser(
        description='公文成稿参数自检器（只判硬冲突；无画像时只出实测值）',
        add_help=False)
    ap.add_argument('file', nargs='?', help='成稿 .md 路径')
    ap.add_argument('-g', '--genre', default=None, help='文种（画像中的键名）')
    ap.add_argument('--ref', default=None, help='参照画像 JSON（本机自算；无则只出实测值）')
    ap.add_argument('--ref-template', action='store_true', help='打印画像 schema 示例后退出')
    ap.add_argument('--match', action='store_true', help='按距离排序所有文种')
    ap.add_argument('--list', action='store_true', help='列出画像中的文种')
    ap.add_argument('-h', '--help', action='store_true', help='显示本帮助')
    a = ap.parse_args()

    if a.help or (not a.file and not a.ref_template):
        print(__doc__)
        return 0 if a.help else 2

    if a.ref_template:
        print(json.dumps(REF_TEMPLATE, ensure_ascii=False, indent=2))
        print('\n把本文件保存为 ref.json，逐项填**本机语料实测**的中位数与四分位。', file=sys.stderr)
        print('没有依据的项留空或删除；标 hard 的项必须同时给 basis。', file=sys.stderr)
        return 0

    if not os.path.exists(a.file):
        print(f'文件不存在: {a.file}', file=sys.stderr)
        return 2
    if os.path.isdir(a.file):
        print(f'这是一个目录，不是文件: {a.file}', file=sys.stderr)
        return 2
    try:
        text = open(a.file, encoding='utf-8').read()
    except UnicodeDecodeError as e:
        print(f'按 UTF-8 读取失败（请转码后再查）: {e}', file=sys.stderr)
        return 2

    ref = None
    if a.ref:
        if not os.path.exists(a.ref):
            print(f'画像文件不存在: {a.ref}', file=sys.stderr)
            return 2
        try:
            ref = json.load(open(a.ref, encoding='utf-8'))
        except json.JSONDecodeError as e:
            print(f'画像不是合法 JSON: {e}', file=sys.stderr)
            return 2
        bad = _ref_ok(ref)
        if bad:
            print('画像 schema 不完整，**不判硬冲突**（避免拿不完整的画像当标准）:', file=sys.stderr)
            for m in bad:
                print(f'  - {m}', file=sys.stderr)
            ref = None

    m = analyze(text)

    if a.list:
        if not ref:
            print('未提供画像，无文种可列。', file=sys.stderr)
            return 2
        for g, d in ref['genres'].items():
            lvl, _why = adequacy(d.get('n', 0))
            print(f'  - {g}  n={d.get("n", 0)}  样本充足度 {lvl}')
        return 0

    if a.genre and a.genre in NO_PARAM:
        print(f'【说明】「{a.genre}」属于正文由制度锁定的文种（通知/请示/批复/函/决定/条例/'
              f'通报/纪要等），是固定填空而非写作技法，**统计参数对它没有意义**。')
        print('  这类稿子该做的是：① 对着本机 references/govdoc-layout/references/'
              'formal-checklist.md 逐项核版式 ② 参考真件样例照结构。')
        print('  本脚本仍会输出实测值与结构硬冲突（占位符、层级连续性等），供参考。')
        print()

    if a.match or not a.genre:
        target = a.genre or '（未指定）'
        if ref:
            ranked = sorted(((g, distance(m, d)) for g, d in ref['genres'].items()),
                            key=lambda x: x[1])
            print('=== 与各文种画像的距离（越小越近）===')
            for i, (g, dist) in enumerate(ranked):
                n = ref['genres'][g].get('n', 0)
                lvl, _ = adequacy(n)
                print(f'  {i + 1}. {g:<16} 距离 {dist:<7} n={n}（{lvl}）')
            print('  ⚠ 同族文种参数重叠大，Top1 准确率有限；跨族误配才是强信号。'
                  '不要只按排名改稿，要自己读一遍。\n')
            if not a.genre:
                target = ranked[0][0]
        else:
            print('=== 未提供画像：只出实测值 ===')
            print('  （本脚本不内置语料数值——内置数字若不可复核，合格线就没有依据）')
            print('  生成画像：govdoc-corpus/scripts/corpus_build.py 跑本机语料；'
                  'schema 见 --ref-template\n')
        fails, lines = render(m, ref, target)
    else:
        fails, lines = render(m, ref, a.genre)

    print('\n'.join(lines))

    # 实测值原样打印，便于写进稿件说明
    print()
    print('【实测值（供稿件说明引用）】')
    print('  ' + ' ｜ '.join(f'{LABEL[k]}={m[k]}' for k in KEYS))
    print(f'  四级标题={m["h4"]} ｜ 破折号={m["dash"]}')
    # 退出码：有硬冲突才非零（便于接入流水线）
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
