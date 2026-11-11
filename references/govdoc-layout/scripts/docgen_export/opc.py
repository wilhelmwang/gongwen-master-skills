# -*- coding: utf-8 -*-
"""WordprocessingML 生成 + OPC（.docx zip 包）打包，原子落盘。

零第三方依赖：docx 即 ZIP，内含 [Content_Types].xml / _rels / document.xml /
styles.xml / fontTable.xml / footer 部件，全部由字符串模板生成。
"""
from __future__ import annotations

import os
import zipfile
from xml.sax.saxutils import escape

from . import rules as R
from .mdparse import para_kind

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
#: officeDocument 关系命名空间。footerReference 等用 r:id 引用关系，
#: 根元素必须声明该前缀，否则产出的 XML 不合法（见 build_document 注释）。
#: ⚠️ 命名必须是 NS_R 而非 R —— 本模块顶部有 `import rules as R`，
#: 用 R 会把 rules 模块覆盖成字符串（v7.5.1 写这一行时踩过，engine 当场 AttributeError）。
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


# ---------- 红头（版头区）：VML 艺术字 + 双红线 ----------
# 来源：纪委样板真实片段（经 dsh-tool-hongtou/templates/document-skeleton.xml 提取）。
# VML 在 .docx 的 document.xml 里同样受支持（Word 与 WPS 均渲染），只需根元素声明下列命名空间。
NS_V = "urn:schemas-microsoft-com:vml"
NS_O = "urn:schemas-microsoft-com:office:office"
NS_W10 = "urn:schemas-microsoft-com:office:word"

# 艺术字类型定义（v:textpath）——样板原样复制。
TEXTPATH_SHAPETYPE = (
    '<v:shapetype id="_x0000_t136" coordsize="21600,21600" o:spt="136" adj="10800" '
    'path="m@7,l@8,m@5,21600l@6,21600e"><v:formulas><v:f eqn="sum #0 0 10800"/>'
    '<v:f eqn="prod #0 2 1"/><v:f eqn="sum 21600 0 @1"/><v:f eqn="sum 0 0 @2"/>'
    '<v:f eqn="sum 21600 0 @3"/><v:f eqn="if @0 @3 0"/><v:f eqn="if @0 21600 @1"/>'
    '<v:f eqn="if @0 0 @2"/><v:f eqn="if @0 @4 21600"/><v:f eqn="mid @5 @6"/>'
    '<v:f eqn="mid @8 @5"/><v:f eqn="mid @7 @8"/><v:f eqn="mid @6 @7"/>'
    '<v:f eqn="sum @6 0 @5"/></v:formulas><v:path textpathok="t" o:connecttype="custom" '
    'o:connectlocs="@9,0;@10,10800;@11,21600;@12,10800" o:connectangles="270,180,90,0"/>'
    '<v:textpath on="t" fitshape="t"/><v:handles>'
    '<v:h position="#0,bottomRight" xrange="6629,14971"/></v:handles>'
    '<o:lock v:ext="edit" text="t" shapetype="t"/></v:shapetype>'
)

# 双红线：样式与 Y 坐标保持样板值，仅 X 坐标按本工程版心宽（PRINT_W）计算。
RED_LINE_THICK = (
    '<v:line id="_x0000_s2067" style="position:absolute;left:0;text-align:left;z-index:1;'
    'mso-position-horizontal-relative:text;mso-position-vertical-relative:text" '
    'from="{x0}pt,53.2pt" to="{x1}pt,53.2pt" strokecolor="red" strokeweight="{w}pt"/>'
)
RED_LINE_FINE = (
    '<v:line id="_x0000_s2068" style="position:absolute;left:0;text-align:left;flip:y;z-index:2;'
    'mso-position-horizontal-relative:text;mso-position-vertical-relative:text" '
    'from="{x0}pt,60.65pt" to="{x1}pt,60.95pt" strokecolor="red" strokeweight="{w}pt"/>'
)


def _art_text_width(text: str) -> float:
    """机关名估算宽度：汉字按 char_pt、其余按 ascii_pt，夹在 [min_width, 版心宽] 之间。"""
    cfg = R.REDHEADER
    units = sum(cfg["char_pt"] if "\u2e80" <= ch <= "\uffef" else cfg["ascii_pt"] for ch in text)
    return max(cfg["min_width_pt"], min(R.PRINT_W / 20.0, round(units, 2)))


def redheader_xml(text: str, before: int = 0) -> str:
    """版头段：VML 艺术字（机关名）＋ 粗细双红线，位于同一段落内。

    几何全部来自 R.REDHEADER；改参数只需改 rules.py，不必动本函数。
    before：段前距（twips）。命令（令）档要求机关标志上边缘至版心上边缘 20mm → 1134，
    由调用方从格式档传入。**必须真写进段落的 w:spacing**：只把值传到 render 层而没落到 XML，
    参数就是被默默丢弃（通用段落走 para_xml 会写，版头走本函数不写——两条路径不一致）。
    """
    cfg = R.REDHEADER
    font = cfg["font"] or R.FONTS["header"][0]
    span = R.PRINT_W / 20.0                      # 版心宽（pt）
    m = cfg["margin_pt"]
    width = _art_text_width(text)
    margin_left = round((span - width) / 2 + m, 2)
    art = (
        f'<w:pict>{TEXTPATH_SHAPETYPE}'
        f'<v:shape id="_x0000_s2069" type="#_x0000_t136" '
        f'style="position:absolute;left:0;text-align:left;margin-left:{margin_left}pt;'
        f'margin-top:-4.2pt;width:{width}pt;height:{cfg["height_pt"]}pt;z-index:3;'
        f'mso-position-horizontal-relative:text;mso-position-vertical-relative:text" '
        f'fillcolor="red" strokecolor="red"><v:shadow color="#868686"/>'
        f'<v:textpath style="font-family:&quot;{font}&quot;;font-weight:bold;v-text-kern:t" '
        f'trim="t" fitpath="t" string="{_esc(text)}"/></v:shape></w:pict>'
    )
    thick = RED_LINE_THICK.format(x0=round(m, 2), x1=round(m + span, 2), w=cfg["line_thick_pt"])
    fine = RED_LINE_FINE.format(x0=round(m - 0.15, 2), x1=round(m + span - 0.10, 2),
                                w=cfg["line_fine_pt"])
    # rPr 与 run_xml 保持一致（只写 w:rFonts，不发 wx: 前缀——根元素未声明 xmlns:wx，
    # 发出去会产出 unbound prefix，严格 XML 解析器会崩）。w:noProof 抑制红头区拼写波浪线。
    rpr = (f'<w:rPr><w:rFonts w:ascii="{font}" w:fareast="{font}"/>'
           f'<w:noProof/><w:sz w:val="32"/></w:rPr>')
    return (
        '<w:p><w:pPr><w:jc w:val="center"/>'
        f'<w:spacing w:before="{before}" w:after="0" w:line="579" w:lineRule="exact"/>'
        '</w:pPr>'
        f'<w:r>{rpr}{art}</w:r>'
        f'<w:r>{rpr}<w:pict>{thick}</w:pict></w:r>'
        f'<w:r>{rpr}<w:pict>{fine}</w:pict></w:r>'
        '</w:p>'
    )


# ---------- run / 段落 XML ----------

def _esc(s: str) -> str:
    return escape(s)


def run_xml(text: str, font: str, size_pt: int, bold: bool = False,
            color: str | None = None) -> str:
    half = size_pt * 2
    bold_xml = "<w:b/>" if bold else ""
    color_xml = f'<w:color w:val="{color}"/>' if color else ""
    return (
        "<w:r><w:rPr>"
        f'<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" '
        f'w:eastAsia="{_esc(font)}" w:cs="Times New Roman"/>'
        f"{bold_xml}{color_xml}"
        f'<w:sz w:val="{half}"/><w:szCs w:val="{half}"/>'
        "</w:rPr>"
        f'<w:t xml:space="preserve">{_esc(text)}</w:t></w:r>'
    )


def _emphasis_runs(text: str, font: str, size_pt: int):
    """「一是/二是」句首序词切 run（黑体强调）。

    规则：序词（X是）后随非标点才算句首；避免「思想是」误伤。
    """
    import re
    pat = re.compile(r"([一二三四五六七八九十]+是)(?=[^，。；、\s]|$)")
    h1 = R.FONTS["h1"][0]
    out, cursor, matched = [], 0, False
    for m in pat.finditer(text):
        matched = True
        if m.start() > cursor:
            out.append(run_xml(text[cursor:m.start()], font, size_pt))
        out.append(run_xml(m.group(1), h1, size_pt))
        cursor = m.end()
    if not matched:
        return [run_xml(text, font, size_pt)]
    if cursor < len(text):
        out.append(run_xml(text[cursor:], font, size_pt))
    return out


_ALIGN = {"L": "left", "C": "center", "R": "right", None: "left"}


def _indent_xml(d: dict) -> str:
    # 字符缩进换 twips：版心 156mm/28 字 ≈ 848 twips/字
    per_char = R.PRINT_W // R.CHARS_PER_LINE
    parts = []
    if d.get("first_line"):
        v = round(d["first_line"] / 100 * per_char)
        parts.append(f'w:firstLineChars="{d["first_line"]}" w:firstLine="{v}"')
    if d.get("right"):
        v = round(d["right"] / 100 * per_char)
        parts.append(f'w:rightChars="{d["right"]}" w:right="{v}"')
    if d.get("left"):
        v = round(d["left"] / 100 * per_char)
        parts.append(f'w:leftChars="{d["left"]}" w:left="{v}"')
    return f"<w:ind {' '.join(parts)}/>" if parts else ""


def table_xml(d: dict) -> str:
    """管道表 → OOXML 表格。等分列宽，表头灰底加粗，行高按行距估算。"""
    rows = d.get("rows") or []
    if not rows:
        return ""
    ncol = max(len(r) for r in rows)
    width = d.get("width") or R.PRINT_W
    col_w = width // ncol
    line = d.get("line") or R.LINE_BODY
    grid = "".join(f'<w:gridCol w:w="{col_w}"/>' for _ in range(ncol))
    out = []
    for i, row in enumerate(rows):
        cells = []
        head = (i == 0)
        for j in range(ncol):
            txt = row[j] if j < len(row) else ""
            shd = ('<w:shd w:val="clear" w:color="auto" w:fill="EDEDED"/>'
                   if head else "")
            cells.append(
                f'<w:tc><w:tcPr><w:tcW w:w="{col_w}" w:type="dxa"/>{shd}'
                '<w:tcMar><w:top w:w="80" w:type="dxa"/><w:left w:w="80" w:type="dxa"/>'
                '<w:bottom w:w="80" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tcMar>'
                '<w:vAlign w:val="center"/></w:tcPr>'
                f'<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="{line}" '
                'w:lineRule="exact"/></w:pPr>'
                f'{run_xml(txt, R.FONTS["body"][0], R.FONTS["body"][1], head)}</w:p></w:tc>')
        hdr = '<w:trPr><w:tblHeader/></w:trPr>' if head else ''
        out.append(f'<w:tr>{hdr}{"".join(cells)}</w:tr>')
    borders = (''.join(f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
                       for s in ("top", "left", "bottom", "right", "insideH", "insideV")))
    return ('<w:tbl><w:tblPr>'
            f'<w:tblW w:w="{width}" w:type="dxa"/>'
            f'<w:tblBorders>{borders}</w:tblBorders>'
            '<w:tblLayout w:type="fixed"/></w:tblPr>'
            f'<w:tblGrid>{grid}</w:tblGrid>{"".join(out)}</w:tbl>')


def para_xml(d: dict) -> str:
    # 表格（管道表 / 版记沉底浮动表）：不走段落路径。
    if d.get("table"):
        return table_xml(d)
    if d.get("end_matter_cell"):
        return ""        # 占位，已在 build_document 中整体成表
    # 信函红双线标记段。
    if d.get("letter_rule"):
        return letter_rule_xml(d["letter_rule"] == "upper")
    # 版头：走 VML 艺术字 + 双红线（红头区），非普通段落。
    if d.get("vml") == "redheader":
        return redheader_xml(d["text"], d.get("before") or 0)
    # 分页标记（版记沉底放不下时由 engine 插入）：只发一个分页符，不参与行高计算。
    if d.get("page_break"):
        return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
    # 留白套打（预印红头纸）：只保留高度，不画任何字符。
    # 不能直接用空 run —— 那样会带上正文字号，高度不可控。
    if d.get("reserve"):
        return (f'<w:p><w:pPr><w:spacing w:before="{d.get("before", 0)}" '
                f'w:after="0" w:line="1" w:lineRule="exact"/></w:pPr></w:p>')
    align = _ALIGN.get(d.get("align"), "left")
    jc = "" if align == "left" else f'<w:jc w:val="{align}"/>'
    ind = _indent_xml(d)
    rule = "exact" if d.get("line_rule") == "exact" else "atLeast"
    # 行距缺失必须显式报错，不能写出 line="None"：
    # 那会产出无法被解析器读取的 document.xml（int('None') 直接抛），
    # 而且症状出现在读侧的体检器里，排查要跨文件。
    if d.get("line") is None:
        raise ValueError(f'段落规格缺少 line（行距）：{sorted(d)} text={d.get("text", "")[:20]!r}')
    spacing = (f'<w:spacing w:before="{d.get("before", 0)}" '
               f'w:after="{d.get("after", 0)}" '
               f'w:line="{d.get("line")}" w:lineRule="{rule}"/>')
    border = ""
    if d.get("border_top"):
        border = ('<w:pBdr><w:top w:val="single" w:sz="6" w:space="1" '
                  f'w:color="{d["border_top"]}"/></w:pBdr>')
    ppr = f"<w:pPr>{jc}{ind}{border}{spacing}</w:pPr>"
    # 正文段启用「一X是」强调；标题/版头/版记等单 run
    if d.get("font") == R.FONTS["body"][0] and d.get("first_line"):
        runs = "".join(_emphasis_runs(d["text"], d["font"], d["size"]))
    else:
        runs = run_xml(d["text"], d["font"], d["size"], d.get("bold", False), d.get("color"))
    return f"<w:p>{ppr}{runs}</w:p>"


# ---------- 页脚（页码一字线，首页隐藏）----------

def footer_xml(font: str, size_pt: int) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:ftr xmlns:w="{W}">'
        '<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
        f'{run_xml("— ", font, size_pt)}'
        f'<w:fldSimple w:instr=" PAGE ">{run_xml("1", font, size_pt)}</w:fldSimple>'
        f'{run_xml(" —", font, size_pt)}'
        "</w:p></w:ftr>"
    )


def letter_footer_xml() -> str:
    """信函页脚：只放「距下页边 20mm 处」的上细下粗红双线，**不放页码**。

    GB/T 9704-2012 10.1：信函首页不显示页码，下页边 20mm 处另有一组红双线。
    """
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:ftr xmlns:w="{W}">{letter_rule_xml(upper=False)}</w:ftr>')


EMPTY_FOOTER_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<w:ftr xmlns:w="{W}"><w:p/></w:ftr>'
)


def styles_xml(default_font: str, size_pt: int, line: int) -> str:
    half = size_pt * 2
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:styles xmlns:w="{W}">'
        "<w:docDefaults><w:rPrDefault><w:rPr>"
        f'<w:rFonts w:ascii="{_esc(default_font)}" w:hAnsi="{_esc(default_font)}" '
        f'w:eastAsia="{_esc(default_font)}" w:cs="{_esc(default_font)}"/>'
        f'<w:sz w:val="{half}"/><w:szCs w:val="{half}"/>'
        "</w:rPr></w:rPrDefault>"
        "<w:pPrDefault><w:pPr>"
        f'<w:spacing w:line="{line}" w:lineRule="exact"/>'
        "</w:pPr></w:pPrDefault></w:docDefaults>"
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:name w:val="Normal"/></w:style></w:styles>'
    )


# 字体表：显式声明 altName（西文名）与 charset。
# 作用：Word 在按名称匹配不到宋体时会回退到 altName，避免静默替换成默认字体；
# charset=86（0x56）声明该字体为 GB2312 中文字体，影响标点与行高计算。
# 只写 w:name 不写 altName/charset 时，包是合法的，但跨机器打开时的字体回退行为不确定。
_FONT_ALTS = {
    "方正小标宋简体": ("FZXiaoBiaoSong-B05S", "86"),
    "仿宋_GB2312": ("FangSong_GB2312", "86"),
    "仿宋": ("FangSong", "86"),
    "黑体": ("SimHei", "86"),
    "楷体_GB2312": ("KaiTi_GB2312", "86"),
    "楷体": ("KaiTi", "86"),
    "宋体": ("SimSun", "86"),
    "Noto Serif SC": ("Noto Serif CJK SC", "86"),
    "Noto Sans SC": ("Noto Sans CJK SC", "86"),
}


def _font_entry(name: str) -> str:
    alt, charset = _FONT_ALTS.get(name, ("", "86"))
    extra = f'<w:altName w:val="{_esc(alt)}"/>' if alt else ""
    cs = f'<w:charset w:val="{charset}"/>' if charset else ""
    return (f'<w:font w:name="{_esc(name)}">{extra}{cs}'
            '<w:family w:val="auto"/><w:pitch w:val="variable"/></w:font>')


def font_table_xml(fonts: list[str]) -> str:
    items = "".join(_font_entry(f) for f in dict.fromkeys(fonts))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:fonts xmlns:w="{W}">{items}</w:fonts>')


# ---------- document.xml 组装 ----------

# ---------- 信函格式（GB/T 9704-2012 10.1）特有红双线 ----------
# 信函的线不是普通红头的双红线，而是「170mm 上粗下细」+「距下页边 20mm 处上细下粗」
# 两组，用无边框表格的两行红色填充模拟。宽度固定 170mm，与版心宽 156mm 无关。
LETTER_RULE_W = 9638          # 170mm（170 × 56.6929）


def _rule_fill_row(h_dxa: int) -> str:
    return ('<w:tr><w:trPr>'
            f'<w:trHeight w:val="{h_dxa}" w:hRule="exact"/>'
            '</w:trPr><w:tc><w:tcPr>'
            f'<w:shd w:val="clear" w:color="FF0000" w:fill="FF0000"/>'
            '</w:tcPr><w:p/></w:tc></w:tr>')


def _rule_gap_row(h_dxa: int) -> str:
    return ('<w:tr><w:trPr>'
            f'<w:trHeight w:val="{h_dxa}" w:hRule="exact"/>'
            '</w:trPr><w:tc><w:p/></w:tc></w:tr>')


def letter_rule_xml(upper: bool) -> str:
    """信函红双线：upper=True 上粗下细（放正文），False 上细下粗（放下页边 20mm 处）。

    行高单位为 twips（0.35mm ≈ 20 twips，0.25mm ≈ 14 twips）。
    用表格而非 VML：表格行高在 Word/WPS 里都稳定，且体检器能直接从 shd 判出填充色。
    """
    rows = ([20, 170, 14] if upper else [14, 170, 20])
    body = (_rule_fill_row(rows[0]) + _rule_gap_row(rows[1]) + _rule_fill_row(rows[2]))
    tbl = ('<w:tbl><w:tblPr>'
           f'<w:tblW w:w="{LETTER_RULE_W}" w:type="dxa"/>'
           '<w:tblpPr w:leftFromText="0" w:rightFromText="0" '
           'w:vertAnchor="text" w:horzAnchor="margin" w:tblpXSpec="center"/>'
           '<w:tblBorders><w:top w:val="none"/><w:left w:val="none"/>'
           '<w:bottom w:val="none"/><w:right w:val="none"/>'
           '<w:insideH w:val="none"/><w:insideV w:val="none"/></w:tblBorders>'
           '<w:tblLayout w:type="fixed"/></w:tblPr>'
           '<w:tblGrid><w:gridCol w:w="%d"/></w:tblGrid>%s</w:tbl>'
           % (LETTER_RULE_W, body))
    return f'<w:p><w:pPr><w:jc w:val="center"/></w:pPr>{tbl}</w:p>'


def end_matter_table_xml(cell_paras: list[str]) -> str:
    """版记：把整块内容包成一个**沉底浮动表**，交给 Word 自己排版。

    为什么不能用「算好前距再来一段」：那是影子渲染（pagin.end_matter_position 按
    已消耗高度估算剩余空间），估算偏差、字体替换引起的换行变化、渲染器忽略段前距，
    这三类都会让版记落点错位，而 XML 里看不出任何异常。
    `w:tblpYSpec="bottom"` 是声明式的：Word 自己把它贴到版心底缘，放不下就整表
    移到下一页，不需要我们猜高度。
    """
    rows = "".join(f'<w:tr><w:tc><w:tcPr><w:tcW w:w="{R.PRINT_W}" w:type="dxa"/>'
                    f'</w:tcPr>{p}</w:tc></w:tr>' for p in cell_paras)
    return ('<w:tbl><w:tblPr>'
            f'<w:tblW w:w="{R.PRINT_W}" w:type="dxa"/>'
            '<w:tblpPr w:leftFromText="0" w:rightFromText="0" '
            'w:vertAnchor="text" w:horzAnchor="margin" w:tblpYSpec="bottom"/>'
            '<w:tblBorders><w:top w:val="none"/><w:left w:val="none"/>'
            '<w:bottom w:val="none"/><w:right w:val="none"/>'
            '<w:insideH w:val="none"/><w:insideV w:val="none"/></w:tblBorders>'
            '<w:tblLayout w:type="fixed"/></w:tblPr>'
            f'<w:tblGrid><w:gridCol w:w="{R.PRINT_W}"/></w:tblGrid>'
            f'{rows}</w:tbl>')


def build_document(specs: list[dict], fonts: dict, lay: dict,
                   show_page_number: bool = True, fmt: dict | None = None) -> str:
    # 命名空间必须齐：footerReference 用了 r:id，若不声明 xmlns:r，
    # 产出的 XML 就是**不合法**的（unbound prefix）——Word 宽容能打开，
    # 但任何严格 XML 解析器都会崩（docgen_export/inspect_govdoc.py 的体检器即当场暴露此问题）。
    # v / o / w10 为版头 VML 艺术字与线条所需（无版头时不出现相应元素，声明闲置无害）。
    parts = ["<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
             f'<w:document xmlns:w="{W}" xmlns:r="{NS_R}" xmlns:v="{NS_V}" '
             f'xmlns:o="{NS_O}" xmlns:w10="{NS_W10}"><w:body>']
    for d in specs:
        # 版记：一组带 end_matter 标记的段落，不逐段发出，改拼成一个沉底浮动表。
        if not d.get("end_matter"):
            parts.append(para_xml(d))
            continue
        if d.get("_em_done"):
            continue
        em = [x for x in specs if x.get("end_matter")]
        d["_em_done"] = True
        for x in em:
            x["_em_done"] = True
        # 单元格段落一律不带 before：表格已经声明式地贴底了（见 end_matter_table_xml）。
        cell_paras = [para_xml({**x, "end_matter": False, "before": 0}) for x in em]
        parts.append(end_matter_table_xml(cell_paras))
    fmt = fmt or R._FORMAT_DEFAULT    # 分节属性：页面几何取自格式档（信函 30mm 天头 / 横排 A4 / 通用 37mm），
    # 不再恒用 R.MARGIN——那是通用档的值，硬写进去会让信函与横排档几何全错。
    letter_rule = bool(fmt.get("letter_rule"))
    footer_ref = ('<w:footerReference w:type="default" r:id="rId2"/>'
                  if (show_page_number or letter_rule) else "")
    orient = '<w:orient w:val="landscape"/>' if fmt.get("landscape") else ""
    pg = (f'<w:pgSz w:w="{fmt["page_w"]}" w:h="{fmt["page_h"]}">{orient}</w:pgSz>'
          f'<w:pgMar w:top="{fmt["margin_top"]}" w:bottom="{fmt["margin_bottom"]}" '
          f'w:left="{fmt["margin_left"]}" w:right="{fmt["margin_right"]}" '
          f'w:footer="{fmt["footer_distance"]}" w:gutter="0"/>')
    sect = (f'<w:sectPr>{footer_ref}{pg}<w:titlePg/></w:sectPr>'
            if (show_page_number or letter_rule) else f'<w:sectPr>{pg}</w:sectPr>')
    parts.append(sect + "</w:body></w:document>")
    return "".join(parts)


# ---------- OPC 打包 ----------

def write_docx(path: str, document_xml: str, title: str,
               fonts: list[str], default_font: str, line: int,
               show_page_number: bool, footer_font: str, footer_size: int,
               fmt: dict | None = None) -> str:
    tmp = path + ".tmp"
    fmt = fmt or R._FORMAT_DEFAULT
    letter_rule = bool(fmt.get("letter_rule"))
    # 部件声明与文档关系必须与 sectPr 的实际引用三处一致（CT ↔ rels ↔ 引用）。
    # 隐藏页码时：不声明任何 footer 部件、不建 footer 关系、sectPr 也不引 —— 否则
    # rels 指向不存在的部件、或 CT 声明了未被引用的部件，都会被严格解析器判为破损包。
    # 信函例外：它也不排页码，但必须引页脚——那里放的是下页边 20mm 处的红双线。
    want_footer = show_page_number or letter_rule
    footer_ct = ('<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
                 if want_footer else '')
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '<Override PartName="/word/fontTable.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml"/>'
        + footer_ct
        + '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
        "</Relationships>"
    )
    doc_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        + ('<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>'
           if want_footer else '')
        + '<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable" Target="fontTable.xml"/>'
        "</Relationships>"
    )
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:title>{_esc(title)}</dc:title></cp:coreProperties>"
    )
    app = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
           "<Application>gongwen-docgen</Application></Properties>")

    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("word/document.xml", document_xml)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        z.writestr("word/styles.xml", styles_xml(default_font, 16, line))
        z.writestr("word/fontTable.xml", font_table_xml(fonts))
        if want_footer:
            z.writestr("word/footer1.xml",
                       letter_footer_xml() if letter_rule
                       else footer_xml(footer_font, footer_size))
        z.writestr("docProps/core.xml", core)
        z.writestr("docProps/app.xml", app)
    os.replace(tmp, path)
    return path
