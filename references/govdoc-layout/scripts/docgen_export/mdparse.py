# -*- coding: utf-8 -*-
"""Markdown 成稿解析：分块、语义 section 归组、标题对称回行、段落类型启发。

数据模型（dataclass，纯值对象）：
  Block(kind, text, level)   —— 行级块：heading/paragraph/image
  Section(heading, blocks)   —— ## 二级标题归组后的语义 section
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Block:
    kind: str          # heading | paragraph | image
    text: str
    level: int = 0
    src: str | None = None


@dataclass
class Section:
    heading: str
    blocks: list = field(default_factory=list)


_H_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_IMG_RE = re.compile(r"^!\[(.*?)\]\((.+?)\)\s*$")

# 四层标题编号（GB/T 9704：一、 /（一）/ 1. /（1））
_NUM1 = re.compile(r"^[一二三四五六七八九十百千]+、")
_NUM2 = re.compile(r"^（[一二三四五六七八九十百千]+）")
_NUM3 = re.compile(r"^\d+[\.．]")
_NUM4 = re.compile(r"^（\d+）")

_DATE = re.compile(r"^\d{4}年\d{1,2}月\d{1,2}日$")


def parse(text: str) -> list[Block]:
    blocks: list[Block] = []
    para: list[str] = []

    def flush():
        if para:
            blocks.append(Block("paragraph", "\n".join(l.rstrip() for l in para).strip()))
            para.clear()

    for raw in text.splitlines():
        m = _H_RE.match(raw)
        if m:
            flush()
            blocks.append(Block("heading", m.group(2).strip(), len(m.group(1))))
            continue
        im = _IMG_RE.match(raw.strip())
        if im:
            flush()
            blocks.append(Block("image", im.group(1).strip(), src=im.group(2).strip()))
            continue
        if not raw.strip():
            flush()
            continue
        para.append(raw)
    flush()
    return blocks


def group(blocks: list[Block]):
    """首个 level1 heading = 文件标题；level2 heading = section 边界；
    首个 level2 之前的内容归入**隐式小节「正文」**。

    v7.5.1 修复（静默数据丢失）：原实现 `cur` 初值为 None，且只在 `cur is not None`
    时才收块，于是**首个 `## ` 之前的所有段落被静默丢弃**——平铺 Markdown 输入
    （只有 `# 标题` + 正文，无 `## `）会产出**只有一个标题**的 docx，而引擎照样打印
    `[OK] 已生成` 并返回 0。本包多处文档写着"平铺 Markdown 也可直接导出"，
    故必须支持而非报错。
    """
    title, sections, cur = None, [], None
    for b in blocks:
        if title is None and b.kind == 'heading' and b.level == 1:
            title = b.text          # 第一个一级标题只作文档标题，不进正文
            continue
        if b.kind == 'heading' and b.level == 2:
            cur = Section(b.text, [])
            sections.append(cur)
            continue
        if cur is None:             # 隐式小节：接住首个 ## 之前的正文
            cur = Section('正文', [])
            sections.append(cur)
        cur.blocks.append(b)
    return title, sections


def para_kind(text: str) -> str | None:
    """正文段落是否为编号标题：level1/2/3/4 或 None。"""
    first = text.split("\n", 1)[0].strip()
    if _NUM1.match(first):
        return "level1"
    if _NUM2.match(first):
        return "level2"
    if _NUM3.match(first):
        return "level3"
    if _NUM4.match(first):
        return "level4"
    return None


def is_date(text: str) -> bool:
    return bool(_DATE.match(text.strip()))


def wrap_title(text: str, max_chars: int = 20, enabled: bool = True) -> str:
    """长标题对称回行：逐行不增、标点后断行优先、避开开括号起行。

    返回带 \n 的标题文本（调用方按行渲染多段落）。
    """
    t = text.strip()
    if not enabled or len(t) <= max_chars:
        return t
    n = (len(t) + max_chars - 1) // max_chars
    while n > 1 and (len(t) + n - 2) // (n - 1) <= max_chars:
        n -= 1                      # 能减一行更美观（每行更接近均分）
    min_seg = 4 if len(t) >= 8 else 2
    cuts, prev_len = [], None
    pos = 0
    for i in range(n - 1):
        remain_lines = n - i
        target = min((len(t) - pos) // remain_lines, max_chars)
        lo = max(pos + min_seg, target - 4)
        hi = min(pos + max_chars, len(t) - (remain_lines - 1) * min_seg)
        best, best_score = None, float("inf")
        for p in range(lo, min(hi, len(t) - 1) + 1):
            seg = p - pos
            if prev_len and seg > prev_len:
                continue
            score = abs(seg - target) * 10
            if t[p - 1] in "，、：；":
                score -= 12          # 标点后断
            if t[p] in "（《【“":
                score += 40          # 避开开括号起行
            if t[p] in "，。！？、：；）》】”":
                score += 40          # 避开闭标点起行
            if t[p] in "的了和与及并或等":
                score += 8
            if score < best_score:
                best, best_score = p, score
        p = best or min(pos + target, len(t))
        cuts.append(p)
        prev_len = p - pos
        pos = p
    cuts.append(len(t))
    lines, start = [], 0
    for c in cuts:
        lines.append(t[start:c])
        start = c
    return "\n".join(x for x in lines if x)
