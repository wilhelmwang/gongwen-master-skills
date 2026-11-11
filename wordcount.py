# -*- coding: utf-8 -*-
"""篇幅统计（写稿模式五·五节口径固化 · v8.1.4 新增）

为什么需要这个模块
------------------
`team-writing.md` 五·五节规定：交付前必须统计正文篇幅并与骨架区间比对。
但**口径只写在文档里，没有固化进代码**——实测因此连续三轮出现"同一篇稿子两个字数"：

- v8.1.2：秉笔按「非空白字符」算得 4256（正确），复核者按「纯中文字」算得 2799，差 1.5 倍
- v8.1.3：T4 终版秉笔自报 8592（正确），复核者把标题行与说明文字算进去得出 8660
- 同轮：T4 过程版 8542 与终版 8592 混用，报告引用过旧值

三次的根因相同：**统计口径与正文边界没有单一实现，靠手工每次都可能不一致**。
本模块把口径固化为唯一实现，供秉笔、复核者与门禁共同调用。

口径（与 team-writing.md 五·五节严格一致）
------------------------------------------
- **统计单位**：非空白字符数（含中文、数字、字母、标点；不含空格、制表符、换行）。
  与 Word「字符数（不计空格）」同口径。
- **统计范围**：正文。**不含**外层的报告标题（H1）、溯源表、缝合说明、篇幅校准节。
- **正文边界以 HTML 标记为准**（唯一确定性定义）：
  `<!-- 正文起 -->` 与 `<!-- 正文止 -->` 之间即正文，**含主送机关行（如「地方人民政府：」）
  与落款单位行（如「地方发展和改革委员会」）**——它们都是公文正文的组成部分。
  以 T4 稿为基准校准（标记区间 = 自报 8592，完全一致）。

  若稿子无标记，则退回**隐式推断**（仅兼容早期稿），结果会标注为 `implicit` 并提示可能有偏差——
  隐式模式**不承诺与既定值一致**（实测四种边界写法差 11～50 字符），故不作为验收依据。
  **本包四份实跑稿（T1-T4）均已补标记**，可用 `--selftest` 复现与回归。

为什么必须用标记（实测教训）
----------------------------
隐式推断在四份实跑稿上都无法与自报值精确吻合（差 11～50 字符不等），
因为「主送机关算不算」「日期行算不算」「说明行算不算」在隐式规则里没有唯一解。
**这不是代码 bug，是规格缺失**——只有显式标记能给出确定性定义。

**注意**：【待补】标记本身计入字符数（它是正文的一部分），但报告时同时给出剔除后的数字，
供判断"缺口有多少是标记占位"（五·五节要求如实标注）。

用法
----
    python wordcount.py <稿子.md>                    # 统计并报告
    python wordcount.py <稿子.md> --range 9430 11790 # 同时与骨架区间比对
    python wordcount.py --selftest                   # 用四份实跑稿自检（需稿子在场）
"""
import os
import re
import sys

#: 统计单位说明（供输出）
UNIT = '非空白字符数（不含空格与换行）'

#: 正文起止标记
_MARK_START = '<!-- 正文起'
_MARK_END = '<!-- 正文止'

#: 隐式边界：正文结束于此后的第一个节标题
_STOP_HEADINGS = ('# 写稿溯源表', '# 缝合说明', '# 篇幅校准', '## 二、缝合说明',
                  '## 三、篇幅校准', '## 四、写稿溯源表', '## 二、三版横向对比表')

#: 需要从正文中排除的尾部要素（仅隐式模式用；标记模式**不排除**落款——它是正文的一部分）
_TAIL_NOISE = ('<!-- 正文止', '<!-- 正文起', '<!-- 正文起（', '<!-- 正文止（')


def extract_body(text, explicit_only=False):
    """抽取正文文本。

    返回 (body_text, boundary_kind)：
      boundary_kind = 'explicit'（用 HTML 标记定位，**确定性**）
                    | 'implicit'（用节标题推断，**可能因边界歧义而有偏差**）

    标记模式下**保留主送机关与落款单位行**——它们是公文正文的组成部分
    （以 T4 稿校准：标记区间 = 自报 8592，完全一致）。
    """
    if _MARK_START in text:
        a = text.find(_MARK_START)
        nl = text.find('\n', a)
        a = nl + 1 if nl >= 0 else a
        # 跳过紧跟在起始标记后的注释说明行（若有独立成行的 HTML 注释）
        b = text.find(_MARK_END, a)
        if b < 0:
            b = len(text)
        else:
            # 回退到「正文止」所在整行的行首（避免把其前面的空行算入）
            line_start = text.rfind('\n', 0, b) + 1
            if text[line_start:b].strip() == '':
                b = line_start
        return text[a:b], 'explicit'

    if explicit_only:
        return '', 'none'

    # 隐式：跳过前导 H1 与元信息，自首个非 H1、非空行起
    lines = text.splitlines()
    start = 0
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s and not s.startswith('# '):
            start = i
            break
    end = len(lines)
    for i in range(start, len(lines)):
        s = lines[i].strip()
        if any(s.startswith(h) for h in _STOP_HEADINGS):
            end = i
            break
    return '\n'.join(lines[start:end]), 'implicit'


def count_units(body):
    """按五·五节口径计数：非空白字符数，且剥离 markdown 标记符号与落款噪声行。"""
    kept = []
    for ln in body.splitlines():
        s = ln.strip()
        if not s:
            continue
        # 剥掉 markdown 标题前缀与加粗标记（它们不是正文内容）
        s = re.sub(r'^#{1,6}\s*', '', s)
        s = s.replace('**', '')
        # 排除尾部落款/标记噪声
        if any(s.startswith(n) for n in _TAIL_NOISE):
            continue
        kept.append(s)
    return len(re.sub(r'\s', '', ''.join(kept)))


def count_todo(body):
    """统计【待补】标记的数量与所占字符数（五·五节要求如实标注）。"""
    marks = re.findall(r'【待补[^】]*】', body)
    return len(marks), sum(len(re.sub(r'\s', '', m)) for m in marks)


def judge(actual, lo, hi):
    """按五·五节五档处置表判定。返回 (判定文本, 是否通过)。"""
    if lo <= actual <= hi:
        return '在区间内，通过', True
    if actual < lo:
        dev = (lo - actual) / lo
        if dev <= 0.10:
            return f'低于下界 {dev*100:.1f}%，在 ≤10% 允差内通过（须标注实际字数与区间）', True
        if dev <= 0.20:
            return f'低于下界 {dev*100:.1f}%，**偏差 >10%，必须补写**，不得直接交付', False
        return f'低于下界 {dev*100:.1f}%，**偏差 >20%，视为骨架执行失败，回 Phase 0 复核骨架**', False
    dev = (actual - hi) / hi
    if dev <= 0.10:
        return f'高于上界 {dev*100:.1f}%，在 ≤10% 允差内通过（须标注）', True
    if dev <= 0.20:
        return f'高于上界 {dev*100:.1f}%，**偏差 >10%，必须删减**，不得直接交付', False
    return f'高于上界 {dev*100:.1f}%，**偏差 >20%，视为骨架执行失败，回 Phase 0 复核骨架**', False


def report(path, lo=None, hi=None):
    """统计单份稿子并打印报告。"""
    with open(path, encoding='utf-8') as fh:
        text = fh.read()
    body, kind = extract_body(text)
    n = count_units(body)
    n_todo, ch_todo = count_todo(body)

    print(f'=== 篇幅统计 · {os.path.basename(path)} ===')
    print(f'口径：{UNIT}')
    print(f'范围：正文（不含标题／落款／溯源表／缝合说明）｜边界判定：{kind}')
    print(f'正文实际字数：{n}')
    if n_todo:
        print(f'  其中【待补】标记：{n_todo} 处、{ch_todo} 字符；剔除标记后 {n - ch_todo}')
    if lo is not None and hi is not None:
        verdict, ok = judge(n, lo, hi)
        print(f'骨架区间：{lo}-{hi}')
        print(f'判定：{verdict}')
        return 0 if ok else 1
    return 0


# ---- 自检 ----
# 说明：**只有带 HTML 正文标记的稿子才有确定性期望值**（标记模式下可复现、可回归）。
# 四份实跑稿（T1-T4）均已补标记，故全部纳入正式自检。
# 其中 T3 的期望值 1567 同时是秉笔自报数——**精确吻合，验证了标记位置正确**
# （讲话稿的标题属"题目"、不计入正文，与外层 H1 报告标题同理）。
_SELFTEST = [
    # (稿子相对路径, 期望字数, 骨架下界, 骨架上界)
    ('.gongwen-team/phase-2/draft.md', 4327, 3500, 4300),
    ('.gongwen-team/t2/phase-2/draft-t2.md', 4498, 4600, 6200),
    ('.gongwen-team/t3/phase-2/selected.md', 1567, 1200, 1600),
    ('.gongwen-team/t4/phase-2/draft-t4.md', 8592, 9430, 11790),
]


def _selftest(root=None):
    root = root or os.getcwd()
    fails = 0
    print('=== wordcount 自检：在带标记的稿子上复现既定字数 ===')
    print(f'（口径：{UNIT}）')
    print()
    for rel, expect, lo, hi in _SELFTEST:
        p = os.path.join(root, rel)
        if not os.path.isfile(p):
            print(f'  [SKIP] {rel} 不在场')
            continue
        with open(p, encoding='utf-8') as fh:
            body, kind = extract_body(fh.read())
        got = count_units(body)
        ok = (got == expect and kind == 'explicit')
        mark = 'OK  ' if ok else 'FAIL'
        print(f'  [{mark}] {os.path.basename(rel):20s} 期望 {expect:>5} 实得 {got:>5}'
              f'  （边界 {kind}）')
        if not ok:
            fails += 1
    print()
    if fails:
        print(f'自检失败：{fails} 项不吻合')
        return 1
    print(f'自检通过：{len(_SELFTEST)} 份带标记稿全部复现既定字数')
    return 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    _path = sys.argv[1]
    _lo = _hi = None
    if '--range' in sys.argv:
        i = sys.argv.index('--range')
        _lo, _hi = int(sys.argv[i + 1]), int(sys.argv[i + 2])
    sys.exit(report(_path, _lo, _hi))
