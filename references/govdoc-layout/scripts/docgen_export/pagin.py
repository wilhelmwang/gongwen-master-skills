# -*- coding: utf-8 -*-
"""高度估算与版记沉底：影子渲染（只算行数，不产 XML）。"""
from __future__ import annotations

from . import rules as R
from .mdparse import para_kind, wrap_title

_END_MATTER_HEADINGS = R.END_MATTER


def _lines(text: str, max_chars: int = R.CHARS_PER_LINE) -> int:
    n = 0
    for ln in text.split("\n"):
        s = ln.strip()
        if s:
            n += max(1, (len(s) + max_chars - 1) // max_chars)
    return max(1, n)


def para_h(text: str, line: int, before: int = 0, after: int = 0,
           max_chars: int = R.CHARS_PER_LINE) -> int:
    return before + after + _lines(text, max_chars) * line


def section_h(sec, lay: dict, hidden: set, title_max: int = 20) -> int:
    from . import render as RD
    specs = RD.render_section(sec, lay, hidden, title_max=title_max)
    total = 0
    for d in specs:
        line = d.get("line") or lay["line"]
        total += d.get("before", 0) + d.get("after", 0) + _lines(d["text"]) * line
        if d.get("text", "").count("\n"):
            total += d["text"].count("\n")  # 已断行标题按多行
    return total


def end_matter_position(consumed: int, end_h: int) -> tuple[bool, int]:
    """返回 (是否分页, 版记前距)。

    版记须整体置于页底：当前页剩余足够 → 前距=剩余-高度（沉到底）；
    不足 → 整体移下一页，前距=页高-高度。"""
    if end_h <= 0:
        return False, 0
    if end_h >= R.PRINT_H:
        return (consumed % R.PRINT_H) != 0, 0
    remaining = R.PRINT_H - (consumed % R.PRINT_H)
    if end_h <= remaining:
        return False, remaining - end_h
    return True, R.PRINT_H - end_h
