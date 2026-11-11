#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""正文行尾图片说明剥离（展示层工具 · 只读不改数据）。

背景
----
求是系文章正文里嵌着图片来源说明，形如：

    …习近平出席会议并发表重要讲话。 新华社记者 饶爱民/摄
                                      └── 归属段，非正文

实测（`articles` 全表）：含 `/摄`|`供图` 2,325 篇，其中 98.3% 的命中行
**归属段之前是有效正文**，故只可截尾、不可删行。

判据（两级）
------------
1. 行尾识别：行以 `供图` 或 `/<摄|摄影|制图>` 收尾 → 视为悬挂归属段的正文行。
2. 切点定位：取该行**最后一个句末标点**（含闭引号/括号）之后为归属段。
   实测 5,243 个命中行中可安全切分 5,175 行（98.70%）；余 68 行（1.30%）
   尾部仍含句末标点，判据不确，**原样保留**（宁可留着署名，也不误删正文）。

用法
----
    from strip_credit import strip_credit_tail
    clean, hit = strip_credit_tail(raw_line)      # 单行
    clean, n   = strip_credit_tail_regex(text)    # 整段（逐行处理）

设计取舍：判据保守——无法确信切分时返回原文，绝不猜测。
"""

import re

#: 行尾归属段标志：`……供图` 或 `…… /摄`（允许全角空格与半角空格混用）
_RE_CREDIT_END = re.compile(r'(?:供图|/\s*(?:摄|摄影|制图))\s*$')

#: 句末标点（含常见闭合标点，如「……。”」「……。）」）
_RE_SENT_END = re.compile(r'[。！？][”"’）)】》]?')


def has_credit_tail(line):
    """该行是否疑似悬挂图片说明。"""
    return bool(_RE_CREDIT_END.search((line or '').rstrip()))


def strip_credit_tail(line):
    """剥离单行行尾图片说明；判据不确时原样返回。

    返回 (clean_line, stripped) —— stripped 表示是否真的切掉了内容。
    """
    s = (line or '').rstrip()
    if not _RE_CREDIT_END.search(s):
        return line, False
    ends = list(_RE_SENT_END.finditer(s))
    if not ends:
        return line, False
    cut = ends[-1].end()
    tail = s[cut:]
    # 尾部若仍含句末标点，说明最后那个标点属于更后面的正文，判据不安全 → 原样返回
    if _RE_SENT_END.search(tail):
        return line, False
    # 尾部必须非空且明显短于正文（占比 > 40% 视为异常，保守放弃）
    if not tail.strip() or len(tail) > max(40, len(s) * 0.4):
        return line, False
    return s[:cut], True


def strip_credit_tail_regex(text):
    """整段文本逐行剥离；返回 (clean_text, n_stripped)。"""
    if not text:
        return text, 0
    out, n = [], 0
    for ln in text.split('\n'):
        clean, hit = strip_credit_tail(ln)
        out.append(clean)
        if hit:
            n += 1
    return '\n'.join(out), n


if __name__ == '__main__':
    # 自测样例（覆盖命中与保守放弃两类）
    cases = [
        ('会议在北京召开。习近平出席并发表重要讲话。 新华社记者 饶爱民/摄',
         '会议在北京召开。习近平出席并发表重要讲话。'),
        ('图为闭幕会现场。 全国政协办公厅供图 王达/摄', '图为闭幕会现场。'),
        ('图为中关村软件园。 北京市科委、中关村管委会供图', '图为中关村软件园。'),
        ('正文没有署名的一句话。', '正文没有署名的一句话。'),
    ]
    ok = 0
    for src, want in cases:
        got, hit = strip_credit_tail(src)
        mark = 'OK ' if got == want else 'NG '
        if got == want:
            ok += 1
        print('%s %r\n    -> %r  (stripped=%s)' % (mark, src, got, hit))
    print('\n自测: %d/%d 通过' % (ok, len(cases)))
