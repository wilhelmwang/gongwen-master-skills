# -*- coding: utf-8 -*-
"""生成风格评测器（LLM-as-judge · 2026-09-03；rubric v2 结构锚定 2026-09-11）
用法：python judge_style.py --task t01 --draft 成稿.md     # 单任务四维打分
      python judge_style.py --suite  [--draft-dir dir]     # 跑全部任务（缺稿提示）
四维：风格贴合 / 结构完整 / 引用规范 / 去AI味（各 0-100 + 依据）

rubric v2 变更（为什么改）
-------------------------
2026-09-11 由子 agent 复核发现：原四维提示词**只有维度名、无任何判分标准**，
「结构完整」尤其缺参照物——judge 只收到 title/brief/prite/成稿，范本原文、
_provenance.json、各文种 formulas.md 一个都没传进去，模型只能凭印象对比自己
脑补的规范结构。后果有三：
  ① 不可复现（同稿两次打分漂移无约束）
  ② 不可比（生成稿结构 75-100，正式发表的全文范本 30-80）
  ③ 结构性维度却要求"引用成稿关键句"作证据 → 文本证据偏置，
     小标题在抽取中丢失的稿子找不到可引结构标记，只能被降分
「结构完整」58.8 的均分**是口径缺失的产物，不是范本质量差**。本版改成四查锚定
打分（必备构件 40 / 层次标记 20 / 落款要素 20 / 文本洁净度 20），并要求 why 写出
核对过程而非"结构清晰完整"这类空话。
"""
import argparse, json, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE, 'datahub', 'scripts', 'qs'))

RUBRIC_VERSION = 'rubric-v2-structure-anchored (2026-09-11)'
DIMS = ['风格贴合', '结构完整', '引用规范', '去AI味']
SYSTEM = (
 '你是「公文大师」写作质量评审官。对给定写作任务与成稿，按且仅按以下四维打分（0-100 整数），'
 '每维给出依据。四个维度名必须一字不差：风格贴合、结构完整、引用规范、去AI味。\n'
 '\n'
 '【风格贴合】依据任务指定的文风/重点（见「风格/重点」栏）逐项核对：'
 '该文风的标志性手法是否出现、题材是否吻合、语言是否是该文体的语感。每缺一项标志手法扣 10 分。\n'
 '\n'
 '【结构完整】只按以下四查评分，**不得凭"看起来完整"给分**：\n'
 '  一查 必备构件（40 分）：以任务给出的【必备构件清单】逐项在成稿中定位。'
 '每缺 1 项扣 40/n（n=清单项数）；某构件存在但无实质内容时扣该分的一半。'
 '清单未给出时，按该文种通用体例自行列出构件并写明你列了哪几项。\n'
 '  二查 层次标记（20 分）：标题是否完整未被拆行；「一、二、三」或「（一）（二）」是否连续、'
 '不漏号、不重号。每类缺陷扣 4 分，本查最多扣 20。\n'
 '  三查 落款要素（20 分）：公文类文种须有发文机关署名与成文日期，各 10 分；'
 '（文种本身不需要落款时——讲话、理论文章、书评体体会等——本查按满分计，不扣分）。\n'
 '  四查 文本洁净度（20 分）：出现以下每类扣 5 分——重复标题或重复发文字号；'
 '网页页脚或网站标识；图片说明/摄影署名混入正文；跨篇内容串扰；零宽字符或占位符残留。\n'
 '  档位对照：95-100 四查全过；85-94 构件齐、仅 1-2 处层次或洁净缺陷；'
 '70-84 缺 1 个必备构件或 ≥3 处层次/洁净缺陷；55-69 缺 2 个必备构件；'
 '40-54 缺 ≥3 个，或成稿只是片段；40 以下 明显截断/基本不是该文种。\n'
 '  本维 why 必须写成「构件核对：A有/B有/C缺；扣分：…；合计 N 分」形式，'
 '禁止出现"结构清晰完整"这类无核对过程的表述。证据引用**构件定位处**（标题/序号/落款）即可，'
 '不要因为正文小标题在抽取中丢失就判结构缺陷。\n'
 '\n'
 '【引用规范】权威表述与数据是否可核、引述是否合该文种惯例（文种不强制引用时不重罚）。\n'
 '\n'
 '【去AI味】是否为真人公文语感：有无"首先其次最后"式模板腔、空泛排比堆砌、'
 '无信息量的过渡句、英文式长句。\n'
 '\n'
 '只输出 JSON，键名与四维完全一致：'
 '{"风格贴合": {"score": n, "why": "..."}, "结构完整": {"score": n, "why": "..."}, '
 '"引用规范": {"score": n, "why": "..."}, "去AI味": {"score": n, "why": "..."}}。'
 '禁止使用其他维度名（如"内容贴合/逻辑结构/语言表达"）。')

def judge_one(task, draft):
    from llm_client import chat, JUDGE_MODEL
    _chat = lambda s, u: chat(s, u, model=JUDGE_MODEL)
    spec = task.get('structure_spec') or {}
    spec_txt = ''
    if spec.get('required'):
        spec_txt = ('\n【必备构件清单】' + '｜'.join(spec['required'])
                   + (f"（文种：{spec['doc_type']}）" if spec.get('doc_type') else ''))
        if spec.get('note'):
            spec_txt += '\n【体例提示】' + spec['note']
    user = (f"【写作任务】{task['title']}\n{task['brief']}"
            f"\n【风格/重点】{'，'.join(task['prite'])}{spec_txt}\n【成稿】\n{draft}")
    try:
        out = _chat(SYSTEM, user)
    except Exception as e:
        return {'error': str(e)}
    s = out[out.find('{'):out.rfind('}') + 1]
    try:
        res = json.loads(s)
    except Exception:
        return {'raw': out[:400]}
    # v6.9.0：四维名强校验——缺维/错名时带错误提示重试一次
    missing = [d for d in DIMS if d not in res]
    if missing:
        retry = _chat(SYSTEM + f'\n【注意】上一次输出维度名错误（{missing}）。必须严格输出四维 JSON，键名一字不差。',
                      user)
        s2 = retry[retry.find('{'):retry.rfind('}') + 1]
        try:
            res2 = json.loads(s2)
            if all(d in res2 for d in DIMS):
                return res2
        except Exception:
            pass
        return {'raw': out[:400], 'missing_dims': missing}
    return res

def draft_paths_for(task_id, draft_dir):
    """返回该任务的成稿文件（约定命名 <task_id>_<档位>.md，如 t01_A.md / t01_C.md）"""
    if not os.path.isdir(draft_dir):
        return []
    return sorted(os.path.join(draft_dir, f) for f in os.listdir(draft_dir)
                  if f.startswith(task_id + '_') and f.endswith('.md'))


def _run_one(t, draft_path):
    draft = open(draft_path, encoding='utf-8').read()
    return {'task': t['id'], 'title': t.get('title'), 'draft': os.path.basename(draft_path),
            'result': judge_one(t, draft)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--task', help='单任务 ID（与 --suite 二选一）')
    ap.add_argument('--draft', help='成稿文件路径（单任务模式）')
    ap.add_argument('--suite', action='store_true', help='跑全部任务（缺稿逐个提示）')
    ap.add_argument('--draft-dir', default=os.path.join(BASE, 'datahub', 'eval', 'drafts'),
                    help='成稿目录（suite 模式；约定命名 <task_id>_<档位>.md）')
    ap.add_argument('--out', help='结果 JSON 输出路径（suite 模式默认 datahub/eval/judge_results_suite.json）')
    a = ap.parse_args()

    if bool(a.task) == bool(a.suite):
        print('用法：--task <id> [--draft 文件]  或  --suite [--draft-dir 目录]（二者只能选一）',
              file=sys.stderr)
        return 2

    tasks = json.load(open(os.path.join(BASE, 'datahub', 'eval', 'judge_tasks.json'),
                           encoding='utf-8'))['tasks']

    if a.task:                                   # ---- 单任务 ----
        t = next((x for x in tasks if x['id'] == a.task), None)
        if not t:
            print(f'任务 {a.task} 不存在', file=sys.stderr)
            return 1
        if not a.draft or not os.path.exists(a.draft):
            print(f'缺成稿：{a.task} {t["title"]} —— 请用 --draft 提供成稿', file=sys.stderr)
            return 1
        print(json.dumps(judge_one(t, open(a.draft, encoding='utf-8').read()),
                         ensure_ascii=False, indent=1))
        return 0

    # ---- suite：全任务（缺稿与判分失败都显式计入，不静默跳过）----
    rows, missing, ok_n, err_n = [], [], 0, 0
    for t in tasks:
        paths = draft_paths_for(t['id'], a.draft_dir)
        if not paths:
            missing.append(t['id'])
            rows.append({'task': t['id'], 'title': t.get('title'), 'draft': None,
                         'result': {'status': 'MISSING_DRAFT'}})
            continue
        for p in paths:
            row = _run_one(t, p)
            res = row['result']
            # 「有稿」不等于「已判」：LLM 报错/维度缺失都不算判分成功
            if isinstance(res, dict) and not res.get('error') and not res.get('raw') \
                    and not res.get('missing_dims'):
                ok_n += 1
            else:
                err_n += 1
                row['result'].setdefault('status', 'JUDGE_FAILED')
            rows.append(row)

    out = a.out if (a.out and os.path.isabs(a.out)) else \
        os.path.join(BASE, 'datahub', 'eval', a.out or 'judge_results_suite.json')

    # ---- 聚合：按「结构是否可比」分池，避免节选范本拖低结构均分（rubric v2）----
    summary = {
        'tasks': len(tasks),
        'judged_ok': ok_n,
        'judge_failed': err_n,
        'missing_draft': list(missing),
    }

    def _score(res, dim):
        v = res.get(dim) if isinstance(res, dict) else None
        s = v.get('score') if isinstance(v, dict) else None
        return s if isinstance(s, int) else None

    pools = {'全文范本（结构可比）': [], '节选范本（结构不可比）': []}
    for row in rows:
        t = next((x for x in tasks if x['id'] == row['task']), None) or {}
        spec = t.get('structure_spec') or {}
        comp = spec.get('comparable')
        key = ('全文范本（结构可比）' if comp is True else
               '节选范本（结构不可比）' if comp is False else None)
        if not key or not isinstance(row['result'], dict):
            continue
        if row['result'].get('status') in ('MISSING_DRAFT', 'JUDGE_FAILED'):
            continue
        pools[key].append(row['result'])

    agg = {}
    for pool, rs in pools.items():
        if not rs:
            continue
        agg[pool] = {'n': len(rs)}
        for dim in DIMS:
            vals = [x for x in (_score(r, dim) for r in rs) if x is not None]
            # 结构维度在「节选池」里照打但不计入参考分——设计上已知不可比
            if dim == '结构完整' and pool.startswith('节选'):
                agg[pool][dim] = {'n': len(vals), 'mean': None,
                                  'note': '结构不可比（节选范本），不计入体例参考分'}
            elif vals:
                agg[pool][dim] = {'n': len(vals), 'mean': round(sum(vals) / len(vals), 1)}
    if agg:
        summary['aggregate'] = agg
    summary['rubric_version'] = RUBRIC_VERSION
    from pathlib import Path as _P
    _P(out).write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')

    print('=== suite 评测 ===')
    print(f'  rubric: {RUBRIC_VERSION}')
    print(f'  任务总数 {len(tasks)} ｜ 判分成功 {ok_n} ｜ 判分失败 {err_n} ｜ 缺稿 {len(missing)}')
    if err_n:
        print('  ⚠ 判分失败通常为 LLM 凭据/端点问题（先跑 release.py 的 faith 门禁探针确认端点可达性）')
    if missing:
        print(f'  缺稿任务: {" ".join(missing)}')
        print(f'  → 在 {a.draft_dir} 放置 <task_id>_<档位>.md 即可纳入评测')
    for pool, d in agg.items():
        dims = ' ｜ '.join(f'{k} {v.get("mean")}' for k, v in d.items()
                          if isinstance(v, dict) and v.get('mean') is not None)
        print(f'  [{pool}] n={d["n"]}: {dims}')
    if '全文范本（结构可比）' in agg and '节选范本（结构不可比）' in agg:
        a1 = (agg['全文范本（结构可比）'].get('结构完整') or {}).get('mean')
        a2 = (agg['节选范本（结构不可比）'].get('结构完整') or {}).get('mean')
        if a1 is not None and a2 is not None:
            print(f'  结构分池对照：全文 {a1} vs 节选 {a2}（差 {round(a1 - a2, 1)} 分）'
                  '——锚定口径应能拉开明显差距；若差距小，说明口径仍未锚定')
    print(f'  结果: {out}')
    return 0 if ok_n or not err_n else 1

if __name__ == '__main__':
    sys.exit(main())
