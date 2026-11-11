# -*- coding: utf-8 -*-
"""规则 A-F 映射回归 v2.0（2026-09-11）

v2.0 变更：
  · 补规则 F（团队模式）覆盖 —— v1.2 完全未覆盖
  · 修复解析器区间 bug：规则头正则原为 `[A-E]`，导致规则 E 的区间一直吞掉紧随其后的
    规则 F 表格（F 关键词被误当作 E 条目参与匹配）
  · **补退出码**：v1.2 只打印 PASS/FAIL 却从不 sys.exit，失败也返回 0，
    无法作为门禁使用（release 流水线依赖本退出码）

模型：规则 A-E 决定"路由到哪个技能"；规则 F 是**正交的模式开关**（是否升格为团队模式），
不参与 C>B>A>D>E 优先级链。故 route() 返回基础路由，is_team() 独立判定。
"""
import os, re, sys


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

BASE = os.path.dirname(os.path.abspath(__file__))
try:                                   # v8 双态：master SKILL.md 经 skills_manifest 定位
    from skills_manifest import skill_md as _skill_md
    FP = _skill_md('gongwen-master')
except Exception:
    FP = os.path.join(BASE, 'gongwen-master', 'SKILL.md')
c = open(FP, encoding='utf-8').read()  # 存在性冒烟：规则表载体必须可读

# ---- 路由引擎：唯一实现见 router.py（v7.3.2；此前解析与裁决逻辑内联在本文件，已抽共享）----
import router as _router

RULES = _router.rules()
PRI = _router.PRI
NEWBIE = _router.NEWBIE


def is_team(query):
    return _router.is_team(query)


def route(query):
    return _router.route(query)


CASES = [
    ('写份防汛通知', 'A', 'notice'), ('起草领导讲话', 'A', 'speech'),
    ('给我写个工作汇报', 'A', 'report'), ('上半年工作总结', 'A', 'summary'),
    ('会议纪要怎么写', 'A', 'minutes'), ('出一份调研报告', 'A', 'research'),
    ('制定实施方案', 'A', 'plan'), ('起草一份规章制度', 'A', 'regulation'),
    ('写理论文章', 'A', 'theory'), ('学习心得体会', 'A', 'reflection'),
    ('写新闻稿', 'A', 'news'), ('向上级请示', 'A', 'request'),
    ('写个批复', 'A', 'request'), ('通报表彰先进', 'A', 'circular'),
    ('写简报', 'A', 'circular'), ('出个专报', 'A', 'circular'),
    ('经验交流材料', 'A', 'experience'), ('任免通知', 'A', 'duty'),
    ('感谢信', 'A', 'letter'), ('公开信致全体市民', 'A', 'letter'),
    ('用文风一的风格写', 'B', 'govdoc-styles'), ('耿彦波式讲话', 'B', 'govdoc-styles'),
    ('郑栅洁式发言', 'B', 'govdoc-styles'),
    ('用置身事内体写', 'B', 'shuji'), ('账本体财政分析', 'B', 'shuji'),
    ('小镇喧嚣深描体', 'B', 'shuji'), ('结构性改革黄奇帆视角', 'B', 'shuji'),
    ('三笔会诊这篇稿子', 'B', 'govdoc-styles'),
    ('引用求是权威表述', 'C', 'qiushi-db'), ('引用中央精神', 'C', 'qiushi-db'),
    ('不知道怎么写通知', 'D', 'gongwen-master'), ('不会写总结', 'D', 'gongwen-master'),
    ('帮我弄个材料', 'D', 'gongwen-master'),
    ('帮我润色这段话', 'E', 'polish'), ('质检这段公文', 'E', 'polish'),
    ('公文排版格式', 'E', 'layout'), ('核查这篇文章事实', 'E', 'article-review'),
    ('用文风三风格写高质量发展报告', 'B', 'govdoc-styles'),
    ('不知道怎么写调研报告', 'D', 'gongwen-master'),
    ('领导讲话 用文风二', 'B', 'govdoc-styles'),
    ('写份通报表扬', 'A', 'circular'),
]

# 规则 F（团队模式）用例：query, 期望命中场景关键词（子串）, 期望同时命中的基础规则
# 注：F 与 E 在「核查」上按设计重叠——F 场景 3 明确"复用 article-review 模式 B"，
#     故 '深度核查这篇文章' 同时命中 F（团队模式）+ E（article-review 基础路由）。
# v7.6.0 新增：C3a 以稿写稿 / C3b 单位语料接入
CASES += [
    ('把这些材料写成一份通知', 'E', 'govdoc-material'),      # E 编辑类动作优先于 A 文种词
    ('按材料写一份总结', 'E', 'govdoc-material'),
    ('以稿写稿 根据材料起草', 'E', 'govdoc-material'),
    ('导入我们单位的历年公文', 'E', 'govdoc-corpus'),
    ('建立本单位公文库', 'E', 'govdoc-corpus'),
    ('单位语料接入', 'E', 'govdoc-corpus'),
    ('写份总结 参考我们单位公文库', 'A', 'govdoc-summary'),   # corpus 不抢文种词优先级
]

F_CASES = [
    # --- 评审腿（场景 1-3）---
    ('这篇稿子帮我评审一下', '评审', 'NO-MATCH'),
    ('让专家看看这份材料', '专家', 'NO-MATCH'),
    ('深度核查这篇文章', '核查', 'E'),
    ('多视角审一下', '多视角', 'NO-MATCH'),
    ('写份通知 帮我把关', '把关', 'A'),
    # --- 写稿腿（场景 4-7 · v8.1.0 新增）---
    ('一起写稿这份工作汇报', '一起写稿', 'A'),
    ('团队写稿起草通知', '团队写稿', 'A'),
    ('专家团一起写份防汛通知', '专家团一起写', 'A'),
    ('分段承包写份工作总结', '分段承包', 'A'),
    ('分工写一份实施方案', '分工写', 'A'),
    ('各写一版挑一个', '各写一版', 'NO-MATCH'),
    ('竞稿三份让我挑', '竞稿', 'NO-MATCH'),
    ('骨架会战这份讲话', '骨架会战', 'A'),
    ('全程合写这份政府工作报告', '全程合写', 'A'),
]


def main():
    print(f'解析: ' + ' / '.join(f'{r} {len(RULES[r])}' for r in ['A', 'B', 'C', 'D', 'E', 'F']))
    print('===== 回归结果 =====')
    pass_n = fail_n = 0
    for q, er, et in CASES:
        r, kw, target = route(q)
        if r == 'NO-MATCH':
            ok, disp = False, 'NO-MATCH'
        else:
            ok = (r == er) and (et in target)
            disp = f'{r}「{kw[:16]}」→ {target[:32]}'
        mark = '✅' if ok else '❌'
        print(f'  {mark} [{q[:22]:24s}] {disp:52s}期望 {er}→{et}')
        pass_n += ok
        fail_n += (not ok)

    # 规则 F 覆盖
    print('  --- 规则 F（团队模式）---')
    for q, kw_expect, base_expect in F_CASES:
        hit = is_team(q)
        base_rule = route(q)[0]
        ok = (hit is not None and kw_expect in hit[0]) and (base_rule == base_expect)
        disp = f'F「{hit[0][:14]}」→ {hit[1][:26]}' if hit else 'NO-MATCH'
        mark = '✅' if ok else '❌'
        print(f'  {mark} [{q[:22]:24s}] {disp:44s}基础规则={base_rule}(期望 {base_expect})')
        pass_n += ok
        fail_n += (not ok)

    total = len(CASES) + len(F_CASES)
    print(f'\nPASS {pass_n}/{total} | FAIL {fail_n}')
    # v2.0：补退出码，使本脚本可作为门禁（v1.2 恒返回 0）
    return 1 if fail_n else 0


if __name__ == '__main__':
    sys.exit(main())
