#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公文大师跨环境安装器（gongwen-installer · v1.0.0，2026-09-01）
唯一安装通道：任何 agent（WorkBuddy / 豆包 / Claude / 通用）加载 installer skill 后自行安装。

用法：
  python install.py                          # 自动探测技能根目录并安装
  python install.py --target <目录>           # 显式指定技能根目录（如豆包 Doubao/skills）
  python install.py --source <包源目录>        # 指定包源（默认：脚本上级目录 = 本包）
  python install.py --no-deps                 # 跳过 pip 依赖安装
  python install.py --upgrade                 # 目标已存在时先备份再替换（等效 upgrade_check --upgrade）

技能根目录自动探测优先级：
  1. --target 参数
  2. 环境变量 GONGWEN_SKILLS_DIR
  3. WorkBuddy : ~/.workbuddy/skills/
  4. 豆包      : ~/Doubao/skills/（Windows 桌面版常见）
  5. Claude    : ~/.claude/skills/
  6. 通用      : ~/.skills/

安装动作：复制全部技能目录 + datahub 数据层 + 工具脚本 → 安装依赖 → 运行 verify_install 校验 → 输出报告。

v7.3.0：
  · 技能清单改由 skills_manifest.py 单一来源提供（原硬编码残留已删除的 `biganzi`、
    漏掉 `govdoc-styles`，会导致安装后整个文风族缺失）
  · ROOT_FILES 补齐 verify_install 依赖的 `skills_manifest.py` 与 `validate_skills.py`
    （此前缺失 → 装到目标环境后 frontmatter 校验与清单审计必失败）
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# 技能清单：单一来源（受治理 24 + 安装器本身 1）。包源可能不含 skills_manifest.py
# （极旧包），故保留目录扫描兜底。
_SRC_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_SRC_ROOT))
try:
    from skills_manifest import GOVERNED, INSTALLER
    SKILLS = list(GOVERNED) + [INSTALLER]
except Exception:
    SKILLS = sorted(d.name for d in _SRC_ROOT.iterdir()
                    if d.is_dir() and (d / 'SKILL.md').exists()) if _SRC_ROOT.is_dir() else []

# 根文件（与技能一起复制）。verify_install.py 依赖 skills_manifest + validate_skills，
# 二者必须随包，否则目标环境自检必失败。
ROOT_FILES = ['VERSION', 'README.md', 'requirements.txt',
              'verify_install.py', 'upgrade_check.py', 'rules_regression.py',
              'gongwen_tool.py', 'skills_manifest.py', 'skillmeta.py', 'validate_skills.py',
              'release.py', 'release_gates.json', 'doc_code_check.py', 'router.py', 'trigger_eval.py',
              'build_gold.py',
              'bootstrap_data.py', 'gen_registry.py', 'registry.json',
              'THIRD_PARTY_NOTICES.md']

def probe_target(arg_target=None):
    """探测技能根目录"""
    if arg_target:
        return Path(arg_target).expanduser()
    env = os.environ.get('GONGWEN_SKILLS_DIR')
    if env:
        return Path(env).expanduser()
    home = Path.home()
    candidates = [
        home / '.workbuddy' / 'skills',   # WorkBuddy
        home / 'Doubao' / 'skills',        # 豆包 Windows 桌面版
        home / '.doubao' / 'skills',       # 豆包 CLI
        home / '.claude' / 'skills',       # Claude
        home / '.skills',                  # 通用
    ]
    # 优先返回已存在的（说明该环境在用）
    for c in candidates:
        if c.exists():
            return c
    # 都没有 → 默认 WorkBuddy
    return candidates[0]

def install(source, target, with_deps=True, upgrade=False):
    source = Path(source).resolve()
    target = Path(target).resolve()
    dest = target / 'gongwen-skills'
    print(f'=== 公文大师安装器 ===')
    print(f'包源     : {source}')
    print(f'技能根   : {target}')
    print(f'安装目标 : {dest}')

    # 源完整性检查
    missing = [s for s in SKILLS if not (source / s).is_dir()]
    if missing:
        print(f'❌ 包源缺少技能目录: {missing[:5]}...')
        return 1
    if not (source / 'VERSION').exists():
        print('❌ 包源缺少 VERSION（非完整包）')
        return 1
    ver = (source / 'VERSION').read_text(encoding='utf-8').strip()
    print(f'安装版本 : {ver}')

    # 目标已存在处理
    if dest.exists():
        if upgrade:
            bak = target / 'backups' / f'pre_install_{ver}_{_ts()}'
            shutil.copytree(dest, bak)
            print(f'⚠️ 目标已存在（旧版）→ 已备份至 {bak}，替换安装')
        else:
            print(f'⚠️ 目标已存在: {dest}')
            print('   提示：使用 --upgrade 备份后替换，或先运行 upgrade_check.py --upgrade')
            return 2

    # 1. 复制技能目录（干净替换：旧目录 move 到 .old 而非删除，任何环境零删除、零确认）
    os.makedirs(dest, exist_ok=True)
    old_dir = dest / '.old_replace'
    os.makedirs(old_dir, exist_ok=True)
    n_skill = 0
    for s in SKILLS:
        dst_s = dest / s
        if dst_s.exists():
            shutil.move(str(dst_s), str(old_dir / s))   # 重命名移动，非删除
        shutil.copytree(source / s, dst_s)
        n_skill += 1
    print(f'✅ 技能目录 {n_skill}/{len(SKILLS)}（干净替换，旧版移入 .old_replace）')

    # 2. 复制数据层（datahub/ 全目录：sqlite + derived + scripts + schema；backups 不入安装）
    dst_dh = dest / 'datahub'
    if (source / 'datahub').exists():
        if dst_dh.exists():
            shutil.move(str(dst_dh), str(old_dir / 'datahub'))
        shutil.copytree(source / 'datahub', dst_dh,
                        ignore=shutil.ignore_patterns('backups'))
        print('✅ 数据层 datahub/（sqlite 3 库 + derived 资产 + scripts 引擎）')
    else:
        print('⚠️ 包源无 datahub/（运行时数据缺失，检索功能不可用）')

    # 3. 根文件 + 清理旧版根残留（v5 的 scripts/ config.json dictionaries 等，同样 move）
    for f in ROOT_FILES:
        sf = source / f
        if sf.exists():
            shutil.copy2(sf, dest / f)
    for old in (dest / 'scripts', dest / 'config.json', dest / 'dictionaries'):
        if old.exists() and not (source / old.name).exists():
            shutil.move(str(old), str(old_dir / old.name))
            print(f'🧹 旧版残留移入 .old_replace: {old.name}/')
    print('✅ 工具脚本（verify/upgrade/VERSION）')

    # 4. 依赖
    if with_deps:
        req = dest / 'requirements.txt'
        if req.exists():
            print('⏳ 安装 Python 依赖...')
            r = subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '-r', str(req)])
            if r.returncode == 0:
                print('✅ 依赖安装完成')
            else:
                print('⚠️ 依赖安装失败（可手动 pip install -r requirements.txt）')
        else:
            print('⚠️ 无 requirements.txt，跳过依赖')

    # 5. 校验
    print('\n=== 校验 ===')
    vp = dest / 'verify_install.py'
    if vp.exists():
        r = subprocess.run([sys.executable, '-u', str(vp)], cwd=str(dest))
        ok = r.returncode == 0
        print(f'\n校验: {"✅ 通过" if ok else "❌ 未通过"}')
    else:
        ok = False
        print('❌ verify_install.py 缺失')

    # 6. 报告
    print(f'\n=== 安装报告 ===')
    print(f'目标   : {dest}')
    print(f'版本   : {ver}')
    print(f'状态   : {"✅ 完整可用" if ok else "⚠️ 有异常"}')
    print(f'验证   : python {dest / "verify_install.py"}')
    return 0 if ok else 1

def _ts():
    import datetime
    return datetime.datetime.now().strftime('%Y%m%d_%H%M%S')

def find_package_root(start):
    """从 start 向上查找含 VERSION + gongwen-master 的包根目录"""
    cur = Path(start).resolve()
    for _ in range(5):
        if (cur / 'VERSION').exists() and (cur / 'gongwen-master').is_dir():
            return cur
        cur = cur.parent
    return None



def fix_target(target):
    """归一：安装目标技能目录（install() 内部用 target/'gongwen-skills'）"""
    import pathlib
    t = pathlib.Path(target)
    return t / 'gongwen-skills' if not (t / 'VERSION').exists() else t


def smoke(root):
    """冒烟自检：资产在位 + 双引擎各 1 条检索（2026-09-03）"""
    import subprocess, sys
    root = fix_target(root)
    print('\n=== 冒烟自检（--smoke）===')
    oks = []
    dh = root / 'datahub'
    for rel, note in [('sqlite/gongwen_corpus.db', '主库'),
                      ('derived/qs_index.pkl', '检索索引'), ('scripts/qs/qiushi_engine.py', '求是引擎'),
                      ]:
        ok = (dh / rel).exists()
        oks.append(ok)
        print(f"  {'✅' if ok else '❌'} {note}: {rel}")
    py = sys.executable
    r2 = subprocess.run([py, str(dh / 'scripts' / 'qs' / 'qiushi_engine.py'), 'search', '新质生产力', '--top', '1'],
                        capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=str(root))
    h2 = len(r2.stdout.strip()) > 40
    oks.append(h2)
    print(f"  {'✅' if h2 else '❌'} 求是检索冒烟: '新质生产力' TOP1（{len(r2.stdout.strip())} 字符输出）")
    print(f"冒烟结果: {sum(oks)}/{len(oks)} 通过" + (' → 安装可用 ✅' if all(oks) else ' → 请检查 ⚠️'))
    return 0 if all(oks) else 1

def main():
    ap = argparse.ArgumentParser(description='公文大师跨环境安装器')
    ap.add_argument('--target', help='技能根目录（默认自动探测）')
    ap.add_argument('--source', default=None, help='包源目录（默认：自动查找含 VERSION 的包根）')
    ap.add_argument('--no-deps', action='store_true', help='跳过 pip 依赖安装')
    ap.add_argument('--upgrade', action='store_true', help='目标已存在时备份后替换')
    ap.add_argument('--smoke', action='store_true', help='安装完成后自动冒烟自检（检索×2 + 资产在位）')
    ap.add_argument('--check-target', action='store_true', help='仅探测并打印技能根目录，不安装')
    args = ap.parse_args()

    source = Path(args.source).resolve() if args.source else find_package_root(Path(__file__).resolve().parent)
    if source is None:
        print('❌ 未找到包源（含 VERSION + gongwen-master 的目录）。请用 --source <包源目录> 指定。')
        return 1
    target = probe_target(args.target)
    if args.check_target:
        print(f'技能根目录: {target}')
        dest = target / 'gongwen-skills'
        print(f'安装目标  : {dest}')
        if dest.exists():
            ver = (dest / 'VERSION').read_text(encoding='utf-8').strip() if (dest / 'VERSION').exists() else '未知'
            print(f'已存在    : 是（版本 {ver}）→ 建议 --upgrade 备份后替换')
        else:
            print('已存在    : 否（全新安装）')
        return 0
    rc = install(source, target, with_deps=not args.no_deps, upgrade=args.upgrade)
    if rc == 0 and args.smoke:
        return smoke(fix_target(target))
    return rc

if __name__ == '__main__':
    sys.exit(main())
