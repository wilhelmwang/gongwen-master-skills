# -*- coding: utf-8 -*-
"""路由引擎（唯一实现 · v7.3.2）

为什么单独成模块
----------------
路由判定此前只存在于 `rules_regression.py` 内。触发率评测（`trigger_eval.py`）也需要同一套
判定逻辑 —— 若各写一份，就会出现"同一请求在回归里通过、在触发评测里路由到别处"这种
本包已反复出现的双实现问题（参见 v7.3.1 修复的 4 套 frontmatter 解析）。
故把「解析 master SKILL.md 规则表 + 优先级裁决」收敛为本模块唯一实现。

判定模型
--------
规则 A–E 决定**路由到哪个技能**；规则 F 是**正交的模式开关**（是否升格团队模式），
不参与 `C > B > A > D > E` 优先级链。故 `route()` 返回基础路由，`is_team()` 独立判定。

关键词匹配为**子串匹配**（历史行为，保持兼容）；`trigger_eval` 用近义负例来暴露
子串匹配带来的误触发，而不是在这里擅自改成整词匹配（那会改变线上行为）。
"""
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
try:                                   # v8 双态：技能根经 skills_manifest 统一解析
    from skills_manifest import skill_md as _skill_md
    MASTER_SKILL = _skill_md('gongwen-master')
except Exception:
    MASTER_SKILL = os.path.join(BASE, 'gongwen-master', 'SKILL.md')

#: 优先级链（新手信号命中时 D 提前，见 route()）
PRI = ['C', 'B', 'A', 'D', 'E']

#: 新手信号词（含这些词时 D 优先于 A/B）
NEWBIE = ('新手', '不懂', '不会写', '第一次写', '不知道怎么写', '怎么开始',
          '帮我弄个材料', '写点东西', '教我用', '帮我选')

_RULE_NAMES = ['A', 'B', 'C', 'D', 'E', 'F']
_ENDS = ['#### 匹配优先级', '### Step 3', '## 意图解析', '## 成品交付',
         '## 会话驻留', '## 路由中枢', '## 角色定位']


def load_rules(path=MASTER_SKILL):
    """从 master SKILL.md 解析规则 A–F 的 (关键词表, 路由目标) 列表。

    区间终点取「下一个规则头（A–F 全量）」或任一章节锚的最小值 —— 早期实现只认 [A-E]，
    导致规则 E 的区间吞掉紧随其后的规则 F 表格。
    """
    text = open(path, encoding='utf-8').read()
    rules = {}
    for rname in _RULE_NAMES:
        start = text.find(f'#### 规则 {rname}：')
        if start < 0:
            rules[rname] = []
            continue
        # 边界须显式包含 C2：原 `[A-F](?!\w)` 要求 [A-F] 后不是词字符，
        # 而「规则 C2：」里 C 后面是数字「2」（词字符）→ 匹配失败 → **C 区间吞掉 C2 整张表**。
        # 后果：C 的词表里混入 C2 的全部关键词（实测 9 → 28 词），查询同时命中 C 与 C2。
        # 因优先级链 C2 先于 C，输出目标仍正确，故长期未暴露——属"结果对但构造错"的潜伏缺陷。
        cands = [m.start() for m in re.finditer(r'#### 规则 ([A-F])(?!\w)：', text)
                 if m.start() > start + 5]
        cands += [text.find(e, start + 5) for e in _ENDS]
        cands = [x for x in cands if x > start + 5]
        sec = text[start:min(cands)] if cands else text[start:]
        entries = []
        for kw, target in re.findall(r'\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|', sec):
            kw, target = kw.strip(), target.strip().replace('**', '')
            if not kw or not target or '——' in kw or ('(' in kw and '）' not in kw):
                continue
            if any(x in kw for x in ('关键词', '路由目标', '优先级说明', '同一请求', '新手信号')):
                continue
            # 表分隔行 |---|:---| 会被误当条目（关键词与目标都是横线），过滤掉
            if re.fullmatch(r'[\s:\-—]*', kw) or re.fullmatch(r'[\s:\-—]*', target):
                continue
            kws = [k.strip() for k in kw.split('、') if k.strip()]
            if kws:
                entries.append((kws, target))
        rules[rname] = entries
    return rules


#: 「对已有稿进行编辑」的判定（**派生自规则表，不手写清单**）：
#: 规则 E 命中的关键词，若其路由目标属于 polish/layout（而非 workflow/article-review），
#: 且不属于 layout 里的「流程设计」子类，即视为"编辑已有稿"的动作意图。
# v7.6.0：govdoc-corpus 是「接入/建库」类动作，不属于「对已有稿编辑」。
# 放进本表 → 它与文种词同现时按优先级链走 A（如「写份总结 参考我们单位公文库」
# 应路由 govdoc-summary 而非 corpus）。govdoc-material 则**保持**为编辑类动作——
# 「把这些材料写成通知」的真诉求是以稿写稿，E 应优先于 A。
_NON_EDIT_TARGETS = ('govdoc-workflow', 'article-review', 'govdoc-corpus')
_NON_EDIT_KEYWORDS = ('流程', '审批流程', '工作流程图')   # 同属 layout，但不是"编辑已有稿"

#: 非公文任务护栏：命中即判 NO-MATCH。
#: 动机（v7.3.2 触发率实测）：纯子串匹配会把"翻译/做成图表/PPT/英文版"类请求
#: 误路由到公文技能——用户要的是翻译或可视化，不是写公文。
#: 由 doc_code_check 的 C7 校验：护栏词不得与规则表关键词完全重合（防误屏蔽本包自身能力）。
NON_DOC_TASK = ('翻译', '译成', '英文版', '做成图表', '生成图表', '做成ppt', '做个ppt',
                '写代码', '写个脚本', '查一下报错', '调试代码',
                '这篇论文', '学术论文', '期刊论文', '毕业论文',
                '文献综述', '文献翻译')   # 学术场景 ≠ 公文场景（修 v7.3.2 实测 m04）
# 注：不可用裸词「论文」——它是规则关键词「理论文章」的子串（理**论文**章），
#     会把 theory 整个屏蔽。由 doc_code_check 的 C7 自动拦截这类误伤。

_RULES_CACHE = None


def rules():
    global _RULES_CACHE
    if _RULES_CACHE is None:
        _RULES_CACHE = load_rules()
    return _RULES_CACHE


def is_team(query, r=None):
    """规则 F：团队模式开关（正交于路由链）。命中返回 (关键词, 场景目标)，否则 None"""
    for kws, target in (r or rules()).get('F', []):
        for k in kws:
            if k in query:
                return k, target
    return None


def is_edit_action(kw, target):
    """该 E 类命中词是否属于「对已有稿编辑」的动作意图"""
    if not kw:
        return False
    if any(t in (target or '') for t in _NON_EDIT_TARGETS):
        return False
    return kw not in _NON_EDIT_KEYWORDS


def route(query, r=None):
    """返回 (命中规则, 命中关键词, 路由目标)；无命中返回 ('NO-MATCH', None, None)

    裁决顺序（v7.3.2 起）：
      0. **非公文任务护栏**：命中翻译/图表/PPT 类标记 → NO-MATCH
      1. 逐规则收集命中，**同规则内取更长关键词**；等长时保持表序
      2. 新手信号 → D 提前
      3. **E 为编辑类动作且 A 同现 → E 优先**（用户手里已有稿要改时，动作才是真诉求）

    历史行为保持：跨规则仍按 `C > B > A > D > E`；关键词仍为子串匹配。
    """
    r = r or rules()
    q = query.lower()
    if any(m.lower() in q for m in NON_DOC_TASK):
        return 'NO-MATCH', None, None

    hits = {}
    for name in PRI:
        best = None
        for kws, target in r.get(name, []):
            matched = [k for k in kws if k and k in query]
            if not matched:
                continue
            # 同规则内：**更长关键词优先**（更具体）；等长时保持 SKILL.md 表序（原行为）。
            # 注：曾试过"等长取更靠后者"以修 m01，但那会使「任免通知」误取「通知」→ notice
            # （回归 48/50）。m01 实为 spec 有意排除裸词「报告」的设计权衡，不需该启发式。
            cand = max(matched, key=len)
            if best is None or len(cand) > len(best[0]):
                best = (cand, target)
        if best:
            hits[name] = best
    if not hits:
        return 'NO-MATCH', None, None

    # 新手信号：D 提前（含"不知道怎么写通知"这类）
    if any(nb in query for nb in NEWBIE) and 'D' in hits:
        return 'D', hits['D'][0], hits['D'][1]

    # 编辑类动作优先于文种词
    if 'A' in hits and 'E' in hits:
        ekw, etarget = hits['E']
        if is_edit_action(ekw, etarget):
            return 'E', ekw, etarget

    first = min(hits, key=lambda n: PRI.index(n))
    return first, hits[first][0], hits[first][1]


if __name__ == '__main__':
    rs = rules()
    print('规则解析: ' + ' / '.join(f'{k} {len(v)}' for k, v in rs.items()))
    for q in ('写份防汛通知', '引用中央精神', '不知道怎么写通知', '帮我润色这段话'):
        print(f'  {q!r:26s} → {route(q)}')
