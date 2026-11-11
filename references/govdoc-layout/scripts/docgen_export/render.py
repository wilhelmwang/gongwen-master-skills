# -*- coding: utf-8 -*-
"""语义 section → 段落规格列表（纯数据层，不碰 XML）。

段落规格（dict）字段：
  text, font, size, align(L/C/R), first_line(chars×100|0), right(chars×100),
  left(chars×100), line(twips), line_rule('exact'|'auto'), before(twips),
  after(twips), color(hex|None), border_top(hex|None), bold(bool)
"""
from __future__ import annotations

import re

from . import rules as R
from .mdparse import is_date, para_kind, wrap_title

_BOLDIFY = None  # 「一X是」强调在此实现层不做 run 级切分，保持段落纯文本；
#                 段首序词强调由 opc 层按规则在同段落内生成两个 run。


def _p(text, font, size, **kw):
    d = {"text": text, "font": font, "size": size, "align": "L",
         "first_line": 0, "right": 0, "left": 0,
         "line": R.LINE_BODY, "line_rule": "exact",
         "before": 0, "after": 0, "color": None,
         "border_top": None, "bold": False}
    d.update(kw)
    return d


def _signing_right_chars(unit: str, date_line: str, unsealed: bool) -> int:
    """署名与日期右端对齐：右空 = (日期宽 - 署名宽 + 4字)；下限 2 字。"""
    if unsealed:
        return R.SIGN_UNIT_RIGHT
    delta = len(date_line.strip()) - len(unit.strip()) + 4
    return max(R.SIGN_UNIT_RIGHT, delta * 100)


def render_title(title: str, lay: dict, title_max: int = 20) -> list[dict]:
    lines = wrap_title(title, title_max).split("\n")
    out = []
    for i, ln in enumerate(lines):
        out.append(_p(ln, F("title"), FSIZE("title"), align="C",
                      line=lay["title_line"], after=lay["after_title"] if i == len(lines) - 1 else 0))
    return out


def F(key):
    return R.FONTS[key][0]


def FSIZE(key):
    return R.FONTS[key][1]


# 仅作结构标记、不渲染为标题行的 section 名：
# 旧版把它们的默认值塞在 --hide-sections 的 defaults 里，而专门分支又不看 hidden，
# 于是“默认隐藏”实际上只对 `## 正文` 这个标题行生效，别的全是空操作。
# 现拆开：结构标记归结构标记（固定行为），hide 归 hide（用户显式控制）。
_MARKER_ONLY = {"标题", "主送单位", "正文", "落款"}


def _section_base(head: str) -> str:
    return head.replace("（可选）", "").strip()


def _hidden_mode(head: str, hidden: set) -> str:
    """该 section 的隐藏模式：'' | 'hide'（藏掉整节）| 'blank'（留白套打）。

    语法：`--hide-sections 版头` → 藏掉整节
          `--hide-sections 留白:版头` → 留白套打（只留高度，不画内容）
    两者区分是必要的：预印红头纸套打要把机关标志那块留白留出来，
    而“藏掉整节”是连位置都不要。旧版两者都做不到。
    """
    base = _section_base(head)
    for x in hidden:
        x = x.strip()
        if not x:
            continue
        blank = x.startswith("留白:")
        name = x.split(":", 1)[1].strip() if ":" in x else x
        if _section_base(name) == base:
            return "blank" if blank else "hide"
    return ""


def _reserve(sec, lay: dict) -> list[dict]:
    """留白套打：只发出一段“无内容但有高度”的段落。

    高度公式与上游 repo1 `letterheadReserveParagraph` 一致：
    before = (reserve_mm - 37) * 56.692913，因为版头留白的默认基准是天头 37mm。
    """
    reserve_mm = lay.get("reserve_mm", 72)
    before = max(0, round((reserve_mm - 37) * 56.692913))
    return [{"text": "", "font": F("body"), "size": 0,
             "before": before, "line": 1, "align": "C", "reserve": True}]


def render_section(sec, lay: dict, hidden: set, *, title_max: int = 20,
                   fmt: dict | None = None) -> list[dict]:
    """按语义 heading 分派渲染（含通用兜底：编号标题/普通正文）。

    隐藏判定放在**函数最前面**：旧版把 `if head not in hidden` 写在通用分支上，
    上面 9 个专门分支（版头/份号/密级/签发人/发文字号/版记/标题/主送单位/落款）
    直接 return，于是 `--hide-sections 版头` 之类的调用全部是空操作。

    fmt（格式档）只影响**页面几何相关**的渲染：信函的版头不画 VML 艺术字红头
    （它的红双线在字号下 4mm 处，是另一个东西），命令的发文机关标志段前距 20mm。
    内容与字体一律不受格式档影响。
    """
    fmt = fmt or R._FORMAT_DEFAULT
    head = sec.heading.strip()
    mode = _hidden_mode(head, hidden)
    if mode == "hide":
        return []
    if mode == "blank":
        return _reserve(sec, lay)
    out: list[dict] = []

    if head in {"版头", "版头（可选）"}:
        letter = fmt.get("family") == "letter"
        cmd_before = fmt.get("agency_before", 0)
        first = True
        for b in sec.blocks:
            if b.kind == "paragraph" and b.text:
                if first:
                    if letter:
                        # 信函：发文机关标志是居中红字，不走 VML 红头。
                        # 它下面的红双线由上方的 letter_rule 标记发出。
                        out.append(_p(b.text, F("header"), FSIZE("header"), align="C",
                                      line=lay["line"], color="FF0000"))
                        out.append({"letter_rule": "upper", "line": lay["line"]})
                    else:
                        # 首行 = 发文机关标志：交给 opc 层渲染 VML 艺术字 + 双红线（红头区）。
                        # 参数在 rules.REDHEADER；其余行仍按原文渲染为红色大字。
                        # 命令（令）：机关标志上边缘至版心上边缘 20mm → before=1134。
                        out.append(_p(b.text, F("header"), FSIZE("header"), align="C",
                                      line=lay["line"], after=lay["after_header"],
                                      before=cmd_before, vml="redheader"))
                    first = False
                else:
                    out.append(_p(b.text, F("header"), FSIZE("header"), align="C",
                                  line=lay["line"], after=lay["after_header"], color="C00000"))
        return out

    if head in {"份号", "份号（可选）"}:
        for b in sec.blocks:
            if b.kind == "paragraph" and b.text:
                out.append(_p(b.text, F("body"), FSIZE("body")))
        return out

    if head in {"密级", "密级（可选）", "紧急程度", "紧急程度（可选）"}:
        for b in sec.blocks:
            if b.kind == "paragraph" and b.text:
                out.append(_p(b.text, F("h1"), FSIZE("body")))
        return out

    if head in {"签发人", "签发人（可选）"}:
        for b in sec.blocks:
            if b.kind == "paragraph" and b.text:
                out.append(_p(b.text, F("h2"), FSIZE("body"), align="R", right=200))
        return out

    if head in {"发文字号", "发文字号（可选）"}:
        for b in sec.blocks:
            if b.kind == "paragraph" and b.text:
                has_tab = "\t" in b.text
                out.append(_p(b.text, F("body"), FSIZE("body"),
                              align="L" if has_tab else "C",
                              right=PRINT_W_TABSTOP if has_tab else 0,
                              after=lay["after_docnum"], border_top="FF0000"))
        return out

    if head in R.END_MATTER:
        for b in sec.blocks:
            if b.kind == "paragraph" and b.text:
                d = _p(b.text, F("small"), FSIZE("small"), border_top="000000")
                d["end_matter"] = True     # build_document 会把它们包成沉底浮动表
                out.append(d)
        return out

    if head == "标题":
        for b in sec.blocks:
            if b.kind == "paragraph" and b.text:
                out.extend(render_title(b.text, lay, title_max))
        return out

    if head == "主送单位":
        for b in sec.blocks:
            if b.kind == "paragraph" and b.text:
                out.append(_p(b.text, F("body"), FSIZE("body"), after=lay["after_recipient"]))
        return out

    if head == "落款":
        lines = [l.strip() for b in sec.blocks if b.kind == "paragraph"
                 for l in b.text.split("\n") if l.strip()]
        if not lines:
            return out
        unsealed_lay = lay.get("unsealed", False)
        date_right = R.SIGN_UNIT_RIGHT if unsealed_lay else R.SIGN_DATE_RIGHT
        if len(lines) == 1:
            rc = date_right if is_date(lines[0]) else R.SIGN_UNIT_RIGHT
            out.append(_p(lines[0], F("body"), FSIZE("body"), align="R", right=rc,
                          before=lay["before_signing"]))
            return out
        date_line = lines[-1]
        for i, unit in enumerate(lines[:-1]):
            out.append(_p(unit, F("body"), FSIZE("body"), align="R",
                          right=_signing_right_chars(unit, date_line, unsealed_lay),
                          before=lay["before_signing"] if i == 0 else 0))
        out.append(_p(date_line, F("body"), FSIZE("body"), align="R", right=date_right))
        return out

    if head in {"附注", "附注（可选）"}:
        for b in sec.blocks:
            if b.kind == "paragraph" and b.text:
                t = b.text.strip()
                if not (t.startswith("（") and t.endswith("）")):
                    t = f"（{t}）"
                out.append(_p(t, F("body"), FSIZE("body"), left=200))
        return out

    # 通用 section：heading 自身渲染（编号标题按层级），正文按段落启发
    # （结构标记名不渲为标题行；隐藏已在上方统一处置）
    if head not in _MARKER_ONLY:
        kind = para_kind(head)
        if kind:
            out.append(_numbered(head, kind))
        else:
            out.append(_p(head, F("h1"), FSIZE("h1")))
    for b in sec.blocks:
        if b.kind == "paragraph" and b.text:
            out.extend(render_body(b.text, lay, fmt))
        elif b.kind == "heading":
            out.append(_p(b.text, F("h1"), FSIZE("h1")))
    return out


PRINT_W_TABSTOP = R.PRINT_W  # 发文字号带 tab 时的右制表位


def _numbered(text: str, kind: str) -> dict:
    font, indent = {
        "level1": (F("h1"), True),
        "level2": (F("h2"), True),
        "level3": (F("h3"), True),   # 国标：三级仿宋不加粗、缩进 2 字
        "level4": (F("h4"), False),
    }[kind]
    d = _p(text, font, FSIZE("body"), bold=False)
    if indent:
        d["first_line"] = 200
    return d


def render_body(text: str, lay: dict | None = None,
                fmt: dict | None = None) -> list[dict]:
    """正文段 → 规格。首行是 Markdown 管道表时改出**表格规格**。"""
    if is_pipe_table(text):
        return [table_spec(text, lay, fmt)]
    lines = [l for l in text.split("\n") if l.strip()]
    if not lines:
        return []
    kind = para_kind(text)
    if kind and len(lines) > 1:
        # 编号标题 + 其下正文段
        return [_numbered(lines[0], kind),
                _p("\n".join(lines[1:]), F("body"), FSIZE("body"), first_line=200)]
    if kind:
        return [_numbered(lines[0], kind)]
    return [_p(text, F("body"), FSIZE("body"), first_line=200)]


def is_pipe_table(text: str) -> bool:
    """Markdown 管道表识别：首行含 |，且第二行是 |---| 分隔行。"""
    ls = [l.strip() for l in text.split("\n") if l.strip()]
    if len(ls) < 2 or "|" not in ls[0]:
        return False
    return bool(re.match(r"^\|?[\s:\-|]+\|?$", ls[1])) and "-" in ls[1]


def _cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def table_spec(text: str, lay: dict | None = None, fmt: dict | None = None) -> dict:
    """管道表 → 表格规格。宽度优先取格式档（横排档 225mm），否则版心宽 156mm。"""
    ls = [l for l in text.split("\n") if l.strip()]
    rows = [_cells(ls[0])] + [_cells(l) for l in ls[2:]]
    width = (fmt or {}).get("table_width") or R.PRINT_W
    return {"table": True, "rows": rows, "width": width,
            "line": (lay or {}).get("line", R.LINE_BODY)}
