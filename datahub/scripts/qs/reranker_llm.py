# -*- coding: utf-8 -*-
"""R 层：LLM 重排适配器 v1.0（2026-09-03 · F5）
hybrid3 召回 top20 → LLM listwise 精排 top5；无 key/失败 自动回退 RRF 顺序（fail-open）
用法：python reranker_llm.py "<查询>" --cands "<json数组>"
      --mode ab   # 输出 RRF 序 + LLM 序双份（A/B 用）
"""
import json, os, sys, argparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

PROMPT_SYS = ('你是信息检索重排器。给定查询与候选文档（编号+标题+摘要），'
              '输出与查询最相关的 Top5 编号（按相关度降序，只输出 JSON 数组如 ["7","3","12","1","19"]）。'
              '依据权威表述贴切度、主题契合度判断。')

def rrf_order(cands):
    """保留原 RRF 顺序（A/B 对照组）"""
    return [c['id'] for c in cands]

def llm_rerank(query, cands, top_n=5):
    from llm_client import chat
    lines = []
    for c in cands:
        lines.append(f"[{c['id']}] {c.get('title','')}｜{c.get('snippet','')[:120]}")
    user = f'查询：{query}\n候选：\n' + '\n'.join(lines)
    raw = chat(PROMPT_SYS, user)
    s = raw[raw.find('['):raw.rfind(']') + 1]
    order = json.loads(s)
    id2c = {c['id']: c for c in cands}
    ordered = [id2c[i] for i in order if i in id2c]
    return [c['id'] for c in ordered[:top_n]]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('query')
    ap.add_argument('--cands', required=True)
    ap.add_argument('--mode', default='llm', choices=['llm', 'ab'])
    a = ap.parse_args()
    cands = json.loads(a.cands)
    rrf = rrf_order(cands)
    if a.mode == 'ab':
        try:
            llm = llm_rerank(a.query, cands)
            print(json.dumps({'rrf': rrf, 'llm': llm}, ensure_ascii=False))
        except Exception as e:
            print(json.dumps({'rrf': rrf, 'llm': rrf, 'error': str(e)}, ensure_ascii=False))
    else:
        try:
            print(json.dumps(llm_rerank(a.query, cands), ensure_ascii=False))
        except Exception as e:
            print(json.dumps(rrf, ensure_ascii=False), f'<!--fail-open: {e}-->')

if __name__ == '__main__':
    main()