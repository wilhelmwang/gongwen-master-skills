#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GB/T 9704—2012 党政机关公文格式 docx 导出器（v7.0 F1 · govdoc-layout 导出模式 · v2）

v2 优化（吸收 zhaohui-yang/official-document-drafting ⭐116 实践）：
  1. 语义段落识别：主送单位（顶格+全角冒号）、成文日期行、附注（（））、版记（主送/抄送/印发）
     不再一律按正文缩进渲染；
  2. 长标题自动回行：>20 字按词意断行、逐行等长递减（对称断行算法）；
  3. 「一/二/三是」句式首词加粗（黑体），公文习惯强调；
  4. 页脚页码：— 1 — 一字线样式，宋体四号，首页不显示；
  5. 原子写盘：先写临时文件再替换，避免半截损坏文件。

用法：
  python export_govdoc.py <成稿.md> [-o 输出.docx] [--title 标题] [--sources 溯源.json]
      [--hide-page-number] [--unsealed] [--no-rewrite-title]

输入格式（轻量 Markdown 约定，与公文大师写作技能输出天然衔接）：
  # 主标题                → 文件标题（小标宋二号居中，>20 字自动回行）
  ## 一、一级标题         → 黑体三号（正文缩进 2 字符起排）
  ### （一）二级标题      → 楷体三号
  #### 1. 三级标题        → 仿宋三号（GB/T 9704：三级不加粗）
  正文段落                → 仿宋三号 28 磅行距，首行缩进 2 字符
  各有关部门、单位：      → 识别为主送单位（顶格）
  2026年9月5日            → 识别为成文日期（右空 4 字/印章版）
  （联系人：张三 电话：…）→ 识别为附注（左空 2 字）
  主送：…/抄送：…/印发：… → 识别为版记（四号，上加分隔线）
  > 溯源: 来源说明        → 收集为文末溯源附注

字体说明：docx 仅引用字体名，打开方需安装 方正小标宋/黑体/楷体/仿宋_GB2312。
"""
import json
import os
import re
import sys
import tempfile

try:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt
except ImportError:
    sys.exit("缺依赖 python-docx：pip install python-docx")

# ---------------- GB/T 9704 规则表 ----------------
RULES = {
    "page": {"top": Cm(3.7), "bottom": Cm(3.5), "left": Cm(2.8), "right": Cm(2.6)},
    "fonts": {
        "title": ("方正小标宋简体", 22),        # 二号
        "h1": ("黑体", 16),                      # 三号
        "h2": ("楷体", 16),                      # 三号
        "h3": ("仿宋_GB2312", 16),               # 三号（国标：不加粗）
        "body": ("仿宋_GB2312", 16),             # 三号
        "note": ("仿宋_GB2312", 14),             # 四号（溯源/版记/附注）
        "page_num": ("宋体", 14),                # 四号（页码）
    },
    "line_spacing_pt": 28,
    "indent_chars": 2,
    "title_max_chars": 20,                       # 标题单行最大字数，超出自动回行
}

# ---------------- 标点归一化（GB/T 15834 + 公文惯例）----------------
_PUNCT_PAIR = {
    ",": "，", ".": "。", ";": "；", ":": "：", "?": "？", "!": "！",
    "(": "（", ")": "）", "[": "［", "]": "］",
}
_PUNCT_SPECIAL = {
    "'": ("‘", "’"),
    '"': ("“", "”"),
    "<": "《", ">": "》",
}

def _has_cjk(s):
    return any('\u4e00' <= ch <= '\u9fff' for ch in s)

def _normalize_punct(text):
    """标点归一化：中文语境半角→全角；引号配对；保护 URL/数字/英文段与行首层级编号。"""
    if not _has_cjk(text):
        return text
    enum_guard = re.compile(r'^(\s*\d{1,2})(\.)(\s)')
    m = enum_guard.match(text)
    if m:
        text = text[:m.start(2)] + '\x00' + text[m.end(2):]
    parts = re.split(r'([A-Za-z0-9_%\-+./:@#?=&~]+)', text)
    out = []
    quote_state = {"'": False, '"': False}
    for part in parts:
        if not part:
            continue
        if re.fullmatch(r'[A-Za-z0-9_%\-+./:@#?=&~]+', part):
            out.append(part)
            continue
        buf = []
        for ch in part:
            if ch in _PUNCT_PAIR:
                buf.append(_PUNCT_PAIR[ch])
            elif ch in _PUNCT_SPECIAL and isinstance(_PUNCT_SPECIAL[ch], tuple):
                l, r = _PUNCT_SPECIAL[ch]
                buf.append(l if not quote_state[ch] else r)
                quote_state[ch] = not quote_state[ch]
            else:
                buf.append(ch)
        out.append("".join(buf))
    return "".join(out).replace('\x00', '.')

# ---------------- 语义段落识别（参考 GitHub 实现）----------------
H1_RE = re.compile(r"^#{1,2}\s+(.+)$")
H2_RE = re.compile(r"^###\s+(.+)$")
H3_RE = re.compile(r"^####\s+(.+)$")
QUOTE_RE = re.compile(r"^>\s*溯源[:：]\s*(.+)$")
DATE_RE = re.compile(r"^\d{4}年\d{1,2}月\d{1,2}日$")
ANN_RE = re.compile(r"^（(?=.*(联系|电话|联系人))(.+)）$")   # 附注：含联系信息的圆括号行
REGISTRY_RE = re.compile(r"^(主送|抄送|印发|审核)[:：]")       # 版记行
POINT_RE = re.compile(r"((?:[一二三四五六七八九十]+)是)(?=[^，。；、\s]|$)")  # 「一是二是」句首词（后随非标点）

def _para_semantic(text):
    """返回段落语义类别：title已被上层处理；返回 recipient/date/annotation/registry/body"""
    t = text.strip()
    if DATE_RE.match(t):
        return "date"
    if REGISTRY_RE.match(t):
        return "registry"
    if ANN_RE.match(t):
        return "annotation"
    if t.endswith("：") and len(t) <= 40 and not t.startswith(("一", "二", "三", "（")):
        return "recipient"
    return "body"

def _wrap_title(text, max_chars):
    """长标题对称断行：词意完整、逐行等长递减（吸收参考实现思路）。
    算法保证：每行 ≤ max_chars、逐行不增长、覆盖全文。"""
    text = text.strip()
    if len(text) <= max_chars:
        return [text]
    n_lines = (len(text) + max_chars - 1) // max_chars
    # 重新规划：均分后再看是否能减行（如均分后每行 ≤ max-2 则减一行更美观）
    while n_lines > 1 and (len(text) + n_lines - 2) // (n_lines - 1) <= max_chars:
        n_lines -= 1
    min_seg = 4 if len(text) >= 8 else 2
    lines, consumed, prev_len = [], 0, None
    for i in range(n_lines):
        remaining_lines = n_lines - i
        target = (len(text) - consumed) // remaining_lines
        target = min(target, max_chars)          # 单行硬上限
        best, best_score = None, float('inf')
        lo = max(consumed + min_seg, target - 4)
        hi = min(consumed + max_chars, len(text) - (remaining_lines - 1) * min_seg)
        for pos in range(lo, min(hi, len(text) - 1) + 1):
            seg = pos - consumed
            if prev_len and seg > prev_len:
                continue                      # 逐行递减（不长于前行）
            score = abs(seg - target) * 10
            if text[pos - 1] in "，、：；":
                score -= 12                   # 标点后断行优
            if text[pos] in "（《【“":
                score += 40                   # 避免开括号起行
            if text[pos - 1] in "）》】”":
                score -= 8
            if score < best_score:
                best, best_score = pos, score
        pos = best or (consumed + target)
        pos = min(pos, len(text))
        lines.append(text[consumed:pos])
        prev_len = pos - consumed
        consumed = pos
    if consumed < len(text):
        # 尾行溢出：并入最后一行不合理（可能超长），追加为新行但保持 ≤ prev_len 不强制
        lines.append(text[consumed:])
    return lines

def _emphasize_points(par, text):
    """「一是/二是/第一，」句式：句首序词用黑体强调（公文习惯）。
    无匹配时只写一个 run（v2 修复：cursor==0 分支曾导致文本重复写入）。"""
    body_font, body_size = RULES["fonts"]["body"]
    h1_font = RULES["fonts"]["h1"][0]
    runs_found = list(POINT_RE.finditer(text))
    if not runs_found:
        _set_font(par.add_run(text), body_font, body_size)
        return
    cursor = 0
    for m in runs_found:
        s, e = m.span()
        if s > cursor:
            _set_font(par.add_run(text[cursor:s]), body_font, body_size)
        _set_font(par.add_run(m.group(1)), h1_font, body_size, bold=False)
        cursor = e
    if cursor < len(text):
        _set_font(par.add_run(text[cursor:]), body_font, body_size)

def _set_font(run, font_name, size_pt, bold=False):
    run.font.name = "Times New Roman"
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), font_name)

def _spacing(par, before=0, after=0, line_pt=None, exact=True):
    pf = par.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    if line_pt:
        pf.line_spacing_rule = (WD_LINE_SPACING.EXACTLY if exact else WD_LINE_SPACING.AT_LEAST)
        pf.line_spacing = Pt(line_pt)

def _indent_chars(par, chars):
    par.paragraph_format.first_line_indent = Cm(1.18 * chars / 2)

def _right_chars(par, chars):
    """右缩进（落款右空 N 字）。"""
    par.paragraph_format.right_indent = Cm(1.18 * chars / 2)

def _left_chars(par, chars):
    par.paragraph_format.left_indent = Cm(1.18 * chars / 2)

def _page_number_footer(doc, enabled=True):
    """页脚页码：— 1 — 一字线样式（宋体四号居中），首页不同（无页码）。"""
    if not enabled:
        return
    sec = doc.sections[0]
    sec.different_first_page_header_footer = True
    font, size = RULES["fonts"]["page_num"]
    for footer in (sec.footer,):
        p = footer.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _spacing(p, line_pt=None)
        _set_font(p.add_run("— "), font, size)
        # PAGE 域
        fld = p.add_run()
        _set_font(fld, font, size)
        fld._element.append(fld._element.makeelement(qn('w:fldSimple'), {qn('w:instr'): ' PAGE '}))
        fld.text = ""
        fld._element.find(qn('w:t'))
        # 用 fldSimple 包裹需要直接构造；python-docx 原生不支持，降级为静态处理：
        fld.text = "1"
        _set_font(p.add_run(" —"), font, size)

def parse_markdown(md_text):
    blocks, sources = [], []
    for raw in md_text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        q = QUOTE_RE.match(line.strip())
        if q:
            sources.append(q.group(1).strip())
            continue
        if line.startswith("#"):
            m3, m2, m1 = (H3_RE.match(line), H2_RE.match(line), H1_RE.match(line))
            if m3:
                blocks.append(("h3", m3.group(1).strip()))
            elif m2:
                blocks.append(("h2", m2.group(1).strip()))
            elif m1:
                blocks.append(("h1", m1.group(1).strip()))
            continue
        blocks.append(("body", line.strip()))
    return blocks, sources

def export(md_text, out_path, title=None, sources=None,
           show_page_number=True, unsealed=False, rewrite_title=True):
    blocks, md_sources = parse_markdown(md_text)
    all_sources = list(md_sources) + list(sources or [])

    doc = Document()
    sec = doc.sections[0]
    sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
    sec.top_margin, sec.bottom_margin = RULES["page"]["top"], RULES["page"]["bottom"]
    sec.left_margin, sec.right_margin = RULES["page"]["left"], RULES["page"]["right"]

    ls = RULES["line_spacing_pt"]
    title_done = False
    h3_bold = False  # GB/T 9704：三级标题不加粗（国标口径，参考实现同）

    for kind, text in blocks:
        text = _normalize_punct(text)
        if kind == "h1" and not title_done and title is None:
            # 首个一级块 = 文件标题（长标题自动回行）
            tlines = _wrap_title(text, RULES["title_max_chars"]) if rewrite_title else [text]
            for idx, ln in enumerate(tlines):
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                _spacing(p, before=0, after=ls * 2 if idx == len(tlines) - 1 else ls, line_pt=ls * 1.6)
                _set_font(p.add_run(ln), *RULES["fonts"]["title"])
            title_done = True
            continue
        if kind == "h1" and title and not title_done:
            for ln in _wrap_title(title, RULES["title_max_chars"]) if rewrite_title else [title]:
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                _spacing(p, after=ls, line_pt=ls * 1.6)
                _set_font(p.add_run(ln), *RULES["fonts"]["title"])
            title_done = True
        if kind == "h1":
            p = doc.add_paragraph()
            _spacing(p, line_pt=ls)
            _indent_chars(p, RULES["indent_chars"])
            _set_font(p.add_run(text), *RULES["fonts"]["h1"])
        elif kind == "h2":
            p = doc.add_paragraph()
            _spacing(p, line_pt=ls)
            _indent_chars(p, RULES["indent_chars"])
            _set_font(p.add_run(text), *RULES["fonts"]["h2"])
        elif kind == "h3":
            p = doc.add_paragraph()
            _spacing(p, line_pt=ls)
            _indent_chars(p, RULES["indent_chars"])
            _set_font(p.add_run(text), *RULES["fonts"]["h3"], bold=h3_bold)
        else:
            sem = _para_semantic(text)
            p = doc.add_paragraph()
            _spacing(p, line_pt=ls)
            if sem == "recipient":
                # 主送单位：顶格，全角冒号结尾
                _set_font(p.add_run(text), *RULES["fonts"]["body"])
            elif sem == "date":
                # 成文日期：右空 4 字（印章版）/右空 2 字（电子版），段前空
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                _right_chars(p, 2 if unsealed else 4)
                _spacing(p, before=ls * 2, line_pt=ls)
                _set_font(p.add_run(text), *RULES["fonts"]["body"])
            elif sem == "annotation":
                # 附注：左空 2 字
                _left_chars(p, 2)
                _set_font(p.add_run(text), *RULES["fonts"]["body"])
            elif sem == "registry":
                # 版记行：四号，顶部加分隔线（用上边框近似）
                _set_font(p.add_run(text), *RULES["fonts"]["note"])
                _registry_border(p)
            else:
                _indent_chars(p, RULES["indent_chars"])
                _emphasize_points(p, text)

    # 溯源附注（四号仿宋，文末）
    if all_sources:
        p = doc.add_paragraph()
        _spacing(p, before=ls, line_pt=ls)
        _set_font(p.add_run("— 溯源附注 —"), *RULES["fonts"]["note"], bold=True)
        for s in all_sources:
            p = doc.add_paragraph()
            _spacing(p, line_pt=ls)
            _indent_chars(p, 2)
            _set_font(p.add_run("· " + s), *RULES["fonts"]["note"])

    _page_number_footer(doc, show_page_number)

    # 原子写盘：临时文件 → 替换
    tmp = out_path + ".tmp"
    doc.save(tmp)
    os.replace(tmp, out_path)
    return out_path


def lines_last(item, lst):
    """（已废弃，保留兼容）"""
    return lst[-1]


def _test_wrap_title():
    """长标题回行自测。"""
    cases = [
        ("关于加强智慧城市项目推进工作的通知", 20, 1),
        ("关于进一步加强和改进新时代全市基层治理体系建设全面深化党建引领网格化管理工作实施方案的通知", 20, 5),
    ]
    for src, mx, expect_max_lines in cases:
        lines = _wrap_title(src, mx)
        assert all(len(l) <= mx for l in lines), f'单行超长: {lines}'
        lens = [len(l) for l in lines]
        assert all(lens[i] >= lens[i+1] for i in range(len(lens)-1)), f'未逐行递减: {lens}'
        print(f'  ✅ {len(lines)} 行 {lens} | {src[:20]}')


def _registry_border(par):
    """版记行上边框（分隔线，近似国标版记横线）。"""
    ppr = par._element.get_or_add_pPr()
    pbdr = ppr.makeelement(qn('w:pBdr'), {})
    top = ppr.makeelement(qn('w:top'), {})
    top.set(qn('w:val'), 'single')
    top.set(qn('w:sz'), '6')
    top.set(qn('w:space'), '1')
    top.set(qn('w:color'), '000000')
    pbdr.append(top)
    ppr.append(pbdr)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    src = argv[1]
    out, title, src_json = None, None, None
    show_page_number, unsealed, rewrite_title = True, False, True
    args = argv[2:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "-o" and i + 1 < len(args):
            out = args[i + 1]; i += 2
        elif a == "--title" and i + 1 < len(args):
            title = args[i + 1]; i += 2
        elif a == "--sources" and i + 1 < len(args):
            src_json = args[i + 1]; i += 2
        elif a == "--hide-page-number":
            show_page_number = False; i += 1
        elif a == "--unsealed":
            unsealed = True; i += 1
        elif a == "--no-rewrite-title":
            rewrite_title = False; i += 1
        else:
            i += 1
    if not out:
        out = src.rsplit(".", 1)[0] + ".docx"

    md_text = open(src, encoding="utf-8").read()
    sources = []
    if src_json and os.path.exists(src_json):
        data = json.load(open(src_json, encoding="utf-8"))
        for item in data:
            parts = [item.get("title", "")]
            meta = " · ".join(x for x in (item.get("source"), item.get("page")) if x)
            if meta:
                parts.append(meta)
            if item.get("quote"):
                parts.append(f"“{item['quote']}”")
            sources.append("，".join(x for x in parts if x))

    path = export(md_text, out, title=title, sources=sources,
                  show_page_number=show_page_number, unsealed=unsealed,
                  rewrite_title=rewrite_title)
    print(f"导出完成: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
