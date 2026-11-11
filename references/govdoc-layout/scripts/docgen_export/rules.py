# -*- coding: utf-8 -*-
"""GB/T 9704—2012 版式常量与文种-版式方案绑定。

单位约定：一律用 twips（1/20 磅）承载精确版式；与 Word 的对应关系由 opc 层统一转换。
"""
from __future__ import annotations

try:                      # Python 3.11+
    import tomllib
except ImportError:       # Python 3.10：回退 tomli；两者皆无则只走代码默认绑定
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # type: ignore

from pathlib import Path

# ---- 页面（twips；1mm≈56.6929）----
PAGE_W, PAGE_H = 11906, 16838                    # A4 纵向
MARGIN = dict(top=2098, bottom=1984, left=1587, right=1474)   # 37/35/28/26 mm
PRINT_W = PAGE_W - MARGIN["left"] - MARGIN["right"]            # 版心宽 156mm
PRINT_H = PAGE_H - MARGIN["top"] - MARGIN["bottom"]            # 版心高 225mm
CHARS_PER_LINE = 28                                            # 每行 28 字

# ---- 字体字号（GB/T 9704：标题小标宋二号，层级三号，正文三号仿宋）----
FONTS = {
    "title":   ("方正小标宋简体", 22),
    "header":  ("方正小标宋简体", 26),        # 版头「XX文件」大字
    "h1":      ("黑体", 16),
    "h2":      ("楷体_GB2312", 16),
    "h3":      ("仿宋_GB2312", 16),           # 国标：三级标题不加粗
    "h4":      ("仿宋_GB2312", 16),
    "body":    ("仿宋_GB2312", 16),
    "small":   ("仿宋_GB2312", 14),           # 附注/版记（四号）
    "pagenum": ("宋体", 14),                  # 页码（四号宋体一字线）
}

# ---- 红头（发文机关标志）VML 艺术字 ----
# 「版头」段从"红色纯文本"升级为 **艺术字机关名 + 双红线**（GB/T 9704 版头区）。
# 几何默认值取自纪委样板（dsh-tool-hongtou 的 templates/document-skeleton.xml）；
# 宽度按机关名字数自适应、并按版心居中（版心宽用 PRINT_W 换算，不写死）。
# ⚠️ 本单位模板如另有规定（字号/字体/红线粗细/位置），改本字典即可，无需动 opc 层。
REDHEADER = dict(
    height_pt=51,        # 艺术字高度
    font=None,           # 艺术字字体；None = 用 FONTS["header"][0]
    char_pt=33.25,       # 每个汉字估算宽度（样板 12 字 399pt 推算）
    ascii_pt=16.6,       # 每个 ASCII 字符估算宽度
    min_width_pt=150,    # 艺术字最小宽度
    margin_pt=5.25,      # 艺术字/红线相对版心左缘的偏移（样板值）
    line_thick_pt=3.0,   # 粗红线
    line_fine_pt=1.5,    # 细红线
)
LINE_BODY = 579                                  # 28.95 磅固定行距
LINE_TITLE = 579
AFTER_TITLE = 579                                # 标题后空
SPACING_DOCNUM = 290                             # 发文字号段后
SPACING_HEADER = 290                             # 版头段后
SPACING_RECIPIENT = 0                            # 主送后
BEFORE_SIGNING = 579                             # 落款前
INDENT_BODY = "2chars"                           # 正文首行缩进 2 字符
SIGN_DATE_RIGHT = 400                            # 成文日期右空 4 字（盖章版）
SIGN_UNIT_RIGHT = 200                            # 署名右空 2 字（电子版）
END_MATTER = {"版记", "版记（可选）"}
MM_TO_DXA = 56.692913                            # 1mm ≈ 56.6929 twips

# ---- 格式档：页面几何分档（与 _LAYOUT_VARIANTS 的行距/段距维度正交）----
# 三者不改内容，只改「纸面几何」——也就是换一个文种后版面该长什么样。
# 分档依据 GB/T 9704-2012 第 10 章特定格式：
#   10.1 信函：上边缘距纸边 30mm（不是通用的 37mm），170mm 上粗下细红双线，
#        距下页边 20mm 处上细下粗红双线，首页不显示页码。
#   10.2 命令（令）：发文机关标志上边缘至版心上边缘 20mm。
#   8    横排表格：横向 A4 ＋ 225mm 表宽。
_FORMAT_DEFAULT = dict(
    family="default",
    page_w=PAGE_W, page_h=PAGE_H, landscape=False,
    margin_top=MARGIN["top"], margin_bottom=MARGIN["bottom"],
    margin_left=MARGIN["left"], margin_right=MARGIN["right"],
    footer_distance=1587,        # 通用档页脚距（同 pgMar w:footer）
    page_number="auto",          # auto=按文种默认；standard=单双页左右；none=不排页码
    letter_rule=False,           # 是否画信函专用上下红双线
    agency_before=0,             # 发文机关标志段前距（命令档用 mm_to_dxa(20)=1134）
    table_width=None,            # 表格宽度（横排档 12756 = 225mm）
)

_FORMATS = {
    "default": {},
    "letter": dict(family="letter", margin_top=1701, page_number="none",
                   footer_distance=1134, letter_rule=True),
    "command": dict(family="command", agency_before=round(20 * MM_TO_DXA),
                    page_number="standard"),
    "horizontal-table": dict(family="horizontal-table",
                             page_w=PAGE_H, page_h=PAGE_W, landscape=True,
                             table_width=12756, page_number="standard"),
}

#: 文种 → 格式档。与 _DOC_TYPE_BINDINGS 分开成另一条轴，
#: 因为「字体/行距」与「页面几何」是两件独立的事：信函的行距与通知一样，
#: 但页边距、红线、页码规则都不同。
_DOC_TYPE_FORMATS = {
    "信函": "letter",
    "命令": "command",
}


def resolve_format(doc_type=None, explicit=None):
    """格式档解析：显式 --format 优先，其次按文种自动绑定，最后回默认档。"""
    key = explicit or (_DOC_TYPE_FORMATS.get((doc_type or "").strip()) if doc_type else None)
    fmt = dict(_FORMAT_DEFAULT)
    fmt.update(_FORMATS.get(key or "default", {}))
    fmt["key"] = key or "default"
    return fmt

# ---- 文种 → 版式方案（TOML 声明主源 + 代码默认兜底）----
_PKG = Path(__file__).resolve().parent
_PROFILES_DIR = _PKG / "profiles"

_FONT_PRESETS = {
    None: FONTS,  # 默认：GB/T 9704 标准字体
    "noto-cjk": {"title": ("Noto Serif SC", 22), "header": ("Noto Serif SC", 26),
                 "h1": ("Noto Sans SC", 16), "h2": ("Noto Serif SC", 16),
                 "h3": ("Noto Serif SC", 16), "h4": ("Noto Serif SC", 16),
                 "body": ("Noto Serif SC", 16), "small": ("Noto Serif SC", 14),
                 "pagenum": ("Noto Sans SC", 14)},
}

_LAYOUT_VARIANTS = {
    None: dict(line=LINE_BODY, title_line=LINE_TITLE, after_title=AFTER_TITLE,
               after_docnum=SPACING_DOCNUM, after_header=SPACING_HEADER,
               after_recipient=SPACING_RECIPIENT, before_signing=BEFORE_SIGNING),
    "internal-readable": dict(line=600, title_line=600, after_title=600,
                              after_docnum=300, after_header=300,
                              after_recipient=600, before_signing=1800),
    # 讲话易读：供口头宣读的稿子——行距放宽便于视读，段距加大便于停顿
    "speech-readable": dict(line=640, title_line=640, after_title=640,
                            after_docnum=300, after_header=300,
                            after_recipient=400, before_signing=1200),
}

#: 文种 → (font_profile, layout_profile) 的**代码默认绑定**（任何 Python 版本可用）。
#: TOML（profiles/doc-types/<slug>/meta.toml）存在且可解析时覆盖本表。
#: v7.3.1：此前仅依赖 TOML，而包内并无 profiles/ 目录 → 绑定恒为空、
#: `--list-doc-types` 输出空、`--doc-type` 静默回落，SKILL.md 宣称的
#: 「三套 TOML 文种绑定」实为空操作。现补代码默认兜底 + 随包 TOML。
_DEFAULT_DOC_TYPE_BINDINGS = {
    # 法定公文：GB/T 9704 标准版式
    "通知": (None, None), "通报": (None, None), "报告": (None, None),
    "请示": (None, None), "批复": (None, None), "函": (None, None),
    "纪要": (None, None), "决定": (None, None), "意见": (None, None),
    "命令": (None, None), "公告": (None, None), "通告": (None, None),
    "议案": (None, None), "决议": (None, None), "公报": (None, None),
    # 讲话类：供口头宣读，讲话易读版式
    "讲话": (None, "speech-readable"), "致辞": (None, "speech-readable"),
    "发言": (None, "speech-readable"), "动员": (None, "speech-readable"),
    # 内部材料：一屏多字，内部易读版式
    "简报": (None, "internal-readable"), "信息": (None, "internal-readable"),
    "专报": (None, "internal-readable"), "内参": (None, "internal-readable"),
    # 事务性材料：标准版式
    "总结": (None, None), "调研": (None, None), "方案": (None, None),
    "计划": (None, None), "理论": (None, None), "心得": (None, None),
    "经验": (None, None), "制度": (None, None), "规定": (None, None),
    "办法": (None, None), "述职": (None, None), "任免": (None, None),
    "新闻": (None, None), "信函": (None, None), "公开信": (None, None),
}

_DOC_TYPE_BINDINGS = dict(_DEFAULT_DOC_TYPE_BINDINGS)   # 文种 → (font_variant, layout_variant)


def _load_bindings():
    """从 profiles/doc-types/*/meta.toml 读取文种绑定并覆盖代码默认。

    缺 profiles/ 目录、缺 tomllib、或单个 TOML 损坏 → 保留代码默认（不阻断导出）。
    """
    dt_dir = _PROFILES_DIR / "doc-types"
    if tomllib is None or not dt_dir.is_dir():
        return
    for meta in sorted(dt_dir.glob("*/meta.toml")):
        try:
            data = tomllib.loads(meta.read_text(encoding="utf-8"))
            name = (data.get("doc_type") or meta.parent.name.split("-", 1)[-1]).strip()
            if name:
                _DOC_TYPE_BINDINGS[name] = (data.get("font_profile"), data.get("layout_profile"))
        except Exception:
            continue  # 单个配置损坏不阻断导出（保留该文种的代码默认）


_load_bindings()


def is_known_doc_type(doc_type):
    return bool(doc_type) and doc_type.strip() in _DOC_TYPE_BINDINGS


def resolve(doc_type: str | None, font_preset: str | None = None,
            layout_variant: str | None = None):
    """文种 + 可选覆盖 → (fonts, layout)。

    未知文种**不再静默**：仍返回默认方案以保证可用，但调用方应先用
    `is_known_doc_type()` 判定并告警/非零退出（engine 已如此处理）。
    """
    layout = layout_variant
    if doc_type and not (font_preset or layout_variant):
        fv, lv = _DOC_TYPE_BINDINGS.get(doc_type.strip(), (None, None))
        if lv in _LAYOUT_VARIANTS:
            layout = lv
    fonts = dict(_FONT_PRESETS.get(font_preset, FONTS))
    lay = dict(_LAYOUT_VARIANTS.get(layout, _LAYOUT_VARIANTS[None]))
    return fonts, lay


def list_doc_types():
    return sorted(_DOC_TYPE_BINDINGS)
