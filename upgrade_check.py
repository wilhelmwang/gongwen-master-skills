#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公文大师 · 升级检测与执行工具（v7.3.0）
用法（在技能包根目录运行）：
  python upgrade_check.py --check                  # 检测当前版本矩阵
  python upgrade_check.py --compare <新包路径>      # 对比当前与新版差异（不修改）
  python upgrade_check.py --upgrade <新包路径>      # 备份 → 替换全部技能 → 保留用户数据 → 校验

技能清单由 skills_manifest.py 单一来源提供（v7.3.0）——v1.x 在此处硬编码，
且残留已删除的 `biganzi`、漏掉 `govdoc-styles` 与 `govdoc-workflow`，
导致升级静默跳过整个文风族与流程编排族。

用户数据白名单（升级时自动保留）：
  /style-models/   单位文风模型（用户蒸馏产物）
  说明：任何技能下的 style-models/、user-*/、my-* 目录均视为用户数据，升级时备份后恢复。
"""
import os, sys, re, shutil, json, glob, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(BASE, 'VERSION')
sys.path.insert(0, BASE)

# 技能清单：单一来源（受治理 24 + 安装器 1，升级时须整体同步）
try:
    from skills_manifest import GOVERNED, INSTALLER, audit
    SKILLS = list(GOVERNED) + [INSTALLER]
except Exception as _e:  # 清单模块缺失时保守降级为目录扫描
    SKILLS = sorted(d for d in os.listdir(BASE)
                    if os.path.isdir(os.path.join(BASE, d))
                    and os.path.exists(os.path.join(BASE, d, 'SKILL.md')))
    print(f'⚠️ skills_manifest 不可用（{str(_e)[:40]}），已降级为目录扫描：{len(SKILLS)} 个技能')

# 用户数据目录名（升级时保留）
USER_DIRS = {'style-models', 'user-data', 'my-data', 'user_models'}

def _layout(dirpath):
    """目录布局判定（v8.0.0 双态）：
    v8d   = 技能根（部署态/解包态：SKILL.md 在顶、嵌套模块在 references/）
    v8dev = 开发树（gongwen-master/ 子目录含 VERSION）
    v7    = 多技能平铺包根"""
    if os.path.isfile(os.path.join(dirpath, 'SKILL.md')) and \
            os.path.isdir(os.path.join(dirpath, 'references', 'govdoc-notice')):
        return 'v8d'
    if os.path.isfile(os.path.join(dirpath, 'gongwen-master', 'VERSION')):
        return 'v8dev'
    return 'v7'


def _md(dirpath, skill):
    """技能 SKILL.md 在任意布局/任意目录下的绝对路径"""
    lay = _layout(dirpath)
    if lay == 'v8d':
        return os.path.join(dirpath, 'SKILL.md') if skill == 'gongwen-master' \
            else os.path.join(dirpath, 'references', skill, 'SKILL.md')
    if lay == 'v8dev':
        base = os.path.join(dirpath, 'gongwen-master')
        return os.path.join(base, 'SKILL.md') if skill == 'gongwen-master' \
            else os.path.join(base, 'references', skill, 'SKILL.md')
    return os.path.join(dirpath, skill, 'SKILL.md')


def get_version(dirpath, skill):
    """读取技能 version（v7.3.1：委托 skillmeta；v8.0.0：双态布局感知）"""
    fp = _md(dirpath, skill)
    if not os.path.exists(fp):
        return None
    try:
        import skillmeta
        return skillmeta.version(fp) or '?'
    except Exception:
        return '?'

def read_pkg_version(dirpath):
    vf = os.path.join(dirpath, 'VERSION')
    if os.path.exists(vf):
        return open(vf, encoding='utf-8').read().strip()
    return None

def version_matrix(dirpath):
    """返回 {skill: version}"""
    return {s: get_version(dirpath, s) for s in SKILLS}

def collect_user_data(src_dir, dst_dir):
    """收集用户数据目录到 dst（升级后恢复用）"""
    saved = []
    prefix = os.path.abspath(src_dir)
    for root, dirs, files in os.walk(src_dir):
        # 跳过 backups/（避免收集自身备份产物导致递归）
        dirs[:] = [d for d in dirs if d != 'backups']
        abs_root = os.path.abspath(root)
        rel = os.path.relpath(abs_root, prefix)
        rel = '' if rel == '.' else rel
        for d in list(dirs):
            if d in USER_DIRS:
                srcp = os.path.join(abs_root, d)
                dstp = os.path.join(dst_dir, rel, d)
                os.makedirs(os.path.dirname(dstp), exist_ok=True)
                shutil.copytree(srcp, dstp)
                saved.append(os.path.join(rel, d) if rel else d)
                dirs.remove(d)
    return saved

def restore_user_data(saved, backup_dir, target):
    """把备份目录中的用户数据恢复到目标"""
    for rel in saved:
        srcp = os.path.join(backup_dir, rel)
        dstp = os.path.join(target, rel)
        os.makedirs(os.path.dirname(dstp), exist_ok=True)
        if os.path.exists(dstp):
            shutil.rmtree(dstp)
        shutil.copytree(srcp, dstp)

def cmd_check():
    print(f'=== 公文大师版本矩阵 ===')
    pv = read_pkg_version(BASE)
    print(f'包版本 (VERSION): {pv or "未找到 VERSION 文件"}')
    print(f'{"技能":36s} 版本')
    print('-' * 48)
    vm = version_matrix(BASE)
    for s in SKILLS:
        print(f'{s:36s} {vm.get(s)}')
    return 0

def cmd_compare(new_pkg):
    new_pkg = os.path.abspath(new_pkg)
    if not os.path.isdir(new_pkg):
        print(f'❌ 新包路径不存在或不是目录: {new_pkg}')
        return 1
    print(f'=== 对比: 当前 {BASE} vs 新版 {new_pkg} ===')
    old_pv, new_pv = read_pkg_version(BASE), read_pkg_version(new_pkg)
    print(f'包版本: 当前 {old_pv} → 新版 {new_pv}')
    old_vm, new_vm = version_matrix(BASE), version_matrix(new_pkg)
    print(f'\n{"技能":36s} {"当前":8s} {"新版":8s} 状态')
    print('-' * 64)
    changed = added = removed = 0
    for s in SKILLS:
        ov, nv = old_vm.get(s), new_vm.get(s)
        if ov is None and nv is not None:
            print(f'{s:36s} {"-":8s} {nv:8s} [新增]')
            added += 1
        elif ov is not None and nv is None:
            print(f'{s:36s} {ov:8s} {"-":8s} [新版缺失]')
            removed += 1
        elif ov != nv:
            print(f'{s:36s} {ov:8s} {nv:8s} [变更]')
            changed += 1
    print(f'\n变更 {changed} / 新增 {added} / 新版缺失 {removed}')
    return 0

def cmd_upgrade(new_pkg):
    new_pkg = os.path.abspath(new_pkg)
    if not os.path.isdir(new_pkg):
        print(f'❌ 新包路径不存在或不是目录: {new_pkg}')
        return 1
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_dir = os.path.join(BASE, 'backups', f'pre_upgrade_{ts}')
    print(f'=== 升级开始 ===')
    print(f'新版来源: {new_pkg}')
    print(f'备份目录: {backup_dir}')

    # ── v8.0.0 分支：单技能交付，升级 = 整技能目录替换（不再逐技能目录） ──
    if _layout(BASE) in ('v8d', 'v8dev'):
        target = BASE if _layout(BASE) == 'v8d' else os.path.join(BASE, 'gongwen-master')
        new_root = new_pkg if os.path.isfile(os.path.join(new_pkg, 'SKILL.md')) \
            else os.path.join(new_pkg, 'gongwen-master')
        if not os.path.isfile(os.path.join(new_root, 'VERSION')):
            print(f'❌ 新包内未找到技能根（应含 VERSION/SKILL.md）: {new_pkg}')
            return 1
        user_tmp = os.path.join(BASE, 'backups', f'_userdata_{ts}')
        os.makedirs(user_tmp, exist_ok=True)
        saved = collect_user_data(target, user_tmp)
        print('已备份用户数据: ' + (str(saved) if saved else '无（白名单: style-models 等）'))
        _ig = shutil.ignore_patterns('backups', '__pycache__', '.mimosa')
        if os.path.abspath(target) == os.path.abspath(BASE):
            # 部署态：工具与技能同目录，替换「内容」而非目录本身（脚本不能删自己脚下的地）
            keep = {'backups'}
            for e in os.listdir(target):
                if e not in keep:
                    p = os.path.join(target, e)
                    shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
            for e in os.listdir(new_root):
                if e in keep:
                    continue
                sp, dp = os.path.join(new_root, e), os.path.join(target, e)
                shutil.copytree(sp, dp, ignore=_ig) if os.path.isdir(sp) else shutil.copy2(sp, dp)
            print('已替换技能目录内容（部署态，保留 backups/）')
        else:
            os.makedirs(backup_dir, exist_ok=True)
            bk = os.path.join(backup_dir, 'gongwen-master')
            shutil.copytree(target, bk, ignore=_ig)
            print(f'已整目录备份当前技能 → {bk}')
            shutil.rmtree(target)
            shutil.copytree(new_root, target, ignore=_ig)
            print(f'已替换技能目录 ← {new_root}')
        if saved:
            restore_user_data(saved, user_tmp, target)
            print('已恢复用户数据')
        shutil.rmtree(user_tmp, ignore_errors=True)
        print('\n=== 升级后校验 ===')
        print(f'当前包版本: {read_pkg_version(target)}')
        import subprocess
        ok = subprocess.run([sys.executable, os.path.join(BASE, 'verify_install.py')],
                            cwd=BASE).returncode
        print(f'\n升级完成。旧版备份于: {backup_dir}')
        return 0 if ok == 0 else 1

    # 1. 备份用户数据（先于任何替换）
    user_tmp = os.path.join(BASE, 'backups', f'_userdata_{ts}')
    os.makedirs(user_tmp, exist_ok=True)
    saved = collect_user_data(BASE, user_tmp)
    if saved:
        print(f'已备份用户数据: {saved}')
    else:
        print('未发现用户数据目录（白名单: style-models 等）')

    # 2. 备份全部技能目录
    os.makedirs(backup_dir, exist_ok=True)
    for s in SKILLS:
        sp = os.path.join(BASE, s)
        if os.path.exists(sp):
            shutil.copytree(sp, os.path.join(backup_dir, s))
    print(f'已备份 {len(SKILLS)} 个技能目录')

    # 3. 替换技能目录（来自新包）
    replaced = 0
    for s in SKILLS:
        nsp = os.path.join(new_pkg, s)
        osp = os.path.join(BASE, s)
        if os.path.isdir(nsp):
            if os.path.exists(osp):
                shutil.rmtree(osp)
            shutil.copytree(nsp, osp)
            replaced += 1
    print(f'已替换 {replaced}/{len(SKILLS)} 技能目录')

    # 4. 同步 VERSION 与公共文件
    for f in ['VERSION', 'README.md', 'requirements.txt', 'verify_install.py']:
        nf = os.path.join(new_pkg, f)
        if os.path.exists(nf):
            shutil.copy2(nf, os.path.join(BASE, f))
    # 素材库合并（references/素材库）
    nref = os.path.join(new_pkg, 'references', '素材库')
    oref = os.path.join(BASE, 'references', '素材库')
    if os.path.isdir(nref):
        if os.path.exists(oref):
            shutil.rmtree(oref)
        shutil.copytree(nref, oref)
    print('已同步 VERSION/素材库/公共文件')

    # 5. 恢复用户数据
    if saved:
        restore_user_data(saved, user_tmp, BASE)
        print('已恢复用户数据')
    shutil.rmtree(user_tmp, ignore_errors=True)

    # 6. 校验
    print('\n=== 升级后校验 ===')
    new_pv = read_pkg_version(BASE)
    print(f'当前包版本: {new_pv}')
    import subprocess
    ok = subprocess.run([sys.executable, os.path.join(BASE, 'verify_install.py')],
                        cwd=BASE).returncode
    print(f'\n升级完成。旧版备份于: {backup_dir}')
    return 0 if ok == 0 else 1

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 0
    if args[0] == '--check':
        return cmd_check()
    if args[0] == '--compare' and len(args) > 1:
        return cmd_compare(args[1])
    if args[0] == '--upgrade' and len(args) > 1:
        return cmd_upgrade(args[1])
    print(__doc__)
    return 0

if __name__ == '__main__':
    sys.exit(main())
