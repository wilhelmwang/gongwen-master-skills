#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""版式坐标量测（layout-coords v1.0.0）

用途
----
从**渲染后的 PDF** 里量字形的实际毫米坐标，用于验证「代码里写了」是否等于「纸面上到位了」。

为什么必须量 PDF，不能只查 XML
--------------------------------
段前距、行距、锚点这些属性写在 XML 里，只能证明**生成器输出了什么**，
不能证明**渲染器画到了哪里**。段前距失效、字体替换引起换行变化、
渲染器忽略某个属性——这三类都不会让 XML 报错。
「代码里明明写着，纸面上偏偏没有」是本类工具最常见的一类交付事故。

量测口径（与外部参考实现一致，机制已按本机口径重写）
-----------------------------------------------------
1. **必须先合并视觉行**：Poppler / MuPDF 会把一个中文短语按字体切分成相邻的
   多个 word 元素。直接按单个 word 匹配会漏；先按垂直重叠把同一视觉行的 word
   合并成行，再在行文本里找目标短语。
2. **y 取视觉行顶边**：字形顶部与框边有几十个百分点的铅字偏移，量的是**行位置**
   而不是字形本身的包围盒，所以阈值给区间不给单值。
3. **量出来的是页面坐标**，不是版心坐标。要判断「天头 37mm」，需自己减掉页面偏移。

分辨率上限（必须随结论一起声明）
--------------------------------
本量测的分辨率上限约 **±0.5mm**：受 PDF 内字形包围盒与渲染器实现影响。
因此**不要用它宣称 0.1mm 级的符合性**；它只用于发现「差了几毫米」这类真问题。

用法
----
  python measure_layout_coords.py 文件.pdf --anchor 份号=000007 --anchor 机关标志=示例单位文件
  python measure_layout_coords.py 文件.pdf --anchor 份号=000007 --range 份号=37-45
  python measure_layout_coords.py a.pdf b.pdf --anchor 机关标志=示例单位文件 --delta
  python measure_layout_coords.py --text out.txt --anchor 份号=000007   # 复用 pdftotext -bbox-layout 输出

退出码
------
  0 通过 ｜ 1 超区间 ｜ 2 参数/文件错误 ｜ **3 工具链缺失**（没有可用的 PDF 解析后端）
3 与 1 分开是有意的：**「没工具所以没验」不是「验了没通过」**，两者不能混成一个非零码。
"""
import argparse
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

MM_PER_PT = 25.4 / 72.0
ROW_TOL_PT = 1.5          # 视觉行合并的垂直重叠容差（pt）
RESOLUTION_MM = 0.5       # 本量测的分辨率上限，随结论一起声明


# ---------- 后端一：PyMuPDF（首选，跨平台、无外部命令） ----------

def _words_pymupdf(path, page):
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return None
    try:
        doc = fitz.open(path)
    except Exception as e:
        print(f'无法打开 PDF: {path} —— {e}', file=sys.stderr)
        sys.exit(2)
    if page > doc.page_count:
        print(f'PDF 只有 {doc.page_count} 页，取不到第 {page} 页', file=sys.stderr)
        sys.exit(2)
    out = []
    for w in doc[page - 1].get_text('words'):
        out.append((float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4])))
    doc.close()
    return out


# ---------- 后端二：pdftotext -bbox-layout（仅当没装 PyMuPDF 时） ----------

def _words_pdftotext(path, page):
    if not _which('pdftotext'):
        return None
    try:
        raw = subprocess.run(['pdftotext', '-f', str(page), '-l', str(page), '-bbox-layout',
                              path, '-'], capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        print(f'pdftotext 调用失败: {e}', file=sys.stderr)
        sys.exit(2)
    if raw.returncode != 0:
        print(f'pdftotext 退出码 {raw.returncode}: '
              f'{raw.stderr.decode("utf-8", "replace")[:300]}', file=sys.stderr)
        sys.exit(2)
    return _words_from_bbox_layout(raw.stdout.decode('utf-8', 'replace'))


def _words_from_bbox_layout(xml_text):
    """解析 pdftotext -bbox-layout 的 <word xMin yMin xMax yMax>…</word>。"""
    out = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f'pdftotext 输出不是合法 XML: {e}', file=sys.stderr)
        sys.exit(2)
    for el in root.iter():
        tag = el.tag.split('}')[-1]
        if tag != 'word':
            continue
        try:
            out.append((float(el.get('xMin')), float(el.get('yMin')),
                        float(el.get('xMax')), float(el.get('yMax')),
                        ''.join(el.itertext()).strip()))
        except (TypeError, ValueError):
            continue
    return out


def _which(name):
    from shutil import which
    return which(name)


# ---------- 视觉行合并 ----------

def merge_rows(words, tol=ROW_TOL_PT):
    """把同一视觉行的 word 合并成行。

    只按垂直重叠判断，不按 x —— 中文短语在 PDF 里常被按字体切成多个相邻 word，
    按 x 分组会把一行拆成好几组，量出来的 y 仍然是那一行的，但匹配会失败。
    """
    rows = []
    for x0, y0, x1, y1, txt in sorted(words, key=lambda w: (w[1], w[0])):
        placed = False
        for r in rows:
            if y0 <= r['ymax'] + tol and y1 >= r['ymin'] - tol:
                items = r['items'] + [(x0, y0, x1, y1, txt)]
                r['items'] = items
                r['ymin'] = min(r['ymin'], y0)
                r['ymax'] = max(r['ymax'], y1)
                placed = True
                break
        if not placed:
            rows.append({'ymin': y0, 'ymax': y1, 'items': [(x0, y0, x1, y1, txt)]})
    for r in rows:
        r['items'].sort(key=lambda w: w[0])
        r['text'] = ''.join(w[4] for w in r['items'])
    rows.sort(key=lambda r: r['ymin'])
    return rows


def find_row(rows, needle):
    """在视觉行里找目标短语。返回 (行, 命中词) 或 (None, None)。

    先在行文本里找；找不到再用「去掉空白后包含」兜一次——
    PDF 会在字之间插空格，直接 index 会失败。
    """
    for r in rows:
        if needle in r['text']:
            return r, needle
    flat = [(r, r['text'].replace(' ', '')) for r in rows]
    for r, t in flat:
        if needle.replace(' ', '') in t:
            return r, needle.replace(' ', '')
    return None, None


# ---------- 区间解析 ----------

def parse_range(s):
    """'份号=37-45' → ('份号', 37.0, 45.0)。"""
    if '=' not in s:
        print(f'--range 需要 <锚点>=<最小>-<最大> 形式，收到 {s!r}', file=sys.stderr)
        sys.exit(2)
    name, rng = s.split('=', 1)
    m = re.fullmatch(r'\s*(-?\d+(?:\.\d+)?)\s*[-–~]\s*(-?\d+(?:\.\d+)?)\s*', rng)
    if not m:
        print(f'--range 的区间需为 <最小>-<最大>，收到 {rng!r}', file=sys.stderr)
        sys.exit(2)
    return name.strip(), float(m.group(1)), float(m.group(2))


def parse_anchor(s):
    if '=' not in s:
        print(f'--anchor 需要 <名称>=<页面上的文字> 形式，收到 {s!r}', file=sys.stderr)
        sys.exit(2)
    name, text = s.split('=', 1)
    return name.strip(), text.strip()


# ---------- 主流程 ----------

def measure(path, page, anchors):
    """返回 {名称: (mm, 行文本)}；未命中记 None。"""
    words = _words_pymupdf(path, page)
    if words is None:
        words = _words_pdftotext(path, page)
    if words is None:
        print('工具链缺失：本机既没有 PyMuPDF，也没有 pdftotext。', file=sys.stderr)
        print('  ⟹ 本次【未量测】。这不是「通过」，也不是「不通过」。', file=sys.stderr)
        print('  装任一即可：pip install pymupdf 或 安装 poppler-utils。', file=sys.stderr)
        sys.exit(3)
    if not words:
        print(f'第 {page} 页没有可提取的文字（可能是扫描件或纯图形页）。', file=sys.stderr)
        print('  ⟹ 本次【未量测】（扫描件需 OCR，本脚本不做）。', file=sys.stderr)
        sys.exit(3)
    rows = merge_rows(words)
    res = {}
    for name, text in anchors:
        r, hit = find_row(rows, text)
        if r is None:
            res[name] = None
        else:
            res[name] = (r['ymin'] * MM_PER_PT, r['text'])
    return res, rows


def main():
    ap = argparse.ArgumentParser(description='版式坐标量测（从渲染后的 PDF 量字形毫米坐标）',
                                 add_help=False)
    ap.add_argument('pdf', nargs='*', help='PDF 路径，可给两个配合 --delta')
    ap.add_argument('--anchor', action='append', default=[], metavar='名称=文字',
                    help='要定位的锚点（可重复）')
    ap.add_argument('--range', action='append', default=[], metavar='名称=最小-最大',
                    help='锚点允许的毫米区间（可重复）')
    ap.add_argument('--delta', action='store_true',
                    help='两个 PDF 之间比同一锚点的差值（用于「有无某字段时位置差」）')
    ap.add_argument('--page', type=int, default=1, help='量第几页（默认 1）')
    ap.add_argument('--json', action='store_true', help='以 JSON 输出')
    ap.add_argument('--text', metavar='文件',
                    help='改为解析 pdftotext -bbox-layout 的输出文件（不进 PDF）')
    ap.add_argument('-h', '--help', action='store_true', help='显示本帮助')
    a = ap.parse_args()

    if a.help or (not a.pdf and not a.text):
        print(__doc__)
        return 0 if a.help else 2

    if not a.anchor:
        print('至少给一个 --anchor（例如 --anchor 份号=000007）。', file=sys.stderr)
        print('  为什么要给文字：本脚本不做 OCR。哪一行是「份号」只能由你告诉它，'
              '它负责量那一行的位置。', file=sys.stderr)
        return 2
    anchors = [parse_anchor(s) for s in a.anchor]
    ranges = dict((parse_range(s)[0], parse_range(s)[1:]) for s in a.range)

    if a.delta and len(a.pdf) != 2:
        print('--delta 需要正好两个 PDF 路径。', file=sys.stderr)
        return 2

    if a.text:
        if not os.path.exists(a.text):
            print(f'文件不存在: {a.text}', file=sys.stderr)
            return 2
        words = _words_from_bbox_layout(open(a.text, encoding='utf-8', errors='replace').read())
        if not words:
            print(f'{a.text} 中没有 <word> 元素——请确认是 `pdftotext -bbox-layout` 的输出。',
                  file=sys.stderr)
            return 3
        rows = merge_rows(words)
        res = {}
        for name, txt in anchors:
            r, _hit = find_row(rows, txt)
            res[name] = (r['ymin'] * MM_PER_PT, r['text']) if r else None
        return _report('（来自 --text）', res, ranges, None, None, a.json)

    if a.delta:
        r1, _ = measure(a.pdf[0], a.page, anchors)
        r2, _ = measure(a.pdf[1], a.page, anchors)
        return _report_delta(a.pdf, r1, r2, a.json)

    for p in a.pdf:
        if not os.path.exists(p):
            print(f'文件不存在: {p}', file=sys.stderr)
            return 2
        if os.path.isdir(p):
            print(f'这是目录不是文件: {p}', file=sys.stderr)
            return 2
    res, rows = measure(a.pdf[0], a.page, anchors)
    return _report(a.pdf[0], res, ranges, rows, a.page, a.json)


def _fmt(v):
    return '未命中' if v is None else '%.2f mm' % v[0]


def _report(pdf, res, ranges, rows, page, as_json):
    fails = 0
    lines = []
    lines.append('=== 版式坐标量测 ===')
    lines.append(f'  文件：{pdf}' + (f'  第 {page} 页' if page else ''))
    lines.append(f'  分辨率上限：±{RESOLUTION_MM}mm —— 不要用本结果宣称 0.1mm 级符合性')
    lines.append(f'  口径：页面上边缘为 0；量的是视觉行顶边，未减页边距')
    lines.append('')
    lines.append('【锚点】')
    for name, v in res.items():
        flag = ''
        if v is None:
            lines.append(f'  {name:<10} 未命中 —— 页面上找不到该文字；'
                         f'可能是内容没生成，也可能是文字被拆散（已合并视觉行仍找不到）')
            continue
        mm = v[0]
        rng = ranges.get(name)
        if rng:
            lo, hi = rng
            ok = lo <= mm <= hi
            flag = '  ✓' if ok else f'  ✗ 期望 {lo}–{hi}mm'
            if not ok:
                fails += 1
        lines.append(f'  {name:<10} {mm:>7.2f} mm{flag}')
        lines.append(f'  {"":<10} 命中行：{v[1][:70]}')
    lines.append('')
    if rows is not None:
        lines.append('【该页首 6 个视觉行（供人工核对）】')
        for i, r in enumerate(rows[:6]):
            lines.append(f'  {i + 1}. y={r["ymin"] * MM_PER_PT:>7.2f} mm  {r["text"][:60]}')
        lines.append('')
    lines.append(f'  结果：{"超区间 %d 项" % fails if fails else "全部锚点在区间内" if ranges else "已量测（未给区间，仅报数值）"}')
    lines.append('  ℹ️  本量测只证明「画到了这个位置」，不证明「这个位置对」——'
                 '对不对要对照 GB/T 9704 条款与本单位模板。')
    txt = '\n'.join(lines)
    if as_json:
        import json
        print(json.dumps({'pdf': pdf, 'page': page, 'resolution_mm': RESOLUTION_MM,
                          'anchors': {k: (None if v is None else round(v[0], 2))
                                      for k, v in res.items()},
                          'fails': fails}, ensure_ascii=False, indent=2))
    else:
        print(txt)
    return 1 if fails else 0


def _report_delta(pdfs, r1, r2, as_json):
    lines = ['=== 锚点位置差（两件对比） ===']
    lines.append(f'  A：{pdfs[0]}')
    lines.append(f'  B：{pdfs[1]}')
    lines.append(f'  分辨率上限：±{RESOLUTION_MM}mm')
    lines.append('')
    fails = 0
    for name in r1:
        va, vb = r1[name], r2.get(name)
        if va is None or vb is None:
            lines.append(f'  {name:<10} 有一侧未命中，无法求差')
            continue
        d = abs(va[0] - vb[0])
        ok = d <= 0.8
        lines.append(f'  {name:<10} A={va[0]:.2f}mm  B={vb[0]:.2f}mm  差={d:.2f}mm  '
                     f'{"✓" if ok else "✗ 超过 0.8mm"}')
        if not ok:
            fails += 1
    lines.append('')
    lines.append('  结果：' + ('位置差在 0.8mm 内' if not fails else f'{fails} 项差超过 0.8mm'))
    lines.append('  ℹ️  这项用于验证「某字段的有无不应推动其它元素位置」——'
                 '差为 0.00mm 才能说「互不影响」。')
    if as_json:
        import json
        print(json.dumps({'A': pdfs[0], 'B': pdfs[1],
                          'delta_mm': {k: (None if (r1[k] is None or r2.get(k) is None)
                                           else round(abs(r1[k][0] - r2[k][0]), 2))
                                       for k in r1},
                          'fails': fails}, ensure_ascii=False, indent=2))
    else:
        print('\n'.join(lines))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
