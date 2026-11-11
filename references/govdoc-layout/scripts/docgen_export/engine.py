# -*- coding: utf-8 -*-
"""docx 导出统一入口（自研引擎）。

用法与语义 section 约定见模块 docstring（generate_docx.py 亦保留同签名入口）。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from . import mdparse, opc, pagin
from . import render as RD
from . import rules as R

# 默认不隐藏任何 section：
# 曾经的默认值 "标题,主送单位,正文,落款" 是个双重记账的错误设计——它想让「结构标记名」
# （标题/主送单位/正文/落款）不被渲染成标题行，但那是渲染层的职责，写在这里只会造成
# 「默认隐藏」实际只对 `## 正文` 生效（其余都是专用分支，根本不看 hidden）。
# 现在结构标记名的抑制固定在 render._MARKER_ONLY；标签默认不隐藏，用户显式给了就是用户的意思。
_HIDDEN_DEFAULT = ""

# ---------- 入参校验（事前拦截）----------
# 上游 repo1 的做法：文号/日期在**渲染之前**校验，不合法直接 exit 2；
# 本机此前只有 inspect_govdoc.py 事后体检（读已生成的 docx），事前无拦截。
# 两条正则与 repo1 一致，理由：标准要求六角括号、年份全称、顺序号非虚位、不写「第」。
_DOC_NO_RE = re.compile(r"^[^〔〕\[\]【】]+〔\d{4}〕[1-9]\d*号$")
_DATE_RE = re.compile(r"^(\d{4})年((?:[1-9]|1[0-2]))月((?:[1-9]|[12]\d|3[01]))日$")
# 占位符/模板值不参与校验（尚未填写不等于写错）
_PLACEHOLDER_RE = re.compile(r"【[^】]*】|X{2,}|待补|待填|〔YYYY〕|\\d\{4\}")


def _section_text(md: str, name: str) -> list[str]:
    """取 `## <name>` 小节下的非空正文行（不含标题行）。"""
    lines = md.splitlines()
    out, inside = [], False
    for ln in lines:
        if re.match(r"^\s*#{1,6}\s*", ln):
            inside = ln.lstrip("#").strip() == name
            continue
        if inside and ln.strip():
            out.append(ln.strip())
    return out


def validate_govdoc_fields(md: str) -> list[str]:
    """校验文号与成文日期。返回问题列表（空表示通过）。

    只在**能唯一识别**到该字段时判定：找不到就不报（草稿可缺）——
    这与「宁可漏报不可误报」一致，避免把未写的字段报成写错。
    """
    import datetime
    problems: list[str] = []

    doc_no_lines = _section_text(md, "发文字号") or [
        m.group(0) for m in re.finditer(r"[^\s〔〕\[\]【】]{1,20}〔\d{4}〕\d+号", md)]
    for raw in doc_no_lines[:1]:
        if _PLACEHOLDER_RE.search(raw):
            continue
        if not _DOC_NO_RE.match(raw):
            hint = "（不得含「第」、不得虚位补零）" if "第" in raw else ""
            problems.append(
                f"发文字号不符合规则：{raw!r}\n"
                f"    应为「机关代字〔年份全称〕非虚位顺序号号」，如「示例发〔2026〕1号」{hint}")

    date_lines = _section_text(md, "落款") or []
    date_lines = [ln for ln in date_lines if "日" in ln] + [
        m.group(0) for m in re.finditer(r"\d{4}年\d{1,2}月\d{1,2}日", md)]
    for raw in date_lines[:1]:
        raw = raw.strip()
        if _PLACEHOLDER_RE.search(raw):
            continue
        m = _DATE_RE.match(raw)
        if not m:
            problems.append(
                f"成文日期格式不符：{raw!r}\n"
                f"    应为 YYYY年M月D日（月/日不补零），如「2026年1月5日」")
            continue
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            datetime.date(y, mo, d)
        except ValueError:
            problems.append(f"成文日期不存在：{raw!r}（日历回验失败）")
        if not (1949 <= y <= 2100):
            problems.append(f"成文日期年份存疑：{raw!r}（应为 1949—2100）")
    return problems


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="将结构化公文 Markdown 导出为 GB/T 9704 版式 .docx（自研引擎）。")
    p.add_argument("input", nargs="?", type=Path, help="输入 Markdown 文件")
    p.add_argument("-o", "--output", type=Path, help="输出 docx，默认与输入同名")
    p.add_argument("--doc-type", help="按文种套用版式方案（见 --list-doc-types）")
    p.add_argument("--font-preset", choices=["noto-cjk"], help="开源字体预设（无版权字体环境用）")
    p.add_argument("--layout-variant", choices=["internal-readable", "speech-readable"],
                   help="版式变体：internal-readable（内部易读）/ speech-readable（讲话易读）")
    p.add_argument("--unsealed", action="store_true", help="电子版（不盖章）：落款右空 2 字")
    p.add_argument("--letterhead-reserve-mm", type=int, default=72,
                   help="预印红头纸套打的版头留白高度，mm（37—130，默认 72）")
    p.add_argument("--hide-page-number", action="store_true", help="隐藏页码")
    p.add_argument("--no-rewrite-title", action="store_true", help="关闭长标题自动回行")
    p.add_argument("--title-max-chars", type=int, default=20)
    p.add_argument("--show-font-plan", action="store_true", help="打印字体/版式方案后退出")
    p.add_argument("--list-doc-types", action="store_true", help="列出可用文种后退出")
    p.add_argument("--hide-sections", default=_HIDDEN_DEFAULT,
                   help="仅作结构标记、不渲染的 section（逗号分隔）；"
                        "显式列出的 section 会被藏掉，写 `留白:版头` 则只留高度不留内容")
    p.add_argument("--strict-args", action="store_true",
                   help="入参校验不过即中止（文号/日期格式；默认只告警）")
    p.add_argument("--format", default=None,
                   help="格式档（信函 letter / 命令 command / 横排表格 horizontal-table）；"
                        "不写则按文种自动绑定（信函→letter、命令→command）")
    p.add_argument("--org", default=None,
                   help="发文机关名称（命令（令）档用于机关标志；信函档用于发文机关标志）")
    return p.parse_args(argv)


def collect_specs(blocks, lay: dict, hidden: set, title_max: int, rewrite_title: bool,
                  fmt: dict | None = None):
    """全部段落规格（含标题与版记沉底）。"""
    fmt = fmt or R._FORMAT_DEFAULT
    title, sections = mdparse.group(blocks)
    specs: list[dict] = []
    consumed = 0

    # 无「标题」section 时，顶层标题先渲
    has_title_sec = any(s.heading.strip() == "标题" for s in sections)
    if title and not has_title_sec:
        t = title if rewrite_title else "\n".join(
            [title[i:i + title_max] for i in range(0, len(title), title_max)])
        specs.extend(RD.render_title(t, lay, title_max))
        consumed += pagin.para_h(t, lay["title_line"], after=lay["after_title"])

    end_matter = [s for s in sections if s.heading.strip() in R.END_MATTER]
    normal = [s for s in sections if s.heading.strip() not in R.END_MATTER]

    for sec in normal:
        sec_specs = RD.render_section(sec, lay, hidden, title_max=title_max, fmt=fmt)
        specs.extend(sec_specs)
        for d in sec_specs:
            if d.get("table") or d.get("letter_rule"):
                continue          # 表格与红线与版心行高无关，不进 consumed 估算
            consumed += pagin.para_h(d["text"], d.get("line") or lay["line"],
                                     d.get("before", 0), d.get("after", 0))

    for sec in end_matter:
        sec_specs = RD.render_section(sec, lay, hidden, fmt=fmt)
        end_h = sum(pagin.para_h(d["text"], d.get("line") or lay["line"],
                                 d.get("before", 0), d.get("after", 0))
                    for d in sec_specs)
        page_break, before = pagin.end_matter_position(consumed, end_h)
        # 注意：before 这里**只作估算参考，不能落到段落上**。
        # 浮动表（w:tblpYSpec="bottom"）已经交给 Word 自己贴底，此时单元格段落再带
        # before 会连同表格高度一起超出页面。
        if page_break:
            specs.append({"text": "", "font": "", "size": 0, "page_break": True})
        for d in sec_specs:
            specs.append(d)
    return specs, title


def main(argv=None) -> int:
    args = parse_args(argv)

    if args.list_doc_types:
        types = R.list_doc_types()
        if not types:
            print("❌ 无可用文种绑定（绑定表为空，配置异常）", file=sys.stderr)
            return 3
        print(f"可用文种（{len(types)} 个）—— 用 --doc-type <文种> 套用：")
        for dt in types:
            fv, lv = R._DOC_TYPE_BINDINGS.get(dt, (None, None))
            print(f"- {dt:6s} → 字体 {fv or '国标默认'} / 版式 {lv or '官方标准'}")
        return 0

    # 未知文种不再静默回落（v7.3.1）：告警 + 非零退出，避免"以为套用了实际没套"
    if args.doc_type and not R.is_known_doc_type(args.doc_type):
        print(f"❌ 未知文种 --doc-type {args.doc_type!r}：不在绑定表中，"
              f"不会套用任何专用版式。\n   可用文种见 --list-doc-types。", file=sys.stderr)
        return 2

    fonts, lay = R.resolve(args.doc_type, args.font_preset, args.layout_variant)
    lay = dict(lay)
    lay["unsealed"] = args.unsealed
    # 格式档：页面几何分档（信函 30mm/命令 20mm/横排 A4）。
    # 与文种绑定分开：`--doc-type 信函` 自动得 letter 档，也可用 --format 显式指定。
    fmt = R.resolve_format(args.doc_type, args.format)
    if args.format and args.format not in R._FORMATS:
        print(f"❌ 未知 --format {args.format!r}：可为 {'/'.join(R._FORMATS)}。", file=sys.stderr)
        return 2
    # 信函与命令档需要发文机关名称；缺失则报错而不静默套一个假名。
    if fmt.get("family") in ("letter", "command") and not args.org:
        print(f"❌ {fmt['family']} 格式档需要 --org（发文机关名称）。", file=sys.stderr)
        return 2
    if not 37 <= args.letterhead_reserve_mm <= 130:
        print(f"❌ --letterhead-reserve-mm 应在 37—130 之间，实得 {args.letterhead_reserve_mm}。",
              file=sys.stderr)
        return 2
    lay["reserve_mm"] = args.letterhead_reserve_mm

    if args.show_font_plan:
        src = f"文种 {args.doc_type}" if args.doc_type else (
            f"变体 {args.layout_variant}" if args.layout_variant else "默认方案")
        print(f"版式来源: {src}")
        for k in ("title", "h1", "h2", "h3", "body"):
            print(f"- {k}: {fonts[k][0]} / {fonts[k][1]}pt")
        print(f"- 正文行距: {lay['line']} twips / {lay['line'] / 20:.2f}pt")
        return 0

    if args.input is None:
        print("缺少输入 Markdown 文件。", file=sys.stderr)
        return 1

    md = args.input.read_text(encoding="utf-8")

    # 信函与命令档必须有发文机关标志（版头首行）。
    # 来源优先写稿的「## 版头」首行；`--org` 可覆盖——不静态套一个假名。
    if fmt.get("family") in ("letter", "command") and args.org:
        if re.search(r"^##\s*版头", md, re.M):
            md = re.sub(r"(^##\s*版头[^\n]*\n)([^\n]*)",
                        lambda m: m.group(1) + args.org, md, count=1, flags=re.M)
        else:
            md = f"## 版头\n{args.org}\n\n" + md
    if fmt.get("family") in ("letter", "command") and not re.search(r"^##\s*版头\s*$", md, re.M):
        print(f"❌ {fmt['key']} 格式档需要发文机关标志：请在 Markdown 写「## 版头」小节，"
              f"或传 --org <机关名称>。", file=sys.stderr)
        return 2

    # 事前拦截（v8.1.7）：本机此前只有 inspect_govdoc.py 事后体检，
    # 文号/日期写错要到生成后跑体检器才发现；改为渲染前先报。
    _problems = validate_govdoc_fields(md)
    if _problems:
        head = "❌ 入参校验未通过：" if args.strict_args else "⚠️  入参校验提示（本次仍会生成，加 --strict-args 可中止）："
        print(head, file=sys.stderr)
        for _p in _problems:
            print(f"  - {_p}", file=sys.stderr)
        if args.strict_args:
            return 2

    blocks = mdparse.parse(md)
    if not blocks:
        print("输入文件为空，无法生成 docx。", file=sys.stderr)
        return 1

    hidden = {x.strip() for x in args.hide_sections.split(",") if x.strip()}
    specs, title = collect_specs(blocks, lay, hidden,
                                 args.title_max_chars, not args.no_rewrite_title, fmt)

    doc_title = title or "公文稿件"
    # 兜底：正文规格为空时**不许静默产出**只含标题的文件（v7.5.1 前的 mdparse.group
    # 会丢弃首个 ## 之前的全部段落，曾导致"平铺 Markdown → 只有标题的 docx"且报 [OK]）
    if not specs:
        print("❌ 解析后无任何正文段落，已中止（不会产出只有标题的空文）。\n"
              "   请检查输入 Markdown 是否为空、或内容是否都在一级标题之下而无正文块。",
              file=sys.stderr)
        return 1
    # 平铺 Markdown 提示：无「## 落款」小节时，落款行会被当普通正文渲染
    # （无右空缩进）——体检器会如实报 WARN。此处给可操作提示，不静默。
    _heads = {s.heading.strip() for s in mdparse.group(blocks)[1]}
    if '落款' not in _heads and re.search(r'^\d{4}年\d{1,2}月\d{1,2}日$',
                                          '\n'.join(b.text for b in blocks if b.kind == 'paragraph'),
                                          re.M):
        print('  ⚠️  输入含成文日期但无「## 落款」小节 —— 落款行将按普通正文渲染（无右空缩进）。'
              '正式件建议加「## 落款」小节。', file=sys.stderr)
    show_pn = (not args.hide_page_number) and fmt.get("page_number") != "none"
    doc_xml = opc.build_document(specs, fonts, lay, show_page_number=show_pn, fmt=fmt)

    out = args.output or args.input.with_suffix(".docx")
    out.parent.mkdir(parents=True, exist_ok=True)
    font_names = [fonts[k][0] for k in ("header", "title", "h1", "h2", "h3", "body")]
    opc.write_docx(str(out), doc_xml, doc_title, font_names,
                   fonts["body"][0], lay["line"], show_pn,
                   fonts["pagenum"][0], fonts["pagenum"][1], fmt)
    print(f"[OK] 已生成 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
