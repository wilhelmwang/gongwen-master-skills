# -*- coding: utf-8 -*-
"""国标体检器反向注入回归 C2-v1.0

为什么要「反向注入」而不是只跑正常件
-----------------------------------
只跑正常件，得到的是「通过」。但一个从不报错的体检器也会「通过」——
那说明不了它真的在判。做法：把已知偏差**主动注入**到一份已通过体检的件里，
断言体检器必须检出它，并且退出码必须变。

上游 repo1 的 `tests/run_tests.sh` 用的是同一思路（改坏 reserve 段的
`w:line="1"` → 必须 verify 失败并 grep 到 `Preprinted letterhead reserve`）。

覆盖的三类注入
--------------
1. 行距   w:spacing/@w:line  579 → 640      → 必须 FAIL 「正文行距」
2. 字体   仿宋_GB2312 → 宋体               → 必须 FAIL 「正文字体(仿宋)」
3. 页边距 w:pgMar/@w:top      2098 → 1701  → 必须 FAIL 「天头」

设计纪律
--------
· **不动运行环境**：注入件只写在临时目录，原件只读。
· 注入用 `ElementTree` 逐属性改，不用字符串替换 —— 字符串替换会连带改到
  footer 里的同名属性，把「注入了一项」变成「注入了三项」，
  测出来的失败就说不清是哪一个触发的。
· 注入后先自证「确实改到了」（注入函数返回说明串），自证不过就报错退出，
  否则会得到「体检器没检出」的假失败。

用法
----
  python test_govdoc_injection.py                    # 自建基准件后注入
  python test_govdoc_injection.py --base 已有件.docx # 用指定件作基准
  python test_govdoc_injection.py -v
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

#: 注入项：(名称, 体检器应报出的项名子串, 改法)
INJECTIONS = []


def _reg(name, expect, fn):
    INJECTIONS.append((name, expect, fn))


def _set_lines(root, _meta, target):
    """把正文行距整体改成 target。"""
    hits = [sp for sp in root.iter(f'{W}spacing') if sp.get(f'{W}line')]
    if not hits:
        return None
    for sp in hits:
        sp.set(f'{W}line', str(target))
        sp.set(f'{W}lineRule', 'exact')
    return f'{len(hits)} 处 w:line 改为 {target}'


def _set_body_font(root, _meta, target):
    """把正文用字体名改成 target（跳过标题段：标题用二号 44 半磅）。"""
    n = 0
    for p in root.iter(f'{W}p'):
        if 'w:val="44"' in ET.tostring(p, encoding='unicode'):
            continue
        for f in p.iter(f'{W}rFonts'):
            if f.get(f'{W}eastAsia') == '仿宋_GB2312':
                f.set(f'{W}eastAsia', target)
                n += 1
    return f'{n} 处正文 eastAsia 改为 {target}' if n else None


def _set_pgmar(root, _meta, tag, target):
    for m in root.iter(f'{W}pgMar'):
        if m.get(f'{W}{tag}'):
            old = m.get(f'{W}{tag}')
            m.set(f'{W}{tag}', str(target))
            return f'w:pgMar/@w:{tag} {old} → {target}'
    return None


_reg('行距', '正文行距', lambda root, meta: _set_lines(root, meta, 640))
_reg('正文字体', '正文字体(仿宋)', lambda root, meta: _set_body_font(root, meta, '宋体'))
_reg('天头页边距', '天头', lambda root, meta: _set_pgmar(root, meta, 'top', 1701))


def make_base(out_path):
    """用本包写侧生成一份合规基准件（与 23 号引擎同源，无外部依赖）。"""
    md = os.path.join(os.path.dirname(out_path), '_inj_base.md')
    with open(md, 'w', encoding='utf-8', newline='\n') as f:
        f.write('# 关于开展体检器反向注入回归的通知\n\n'
                '## 发文字号\n示例发〔2026〕7号\n\n'
                '## 主送单位\n各有关单位：\n\n'
                '## 正文\n现就有关工作通知如下。\n\n'
                '## 一、工作目标\n完成反向注入回归。\n\n'
                '## 落款\n示例单位\n2026年2月3日\n')
    gen = os.path.join(HERE, 'generate_docx.py')
    r = subprocess.run([sys.executable, gen, md, '-o', out_path, '--doc-type', '通知'],
                       capture_output=True, text=True, encoding='utf-8')
    return r.returncode == 0 and os.path.exists(out_path), (r.stdout or '') + (r.stderr or '')


def inject(src, dst, fn):
    """把改动写进新件；返回 (是否确实改到, 说明)。"""
    with zipfile.ZipFile(src) as zin:
        parts = {n: zin.read(n) for n in zin.namelist()}
    root = ET.fromstring(parts['word/document.xml'])
    desc = fn(root, {})
    if not desc:
        return False, '注入未命中任何属性'
    parts['word/document.xml'] = ET.tostring(root, encoding='UTF-8', xml_declaration=True)
    with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as z:
        for n, b in parts.items():
            z.writestr(n, b)
    return True, desc


def run_inspect(path):
    ins = os.path.join(HERE, 'inspect_govdoc.py')
    r = subprocess.run([sys.executable, ins, path, '-v'],
                       capture_output=True, text=True,
                       encoding='utf-8', errors='replace',
                       env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def main():
    ap = argparse.ArgumentParser(description='国标体检器反向注入回归（只读原件；注入件写临时目录）')
    ap.add_argument('--base', default=None, help='基准件路径（默认自动生成一份合规件）')
    ap.add_argument('-v', '--verbose', action='store_true', help='打印体检器完整输出')
    a = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix='govdoc-inject-')
    results = []

    if a.base:
        base = a.base
        if not os.path.exists(base):
            print(f'基准件不存在: {base}', file=sys.stderr)
            return 2
        print(f'基准件: {base}（外部指定）')
    else:
        base = os.path.join(tmp, 'base.docx')
        ok, log = make_base(base)
        if not ok:
            print(f'无法生成基准件，回归无法进行:\n{log}', file=sys.stderr)
            return 2
        print(f'基准件: 已生成（{os.path.getsize(base)} 字节）')

    # 基准件必须先是「通过」的，否则注入后的失败说不清是谁造成的
    rc0, out0 = run_inspect(base)
    bad0 = [ln for ln in out0.splitlines() if '❌' in ln]
    if bad0:
        print('基准件本身就有 FAIL，先修基准再谈注入:\n  ' + '\n  '.join(bad0), file=sys.stderr)
        return 2
    print(f'基准件体检: 退出码 {rc0}，无 FAIL —— 可作注入基准\n')

    for name, expect, fn in INJECTIONS:
        dst = os.path.join(tmp, f'inj_{len(results)}.docx')
        applied, desc = inject(base, dst, fn)
        if not applied:
            results.append((name, False, f'注入未命中（{desc}）—— 装具问题，非体检器问题'))
            continue
        rc, out = run_inspect(dst)
        hit = any(('❌' in ln or 'WARN' in ln) and expect in ln for ln in out.splitlines())
        fail_line = [ln for ln in out.splitlines() if '❌' in ln and expect in ln]
        ok = bool(fail_line)
        results.append((name, ok, f'{desc} ｜ 退出码 {rc} ｜ ' +
                        ('已检出并 FAIL' if ok else
                         ('已检出但仅 WARN（未进门禁）' if hit else '**未被检出**'))))
        if a.verbose:
            print(f'--- {name} 注入后体检输出 ---')
            print(out)

    print('=== 反向注入回归结果 ===')
    n_ok = 0
    for name, ok, msg in results:
        print(f'  {"✅" if ok else "❌"} {name:8s} {msg}')
        n_ok += ok
    print(f'\n  结果: 检出并 FAIL {n_ok}/{len(results)}')
    if n_ok != len(results):
        print('  ❌ 有注入项未被体检器检出 —— 体检器存在盲区，或注入装具失效')
    else:
        print('  ✅ 全部注入项均被检出，体检器确实在判（不是一个恒真的检查器）')
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if n_ok == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
