#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""风格语义路由 v1.0（A-风格，2026-09-01）
16 风格画像（触发词+特征描述）→ bge 向量 → 用户口语风格需求 → 最近风格建议
用法: python style_router.py "像发改委那种口吻写一段" [--top 2]
"""
import os, json, sys, argparse
import numpy as np

# v6.8.1（P0-2）：去除开发机硬编码路径，统一经环境变量 GONGWEN_BGE_MODEL 指定
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
MODEL = os.environ.get('GONGWEN_BGE_MODEL', '')

# 16 风格画像（触发词 + 特征描述，手工精修自入口路由表）
PROFILES = [
    ("文风一", "biganzi", "公开讲话与治理分析风格：民本落点、坐标赶超、改革创新开放三力、工程闭环；语料 280 篇领导讲话，结构工整、部署语言强", ["文风一", "公开讲话", "领导讲话", "治理分析", "部署"]),
    ("文风二", "biganzi", "城市治理叙事风格：耿彦波式，历史纵深+规划叙事+文化保护论证，城建规划领域", ["文风二", "耿彦波", "城市建设", "城市治理", "规划"]),
    ("文风三", "biganzi", "发改系统风格：郑栅洁式，高质量发展、产业链、宏观调控、项目攻坚、发改委口径", ["文风三", "郑栅洁", "发展改革", "产业链", "宏观调控", "项目攻坚"]),
    ("文风四", "biganzi", "政策解读风格：政策文件解读三要素背景-要义-落地，理论文章撰写", ["文风四", "政策解读", "解读文件", "理论文章"]),
    ("文风五", "biganzi", "基层工作风格：乡镇街道社区汇报、总结、经验材料、典型发言", ["文风五", "基层", "乡镇", "街道", "社区", "村居", "经验材料"]),
    ("文风六", "biganzi", "央企国企风格：年报、领导讲话、汇报材料、战略规划、董事会报告", ["文风六", "央企", "国企", "集团", "上市公司", "年度工作报告"]),
    ("置身事内体", "shuji", "上书下篇结构、财政-土地-债务主线，学术化但通俗的经济学叙事，兰小欢式", ["置身事内", "财政", "土地", "债务", "经济叙事", "政府与经济"]),
    ("以利为利体", "shuji", "财政实证叙事：中央-地方财政关系、分税制、土地财政因果链，数据+制度解释", ["以利为利", "账本体", "财政关系", "分税制", "土地财政"]),
    ("结构性改革体", "shuji", "问题-结构-对策三段，市场化纵深改革视角，产业经济分析，黄奇帆式", ["结构性改革", "黄奇帆", "改革", "产业分析"]),
    ("转型政府体", "shuji", "行政发包制、政治锦标赛，官员激励与治理的立论分析，周黎安式", ["转型中的地方政府", "官员激励", "晋升", "行政发包", "治理"]),
    ("制度逻辑体", "shuji", "组织与制度分析框架：合法性/效率张力，周雪光式", ["制度逻辑", "组织分析", "制度分析"]),
    ("现象中国体", "shuji", "中国宏观现象叙事：社会转型观察，县域基层视角", ["现象中国", "县乡", "基层治理调研", "社会转型"]),
    ("当代政府体", "shuji", "政府机构与运作过程分析，当代中国政府", ["当代政府", "政府运作", "政府机构"]),
    ("中县干部体", "shuji", "基层干部晋升/关系田野叙事，干部考核、选人用人（只取方法）", ["中县干部", "干部考核", "选人用人", "干部晋升"]),
    ("小镇喧嚣体", "shuji", "乡镇政治运作深描：场景-人物-过程白描，田野叙事，吴毅式", ["小镇喧嚣", "深描", "田野叙事", "乡镇政治"]),
    ("三笔会诊", "biganzi", "多风格联审：文风 1/2/3 围绕同一材料交叉评审，输出综合意见", ["三笔会诊", "会诊", "多风格联审", "交叉评审"]),
]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('query', help='口语风格需求')
    ap.add_argument('--top', type=int, default=2)
    args = ap.parse_args()

    if not MODEL or not os.path.isdir(MODEL):
        print('[gongwen] 未设置 GONGWEN_BGE_MODEL 环境变量（指向 bge-small-zh-v1.5 模型目录），无法执行语义路由。')
        print('[gongwen] 请设置后重试，例如：set GONGWEN_BGE_MODEL=D:/models/bge-small-zh-v1.5')
        sys.exit(2)

    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL)

    texts = [f"{name}：{'；'.join(tags)}。{desc}" for name, _, desc, tags in PROFILES]
    P = model.encode(texts, normalize_embeddings=True)
    q = model.encode([args.query], normalize_embeddings=True)[0]
    sims = P @ q

    order = np.argsort(-sims)
    print(f'查询: {args.query}')
    print(f'匹配结果（Top {args.top}）:')
    for i in order[:args.top]:
        name, mod, desc, tags = PROFILES[i]
        print(f'  [{sims[i]:.3f}] {name}（入口 {mod}）: {desc[:44]}')
        print(f'      触发词: {" / ".join(tags[:5])}')

if __name__ == '__main__':
    main()