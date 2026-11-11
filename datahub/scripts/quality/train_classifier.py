#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L2 精品审核·第 3 步：轻量分类器替代逐篇 LLM（零 LLM 推理）

要回答的问题：**能不能用「确定性判据 + 少量 LLM 软标签」训一个小模型，替掉逐篇过 LLM？**
（依据：FineWeb-Edu 用 LLM 打 50 万篇软标签训 fastText 全量过滤；CCI3.0-HQ 用 Qwen2-72B
打 14.5 万样本训 BGE-M3+回归头，macro-F1 0.73 —— 都证明这条路成立。）

验证口径（重要）
----------------
用 **GroupKFold 按域名分组**做交叉验证：同一域名的文档不跨折，否则模型学到的是
"某市门户的排版"、指标虚高（这是弱监督/语料过滤的头号失败模式）。
⚠️ 抽样时我把 20% 域名整域留出了，但**留出域也没抽样**，所以那批没有标签可用；
这里改用域名分组交叉验证给域外估计——口径不同，报告里必须写清楚。

特征来源（全部零成本、已在库）
  · `quality_det.evidence_json`：paras / heads / outline_n / boiler / cjk_ratio / self_repeat13 /
    num_heads / layer_score / signed / has_attend / has_vote / leads 等逐项取值
  · `quality_det` 三列：struct / clean / fmt
  · `samples`：chars / clean_version
  · 实际文种（`evidence_json.eff_type`）one-hot

用法
----
  python train_classifier.py                 # 训练 + 分组交叉验证 + 报告
  python train_classifier.py --folds 5
"""
import argparse
import io
import json
import os
import sqlite3
import sys
from collections import Counter

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))          # datahub/
import paths                        # noqa: E402

DB = os.environ.get('GW_SAMPLES_DB') or paths.samples_db_path()
RULE_VER = 'v3'
NUM_FEATS = ('paras', 'outline_n', 'boiler', 'cjk_ratio', 'self_repeat13', 'num_heads',
             'layer_score', 'bad_char', 'urls', 'ascii_quote', 'cn_quote',
             'half_punct', 'odd_space', 'n_topics')
BOOL_FEATS = ('signed', 'has_attend', 'has_vote', 'lead', 'ends_clean',
              'has_call', 'type_corrected', 'non_article')


def host_of(u):
    import re
    m = re.match(r'https?://([^/]+)', u or '')
    d = (m.group(1) if m else '').lower()
    return d[4:] if d.startswith('www.') else d


def holdout_batches():
    """读 manifest，返回标了 holdout 的批号集合（模型**没见过这些域名**）"""
    p = os.path.join(os.path.dirname(DB), 'step2_batches', 's2_manifest.json')
    if not os.path.exists(p):
        return set()
    with io.open(p, encoding='utf-8') as f:
        man = json.load(f)
    return {b['batch'] for b in man.get('manifest', []) if b.get('holdout')}


def load():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    lab = {u: (t, b) for u, t, b in
           con.execute('SELECT url, tier, batch_id FROM quality_llm')}
    det = {}
    for u, s, c, f, v, e in con.execute(
            'SELECT url, struct, clean, fmt, verdict, evidence_json'
            ' FROM quality_det WHERE rule_ver=?', (RULE_VER,)):
        det[u] = (s, c, f, v, e)
    chars, content = {}, {}
    for u, ch, ct in con.execute('SELECT url, chars, content FROM samples'):
        if u in lab:
            chars[u] = ch
            content[u] = ct or ''
    con.close()
    rows, X, y, groups, is_hold = [], [], [], [], []
    hb = holdout_batches()
    for u, (tier, bid) in lab.items():
        d = det.get(u)
        if not d:
            continue
        s, c, f, v, e = d
        try:
            ev = json.loads(e or '{}')
        except Exception:
            ev = {}
        ct = content.get(u, '')
        feat = [s, c, f, float(chars.get(u) or 0) ** 0.5]
        for k in NUM_FEATS:
            val = ev.get(k)
            feat.append(float(val) if isinstance(val, (int, float)) else 0.0)
        for k in BOOL_FEATS:
            feat.append(1.0 if ev.get(k) else 0.0)
        # ★ 内容类特征（v2 追加）：结构特征分不出「内容充实」与「偏概括」，
        # 而 RUBRIC 的 ② 内容充实（有具体事实与量化数据）正是 A/B 的分界。
        feat.extend(content_feats(ct))
        et = ev.get('eff_type') or ''
        for g in ('会议纪要', '消息', '调研报告', '工作报告', '工作总结'):
            feat.append(1.0 if et == g else 0.0)
        feat.append(1.0 if v == 'C' else 0.0)
        X.append(feat)
        y.append(tier)
        groups.append(host_of(u))
        try:
            num = int(str(bid).split('_')[-1])
        except ValueError:
            num = -1
        is_hold.append(num in hb)
        rows.append(u)
    return (np.array(X, dtype=float), np.array(y), np.array(groups),
            np.array(is_hold, dtype=bool), rows, det)


#: 套话/程度词表（判「通篇表态、空话套话」用；取自公文常见空转表述）
CLICHE = ('高度重视', '扎实推进', '深入贯彻', '进一步加强', '不断完善', '切实', '有力',
          '扎实', '不断', '进一步', '认真', '严格', '积极', '全面', '着力', '大力')
DIGIT_RE = None


def content_feats(ct):
    """内容类特征：量化数据密度 / 套话密度 / 平均句长 / 标点占比

    为什么需要：结构特征（段落数、小标题、样板占比）能把 C 判得不错（F1 0.74），
    但 A 与 B 的分界在**内容**——「有具体事实与量化数据」对上「偏概括、数据少」。
    故补四个零成本的内容代理指标。
    """
    import re
    n = max(len(ct), 1)
    digits = len(re.findall(r'\d', ct))
    cliche = sum(ct.count(w) for w in CLICHE)
    sents = len(re.findall(r'[。！？]', ct)) or 1
    punct = len(re.findall(r'[，。；：、“”（）]', ct))
    body = re.sub(r'\s', '', ct)
    return [digits / n * 100,                    # 数字密度（量化数据）
            cliche / n * 1000,                   # 套话密度（每千字）
            len(body) / sents,                   # 平均句长
            punct / n,                           # 标点占比
            len(set(body)) / max(len(body), 1)]  # 字符去重率（用词丰富度）


def main():
    ap = argparse.ArgumentParser(description='L2 第 3 步：轻量分类器')
    ap.add_argument('--folds', type=int, default=5)
    ap.add_argument('--domain-holdout', action='store_true',
                    help='用 manifest 里标 holdout 的批次当**测试集**、其余当训练集——'
                         '这才是真正的域外验证（模型没见过那些域名）')
    a = ap.parse_args()

    X, y, groups, is_hold, urls, _det = load()
    print(f'样本 {len(y)} 条 ｜ 域名 {len(set(groups))} 个 ｜ 档位分布 '
          f'{dict(Counter(y))}')
    if is_hold.any():
        print(f'  其中域外（holdout 批次）{int(is_hold.sum())} 条 ｜ '
              f'域内 {int((~is_hold).sum())} 条')
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GroupKFold
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import f1_score, confusion_matrix

    def report(tag, ytrue, ypred):
        print(f'\n{tag}')
        print(f'  macro-F1 {f1_score(ytrue, ypred, average="macro"):.3f} ｜ '
              f'全判 B 基线 {f1_score(ytrue, np.array(["B"] * len(ytrue)), average="macro"):.3f}')
        for k in ('A', 'B', 'C'):
            print(f'  {k}: F1 {f1_score(ytrue, ypred, labels=[k], average="macro"):.3f}'
                  f' ｜ 真 {int(sum(ytrue == k)):3d} ｜ 预测 {int(sum(ypred == k)):3d}')
        cm = confusion_matrix(ytrue, ypred, labels=['A', 'B', 'C'])
        for i, k in enumerate('ABC'):
            print(f'  {k}: {list(cm[i])}')

    if a.domain_holdout and is_hold.any():
        tr, te = ~is_hold, is_hold
        sc = StandardScaler().fit(X[tr])
        clf = LogisticRegression(max_iter=2000, class_weight='balanced')
        clf.fit(sc.transform(X[tr]), y[tr])
        report(f'★ 真域外验证：训练 {int(tr.sum())} 条（{len(set(groups[tr]))} 域名）'
               f' → 测试 {int(te.sum())} 条（{len(set(groups[te]))} 个**未见域名**）',
               y[te], clf.predict(sc.transform(X[te])))
        return

    n_uniq = len(set(groups))
    folds = min(a.folds, n_uniq)
    gkf = GroupKFold(n_splits=folds)
    pred = np.array([''] * len(y), dtype=object)
    for tr, te in gkf.split(X, y, groups):
        sc = StandardScaler().fit(X[tr])
        clf = LogisticRegression(max_iter=2000, class_weight='balanced')
        clf.fit(sc.transform(X[tr]), y[tr])
        pred[te] = clf.predict(sc.transform(X[te]))
    report(f'按域名分组交叉验证（{folds} 折，同域不跨折）', y, pred)

    # 全量重训取系数（解释性）
    sc = StandardScaler().fit(X)
    clf = LogisticRegression(max_iter=2000,
                             class_weight='balanced').fit(sc.transform(X), y)
    names = (['struct', 'clean', 'fmt', 'sqrt_chars'] + list(NUM_FEATS)
             + list(BOOL_FEATS) + ['数字密度', '套话密度', '平均句长', '标点占比',
                                   '字符去重率']
             + ['type_纪要', 'type_消息', 'type_调研', 'type_报告',
                'type_总结', 'rule_veto_C'])
    print('\n最强特征（按 |系数| 排序，取 A 类）：')
    co = clf.coef_[list(clf.classes_).index('A')]
    for i in np.argsort(-np.abs(co))[:8]:
        print(f'  {names[i]:16s} {co[i]:+.3f}')


if __name__ == '__main__':
    sys.exit(main())
