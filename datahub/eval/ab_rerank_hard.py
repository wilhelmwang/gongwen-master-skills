# -*- coding: utf-8 -*-
"""检索精排 A/B 实测 harness（独立于包外，不改动包内脚本）
前置：python -m pip install jieba numpy scikit-learn rank-bm25
用法：python ab_rerank_hard.py
说明：
 - 自动从 HKCU\\Environment 读取 OPENCODE_GO_API_KEY（若进程环境未设），仅内存使用，不打明文。
 - 对 benchmark_queries.json 中 tier=='hard' 的条目：SemanticSearch(top_n=20, hybrid3) 取候选
   -> 调用 reranker_llm 的 ab 模式得 {rrf, llm} 双序 -> 用 run_eval 相同判定逻辑算 MRR_A / MRR_B。
 - LLM 每查询仅 1 次，失败 fail-open（llm 序回退 rrf 序，MRR_B==MRR_A）。
"""
import os, sys, json, time, winreg

PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # v6.8.1 P0-2 去硬编码
QS = os.path.join(PKG, "datahub", "scripts", "qs")
sys.path.insert(0, QS)

def ensure_key():
    if os.environ.get("OPENCODE_GO_API_KEY"):
        return True
    try:
        h = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment")
        v = winreg.QueryValueEx(h, "OPENCODE_GO_API_KEY")[0]
        winreg.CloseKey(h)
        os.environ["OPENCODE_GO_API_KEY"] = v
        return True
    except Exception:
        return False

from qiushi_engine import SemanticSearch
import reranker_llm as R

def first_rel_rank(order_ids, results_by_id, expected, top=20):
    # order_ids: 候选文档 id 的排序；results_by_id: id->doc
    for rank, cid in enumerate(order_ids[:top], 1):
        doc = results_by_id.get(cid, {})
        text = (doc.get("title") or "") + " " + (doc.get("snippet") or "")
        if any(k in text for k in expected):
            return rank
    return None

def main():
    ok = ensure_key()
    print("KEY:", "已就位(来自env/注册表)" if ok else "缺失 -> LLM 将全部 fail-open")
    ss = SemanticSearch()
    data = json.load(open(os.path.join(PKG, "datahub/eval/benchmark_queries.json"), encoding="utf-8"))
    hard = [q for q in data["queries"] if q["tier"] == "hard"]
    mrr_a = mrr_b = 0.0
    diff_samples = []
    t0 = time.time()
    for item in hard:
        r = ss.search(item["q"], top_n=20, mode="hybrid3")
        by_id = {x["id"]: x for x in r}
        cands = [{"id": x["id"], "title": x.get("title", ""), "snippet": x.get("snippet", "")} for x in r]
        rrf = R.rrf_order(cands)
        try:
            llm = R.llm_rerank(item["q"], cands)  # top5
            err = None
        except Exception as e:
            llm = rrf[:5]; err = str(e)[:60]
        # B 序：llm top5 + 其余按 rrf
        rest = [i for i in rrf if i not in llm]
        b_order = llm + rest
        fa = first_rel_rank(rrf, by_id, item["expected"])
        fb = first_rel_rank(b_order, by_id, item["expected"])
        if fa: mrr_a += 1.0 / fa
        if fb: mrr_b += 1.0 / fb
        if err is None and llm != rrf[:5] and fa and fb and fb != fa:
            diff_samples.append((item["q"][:20], rrf[:5], llm, fa, fb))
    n = len(hard)
    print(f"\n=== A/B 实测（hard 子集 n={n}，耗时 {time.time()-t0:.0f}s）===")
    print(f"MRR_A(rrf) = {mrr_a/n:.4f}")
    print(f"MRR_B(llm) = {mrr_b/n:.4f}")
    print(f"Δ = MRR_B - MRR_A = {mrr_b/n - mrr_a/n:+.4f}  (>= +0.02 才建议常驻)")
    print("\n差异样例（前3条 llm 序与 rrf 序不同且影响首命中位）：")
    for q, rr, ll, fa, fb in diff_samples[:3]:
        print(f"  - {q}: rrf_top5={rr} | llm_top5={ll} | 首命中 {fa}->{fb}")

if __name__ == "__main__":
    main()
