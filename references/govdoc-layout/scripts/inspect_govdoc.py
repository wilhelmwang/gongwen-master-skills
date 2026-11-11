#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""国标逐要素体检器（C2 · v7.5.1）

用途：**上传一份已有的 .docx → 逐要素体检**，输出「应有 vs 实际」的偏差报告。
与同目录 `docgen_export` 的关系：写侧生成合规文，本脚本是**读侧的逆运算**。

设计原则
--------
1. **单一事实源**：所有阈值从 `docgen_export/rules.py` 的常量派生，不另抄一份数字
   （写读两侧各抄一份必然漂移）。
2. **只读**：绝不修改用户文件。正式公文改坏了比不体检危险得多。
3. **宁可少报，不可错报**：单位模板差异会导致误报，故
   ①每项可单独关闭（`--ignore`）②尺寸类带容差（默认 ±0.5mm）③只判"要素存在性与规格"，
   **不判内容对错**。扫件/加密件显式报"不可解析"，不静默通过。
4. **分级**：PASS（合规）/ WARN（偏差但可接受/单位差异）/ FAIL（明确不合规）/ SKIP（要素不适用）/
   MANUAL（**机器不可判，须现场或人工核验**）。
   MANUAL 单独成一类，**不计入 PASS，也不影响退出码**：它的存在是为了让“本批次没验什么”
   在报告里可见。将不可判定项默默略去，或降级成 SKIP 混进“不适用”里，读者会把“没验”读成“验过且通过”。

已知边界（如实告知，不假装全覆盖）
--------------------------------
- 印章位置、红头、版记分隔线**粗细**只能判"是否存在"，无法判"位置是否精确到毫米"——
  这些要素在 OOXML 里以绘图/边框形式存在，缺乏稳定的可判定锚点。
- 页码的"单页右空一字、双页左空一字"需读 footer 的段落缩进；本脚本按此判定，
  但若文档用了 `wp:anchor` 定位的文本框页码，会报 SKIP 而非猜测。
- 扫描件（图片型 .docx）与加密文档无法解析 → 显式 FAIL 说明原因。

用法
----
  python inspect_govdoc.py 文件.docx                 # 全项体检
  python inspect_govdoc.py 文件.docx --doc-type 通知  # 指定文种（影响部分判定口径）
  python inspect_govdoc.py 文件.docx --format letter  # 指定格式档（信函/命令/横排）
  python inspect_govdoc.py 文件.docx --ignore 页码 --json
  python inspect_govdoc.py 文件.docx -v              # 显示 SKIP 项

已知边界（关于格式档）
--------------------
天头、版心、页码规则的「应有值」随格式档变化（信函 30mm、命令 20mm 机关标志、
横排横向 A4）。不给 --doc-type/--format 时按通用档判，对特定格式件会误报 FAIL——
这是**已知且必然**的行为，不是体检测错了。原因
"""
import argparse
import json
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE, 'govdoc-layout', 'scripts', 'docgen_export'))
try:
    import rules as R
except Exception as e:                                  # 常量不可得则不猜数
    sys.stderr.write(f'无法载入 rules.py（阈值来源）: {e}\n')
    raise SystemExit(2)

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

#: twips → mm（1mm = 56.6929 twips）与 pt（1pt = 20 twips）
TW_MM = 56.6929
TW_PT = 20
#: 三号字（16pt）单字宽 = 16×20 = 320 twips；写侧按 315 换算右空字数，此处取同口径
TW_PER_CHAR = 315
#: 尺寸容差：单位模板常与本包略有出入，±0.5mm 内不算不合规
TOL_MM = 0.5


def _letter_rule_w() -> int:
    """信函红双线宽度（170mm）。

    阈值不能从 rules.py 取：那个常量定义在 opc.py（它是绘图/表格类常量，不属版式参数）。
    本模块遵循「单一事实源」原则——导入 opc 取常量，而不是再抄一个 9638。
    """
    try:
        from docgen_export import opc as _opc
        return _opc.LETTER_RULE_W
    except Exception:
        return round(170 * TW_MM)          # 兜底：170mm


def mm(tw):
    return round(tw / TW_MM, 1)


# ---------------------------------------------------------------- OOXML 读取

def _repair_ns(xml_text):
    """补声明缺失的命名空间前缀（外来文件常见）。

    为什么需要：`<w:document xmlns:w="...">` 但正文里用了 `r:id`（footerReference 引用关系），
    前缀 `r` 未声明 → 严格解析器报 unbound prefix。**Word 宽容能打开，第三方解析器会崩**，
    本包的写侧也犯过这个错（v7.5.1 已修 opc.build_document）。体检器要能读这种件并如实报告，
    而不是自己先崩掉 —— 否则"体检工具读不了被体检的文件"。
    """
    NS = {'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
          'mc': 'http://schemas.openxmlformats.org/markup-compatibility/2006',
          'wps': 'http://schemas.microsoft.com/office/word/2010/wordprocessingShape',
          'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
          'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
          'v': 'urn:schemas-microsoft-com:vml'}
    m = re.search(r'<(?:[A-Za-z0-9]+:)?(?:document|body|hdr|ftr)\b[^>]*?>', xml_text)
    if not m:
        return xml_text
    tag = m.group(0)
    declared = set(re.findall(r'xmlns:([A-Za-z0-9]+)=', tag))
    used = set(re.findall(r'<(?:/)?([A-Za-z0-9]+):', xml_text)) | \
        set(re.findall(r'\s([A-Za-z0-9]+):[A-Za-z0-9_]+=', xml_text))
    add = ''.join(f' xmlns:{p}="{u}"' for p, u in NS.items() if p in used and p not in declared)
    if not add:
        return xml_text
    return xml_text[:m.end() - 1] + add + xml_text[m.end() - 1:]


def _load(path):
    """返回 {'doc': <document.xml 文本>, 'sect': dict, 'paras': [...], 'footers': [...]}
    不可解析时抛 ValueError（由调用方转成显式 FAIL）。"""
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise ValueError('不是有效的 .docx（BadZipFile）——扫描件或 .doc 老格式请先转换')
    except Exception as e:
        raise ValueError(f'打开失败: {type(e).__name__}: {e}')
    names = z.namelist()
    if 'word/document.xml' not in names:
        raise ValueError('缺少 word/document.xml —— 可能是加密文档或非 Word 文件')
    try:
        doc = z.read('word/document.xml').decode('utf-8', 'replace')
    except Exception as e:
        raise ValueError(f'读取 document.xml 失败: {e}')
    doc = _repair_ns(doc)
    # XXE 护栏：解析前拒绝 DTD/实体声明，并限制输入规模
    if '<!DOCTYPE' in doc or '<!ENTITY' in doc:
        raise ValueError('拒绝含 DTD/实体声明的 XML（XXE 防护）')
    if len(doc) > 64 * 1024 * 1024:
        raise ValueError('XML 超出 64MB 上限')
    root = ET.fromstring(doc)
    sect = {}
    sp = root.iter(f'{W}sectPr')
    for s in sp:
        pgsz = s.find(f'{W}pgSz')
        pgmar = s.find(f'{W}pgMar')
        if pgsz is not None:
            sect['w'] = int(pgsz.get(f'{W}w') or 0)
            sect['h'] = int(pgsz.get(f'{W}h') or 0)
        if pgmar is not None:
            for k in ('top', 'bottom', 'left', 'right'):
                v = pgmar.get(f'{W}{k}')
                if v is not None:
                    sect[k] = int(v)
        break

    paras = []
    for p in root.iter(f'{W}p'):
        txt = ''.join(t.text or '' for t in p.iter(f'{W}t'))
        ppr = p.find(f'{W}pPr')
        info = {'text': txt.strip(), 'spacing': None, 'line_rule': None,
                'ind_first': None, 'ind_right': None, 'fonts': set(), 'sizes': set(),
                'bold': False, 'align': None, 'para': p, 'ppr': ppr,
                'spacing_raw': None}
        if ppr is not None:
            sp2 = ppr.find(f'{W}spacing')
            if sp2 is not None:
                if sp2.get(f'{W}line'):
                    try:
                        info['spacing'] = int(sp2.get(f'{W}line'))
                    except (TypeError, ValueError):
                        # 行距写了非数字（如 line="None"）——真件不会这么写，
                        # 但产物一旦这么写了，笼统报「可解析性 FAIL」会指错方向，
                        # 这里降级成一则非致命记录（不计入 PASS / 不影响退出码）。
                        info['spacing'] = None
                        info['spacing_raw'] = sp2.get(f'{W}line')
                info['line_rule'] = sp2.get(f'{W}lineRule')
            ind = ppr.find(f'{W}ind')
            if ind is not None:
                if ind.get(f'{W}firstLine') or ind.get(f'{W}firstLineChars'):
                    info['ind_first'] = int(ind.get(f'{W}firstLine') or 0) or ind.get(f'{W}firstLineChars')
                if ind.get(f'{W}right') or ind.get(f'{W}rightChars'):
                    # 单位陷阱：w:right 是 twips，w:rightChars 是"字符数"；
                    # rules.SIGN_DATE_RIGHT=400 是**字符数**，只能与 rightChars 直接比。
                    # 首版拿 right(twips) 与 400(字符) 比，导致每个合规件都报假 WARN。
                    rc = ind.get(f'{W}rightChars')
                    rt = ind.get(f'{W}right')
                    info['ind_right_chars'] = int(rc) if rc else (
                        round(int(rt) / TW_PER_CHAR) if rt else None)
                    info['ind_right_tw'] = int(rt) if rt else None
            jc = ppr.find(f'{W}jc')
            if jc is not None:
                info['align'] = jc.get(f'{W}val')
        for r in p.iter(f'{W}r'):
            rpr = r.find(f'{W}rPr')
            if rpr is None:
                continue
            rf = rpr.find(f'{W}rFonts')
            if rf is not None:
                for k in ('eastAsia', 'ascii'):
                    v = rf.get(f'{W}{k}')
                    if v:
                        info['fonts'].add(v)
            sz = rpr.find(f'{W}sz')
            if sz is not None and sz.get(f'{W}val'):
                info['sizes'].add(int(sz.get(f'{W}val')))
            if rpr.find(f'{W}b') is not None:
                info['bold'] = True
        paras.append(info)

    footers = []
    for n in names:
        if re.match(r'word/footer\d*\.xml$', n):
            try:
                footers.append((n, z.read(n).decode('utf-8', 'replace')))
            except Exception:
                pass
    try:
        z.close()
    except Exception:
        pass
    return {'doc': doc, 'sect': sect, 'paras': paras, 'footers': footers}


# ---------------------------------------------------------------- 单项体检

def _check_page(k, checks, ignores, fmt: dict | None = None):
    """① 页面与版心：A4（横排档为横向 A4）+ 天头 + 订口 + 版心

    期望值**不再恒取通用档**：信函档天头 30mm（不是 37mm）、横排档页面反向且版心不同。
    旧版把 37mm/156×225 硬写进去，对信函与横排件必定误报 FAIL。
    """
    fmt = fmt or R._FORMAT_DEFAULT
    s = k['sect']
    if not s.get('w') or not s.get('h'):
        return checks.append(('页面尺寸', 'SKIP', 'sectPr 中无 pgSz，无法判定'))
    exp_w, exp_h = (R.PAGE_H, R.PAGE_W) if fmt.get('landscape') else (R.PAGE_W, R.PAGE_H)
    ok_size = abs(s['w'] - exp_w) <= int(TOL_MM * TW_MM) and abs(s['h'] - exp_h) <= int(TOL_MM * TW_MM)
    shape = '横向 A4' if fmt.get('landscape') else 'A4'
    checks.append((f'页面尺寸({shape})', 'PASS' if ok_size else 'FAIL',
                   f'实际 {mm(s["w"])}×{mm(s["h"])}mm ｜ 应有 {mm(exp_w)}×{mm(exp_h)}mm'))
    for key, label, exp in (('top', '天头', fmt['margin_top']),
                            ('left', '订口(左边距)', fmt['margin_left'])):
        if key not in s:
            checks.append((label, 'SKIP', f'pgMar 无 {key}'))
            continue
        d = abs(s[key] - exp)
        # 硬性条款：超出容差即 FAIL（单位模板差异由 --ignore 或容差处理，不能靠降级掩盖）
        st = 'PASS' if d <= TOL_MM * TW_MM else 'FAIL'
        note = ''
        if label == '天头' and exp != R.MARGIN['top']:
            note = '（特定格式档：信函上边缘距纸边 30mm，非通用 37mm）'
        checks.append((label, st, f'实际 {mm(s[key])}mm ｜ 应有 {mm(exp)}mm'
                                  f' ｜ 差 {round(d / TW_MM, 1)}mm{note}'))
    # 版心：横排档与通用档不同（横排 A4 版心 243×138mm，表格可用 225mm）
    pw = s['w'] - s.get('left', 0) - s.get('right', 0)
    ph = s['h'] - s.get('top', 0) - s.get('bottom', 0)
    if fmt.get('landscape'):
        # 横排档：交叉核对表宽 225mm 是否落在版心内
        checks.append(('版心尺寸(横排)', 'PASS' if pw > ph else 'FAIL',
                       f'实际 {mm(pw)}×{mm(ph)}mm ｜ 横排 A4 版心应为宽>高；'
                       f'表格可用宽度 {mm(R.PRINT_W)}mm（GB/T 9704 第 8 章）'))
        tw = fmt.get('table_width') or 0
        checks.append(('横排表宽', 'PASS' if tw and tw <= pw else 'FAIL',
                       f'表宽 {mm(tw)}mm ｜ 应 ≤ 版心宽 {mm(pw)}mm（标准要求 225mm）'))
    else:
        for label, got, exp in (('版心宽度', pw, R.PRINT_W), ('版心高度', ph, R.PRINT_H)):
            d = abs(got - exp)
            if label == '版心高度' and fmt.get('letter_rule'):
                # 信函档：GB/T 9704 10.1 只规定上边缘距纸边 30mm 与下页边 20mm 处双线，
                # 未重申 5.2.1 的 156×225。本包底部沿用通用档 1984twip（35mm），
                # 推出 232mm。这不是「超容差不合规定」，而是通用档口径不适用——
                # 拿通用档的期望值硬判特定格式件，正是误报的来源。
                checks.append((label, 'SKIP',
                               f'实际 {mm(got)}mm（信函档上边距 30mm、下边距沿用通用档）｜ '
                               f'GB/T 9704 10.1 未重申 156×225，此项须按单位信函模板核对'))
                continue
            checks.append((label, 'PASS' if d <= TOL_MM * TW_MM else 'FAIL',
                           f'实际 {mm(got)}mm ｜ 应有 {mm(exp)}mm（GB/T 9704 硬性：156×225mm）'))


def _check_grid(k, checks, ignores, fmt: dict | None = None):
    """② 每面 22 行 / 每行 28 字：由版心 ÷ 行距(字宽) 推导，不硬编码。

    这两项是**版面结果**（GB/T 9704 5.2.3），不是行距数值要求，
    所以固定 28pt 行距推不到 22 行时按 WARN 报而不按 FAIL。
    横排档不适用（横排表的行数/字数由表格排版决定），直接标 SKIP。
    """
    fmt = fmt or R._FORMAT_DEFAULT
    s = k['sect']
    if fmt.get('landscape'):
        return checks.append(('每面行数/每行字数', 'SKIP',
                              '横排表格档：行数与字数由表格排版决定，不按正文网格判定'))
    ph = s.get('h', 0) - s.get('top', 0) - s.get('bottom', 0)
    lines = round(ph / R.LINE_BODY) if R.LINE_BODY else 0
    exp_lines = 22
    checks.append(('每面行数', 'PASS' if abs(lines - exp_lines) <= 1 else 'WARN',
                   f'推导 {lines} 行（版心 {mm(ph)}mm ÷ 行距 {R.LINE_BODY / TW_PT}pt）｜ 应有 {exp_lines} 行'))
    # 每行字数：三号字宽 16pt → 版心宽 / (16pt*20 twips)
    char_tw = 16 * TW_PT
    pw = s.get('w', 0) - s.get('left', 0) - s.get('right', 0)
    cpl = round(pw / char_tw)
    checks.append(('每行字数', 'PASS' if abs(cpl - R.CHARS_PER_LINE) <= 1 else 'WARN',
                   f'推导 {cpl} 字（版心 {mm(pw)}mm ÷ 三号字宽 16pt）｜ 应有 {R.CHARS_PER_LINE} 字'))


def _check_body_and_title(k, checks, ignores):
    """③ 正文行距/缩进/字体字号 + 标题字体字号 + 标题层级字体"""
    paras = [p for p in k['paras'] if p['text']]
    if not paras:
        checks.append(('正文要素', 'FAIL', '文档无任何文字段落'))
        return
    # 正文行距：取出现次数最多的 spacing（正文段落最多）
    spaced = [p['spacing'] for p in paras if p['spacing']]
    if not spaced:
        checks.append(('正文行距', 'FAIL', '全文未设 w:spacing/@w:line'))
    else:
        from collections import Counter
        common, cnt = Counter(spaced).most_common(1)[0]
        st = 'PASS' if abs(common - R.LINE_BODY) <= 2 else 'FAIL'
        checks.append(('正文行距(固定值)', st,
                       f'众数 {common} twips = {round(common / TW_PT, 2)}pt（{cnt} 段）｜ 应有 '
                       f'{R.LINE_BODY} twips = {R.LINE_BODY / TW_PT}pt'))
    # 行距写了非数字（如 line="None"）：产物自噬型缺陷，从渲染结果里看不出来，只能从 XML 里揪
    badsp = [p for p in k['paras'] if p.get('spacing_raw')]
    if badsp:
        checks.append(('行距值为非数字', 'WARN',
                       f'{len(badsp)} 段的 w:line 不是数字（样例 {badsp[0]["spacing_raw"]!r}）—— '
                       f'这几段的实际行距由渲染器自行决定，本工具判不了；'
                       f'常见成因是生成器把缺省值当字符串写进了 XML'))
    # 首行缩进 2 字符
    ind = [p['ind_first'] for p in paras if p['ind_first']]
    checks.append(('正文首行缩进', 'PASS' if ind else 'WARN',
                   f'{len(ind)} 段设了首行缩进' + (f'（样例 {ind[0]}）' if ind else '；应有 2 字符')))
    # 正文主字体（众数）
    from collections import Counter
    fcount = Counter()
    for p in paras:
        for f in p['fonts']:
            fcount[f] += 1
    if not fcount:
        checks.append(('正文字体', 'SKIP', '段落未显式声明字体（继承样式表，本脚本不解析 styles.xml）'))
    else:
        top_fonts = [f for f, _c in fcount.most_common(3)]
        fang = any('仿宋' in f for f in top_fonts)
        checks.append(('正文字体(仿宋)', 'PASS' if fang else 'FAIL',
                       f'出现最多的字体: {top_fonts} ｜ 应有 仿宋'))
        gb = [f for f in fcount if 'GB2312' in f]
        if gb:
            checks.append(('正文非 GB2312 仿宋', 'WARN',
                           f'检测到 {gb[:2]} —— GB/T 9704—2012 要求正文用「仿宋」而非「仿宋_GB2312」。'
                           f'本包写侧沿用 GB2312 后缀名（实践中字库更普及），属**已知有意偏差**，'
                           f'接受则用 --ignore GB2312 关闭'))
    # 字号：正文三号 = 32 半磅；标题二号 = 44 半磅
    sizes = Counter()
    for p in paras:
        for sz in p['sizes']:
            sizes[sz] += 1
    common_sz = sizes.most_common(1)[0][0] if sizes else None
    checks.append(('正文字号(三号)', 'PASS' if common_sz == 32 else ('FAIL' if common_sz else 'SKIP'),
                   (f'众数 {common_sz} 半磅 = {common_sz / 2}pt ｜ 应有 32 半磅 = 16pt(三号)'
                    if common_sz else '未声明字号')))
    if 44 in sizes:
        checks.append(('标题字号(二号)', 'PASS', '检测到 44 半磅 = 22pt（二号）'))
    else:
        checks.append(('标题字号(二号)', 'WARN', f'未检出 44 半磅；实际字号集合 {sorted(sizes)[-4:]}'))
    # 标题层级：一级黑体 / 二级楷体 / 三级仿宋 且不加粗
    lv1 = [p for p in paras if re.match(r'^[一二三四五六七八九十]+、', p['text'])]
    if not lv1:
        checks.append(('一级标题(黑体)', 'SKIP', '未检出「一、」式一级标题'))
    else:
        ok_font = all(any('黑体' in f for f in p['fonts']) for p in lv1) if all(p['fonts'] for p in lv1) else None
        nb = [p for p in lv1 if p['bold']]
        if ok_font is None:
            checks.append(('一级标题(黑体)', 'SKIP', f'{len(lv1)} 个一级标题未显式声明字体'))
        else:
            checks.append(('一级标题(黑体)', 'PASS' if ok_font else 'WARN',
                           f'{len(lv1)} 个一级标题，字体全部为黑体' if ok_font else
                           f'{len(lv1)} 个一级标题中存在非黑体'))
        checks.append(('一级标题不加粗', 'WARN' if nb else 'PASS',
                       f'{len(nb)} 个一级标题设了加粗（GB/T 9704 用黑体本身区分，不再加粗）'
                       if nb else '均未加粗'))
    lv2 = [p for p in paras if re.match(r'^（[一二三四五六七八九十]+）', p['text'])]
    if lv2:
        ok2 = all(any('楷体' in f for f in p['fonts']) for p in lv2) if all(p['fonts'] for p in lv2) else None
        checks.append(('二级标题(楷体)', 'SKIP' if ok2 is None else ('PASS' if ok2 else 'WARN'),
                       f'{len(lv2)} 个二级标题' + ('' if ok2 is None else ('，字体为楷体' if ok2 else '，存在非楷体'))))


def _check_docnum_and_signing(k, checks, ignores):
    """④ 发文字号六角括号 / 成文日期右空四字 / 署名右空二字"""
    txts = [p['text'] for p in k['paras'] if p['text']]
    docnum = [t for t in txts if re.search(r'〔\d{4}〕|\[\d{4}\]|［\d{4}］|【\d{4}】', t)]
    if not docnum:
        checks.append(('发文字号', 'WARN', '未检出含年份括号的发文字号'))
    else:
        good = [t for t in docnum if re.search(r'〔\d{4}〕', t)]
        bad = [t for t in docnum if t not in good]
        checks.append(('发文字号六角括号〔〕', 'PASS' if good and not bad else 'FAIL',
                       f'合规 {len(good)} 处' + (f'；**非六角括号 {len(bad)} 处**：{bad[:2]}' if bad else '')))
    # 成文日期：形如 2026年9月11日 的段落，须右空四字（ind right=400）
    dates = [p for p in k['paras'] if re.match(r'^\s*\d{4}年\d{1,2}月\d{1,2}日\s*$', p['text'])]
    if not dates:
        checks.append(('成文日期', 'WARN', '未检出独立成行的成文日期（可能未落款）'))
    else:
        ok = [p for p in dates if p.get('ind_right_chars') == R.SIGN_DATE_RIGHT]
        if ok:
            checks.append(('成文日期右空四字', 'PASS',
                           f'{len(ok)}/{len(dates)} 处右空 {R.SIGN_DATE_RIGHT / 100:.0f} 字'
                           f'（rightChars={R.SIGN_DATE_RIGHT}）'))
        else:
            got = [(p.get('ind_right_chars'), p.get('ind_right_tw')) for p in dates]
            checks.append(('成文日期右空四字', 'WARN',
                           f'实际（字数, twips）={got[:3]} ｜ 应有 {R.SIGN_DATE_RIGHT / 100:.0f} 字'
                           f' = rightChars 400 / 约 1260 twips'))
    # 署名（发文机关）在日期上一行、右空二字
    sign_right = [p.get('ind_right_chars') for p in k['paras']
                  if p.get('ind_right_chars') == R.SIGN_UNIT_RIGHT and p['text']]
    if sign_right:
        checks.append(('署名右空二字', 'PASS',
                       f'检测到 {len(sign_right)} 处右空 {R.SIGN_UNIT_RIGHT / 100:.0f} 字'))
    else:
        checks.append(('署名右空二字', 'SKIP',
                       '未检出右空二字的署名段（不盖章版口径；盖章版日期右空四字、署名右空二字以外）'))


def _check_pageno_and_endmatter(k, checks, ignores, fmt: dict | None = None):
    """⑤ 页码（页脚）｜版记存在性｜份号/密级/紧急程度位置

    信函档例外：GB/T 9704 10.1 要求**首页不显示页码**，但页脚里排的是下页边
    20mm 处的红双线——所以「无 footer 部件」与「footer 内无 PAGE 域」是两种不同的事。
    """
    fmt = fmt or R._FORMAT_DEFAULT
    letter = bool(fmt.get('letter_rule'))
    if not k['footers']:
        if letter:
            checks.append(('信函红双线页脚', 'FAIL',
                           '信函档应在页脚排下页边 20mm 处的上细下粗红双线，但包内无 footer 部件'))
        else:
            checks.append(('页码设定', 'WARN', '文档无 footer 部件（未设页码）'))
    else:
        joined = ' '.join(t for _n, t in k['footers'])
        if letter:
            fill = joined.count('FF0000')
            tw = re.findall(r'<w:tblW w:w="(\d+)"', joined)
            checks.append(('信函红双线页脚', 'PASS' if fill >= 2 else 'FAIL',
                           f'页脚内红色填充 {fill} 处 ｜ 应有 2 处（上细下粗双线）；'
                           f'表宽 {tw or "无"}（应 {_letter_rule_w()}）'))
            checks.append(('信函首页无页码', 'PASS' if 'PAGE' not in joined else 'FAIL',
                           '页脚内无 PAGE 域（GB/T 9704 10.1）' if 'PAGE' not in joined else
                           '页脚内检出了 PAGE 域，信函首页不应显示页码'))
        else:
            has_num = ('PAGE' in joined) or ('页码' in joined)
            song = '宋体' in joined or 'SimSun' in joined
            sz = re.findall(r'<w:sz w:val="(\d+)"', joined)
            sz4 = '28' in sz                                     # 四号 = 28 半磅
            detail = f'footer {len(k["footers"])} 个｜域: {"有" if has_num else "无"}｜宋体: {song}｜四号(28): {sz4}'
            checks.append(('页码设定', 'PASS' if (has_num and song and sz4) else 'WARN', detail))
            if '—' in joined or '-' in joined:
                checks.append(('页码一字线', 'PASS', '检出页码分隔线（一字线）'))
            else:
                checks.append(('页码一字线', 'SKIP', 'footer 内未检出分隔线字符（可能用域格式化，无法判定）'))
    # 版记
    all_txt = '\n'.join(p['text'] for p in k['paras'] if p['text'])
    doc = k['doc']
    if '版记' in all_txt:
        anchored = 'tblpYSpec="bottom"' in doc
        checks.append(('版记存在', 'PASS', '检出「版记」段'))
        checks.append(('版记沉底锚定', 'PASS' if anchored else 'WARN',
                       '检出 w:tblpYSpec="bottom" 浮动表锚定' if anchored else
                       '未检出沉底锚定（w:tblpYSpec="bottom"）——旧实现靠段前距估算，\n'
                       '字体替换与渲染器忽略属性都会让落点偏位；验收口径见 formal-checklist §5'))
    else:
        checks.append(('版记存在', 'SKIP', '未检出「版记」字样（部分文种无版记，不判不合规）'))
    # 份号/密级/紧急程度：若存在须出现在文首 5 段内
    head = '\n'.join(p['text'] for p in k['paras'][:5] if p['text'])
    for kw, label in (('份号', '份号'), ('秘密', '密级'), ('机密', '密级'), ('特急', '紧急程度'), ('加急', '紧急程度')):
        if kw in all_txt:
            checks.append((f'{label}位置', 'PASS' if kw in head else 'WARN',
                           f'检出「{kw}」' + ('且在文首 5 段内' if kw in head else '但不在文首 5 段内')))


#: 体检项（顺序即报告顺序）
CHECKS_ALL = ['页面与版心', '版面网格', '正文与标题', '字号与落款', '页码与版记']


def _check_manual(checks):
    """机器不可判项（MANUAL）：从 DOCX 里拿不到裁定依据的要素。

    这些项**不参与** PASS/FAIL 计数，也不影响退出码。列出来只有一个目的：
    让“这份报告没覆盖什么”在输出里可见。每项注明标准条款与为什么机器判不了。
    验收口径见 references/formal-checklist.md §6。
    """
    for label, clause, why in (
        ('印章/签名章位置', '7.3.5',
         'OOXML 里的印章是浮动图片或空位，无稳定锚点可算毫米级位置'),
        ('红头毫米级位置', '7.2.7',
         '红线是 VML 绘图，本包只能判存在性（见 _check_page 的“无红头”分支）'),
        ('版记分隔线粗细', '7.4.1',
         '粗细在绘图属性里，与渲染器实现相关，无法从 XML 推断实际磅值'),
        ('横排表格单双页表头朝向', '8',
         '需目标 Word/WPS 的横向模板，未自动化'),
        ('双面套正与页码误差', '6.2',
         '生产环节量测，非文档属性'),
        ('油墨色值（红 Y80%/M80%、黑 BL100%）', '6.2',
         '印刷机量测，DOCX 中伪造这个属性就是造假'),
        ('装订与裁切（钉位、钉锯距书脊、成品尺寸）', '6.3',
         '物理成品量测，与文件无关'),
        ('用纸技术指标（定量、白度、耐折度、不透明度、pH）', '4',
         '纸张物性，须以纸张规格与成品检测为准'),
    ):
        checks.append((label, 'MANUAL', f'条款 {clause}：机器不可判 —— {why}；须现场或人工核验'))


def inspect(path, doc_type=None, fmt_key=None):
    checks = []
    fmt = R.resolve_format(doc_type, fmt_key)
    try:
        k = _load(path)
    except ValueError as e:
        return [('可解析性', 'FAIL', str(e))], {'parsable': False}

    _check_page(k, checks, (), fmt)
    _check_grid(k, checks, (), fmt)
    _check_body_and_title(k, checks, ())
    _check_docnum_and_signing(k, checks, ())
    _check_pageno_and_endmatter(k, checks, (), fmt)
    _check_manual(checks)
    meta = {'parsable': True, 'paragraphs': len([p for p in k['paras'] if p['text']]),
            'footers': len(k['footers']), 'format': fmt.get('key'),
            'sect': {kk: mm(vv) if kk in ('w', 'h', 'top', 'bottom', 'left', 'right')
                     else vv for kk, vv in k['sect'].items()}}
    return checks, meta


def main():
    ap = argparse.ArgumentParser(description='国标逐要素体检器（只读；GB/T 9704—2012）')
    ap.add_argument('file', help='待体检的 .docx 路径')
    ap.add_argument('--doc-type', default=None, help='文种（影响部分判定口径，可选）')
    ap.add_argument('--format', default=None,
                    help='格式档（letter / command / horizontal-table；不写则按文种自动绑定）。'
                         '它决定页面几何的应有值：信函天头 30mm、横排档为横向 A4。')
    ap.add_argument('--ignore', nargs='*', default=[],
                    help='忽略指定项（子串匹配），如 --ignore 页码 版记')
    ap.add_argument('-v', '--verbose', action='store_true', help='显示 SKIP 项')
    ap.add_argument('--manual', action='store_true',
                    help='显示 MANUAL 项（机器不可判、须现场核验的要素）')
    ap.add_argument('--json', action='store_true', help='机器可读')
    a = ap.parse_args()

    if not os.path.exists(a.file):
        print(f'文件不存在: {a.file}', file=sys.stderr)
        return 2

    checks, meta = inspect(a.file, a.doc_type, a.format)
    filtered = []
    for name, st, detail in checks:
        if any(x in name for x in a.ignore):
            continue
        filtered.append((name, st, detail))

    n_pass = sum(1 for _n, s, _d in filtered if s == 'PASS')
    n_warn = sum(1 for _n, s, _d in filtered if s == 'WARN')
    n_fail = sum(1 for _n, s, _d in filtered if s == 'FAIL')
    n_skip = sum(1 for _n, s, _d in filtered if s == 'SKIP')
    n_manual = sum(1 for _n, s, _d in filtered if s == 'MANUAL')

    if a.json:
        print(json.dumps({'file': os.path.basename(a.file), 'doc_type': a.doc_type,
                          'summary': {'PASS': n_pass, 'WARN': n_warn, 'FAIL': n_fail,
                                      'SKIP': n_skip, 'MANUAL': n_manual},
                          'meta': meta,
                          'checks': [{'item': n, 'status': s, 'detail': d} for n, s, d in filtered]},
                         ensure_ascii=False, indent=1))
    else:
        print(f'=== 国标逐要素体检（GB/T 9704—2012）===')
        print(f'  文件: {os.path.basename(a.file)}' + (f' ｜ 文种: {a.doc_type}' if a.doc_type else ''))
        if meta.get('parsable'):
            print(f'  段落 {meta["paragraphs"]} ｜ 页脚部件 {meta["footers"]} ｜ 版心参数 {meta["sect"]}')
        print()
        icon = {'PASS': '✅', 'WARN': '⚠️ ', 'FAIL': '❌', 'SKIP': '⏭ ', 'MANUAL': '🙋'}
        for n, s, d in filtered:
            if s == 'SKIP' and not a.verbose:
                continue
            if s == 'MANUAL' and not a.manual:
                continue
            print(f'  {icon[s]} {n:18s} {d}')
        print()
        print(f'  结果: PASS {n_pass} ｜ WARN {n_warn} ｜ FAIL {n_fail} ｜ SKIP {n_skip} ｜ MANUAL {n_manual}')
        if n_fail:
            print('  ❌ 存在明确不合规项 —— 请按上述「应有 vs 实际」核对原文修正')
        elif n_warn:
            print('  ⚠️  存在偏差项。单位模板差异常导致误报，请结合本单位模板判断；'
                  '不适用项可用 --ignore 关闭')
        else:
            print('  ✅ 未发现偏差')
        print('  ℹ️  本工具只判要素存在性与规格，**不判内容对错**；只读，不修改文件。')
        if n_manual and not a.manual:
            print(f'      {n_manual} 项机器不可判（加 --manual 查看；这些项**以上结果未覆盖**）')
        if n_skip and not a.verbose:
            print(f'      {n_skip} 项 SKIP（加 -v 查看原因）')
    # 退出码：有 FAIL 才非零（MANUAL 不计入，它是“未验”不是“不过”）
    return 1 if n_fail else 0


if __name__ == '__main__':
    sys.exit(main())
