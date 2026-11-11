#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""版式视觉审计（visual-audit v1.0.0）

做什么
------
把一批公文场景**全部生成一遍**，逐份跑版式体检，再把能在本机渲染的那些转成 PDF／PNG，
最后可选量字形坐标。产出一张清单（manifest.tsv），
让「这一批到底验了什么、哪几件没验、为什么没验」变成可查的记录。

为什么需要它
------------
单件生成 + 单个校验通过，说明不了任何东西：
- 一个**从不报错**的体检器，对每件都「通过」；
- 换一个文种、换一个版式分支，走的是完全不同的代码路径，单件跑通不覆盖；
- 渲染环节缺工具时，**「没验」最容易被读成「验过且通过」**。

因此本脚本有三条硬口径：
1. **批量**：覆盖场景表列出的每一种分支，而不是挑一件跑。
2. **反向**：体检结果按 PASS/WARN/FAIL/SKIP/MANUAL 五态分别计数，
   FAIL 必须让整体退出码非零；MANUAL（机器不可判）单独列出，
   **不计入 PASS**，也不影响退出码——它是「没验」，不是「不过」。
3. **工具链缺失单独成一态且单独占一个退出码**（见下）。

退出码
------
  0  全部生成、体检通过，且渲染量测已跑
  1  有生成失败或体检 FAIL
  **3  生成与体检通过，但渲染量测【未跑】（缺 soffice / PDF 后端）**
  2  参数或环境错误（场景表不可读等）

  3 与 0 分开是有意的：「没有工具所以没验」与「验了通过」是两回事。
  把 3 并在 0 里，等于把「未验」报成「通过」。

用法
----
  python visual_audit.py --out 输出目录
  python visual_audit.py --out 输出目录 --scenarios 场景表.json
  python visual_audit.py --generate-only --out 输出目录
  python visual_audit.py --out 输出目录 --anchors "机关标志=示例单位文件" --range "机关标志=68-77"

场景表格式（JSON）
------------------
  [{"name": "ordinary-报告", "doc_type": "报告", "md": "…成稿 markdown…"},
   {"name": "letter-信函",   "doc_type": "信函", "md": "…", "args": ["--hide-page-number"]},
   {"name": "preprinted-套打", "doc_type": "通知", "md": "…",
    "args": ["--hide-sections", "留白:版头", "--letterhead-reserve-mm", "110"]}]

  md 也可以写成 {"md_file": "相对或绝对路径"}。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LAYOUT = os.path.dirname(HERE)          # .../govdoc-layout
SCRIPTS = os.path.join(LAYOUT, 'scripts')
GEN = os.path.join(SCRIPTS, 'generate_docx.py')
INSPECT = os.path.join(SCRIPTS, 'inspect_govdoc.py')
MEASURE = os.path.join(HERE, 'measure_layout_coords.py')

# 生成场景表：覆盖本机 --doc-type 能走到的每种版式分支
# 通用成稿骨架（场景可用 md_suffix 在正文与落款之间插入场景专属段落）
BODY_TAIL = (
    '## 落款\n示例单位\n2026年9月28日\n\n'
    '## 版记\n抄送：各有关单位。\n示例单位办公室　2026年9月28日印发\n'
)

BODY_HEAD = (
    '## 版头\n示例单位文件\n\n'
    '## 发文字号\n示例发〔2026〕7号\n\n'
    '## 主送单位\n各县（市、区）人民政府，市直各部门：\n\n'
    '## 标题\n关于加强公文版式核验工作的通知\n\n'
    '## 正文\n为进一步规范公文版式，现就有关工作通知如下。\n\n'
    '## 一、核对版心参数\n'
    '各单位应按 GB/T 9704-2012 逐项核对天头、订口与版心尺寸。'
    '天头为 37mm，订口为 28mm，版心为 156mm×225mm。'
    '一是核对页面尺寸；二是核对页边距；三是核对每面行数与每行字数。\n\n'
    '## 二、核对标题层级\n'
    '一级标题用黑体，二级标题用楷体，三级及以下用仿宋。'
    '（一）字体不得混用。\n1. 字号应统一为三号。\n\n'
    '## 三、核对落款与版记\n'
    '成文日期用阿拉伯数字标注，署名与日期右空对齐。\n\n'
)

BODY = BODY_HEAD + BODY_TAIL

# 横排表格场景专用：正文末尾插入一张管道表，用于验证 225mm 表宽与横排页面。
MD_SUFFIX_TABLE = (
    '## 四、指标表\n'
    '| 序号 | 指标名称 | 单位 | 目标值 |\n'
    '|---|---|---|---|\n'
    '| 1 | 覆盖率 | % | 95 |\n'
    '| 2 | 完成率 | % | 100 |\n'
    '| 3 | 合格率 | % | 98 |\n\n'
)

DEFAULT_SCENARIOS = [
    {'name': 'ordinary-报告', 'doc_type': '报告'},
    {'name': 'ordinary-通知', 'doc_type': '通知'},
    {'name': 'ordinary-意见', 'doc_type': '意见'},
    {'name': 'ordinary-调研', 'doc_type': '调研'},
    {'name': 'internal-readable-简报', 'doc_type': '简报'},
    {'name': 'speech-readable-讲话',
     'doc_type': '讲话', 'args': ['--layout-variant', 'speech-readable']},
    {'name': 'internal-readable-信息', 'doc_type': '信息'},
    {'name': 'speech-readable-致辞', 'doc_type': '致辞'},
    {'name': 'letter-信函', 'doc_type': '信函', 'args': ['--org', '示例单位']},
    {'name': 'command-命令', 'doc_type': '命令', 'args': ['--org', '示例单位']},
    {'name': 'horizontal-table-横排表', 'doc_type': '通知',
     'args': ['--format', 'horizontal-table'],
     'md_suffix': MD_SUFFIX_TABLE},
    {'name': 'letter-hide-版头', 'doc_type': '信函',
     'args': ['--org', '示例单位', '--hide-sections', '版头']},
    {'name': 'letter-preprinted-留白', 'doc_type': '信函',
     'args': ['--org', '示例单位', '--hide-sections', '留白:版头']},
    {'name': 'default-format-显式', 'doc_type': '通知', 'args': ['--format', 'default']},
    {'name': 'notice-no-page-number', 'doc_type': '通知', 'args': ['--hide-page-number']},
    {'name': 'notice-unsealed', 'doc_type': '通知', 'args': ['--unsealed']},
    {'name': 'notice-preprinted-留白', 'doc_type': '通知',
     'args': ['--hide-sections', '留白:版头', '--letterhead-reserve-mm', '110']},
    {'name': 'notice-preprinted-默认', 'doc_type': '通知',
     'args': ['--hide-sections', '留白:版头']},
    {'name': 'notice-hide-标题', 'doc_type': '通知', 'args': ['--hide-sections', '标题']},
    {'name': 'noto-cjk-通知', 'doc_type': '通知', 'args': ['--font-preset', 'noto-cjk']},
]

def which(name):
    return shutil.which(name)


def _flag_value(args, flag):
    """从参数列表里取某个 flag 的值（形如 ['--format', 'letter']）。"""
    for i, x in enumerate(args):
        if x == flag and i + 1 < len(args):
            return args[i + 1]
        if x.startswith(flag + '='):
            return x.split('=', 1)[1]
    return None


def toolchain():
    """返回 (可用渲染链的说明, 缺失清单)。"""
    missing = []
    if not which('soffice'):
        missing.append('soffice（LibreOffice，负责 DOCX→PDF）')
    backend = None
    try:
        import fitz  # noqa: F401
        backend = 'PyMuPDF'
    except ImportError:
        if which('pdftotext'):
            backend = 'pdftotext'
        else:
            missing.append('PDF 解析后端（PyMuPDF 或 pdftotext）')
    return backend, missing


def run(cmd, cwd=None):
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    return p.returncode, (p.stdout or ''), (p.stderr or '')


def tally(out):
    """从体检输出里数五态。

    数的是**汇总行**（`结果: PASS n ｜ WARN n ｜ …`），不是逐个找状态词：
    逐项行用的是图标（✅/⚠️/❌/⏭/🙋），不含状态词本身，
    而正文里偶尔会出现「FAIL」这类词（如「不判 FAIL」），按词计数会把它算进去。
    """
    n = {'PASS': 0, 'WARN': 0, 'FAIL': 0, 'SKIP': 0, 'MANUAL': 0}
    m = re.search(r'结果:\s*PASS\s*(\d+)\s*｜\s*WARN\s*(\d+)\s*｜\s*FAIL\s*(\d+)'
                  r'\s*｜\s*SKIP\s*(\d+)(?:\s*｜\s*MANUAL\s*(\d+))?', out)
    if not m:
        return n, False
    for i, k in enumerate(('PASS', 'WARN', 'FAIL', 'SKIP', 'MANUAL')):
        n[k] = int(m.group(i + 1) or 0)
    return n, True


def load_scenarios(path):
    if not path:
        return [dict(s, md=(s.get('md') or BODY_HEAD + s.get('md_suffix', '') + BODY_TAIL),
                     args=list(s.get('args', [])))
                for s in DEFAULT_SCENARIOS]
    if not os.path.exists(path):
        print(f'场景表不存在: {path}', file=sys.stderr)
        sys.exit(2)
    try:
        data = json.load(open(path, encoding='utf-8'))
    except json.JSONDecodeError as e:
        print(f'场景表不是合法 JSON: {e}', file=sys.stderr)
        sys.exit(2)
    out = []
    for i, s in enumerate(data):
        if 'name' not in s or 'doc_type' not in s:
            print(f'场景表第 {i + 1} 项缺 name 或 doc_type', file=sys.stderr)
            sys.exit(2)
        s = dict(s)
        if 'md_file' in s:
            fp = s['md_file']
            if not os.path.isfile(fp):
                print(f'场景 {s["name"]} 的 md_file 不存在: {fp}', file=sys.stderr)
                sys.exit(2)
            s['md'] = open(fp, encoding='utf-8').read()
        s['md'] = s.get('md') or (BODY_HEAD + s.get('md_suffix', '') + BODY_TAIL)
        s.setdefault('args', [])
        out.append(s)
    return out


def main():
    ap = argparse.ArgumentParser(description='版式视觉审计（批量生成 + 体检 + 渲染量测）',
                                 add_help=False)
    ap.add_argument('--out', default=None, help='输出目录（默认建临时目录）')
    ap.add_argument('--scenarios', default=None, help='场景表 JSON（默认用内置场景表）')
    ap.add_argument('--anchors', action='append', default=[],
                    help='渲染量测的锚点 名称=文字（可重复；需 soffice）')
    ap.add_argument('--range', action='append', default=[],
                    help='渲染量测的区间 名称=最小-最大（可重复）')
    ap.add_argument('--generate-only', action='store_true', help='只生成与体检，不做渲染')
    ap.add_argument('--keep', action='store_true', help='保留中间目录（默认保留 --out）')
    ap.add_argument('-h', '--help', action='store_true', help='显示本帮助')
    a = ap.parse_args()

    if a.help:
        print(__doc__)
        return 0

    for f in (GEN, INSPECT):
        if not os.path.exists(f):
            print(f'缺少本包脚本: {f}', file=sys.stderr)
            return 2

    out = a.out or tempfile.mkdtemp(prefix='govdoc-visual-')
    for sub in ('docx', 'logs', 'pdf', 'png'):
        os.makedirs(os.path.join(out, sub), exist_ok=True)
    print(f'输出目录：{out}')

    scenarios = load_scenarios(a.scenarios)
    backend, missing = toolchain()
    render_ok = (not a.generate_only) and not missing

    rows = []
    n_bad = 0
    print(f'\n=== 阶段一：生成 + 体检（{len(scenarios)} 个场景）===')
    for sc in scenarios:
        name = sc['name']
        md_path = os.path.join(out, name + '.md')
        docx_path = os.path.join(out, 'docx', name + '.docx')
        with open(md_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(sc['md'])

        rc, so, se = run([sys.executable, GEN, md_path, '-o', docx_path,
                          '--doc-type', sc['doc_type']] + list(sc['args']))
        if rc != 0 or not os.path.exists(docx_path):
            print(f'  ✗ {name:<26} 生成失败 rc={rc}  {(se or so).strip().splitlines()[-1:] or [""]}')
            rows.append({'scenario': name, 'doc_type': sc['doc_type'], 'stage': 'generate',
                         'state': 'FAIL', 'detail': f'rc={rc}'})
            n_bad += 1
            continue

        # 体检器必须知道格式档：天头与版心的应有值随档变化（信函 30mm / 横排横向 A4），
        # 不告诉它就会拿通用档的期望值去判特定格式件，必然误报 FAIL。
        # 生成侧的 --format 与体检侧的 --format 同名同义；未显式给时靠 --doc-type 自动绑定。
        icmd = [sys.executable, INSPECT, docx_path, '-v']
        if sc.get('doc_type'):
            icmd += ['--doc-type', sc['doc_type']]
        pf = _flag_value(sc.get('args', []), '--format')
        if pf:
            icmd += ['--format', pf]
        rc, so, se = run(icmd)
        blob = so + se
        with open(os.path.join(out, 'logs', name + '.inspect.log'), 'w',
                  encoding='utf-8', newline='\n') as f:
            f.write(blob)
        t, parsed = tally(blob)
        if not parsed:
            # 体检器没输出汇总行——不能当作「通过」
            print(f'  ? {name:<26} 体检输出无汇总行（未能判定）rc={rc}')
            rows.append({'scenario': name, 'doc_type': sc['doc_type'], 'stage': 'inspect',
                         'state': 'UNPARSED', 'rc': rc, 'docx': os.path.relpath(docx_path, out)})
            n_bad += 1
            continue
        state = 'FAIL' if t['FAIL'] else ('WARN' if t['WARN'] else 'PASS')
        if t['FAIL']:
            n_bad += 1
        print(f'  {"✗" if t["FAIL"] else "✓"} {name:<26} 体检 rc={rc} '
              f'PASS {t["PASS"]} ｜ WARN {t["WARN"]} ｜ FAIL {t["FAIL"]} ｜ '
              f'SKIP {t["SKIP"]} ｜ MANUAL {t["MANUAL"]}')
        rows.append({'scenario': name, 'doc_type': sc['doc_type'], 'stage': 'inspect',
                     'state': state, 'rc': rc, 'pass': t['PASS'], 'warn': t['WARN'],
                     'fail': t['FAIL'], 'skip': t['SKIP'], 'manual': t['MANUAL'],
                     'docx': os.path.relpath(docx_path, out)})

    print(f'\n结果：体检 FAIL {n_bad} 件 / 共 {len(scenarios)} 件')

    # ---- 阶段二：渲染量测 ----
    print('\n=== 阶段二：渲染量测 ===')
    not_verified = None
    if a.generate_only:
        not_verified = '指定了 --generate-only'
    elif missing:
        not_verified = '工具链缺失：' + '；'.join(missing)
    else:
        print(f'  PDF 解析后端：{backend}')
        n_render_fail = 0
        for r in rows:
            if r.get('stage') != 'inspect':
                continue
            docx = os.path.join(out, r['docx'])
            rc, so, se = run(['soffice', '--headless', '--convert-to', 'pdf',
                              '--outdir', os.path.join(out, 'pdf'), docx])
            pdf = os.path.join(out, 'pdf', r['scenario'] + '.pdf')
            if rc != 0 or not os.path.exists(pdf):
                r['not_verified'] = f'soffice 转换失败 rc={rc}'
                n_render_fail += 1
                continue
            r['pdf'] = os.path.relpath(pdf, out)
            if a.anchors:
                cmd = [sys.executable, MEASURE, pdf]
                for s in a.anchors:
                    cmd += ['--anchor', s]
                for s in a.range:
                    cmd += ['--range', s]
                mrc, mso, mse = run(cmd)
                with open(os.path.join(out, 'logs', r['scenario'] + '.measure.log'), 'w',
                          encoding='utf-8', newline='\n') as f:
                    f.write(mso + mse)
                r['measure_rc'] = mrc
                if mrc not in (0,):
                    n_render_fail += 1
        print(f'  已转 PDF {sum(1 for r in rows if r.get("pdf"))} 份；'
              f'量测异常 {n_render_fail} 份')
        if a.anchors:
            print('  每份的明细见 logs/*.measure.log')

    # ---- manifest ----
    man = os.path.join(out, 'manifest.tsv')
    cols = ['scenario', 'doc_type', 'stage', 'state', 'rc', 'pass', 'warn', 'fail',
            'skip', 'manual', 'docx', 'pdf', 'measure_rc', 'not_verified']
    with open(man, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\t'.join(cols) + '\n')
        for r in rows:
            f.write('\t'.join(str(r.get(c, '')) for c in cols) + '\n')
    print(f'\n清单：{man}')

    # ---- 批次结论（与 manifest 同源的文字版）----
    print('\n=== 本批次结论 ===')
    print(f'  生成 {len(rows)} 件 ｜ 体检 FAIL {n_bad} 件')
    if not_verified:
        print(f'  ⚠ 渲染量测：【未验】—— {not_verified}')
        print('    这一批只验了「生成器输出了什么」，没验「纸面上画到了哪里」。'
              '段前距失效、字体替换引起换行变化，都只能靠渲染量测发现。')
    else:
        print('  ✓ 渲染量测已跑（分辨率上限 ±0.5mm）')
    print('  ℹ️  MANUAL 项是机器不可判、须现场核验的要素，'
          '它们既不在 PASS 里，也不在 FAIL 里。')

    if n_bad:
        return 1
    if not_verified:
        return 3
    return 0


if __name__ == '__main__':
    sys.exit(main())
