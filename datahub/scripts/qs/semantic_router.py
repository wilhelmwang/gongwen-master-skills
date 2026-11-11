#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""语义路由兜底层（v6.9.0 P1-3 · 2026-09-05）
定位：关键词规则（A-F）未命中时的第二道兜底，在 LLM 语义路由之前。
优先级不变：关键词命中 > 语义兜底（本模块）> LLM 语义 > 保底框架。

原理：bge-small-zh 向量编码"路由意图画像"（每技能一组典型表述），
用户口语查询向量 → 余弦最近技能。模型缺失时显式降级（返回 None）。

用法：
  from semantic_router import route_semantic
  target = route_semantic('领导让发个调整作息的东西')   # → 'govdoc-notice' 或 None
  python semantic_router.py --eval                      # 跑 route_benchmark 90 条
"""
import os, sys, json


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

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 模型目录统一经 datahub/paths.py 解析（环境变量 → assets.json 登记项），与检索引擎同源
sys.path.insert(0, os.path.join(BASE, 'datahub'))
try:
    from paths import bge_model_status
except Exception:                                    # datahub 被裁剪时的降级
    def bge_model_status():
        return False, '', 'unset', 'datahub/paths.py 不可用'

# 路由意图画像：每技能 4 条典型口语表述（与 route_benchmark 无重叠，防泄漏）
PROFILES = {
    'govdoc-notice': ['发通知告诉大家一件事', '把安排下发给各部门', '会议时间地点告知全体', '布置工作任务的通知'],
    'govdoc-speech': ['领导在会上讲话发言', '开幕致辞讲话稿', '动员鼓劲的讲话', '表态发言的稿子'],
    'govdoc-report': ['向上级汇报工作情况', '述职履职情况的报告', '工作进展汇报材料', '情况报告呈报上级'],
    'govdoc-summary': ['年度工作总结回顾', '阶段性工作收尾总结', '全年工作盘点成文', '专项总结撰写'],
    'govdoc-research': ['实地调查研究的报告', '蹲点调研后的成文', '考察情况的书面材料', '问题调查分析报告', '外地考察调研形成的报告', '深入了解情况后的调研文章'],
    'govdoc-plan': ['工作计划的制定', '实施方案的起草', '年度任务规划安排', '行动方案编制', '工作推进的路线图', '任务安排的计划书'],
    'govdoc-request': ['向上级请示批准事项', '申请资金政策的文书', '请求批复的公文', '报请上级审定', '请示审批恳请同意', '呈请上级研究决定', '向上级机关要钱要物要政策的请示', '恳请领导批准同意办理'],
    'govdoc-circular': ['表彰先进的通报', '批评违规的通报', '工作情况简报编发', '重要事项通报周知', '表彰决定的通报发布', '表扬批评通报文书', '通报表扬好人好事', '督查情况通报和简报', '内部信息简报定期刊发', '政务信息刊物编发'],
    'govdoc-minutes': ['会议纪要的整理', '会议记录归档成文', '议定事项纪要', '会议备忘录撰写'],
    'govdoc-news': ['新闻稿对外发布', '宣传报道的撰写', '工作成果通稿', '媒体发布的消息稿'],
    'govdoc-letter': ['公开信的起草', '致某群体的信函', '感谢信慰问信撰写', '回应关切的一封信', '致市民的倡议公开信', '倡议书公开信写作'],
    'govdoc-reflection': ['学习心得体会撰写', '感想感悟类文章', '培训后的体会成文', '观后感的写作'],
    'govdoc-experience': ['经验交流材料撰写', '典型做法的经验总结', '先进经验的介绍材料', '做法成效的提炼', '典型经验的做法总结', '好经验好做法成文'],
    'govdoc-regulation': ['规章制度办法的制定', '实施细则起草', '管理规定成文', '内部条例撰写'],
    'govdoc-theory': ['理论文章的撰写', '政论文章起草', '思想评论写作', '学理性阐释文章'],
    'govdoc-layout': ['公文的排版格式', '文件版式规范调整', '公文格式国标设置', '文档样式排版'],
    'govdoc-polish': ['稿件修改润色', '文字优化的要求', '扩写缩写改写', '文稿检查校对', '帮我修改润色这篇稿子', '压缩精简文字表述', '语言表达调整润饰'],
    'govdoc-duty': ['干部任免的通知', '人事调整的文件', '分工职责的明确', '任职免职事项', '干部职务任免文件', '岗位职责人事专文'],
    'govdoc-styles': ['用追梦笔写', '新年贺词风格', '用求是笔写', '理论阐发体文章', '用文风的风格写', '模仿某领导文风', '机关文风的材料', '指定风格的讲话', '用文风一写', '用文风三写', '按文风五写', '像文风二那样写', '湘江笔风格', '乔木笔风格', '翔宇先生风格', '笃行先生文风'], 
    'shuji': ['用某本书的文风写作', '置身事内式叙事', '学术著作风格的成文', '书体风格模仿'],
    'article-review': ['分析拆解一篇文章', '核查文章的事实', '点评稿件的质量', '文章深度解读'],
    'qiushi-db': ['引用求是杂志的表述', '查政策权威说法', '地方本地数据引用', '找权威论断金句'],
}

_MODEL = {'m': None}

def _load_model():
    if _MODEL['m'] is not None:
        return _MODEL['m']
    ok, model_dir, src, why = bge_model_status()
    if not ok:
        print(f'[semantic-router] 语义路由兜底关闭（模型来源 {src}：{why}，保持关键词+LLM 流程）')
        return None
    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np
        _MODEL['m'] = SentenceTransformer(model_dir)
        _MODEL['np'] = np
        # 预编码画像
        names, texts = [], []
        for k, v in PROFILES.items():
            for t in v:
                names.append(k); texts.append(t)
        _MODEL['names'] = names
        _MODEL['P'] = _MODEL['m'].encode(texts, normalize_embeddings=True)
        return _MODEL['m']
    except Exception as e:
        print(f'[semantic-router] 模型加载失败，兜底关闭: {e}')
        return None

def route_semantic(query, top=1, threshold=0.55):
    """语义路由兜底：返回 (技能名, 相似度) 或 (None, best_score)"""
    m = _load_model()
    if m is None:
        return None, 0.0
    np = _MODEL['np']
    q = m.encode([query], normalize_embeddings=True)[0]
    sims = _MODEL['P'] @ q
    order = np.argsort(-sims)
    best_name, best_score = _MODEL['names'][order[0]], float(sims[order[0]])
    if top == 1:
        return (best_name, best_score) if best_score >= threshold else (None, best_score)
    return [(_MODEL['names'][i], float(sims[i])) for i in order[:top]]

def run_eval(bench_path=None):
    bench_path = bench_path or os.path.join(BASE, 'datahub', 'eval', 'route_benchmark.json')
    d = json.load(open(bench_path, encoding='utf-8'))
    qs = d['queries']
    hit, miss, n = 0, 0, len(qs)
    print(f'=== 语义路由评测（{n} 条口语→文种）===')
    for it in qs:
        name, score = route_semantic(it['q'])
        # 命中判定：路由目标等于期望，或 LLM 层面可接受（同族映射）
        ok = (name == it['expected'])
        if ok:
            hit += 1
        else:
            miss += 1
            print(f"  ✗ {it['q'][:24]} → {name or 'None'}({score:.2f}) 期望 {it['expected']}")
    print(f'\nN@1 命中 {hit}/{n} = {hit/n:.0%}')
    return 0 if hit / n >= 0.6 else 1

if __name__ == '__main__':
    if '--eval' in sys.argv:
        sys.exit(run_eval())
    else:
        q = ' '.join(sys.argv[1:]) or '领导让发个调整作息的东西'
        name, score = route_semantic(q)
        print(f'{q} → {name or "None"} ({score:.3f})')
