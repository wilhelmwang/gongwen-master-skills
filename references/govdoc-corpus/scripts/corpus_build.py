#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单位私有语料接入与画像蒸馏（govdoc-corpus v1.0.0）

把本单位历年公文批量接入为**本地**语料库，并蒸馏出三份可用的画像产物。

合规前提（不得为"增强效果"而破坏）
----------------------------------
1. **纯本地**：本脚本只用 Python 标准库 + jieba，**不含任何网络调用、不读取 LLM 凭据**。
   这是处理内部材料的前提；要做语义分析属于另一次需单独授权的动作，涉密材料一律禁止。
2. **独立库**：写入用户指定的独立 SQLite，**绝不写入 `gongwen_corpus.db`**
   （单位语料与求是/地方公共语料必须物理隔离，避免内部口径被当权威表述引用）。
3. **不静默跳过**：无法解析的文件逐项报出，写进 build_report.md。
4. **不改写原文**：入库的是原文；清洗只作用于派生统计（去页码/页脚等版式噪声），
   且原文另存 `raw_content` 以便回溯。
5. **不夸大画像**：按文种给出「样本充足度」评级，不足时明说不足以作为依据。

用法
----
  python corpus_build.py --src "D:/单位公文" --out "D:/单位语料库" --plan   # 干跑，只看清单
  python corpus_build.py --src "D:/单位公文" --out "D:/单位语料库"          # 正式导入
  python corpus_build.py --src ... --out ... --json                        # 机器可读报告
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sqlite3
import sys
import zipfile
from collections import Counter, defaultdict
import xml.etree.ElementTree as ET

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

#: 可处理的扩展名 → 处理方式
DIRECT = {'.docx': 'docx', '.txt': 'text', '.md': 'text'}
#: 需先转换的扩展名（脚本不自行处理，显式报出）
NEEDS_CONVERT = {'.doc': 'Word 97-2003 老格式', '.pdf': 'PDF', '.wps': 'WPS',
                 '.jpg': '扫描件（图片型）', '.jpeg': '扫描件（图片型）',
                 '.png': '扫描件（图片型）', '.tif': '扫描件（图片型）', '.tiff': '扫描件（图片型）'}

#: 文种识别关键词（顺序即优先级：更具体的在前）
DOC_TYPES = [
    ('会议纪要', ('纪要', '会议记录')), ('调研报告', ('调研', '考察报告', '调查')),
    ('工作总结', ('工作总结', '总结', '工作回顾')), ('述职报告', ('述职',)),
    ('工作报告', ('工作报告', '工作情况报告', '汇报')), ('实施方案', ('实施方案', '工作方案', '方案')),
    ('请示', ('请示',)), ('批复', ('批复',)), ('通知', ('通知',)), ('通报', ('通报',)),
    ('简报', ('简报', '信息专报', '专报', '要情')), ('讲话稿', ('讲话', '致辞', '发言')),
    ('报告', ('报告',)), ('制度规定', ('规定', '办法', '制度', '细则', '章程')),
    ('意见', ('意见',)), ('决定', ('决定',)), ('函', ('函',)), ('公告通告', ('公告', '通告')),
    ('经验材料', ('经验',)), ('体会', ('心得', '体会')),
]

#: 实名口径/固定表述的常见模式（用于口径清单）
OFFICE_PATTERNS = [r'我(?:局|市|县|区|委|办|厅|部|院|校|公司|集团|单位|系统|省|镇|乡|街道)',
                   r'本(?:局|市|县|区|委|办|厅|部|院|单位|地区|系统)',
                   r'全(?:市|县|区|省|国)']

#: 版式噪声（清洗用于统计的正文，原文保留在 raw_content）
NOISE = [
    r'第\s*\d+\s*页\s*共\s*\d+\s*页', r'^\s*[-—]\s*\d+\s*[-—]\s*$',
    r'京ICP备\S*', r'网站标识码\S*', r'主办单位：\S*', r'版权所有：\S*',
    r'责任编辑：.*$', r'新华社记者\s*\S+/摄',
]


# ---------------------------------------------------------------- 解析

def docx_text(path):
    """纯标准库提取 .docx 正文（段落边界保留为换行）"""
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise ValueError('不是有效的 .docx（可能损坏或实为 .doc 改名）')
    names = z.namelist()
    if 'word/document.xml' not in names:
        raise ValueError('缺少 word/document.xml（可能是加密文档）')
    xml = z.read('word/document.xml').decode('utf-8', 'replace')
    z.close()
    # 补声明缺失的命名空间前缀（外来件常见；Word 宽容能开，严格解析器会崩）
    m = re.search(r'<w:document\b[^>]*?>', xml)
    if m and 'xmlns:r=' not in m.group(0):
        xml = xml[:m.end() - 1] + ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"' + xml[m.end() - 1:]
    # XXE 护栏：解析前拒绝 DTD/实体声明，并限制输入规模
    if '<!DOCTYPE' in xml or '<!ENTITY' in xml:
        raise ValueError('拒绝含 DTD/实体声明的 XML（XXE 防护）')
    if len(xml) > 64 * 1024 * 1024:
        raise ValueError('XML 超出 64MB 上限')
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise ValueError(f'document.xml 解析失败: {e}')
    out = []
    for p in root.iter(f'{W}p'):
        seg = ''.join(t.text or '' for t in p.iter(f'{W}t'))
        if seg.strip():
            out.append(seg.strip())
    return '\n'.join(out)


def read_text(path):
    for enc in ('utf-8', 'gb18030', 'utf-16'):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise ValueError('编码无法识别（试过 utf-8/gb18030/utf-16）')


def clean(text):
    t = text.replace('\r\n', '\n').replace('\r', '\n')
    for pat in NOISE:
        t = re.sub(pat, '', t, flags=re.M)
    for zw in ('\u200b', '\u200c', '\u200d', '\ufeff'):
        t = t.replace(zw, '')
    return '\n'.join(l.strip() for l in t.split('\n') if l.strip())


def txt_hash(text):
    return hashlib.sha256(clean(text).encode('utf-8')).hexdigest()[:32]


# ---------------------------------------------------------------- 元数据

def detect_doc_type(filename, title, body):
    src = f'{filename}\n{title}'
    for name, kws in DOC_TYPES:
        if any(k in src for k in kws):
            return name
    for name, kws in DOC_TYPES:           # 退一步看正文开头
        if any(k in body[:400] for k in kws):
            return name
    return '未识别'


def detect_year(text, filename):
    # 优先落款日期（文末 300 字内的 YYYY年M月D日）
    tail = text[-300:]
    ys = re.findall(r'(20\d{2})\s*年', tail)
    if ys:
        return int(ys[-1])
    ys = re.findall(r'(20\d{2})\s*年', filename) or re.findall(r'(20\d{2})\s*年', text[:600])
    if ys:
        return int(ys[0])
    ys = re.findall(r'(20\d{2})', filename)
    return int(ys[0]) if ys else None


def detect_dept(text):
    """从落款行识别发文部门（文末 200 字内的机关名）

    后缀必须**长词优先**：写成 `委|委员会` 时正则会在"地方发展和改革委员会"上
    先匹配短的 `委`，产出截断的"地方发展和改革委"（实测踩过）。故委员会/管理局
    一类长后缀排在前。
    """
    tail = text[-200:]
    suffix = (r'(?:委员会|管理局|人民政府|管理处|政府|办公室|办公厅|公司|集团|'
              r'局|委|办|厅|部|院|校|中心|署|站|所)')
    found = re.findall(r'([\u4e00-\u9fa5]{2,20}' + suffix + r')', tail)
    if found:
        return found[-1]
    return ''


def _is_signoff(line):
    """是否为落款行（机关名或成文日期）——统计「惯用收尾」时应排除。

    公文末行几乎总是日期/机关名，把它们算作"惯用收尾"会让该画像毫无信息量
    （每个单位都会得到一串日期）。判据：日期，或**无句末标点且非标题行**的短行
    （正文句子必有句末标点，机关名没有）。
    """
    s = line.strip()
    if re.fullmatch(r'\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日', s):
        return True
    if not s or len(s) > 30 or s[-1] in '。！？：；…”“"':
        return False
    if re.match(r'^(?:[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|\d+[\.．]|#)', s):
        return False            # 标题行不算落款
    return True


def split_sents(text):
    return [s for s in re.split(r'(?<=[。！？；])', text) if len(s.strip()) >= 4]


# ---------------------------------------------------------------- 蒸馏

def distill(docs, topn=30):
    """确定性统计画像：句长 / 结构装置 / 惯用开头收尾 / 高频表述 / 实名口径"""
    import jieba
    jieba.setLogLevel(60)

    sent_lens, level1, level2, level3 = [], 0, 0, 0
    heads, tails, tokens = [], [], Counter()
    office = Counter()
    total_chars = 0

    for d in docs:
        body = d['content']
        total_chars += len(body)
        sents = split_sents(body)
        sent_lens += [len(s) for s in sents]
        for line in body.split('\n'):
            s = line.strip()
            if re.match(r'^[一二三四五六七八九十]+、', s):
                level1 += 1
            elif re.match(r'^（[一二三四五六七八九十]+）', s):
                level2 += 1
            elif re.match(r'^\d+[\.．]', s):
                level3 += 1
        lines = [l.strip() for l in body.split('\n') if l.strip()]
        if lines:
            heads.append(lines[0][:40])
            # 收尾取「排除落款行后的末行」——否则每个单位都会得到一串日期，画像无信息量
            body_lines = [l for l in lines if not _is_signoff(l)]
            if body_lines:
                tails.append(body_lines[-1][:40])
        for pat in OFFICE_PATTERNS:
            for m in re.findall(pat, body):
                office[m] += 1
        for w in jieba.cut(body):
            w = w.strip()
            if len(w) >= 2 and not w.isdigit():
                tokens[w] += 1

    def pct(vals, p):
        if not vals:
            return 0
        vs = sorted(vals)
        return vs[min(len(vs) - 1, int(len(vs) * p))]

    return {
        'docs': len(docs), 'total_chars': total_chars,
        'sent': {'n': len(sent_lens), 'mean': round(sum(sent_lens) / len(sent_lens), 1) if sent_lens else 0,
                 'p50': pct(sent_lens, 0.5), 'p90': pct(sent_lens, 0.9),
                 'over60': sum(1 for x in sent_lens if x > 60)},
        'levels': {'level1_一、': level1, 'level2_（一）': level2, 'level3_1.': level3},
        'head_top': Counter(heads).most_common(topn),
        'tail_top': Counter(tails).most_common(topn),
        'token_top': tokens.most_common(topn),
        'office_top': office.most_common(topn),
        'by_type': dict(Counter(d['doc_type'] for d in docs)),
        'by_year': dict(sorted(Counter(d['year'] for d in docs if d['year']).items())),
        'by_dept': dict(Counter(d['dept'] for d in docs if d['dept']).most_common(20)),
    }


def adequacy(n):
    """样本充足度评级（画像质量强依赖样本量，必须如实给出）"""
    if n >= 8:
        return '充足'
    if n >= 3:
        return '一般（趋势可参考，不宜作为硬依据）'
    if n >= 1:
        return '不足（仅作线索，不得据此下结论）'
    return '无样本'


# ---------------------------------------------------------------- 建库

SCHEMA = '''
CREATE TABLE IF NOT EXISTS docs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  path TEXT UNIQUE, filename TEXT, fmt TEXT, doc_type TEXT, year INTEGER,
  dept TEXT, chars INTEGER, txt_hash TEXT, content TEXT, raw_content TEXT,
  added_at TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
  filename, content, content='docs', content_rowid='id'
);
CREATE TABLE IF NOT EXISTS build_meta (k TEXT PRIMARY KEY, v TEXT);
'''


def build(src, out, plan_only=False, as_json=False):
    if not os.path.isdir(src):
        print(f'❌ 源目录不存在: {src}', file=sys.stderr)
        return 2
    files, skipped = [], []
    for r, _dd, ff in os.walk(src):
        for f in sorted(ff):
            ext = os.path.splitext(f)[1].lower()
            p = os.path.join(r, f)
            if ext in DIRECT:
                files.append((p, f, DIRECT[ext]))
            elif ext in NEEDS_CONVERT:
                skipped.append({'file': f, 'reason': f'{NEEDS_CONVERT[ext]}，需先经 convert-documents-to-markdown 转换'})
            # 其他扩展名（.xlsx 等）不计入，也不报错
    if plan_only:
        rep = {'src': src, 'to_process': len(files), 'skipped': skipped,
               'by_ext': dict(Counter(os.path.splitext(f)[1].lower() for _p, f, _k in files))}
        if as_json:
            print(json.dumps(rep, ensure_ascii=False, indent=1))
        else:
            print(f'=== 干跑（未写入任何文件）===')
            print(f'  源目录: {src}')
            print(f'  待处理: {len(files)} 件')
            for ext, n in rep['by_ext'].items():
                print(f'    {ext}: {n} 件')
            if skipped:
                print(f'  ⚠️  需先转换 {len(skipped)} 件（本脚本不处理）:')
                for s in skipped[:15]:
                    print(f'      {s["file"]} —— {s["reason"]}')
                if len(skipped) > 15:
                    print(f'      … 共 {len(skipped)} 件')
            print('\n  确认无误后去掉 --plan 正式导入。')
        return 0

    # 解析
    docs, failed = [], []
    for p, f, kind in files:
        try:
            raw = docx_text(p) if kind == 'docx' else read_text(p)
        except Exception as e:
            failed.append({'file': f, 'reason': f'{type(e).__name__}: {e}'})
            continue
        if len(raw.strip()) < 50:
            failed.append({'file': f, 'reason': '提取到的文字过少（可能为图片型/空文档）'})
            continue
        body = clean(raw)
        docs.append({'path': p, 'filename': f, 'fmt': kind,
                     'doc_type': detect_doc_type(f, body.split('\n')[0] if body else '', body),
                     'year': detect_year(body, f), 'dept': detect_dept(body),
                     'chars': len(body), 'txt_hash': txt_hash(raw),
                     'content': body, 'raw_content': raw})

    os.makedirs(out, exist_ok=True)
    db = os.path.join(out, 'corpus.db')
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    now = datetime.datetime.now().isoformat(timespec='seconds')
    for d in docs:
        conn.execute('''INSERT OR REPLACE INTO docs
            (path,filename,fmt,doc_type,year,dept,chars,txt_hash,content,raw_content,added_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (d['path'], d['filename'], d['fmt'], d['doc_type'], d['year'], d['dept'],
             d['chars'], d['txt_hash'], d['content'], d['raw_content'], now))
    conn.execute("INSERT INTO docs_fts(docs_fts) VALUES('rebuild')")
    conn.execute('INSERT OR REPLACE INTO build_meta VALUES (?,?)', ('last_build', now))
    conn.execute('INSERT OR REPLACE INTO build_meta VALUES (?,?)', ('src', src))
    conn.commit()
    conn.close()

    # 蒸馏（幂等：每次全量重算）
    prof = distill(docs) if docs else {}
    written = []

    def w(name, text):
        from pathlib import Path as _P
        _P(os.path.join(out, name)).write_text(text, encoding='utf-8')
        written.append(name)

    if docs:
        s = prof['sent']
        lv = prof['levels']
        w('profile_文风画像.md', '\n'.join([
            '# 单位文风画像（确定性统计）', '',
            f'> 样本 {prof["docs"]} 件 / 约 {prof["total_chars"]:,} 字 ｜ 生成 {now}',
            f'> ⚠️ 本画像为**统计结果**，非语义提炼。样本充足度见下，不足时不得作为硬依据。', '',
            '## 句长', f'- 平均 {s["mean"]} 字 ｜ 中位 {s["p50"]} 字 ｜ P90 {s["p90"]} 字 ｜ 超 60 字的句子 {s["over60"]} 句',
            '', '## 结构装置频次', f'- 一级「一、」{lv["level1_一、"]} 处 ｜ 二级「（一）」{lv["level2_（一）"]} 处 ｜ 三级「1.」{lv["level3_1."]} 处',
            '', '## 惯用开头（文首首行 Top10）', ''] +
            [f'- {t}（{n} 次）' for t, n in prof['head_top'][:10]] +
            ['', '## 惯用收尾（文末末行 Top10）', ''] +
            [f'- {t}（{n} 次）' for t, n in prof['tail_top'][:10]] +
            ['', '## 高频表述（分词 Top20）', ''] +
            [f'- {t}（{n} 次）' for t, n in prof['token_top'][:20]] + ['']))

        w('profile_口径清单.md', '\n'.join([
            '# 单位常用口径与固定表述', '',
            f'> 样本 {prof["docs"]} 件 ｜ 由确定性统计得出（非语义推断）', '',
            '## 实名口径（本单位如何自称）', ''] +
            ([f'- {t}（{n} 次）' for t, n in prof['office_top'][:20]]
             or ['- （样本中未检出「我局/我市」类实名口径；如确应有，请确认样本是否覆盖公文正件）']) +
            ['', '## 发文主体分布', ''] +
            ([f'- {t}（{n} 件）' for t, n in prof['by_dept'].items()] or ['- （未识别到落款机关）']) +
            ['', '## 使用建议', '',
             '- 写作时**照用**上表口径（本单位自称是硬约定，不得改写为通用说法）',
             '- 应避免的表述：本清单只收录"本单位怎么写"，**不含禁用词**；禁用语检查请走 `govdoc-polish` 质检模式（含 107,195 条敏感词库）', '']))

        idx = ['# 本单位历史范文索引（按文种 × 年份）', '',
               f'> 样本 {prof["docs"]} 件 ｜ 生成 {now}', '',
               '> 用途：写作前查本单位同类先例，再回 `corpus.db` 取全文（`SELECT content FROM docs WHERE path=?`）。', '']
        by_ty = defaultdict(lambda: defaultdict(list))
        for d in docs:
            by_ty[d['doc_type']][d['year'] or '年份未识别'].append(d)
        for ty in sorted(by_ty, key=lambda k: -sum(len(v) for v in by_ty[k].values())):
            n = sum(len(v) for v in by_ty[ty].values())
            idx.append(f'## {ty}（{n} 件）｜ 样本充足度：{adequacy(n)}')
            for y in sorted(by_ty[ty], key=lambda x: (x == '年份未识别', x)):
                for d in by_ty[ty][y]:
                    idx.append(f'- [{y}] {d["filename"]}（{d["chars"]} 字）')
            idx.append('')
        w('index_范文索引.md', '\n'.join(idx))

    # 报告
    rep_lines = ['# 建库报告', '', f'> 源目录：{src}', f'> 输出目录：{out}',
                 f'> 时间：{now}', '',
                 f'## 处理结果', '',
                 f'- 待处理 {len(files)} 件 ｜ **成功 {len(docs)} 件** ｜ 失败 {len(failed)} 件 ｜ 需先转换 {len(skipped)} 件',
                 f'- 本地库：`corpus.db`（独立库，**未写入公共语料库**）', '']
    if prof.get('by_type'):
        rep_lines += ['## 文种分布与样本充足度', '',
                      '| 文种 | 件数 | 充足度 |', '|---|---|---|']
        for ty, n in sorted(prof['by_type'].items(), key=lambda x: -x[1]):
            rep_lines.append(f'| {ty} | {n} | {adequacy(n)} |')
        rep_lines.append('')
    if prof.get('by_year'):
        rep_lines += ['## 年份分布', '', ' ｜ '.join(f'{y}:{n}' for y, n in sorted(prof['by_year'].items())), '']
    low = [ty for ty, n in prof.get('by_type', {}).items() if n < 3]
    if low:
        rep_lines += ['## ⚠️ 样本不足的文种（画像不足以作为依据）', '',
                      ' ｜ '.join(f'{t}（{prof["by_type"][t]} 件）' for t in low), '']
    if failed:
        rep_lines += ['## 解析失败清单（逐项列出，未静默跳过）', '', '| 文件 | 原因 |', '|---|---|']
        rep_lines += [f'| {x["file"]} | {x["reason"]} |' for x in failed[:40]]
        if len(failed) > 40:
            rep_lines.append(f'| … | 共 {len(failed)} 件 |')
        rep_lines.append('')
    if skipped:
        rep_lines += ['## 需先转换的文件（本脚本不处理）', '',
                      '先用 `convert-documents-to-markdown` 转成 Markdown 后重新导入：', '']
        rep_lines += [f'- {x["file"]} —— {x["reason"]}' for x in skipped[:40]]
        if len(skipped) > 40:
            rep_lines.append(f'- … 共 {len(skipped)} 件')
        rep_lines.append('')
    rep_lines += ['## 合规声明', '',
                  '- 全程本地运行：本脚本**不含网络调用、不读取 LLM 凭据**，解析与统计均在本机完成。',
                  '- 独立库：语料写入本目录 `corpus.db`，**未写入** `gongwen_corpus.db`（与公共语料物理隔离）。',
                  '- 涉密件不应导入；如误导入，请删除本目录并重新筛选源目录后重建。', '']
    w('build_report.md', '\n'.join(rep_lines))

    if as_json:
        print(json.dumps({'src': src, 'out': out, 'ok': len(docs), 'failed': failed,
                          'needs_convert': skipped, 'written': written,
                          'by_type': prof.get('by_type', {})}, ensure_ascii=False, indent=1))
    else:
        print(f'✓ 建库完成：{out}')
        print(f'  成功 {len(docs)} 件 ｜ 失败 {len(failed)} 件 ｜ 需先转换 {len(skipped)} 件')
        print(f'  产物：{", ".join(written)}')
        if failed:
            print(f'  ⚠️  {len(failed)} 件解析失败，详见 build_report.md（未静默跳过）')
        low = [t for t, n in prof.get('by_type', {}).items() if n < 3]
        if low:
            print(f'  ⚠️  样本不足的文种（画像不可作硬依据）：{"、".join(low)}')
        print('\n  ℹ️ 全程本地运行，未联网、未调用 LLM；语料写入独立库，未污染公共语料库。')
    return 0


def main():
    ap = argparse.ArgumentParser(description='单位私有语料接入与画像蒸馏（纯本地）')
    ap.add_argument('--src', required=True, help='单位公文目录')
    ap.add_argument('--out', required=True, help='输出目录（独立语料库，勿指向公共数据根）')
    ap.add_argument('--plan', action='store_true', help='干跑：只列清单，不写入任何文件')
    ap.add_argument('--json', action='store_true', help='机器可读报告')
    a = ap.parse_args()
    out_abs = os.path.abspath(a.out)
    if 'gongwen' in os.path.basename(out_abs).lower() and '语料' not in os.path.basename(out_abs):
        print(f'⚠️  输出目录名含 "gongwen"：{out_abs}\n'
              f'   请确认真实目标是**独立**语料库而非公共数据根（<数据根>）。', file=sys.stderr)
    return build(a.src, out_abs, a.plan, a.json)


if __name__ == '__main__':
    sys.exit(main())
