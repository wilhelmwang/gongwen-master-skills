# -*- coding: utf-8 -*-
"""AI 味检测器（v1.0 · 2026-09-06 · 去 AI 味深化）

设计：三级检测——
  L1 词汇层：AI 高频套话/翻译腔词典（regex 规则，可解释、零成本）
  L2 结构层：段落均长/排比堆砌/过度并列/机械总-分-总（统计特征）
  L3 语义层：（可选）LLM judge 复核——调用 judge_style.py 的去AI味维度

用法：
  python ai_flavor_detector.py --file 成稿.md            # 检测
  python ai_flavor_detector.py --file 成稿.md --suggest  # 检测+改写建议
输出：JSON（score 0-100，越高越"人味"）+ 逐条命中位置与建议。

评分逻辑：score = 100 - Σ(规则权重 × 命中密度)，密度按每千字命中数。
"""
import argparse
import json
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

# ---------- L1 词汇层词典（AI 味套话 → 建议替换） ----------
L1_RULES = [
    # (pattern, weight, 建议替换/说明)
    (r'值得注意的是', 3, '删除或改「需要指出」'),
    (r'总而言之|综上所述', 3, '公文结论直接陈述，不用总结套话'),
    (r'首先.*?其次.*?再次.*?最后', 4, '改用「一是/二是/三是」公文序次'),
    (r'不仅.{0,20}而且', 2, '拆句或改「既…又…」'),
    (r'进一步|大力|切实|深入|扎实|持续', 1, '公文动词可保留，堆叠≥3 处需精简'),
    (r'赋能|抓手|闭环|颗粒度|对齐|拉通|沉淀(?!数据)', 4, '互联网黑话，公文应换实义动词'),
    (r'夯实.{0,6}基础', 3, '改具体动作，如「补齐基础设施短板」'),
    (r'打造.{0,6}(高地|标杆|品牌|矩阵)', 3, '改「建设/培育」'),
    (r'(全面|深入)推进.{0,10}(深入|全面)', 3, '同义堆叠，删一个'),
    (r'起到了?.{0,6}积极(的)?作用', 3, '改具体成效'),
    (r'作为一?个?[^，。]{2,8}而言', 3, '删除框架句'),
    (r'在.{2,12}的(大)?背景下', 2, '背景句慎用，公文可直述'),
    (r'不容忽视|毋庸置疑|不言而喻', 3, '改直陈'),
    (r'为我们提供了?宝贵(的)?(经验|启示)', 3, '改具体启示内容'),
    (r'让我(们)?\s*共同', 4, '公文中不用号召式结尾（除非讲话稿）'),
    (r'关键词[:：]', 3, 'AI 摘要痕迹，删除'),
    (r'\*\*[^*]{2,20}\*\*', 2, 'markdown 加粗公文不用（标题除外）'),
    (r'——{1,}', 1, '破折号连用检查'),
    (r'[""]{1}', 1, '引号风格检查（公文用全角引号）'),
    (r'综上所述|综上', 3, '改「综上」或直接结论'),
    (r'一方面.{0,40}另一方面', 2, '可保留但≥3 处需换「一是/二是」'),
]

# ---------- L2 结构层（集中实现见 _structural_rules） ----------
L2_RULES = [
    ('emoji 出现（公文禁用）', 5,
     lambda t: len(re.findall(r'[\U0001F300-\U0001FAFF\u2705\u274C\u2B50]', t))),
    ('口语化语气词（呢/吧/啦/哦）', 3,
     lambda t: len(re.findall(r'[呢吧啦哦][，。？！]', t))),
]


def _structural_rules(text):
    """L2 规则集中实现（避免 lambda 序列化问题）。"""
    hits = []
    # 1 段落机械节奏
    ps = [p for p in re.split(r'\n\s*\n', text) if len(p.strip()) > 30]
    if len(ps) >= 4:
        lens = [len(p) for p in ps]
        if sum(lens) / len(lens) > 150 and (max(lens) - min(lens)) < 80:
            hits.append(('段落均长>150 且方差小（机械节奏）', 3, 1))
    # 2 过度并列
    if len(re.findall(r'[一二三四五六七八九十]是', text)) >= 5:
        hits.append(('「一是二是…」超过 5 项（过度并列）', 3, 1))
    # 3 排比堆砌：连续 3 段同开头 4 字
    starts = [p.strip()[:4] for p in ps if p.strip()]
    run = 1
    for i in range(1, len(starts)):
        run = run + 1 if starts[i] == starts[i - 1] else 1
        if run >= 3:
            hits.append((f'排比堆砌：连续{run}段同开头「{starts[i]}」', 4, 1))
            break
    # 4 emoji
    n = len(re.findall(r'[\U0001F300-\U0001FAFF\u2705\u274C\u2B50\u2714]', text))
    if n:
        hits.append(('emoji 出现（公文禁用）', 5, n))
    # 5 语气词
    n = len(re.findall(r'[呢吧啦哦][，。？！]', text))
    if n >= 2:
        hits.append(('口语化语气词', 3, n))
    return hits


def detect(text: str):
    """检测全文，返回 dict(score, hits)"""
    n_chars = max(1, len(re.sub(r'\s', '', text)))
    hits = []
    for pat, w, sugg in L1_RULES:
        found = re.findall(pat, text)
        if found:
            density = len(found) / n_chars * 1000
            if density >= 0.5:  # 每千字≥0.5 次才计
                hits.append({'layer': 'L1', 'rule': pat, 'count': len(found),
                             'weight': w, 'suggestion': sugg,
                             'samples': [text[max(0, m.start() - 10):m.end() + 15]
                                         for m in re.finditer(pat, text)][:3]})
    for name, w, cnt in _structural_rules(text):
        hits.append({'layer': 'L2', 'rule': name, 'count': cnt,
                     'weight': w, 'suggestion': '见 rule 名称'})
    penalty = sum(h['weight'] * min(h['count'], 5) for h in hits)
    score = max(0, min(100, 100 - penalty * 2))
    return {'score': score, 'n_chars': n_chars, 'hits': hits}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', required=True)
    ap.add_argument('--suggest', action='store_true', help='输出改写建议清单')
    args = ap.parse_args()
    text = open(args.file, encoding='utf-8').read()
    r = detect(text)
    print(f"AI味评分: {r['score']}/100（越高越人味） | {r['n_chars']} 字 | 命中 {len(r['hits'])} 条规则")
    for h in r['hits'][:15]:
        print(f"  [{h['layer']}] x{h['count']} w{h['weight']} {h['rule'][:40]} → {h['suggestion'][:40]}")
    if args.suggest:
        print('\n改写建议（按权重排序）:')
        for h in sorted(r['hits'], key=lambda x: -x['weight']):
            print(f"  - {h['suggestion']}")
    # 门禁：≥70 通过
    sys.exit(0 if r['score'] >= 70 else 1)


if __name__ == '__main__':
    main()
