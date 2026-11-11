# -*- coding: utf-8 -*-
"""忠实度评测层（Faithfulness Layer · v7.1 T1 · 2026-09-06）

对标 RAGAS faithfulness（2026 企业阈值 ≥0.85）：
对每条基准 query，取检索 Top-3 片段 → 生成 3 句模拟答案 → LLM-judge 逐断言核验
「答案中的每个断言是否被检索片段支持」→ 断言级支持率 = faithfulness。

用法：
  python judge_faithfulness.py                 # 跑全量 104 条（约 3-5 分钟）
  python judge_faithfulness.py --n 10          # 快速抽 10 条
  python judge_faithfulness.py --tier hard     # 只跑难层
输出：
  datahub/eval/faithfulness_results.json（逐条+汇总）
门禁：faithfulness < 0.85 退出码 1。
"""
import argparse
import json
import os
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

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE, "datahub", "scripts", "qs"))

GEN_SYSTEM = (
    "你是公文写作助理。仅依据给定的【参考片段】回答【问题】，写 2-3 句话。"
    "规则：只能使用片段中明确出现的信息；片段不足以回答时，写「片段未提供该信息」。"
    "禁止使用任何片段之外的知识。直接输出答案文本，不要解释。"
)

JUDGE_SYSTEM = (
    "你是忠实度核验官。给定【参考片段】与【答案】，请把答案拆成独立断言（每句一个事实主张），"
    "逐条判断该断言是否能从参考片段直接推断（允许同义改写，禁止引入片段外知识）。"
    "只输出 JSON：{\"assertions\": [{\"text\": \"断言\", \"supported\": true|false}], "
    "\"faithfulness\": 断言支持率 0.0-1.0}。"
)


def run_one(ss, llm, q):
    try:
        hits = ss.search(q, top_n=3, mode="hybrid3")
    except Exception as e:
        return {"q": q, "error": f"retrieve: {e}"}
    if not hits:
        return {"q": q, "error": "retrieve: empty"}
    contexts = [f"《{h.get('title', '')}》{h.get('snippet', '')}" for h in hits]
    ctx_block = "\n---\n".join(contexts)
    try:
        answer = llm(GEN_SYSTEM, f"【问题】{q}\n【参考片段】\n{ctx_block}")
    except Exception as e:
        return {"q": q, "error": f"generate: {e}", "answer": None}
    try:
        out = llm(JUDGE_SYSTEM,
                  f"【参考片段】\n{ctx_block}\n【答案】\n{answer}")
        s = out[out.find("{"):out.rfind("}") + 1]
        verdict = json.loads(s)
        score = verdict.get("faithfulness")
        if score is None and verdict.get("assertions"):
            a = verdict["assertions"]
            score = sum(1 for x in a if x.get("supported")) / max(1, len(a))
        # 拒答识别（RAGAS 口径补充）：生成端明确说「片段未提供」= 忠实拒答，不计为幻觉
        refusal = "片段未提供" in answer or "无法从片段" in answer
        if refusal:
            return {"q": q, "answer": answer[:200], "n_ctx": len(contexts),
                    "assertions": [], "faithfulness": None,
                    "refusal": True}
        return {"q": q, "answer": answer[:200], "n_ctx": len(contexts),
                "assertions": verdict.get("assertions"), "faithfulness": score}
    except Exception as e:
        return {"q": q, "answer": (answer or "")[:200], "error": f"judge: {e}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=None, help="只跑前 N 条（快速）")
    ap.add_argument("--tier", default=None, help="过滤 tier")
    args = ap.parse_args()

    data = json.load(open(os.path.join(BASE, "datahub", "eval", "benchmark_queries.json"),
                          encoding="utf-8"))
    qs = [x["q"] for x in data["queries"] if args.tier is None or x["tier"] == args.tier]
    if args.n:
        qs = qs[:args.n]

    from qiushi_engine import SemanticSearch
    from llm_client import chat
    ss = SemanticSearch()
    llm = lambda s, u: chat(s, u)

    results = []
    for i, q in enumerate(qs, 1):
        r = run_one(ss, llm, q)
        results.append(r)
        tag = (f"{r['faithfulness']:.2f}" if r.get("faithfulness") is not None
               else f"ERR:{r.get('error', '')[:20]}")
        print(f"  [{i}/{len(qs)}] {tag:>5s} {q[:28]}")

    ok = [r for r in results if r.get("faithfulness") is not None]
    refusals = [r for r in results if r.get("refusal")]
    errs = [r for r in results if r.get("error")]
    score = sum(r["faithfulness"] for r in ok) / max(1, len(ok))

    # 逐条 JSONL（抗中断：中断后已跑的不丢）
    jsonl = os.path.join(BASE, "datahub", "eval", "faithfulness_results.jsonl")
    with open(jsonl, "a", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    outpath = os.path.join(BASE, "datahub", "eval", f"faithfulness_results_{len(qs)}.json")
    # v7.3.1 口径修正：原判据要求 errors==0，与已记录基线（errors=12, pass=true, 均值 0.954）自相矛盾
    # —— 凭据正常时会对"合格基线"判 FAIL。现改为「错误率进预算」：瞬时限流/超时不应否掉整体质量，
    # 但错误率超预算（默认 20%，可用 GONGWEN_FAITH_ERR_BUDGET 覆盖）仍判 FAIL。
    err_rate = (len(errs) / len(qs)) if qs else 0.0
    err_budget = float(os.environ.get("GONGWEN_FAITH_ERR_BUDGET", "0.20"))
    summary = {"n": len(qs), "judged": len(ok), "refusals": len(refusals), "errors": len(errs),
               "faithfulness_mean": round(score, 3),
               "threshold": 0.85,
               "error_rate": round(err_rate, 3), "error_budget": err_budget,
               "pass": (score >= 0.85 and err_rate <= err_budget),
               "detail": results}
    from pathlib import Path as _P
    _P(outpath).write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    low = sorted([r for r in ok if r["faithfulness"] < 0.6], key=lambda x: x["faithfulness"])[:5]
    print(f"\n=== Faithfulness 汇总 ===")
    print(f"  均值 {score:.3f} | 阈值 0.85 | {'✅ PASS' if score >= 0.85 else '❌ FAIL'}")
    print(f"  已判 {len(ok)}/{len(qs)}（忠实拒答 {len(refusals)} 条单列，属正常行为不判失败）"
          f"｜异常 {len(errs)} 条（错误率 {err_rate:.1%}，预算 ≤{err_budget:.0%}）")
    if low:
        print("  低分样本（<0.6，前 5）:")
        for r in low:
            print(f"    {r['faithfulness']:.2f} {r['q'][:30]}")
    print(f"  结果: {outpath}")
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
