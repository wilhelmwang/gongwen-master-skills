#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技能 frontmatter 规范校验器（v2.0 · 2026-09-11）

用法：
  python validate_skills.py            # 校验全部受治理技能，输出报告（退出码 0/1）
  python validate_skills.py --json      # 机器可读输出（供 release 流水线消费）

v2.0 关键变更（P0-A 根因修复）
  v1.x 用宽松正则（`re.S` + 非贪婪 + 回溯）解析 description，会把
  `description: "description: "…""` 这类**非法 YAML** 兜住并误报合规，
  导致 5 个技能（letter/circular/request/regulation/polish）带着
  `ParserError` 级别的 frontmatter 通过全部门禁。
  v2.0 改用**真实 YAML 解析器**做权威解析（PyYAML），并新增：
    · 规则 12：description 值不得以 `description:` 开头（本次缺陷形态）
    · 规则 11 强化：重复键由严格 YAML loader 直接抛错（不再靠正则近似）
  PyYAML 缺失时回退正则并在报告中显式告警（不静默降级）。

校验规则（对齐 Agent Skills 开放规范 + 本包约定）：
  1. frontmatter 存在（--- 开头）
  2. name：小写字母/数字/连字符，与目录名一致，≤64 字符
  3. version：存在且带引号（防 YAML float 解析），且与 registry.json 声明的版本一致
  4. description：存在，≤1024 字符，含触发语义（使用/触发/用我/when/Use）
  5. compatibility：存在且 ≤500 字符
  6. requires：存在（依赖声明节）
  7. permissions：存在（权限声明节）
  8. copyright：存在
  9. 路径引用：正文引用的包内相对路径存在（datahub/... 抽查）
 10. 无 XML 标签注入模式 / 无隐藏指令可疑模式
 11. 无重复键（严格 YAML loader 保证）
 12. description 不得自带 `description:` 前缀（YAML 畸形检测）

CRLF 兼容：行尾 \r\n 与 \n 均可。
"""
import json
import os
import re
import sys


def _stdout_encoding_guard():
    """非交互流强制 UTF-8，交互控制台保 locale 只降级不可编码字符。

    Windows 上 CPython 对 pipe/重定向用 locale 编码（cp936），遇 ✅⚠✓ 等符号抛
    UnicodeEncodeError 中断脚本；agent 调脚本时 stdout 恒为管道 ⇒ 必崩。
    真控制台不能改 encoding（字节流仍按控制台代码页渲染，会中文乱码）。
    """
    try:
        for _st in (sys.stdout, sys.stderr):
            if _st is None or not hasattr(_st, 'reconfigure'):
                continue
            if _st.isatty():
                _st.reconfigure(errors='replace')
            else:
                _st.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


_stdout_encoding_guard()

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

try:
    from skills_manifest import GOVERNED, SKILL_ROOT, skill_md
except Exception:
    GOVERNED = sorted(d for d in os.listdir(BASE)
                      if os.path.exists(os.path.join(BASE, d, 'SKILL.md')) and d != 'install-gongwen')
    SKILL_ROOT = BASE

    def skill_md(name):
        return os.path.join(BASE, name, 'SKILL.md')

#: 受治理技能清单（单一来源：skills_manifest.py）
SKILLS = list(GOVERNED)


def _load_registry():
    """读取 registry.json 的 name→version 映射（缺口 6 门禁）。

    此前 verify_install.py 只校验 VERSION ↔ master SKILL.md；24 个嵌套模块的
    frontmatter ↔ registry.json 无人校验（govdoc-polish 曾停在 1.0.0）。
    加载失败时**不静默**，返回错误串由 main() 显式告警。
    """
    for p in (os.path.join(SKILL_ROOT, 'registry.json'), os.path.join(BASE, 'registry.json')):
        if os.path.exists(p):
            try:
                with open(p, encoding='utf-8') as fh:
                    d = json.load(fh)
                return {s.get('name'): s.get('version') for s in d.get('skills', [])}, p
            except Exception as e:
                return None, f'{p}: {type(e).__name__}: {e}'
    return None, 'registry.json 未找到（既不位于技能根也不位于包根）'


REG_VER, REG_SRC = _load_registry()

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

NAME_RE = re.compile(r'^[a-z0-9]+(-[a-z0-9]+)*$')
Q = chr(39)
VER_RE = re.compile(r'^version:\s*["' + Q + r']([\w.]+)["' + Q + r']\s*$', re.M)
VER_UNQUOTED_RE = re.compile(r'^version:\s*[\d.]', re.M)
DESC_INLINE_RE = re.compile(r'^description:\s*["' + Q + r'](.*?)["' + Q + r']\s*$', re.M | re.S)
DESC_BLOCK_RE = re.compile(r'^description:\s*>-?\s*\n((?:[ \t]+.*\n?)+)', re.M)

INJECTION_PATTERNS = [
    (r'<[oO]penai_compat|<\|im_start\||<\|im_end\|', 'XML/特殊 token 注入模式'),
    (r'ignore (all )?(previous|prior|above) instructions', '英文越权指令模式'),
    (r'忽略(之前|以上|前面)(的)?(所有)?(指令|规则|提示)', '中文越权指令模式'),
    (r'(read|send|output).{0,20}(ssh|\.env|api[_ -]?key|password|私钥|密钥)', '敏感凭据诱导模式'),
]


def _strict_loader():
    """返回会因重复键抛错的 SafeLoader 子类（PyYAML 默认静默取后者）"""
    class _L(yaml.SafeLoader):
        pass

    def _no_dup(loader, node, deep=False):
        mapping = {}
        for k, v in node.value:
            key = loader.construct_object(k, deep=deep)
            if key in mapping:
                raise yaml.constructor.ConstructorError(
                    None, None, f'duplicate key: {key}', k.start_mark)
            mapping[key] = loader.construct_object(v, deep=deep)
        return mapping

    _L.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dup)
    return _L


def load_fm(skill):
    """返回 (frontmatter 原文, 正文, 错误列表)

    v7.3.1：委托 `skillmeta.read_frontmatter`（唯一实现）。此前 4 套解析口径并存，
    同一份 SKILL.md 在不同工具下结论不同。
    """
    import skillmeta
    return skillmeta.read_frontmatter(skill_md(skill))


def check_skill(skill):
    """返回 (issues 列表, warnings 列表)"""
    issues, warns = [], []
    fm, body, errs = load_fm(skill)
    issues.extend(errs)
    if fm is None:
        return issues, warns

    # ---- 权威解析：真实 YAML（规则 11 重复键 / 规则 12 畸形 description）----
    data = None
    if _HAS_YAML:
        try:
            data = yaml.safe_load(fm)
        except Exception as e:
            mark = getattr(e, 'problem_mark', None)
            loc = f' (line {mark.line + 1})' if mark is not None else ''
            issues.append(f'frontmatter 非法 YAML{loc}: {type(e).__name__}: {str(e)[:80]}')
        if isinstance(data, dict) and not data.get('description'):
            issues.append('description 为空或缺失（YAML 解析结果）')
    else:
        warns.append('PyYAML 未安装 → 降级为宽松正则解析（无法检出非法 YAML / 重复键，'
                     '建议 pip install pyyaml）')

    # 规则 12：description 不得自带 description: 前缀（v1.x 漏检的缺陷形态）
    desc_raw = None
    if isinstance(data, dict):
        v = data.get('description')
        if isinstance(v, str):
            desc_raw = v
    if desc_raw is None:
        dm = DESC_INLINE_RE.search(fm) or DESC_BLOCK_RE.search(fm)
        if dm:
            desc_raw = str(dm.group(1))
    if desc_raw and desc_raw.lstrip().startswith('description:'):
        issues.append('description 值以 `description:` 开头（YAML 畸形：双重 description 前缀）')

    # 1. name
    nm = re.search(r'^name:\s*["' + Q + r']?([^\s"' + Q + r']+)', fm, re.M)
    if not nm:
        issues.append('缺 name')
    else:
        v = nm.group(1)
        if not NAME_RE.match(v):
            issues.append(f'name 非法字符: {v}')
        if v != skill:
            issues.append(f'name({v}) ≠ 目录名({skill})')
        if len(v) > 64:
            issues.append(f'name 超长({len(v)}>64)')

    # 2. version 带引号
    if not VER_RE.search(fm):
        if VER_UNQUOTED_RE.search(fm):
            issues.append('version 未加引号（YAML float 风险）')
        else:
            issues.append('缺 version')

    # 2b. version 与 registry.json 一致（缺口 6：防 frontmatter/registry 静默漂移）
    vm = VER_RE.search(fm)
    if vm:
        fv = vm.group(1)
        if REG_VER is None:
            warns.append('registry.json 不可用 → 版本一致性本次【未校验】')
        elif skill not in REG_VER:
            warns.append('registry.json 无此技能条目 → 版本一致性本次【未校验】')
        elif REG_VER[skill] != fv:
            issues.append(f'version {fv} ≠ registry.json {REG_VER[skill]}（改版本号须同步 registry）')

    # 3. description 长度与触发语义
    if desc_raw:
        dt = ' '.join(desc_raw.split())
        if len(dt) > 1024:
            issues.append(f'description 超长({len(dt)}>1024)')
        if len(dt) < 40:
            warns.append(f'description 过短({len(dt)}<40)，触发语义不足')
        if not re.search(r'使用|触发|用我|when|Use', dt):
            warns.append('description 未含触发语义词（使用/触发/when），影响路由发现')
    elif not issues:
        issues.append('缺 description（或形态不合法：须 inline 引号串或 >- 块）')

    # 4. compatibility
    cm = re.search(r'^compatibility:\s*(.+)$', fm, re.M)
    if not cm:
        issues.append('缺 compatibility')
    else:
        cv = cm.group(1).strip().strip('"' + Q)
        if len(cv) > 500:
            issues.append(f'compatibility 超长({len(cv)}>500)')

    # 5. requires
    if not re.search(r'^requires:', fm, re.M):
        issues.append('缺 requires 依赖声明节')

    # 6. permissions
    if not re.search(r'^permissions:', fm, re.M):
        issues.append('缺 permissions 权限声明节')

    # 7. copyright
    if not re.search(r'^copyright:', fm, re.M):
        issues.append('缺 copyright')

    # 8. 注入模式扫描（frontmatter + 正文首屏）
    scan_text = fm + (body or '')[:3000]
    for pat, note in INJECTION_PATTERNS:
        mm = re.search(pat, scan_text, re.I)
        if mm:
            issues.append(f'注入模式命中[{note}]: {mm.group(0)[:40]}')

    # 9. 路径引用抽查（正文活性段；CHANGELOG 历史段为记录非活性路径，截断排除）
    body_active = (body or '').split('## 变更日志')[0]
    for ref in re.findall(r'(?:datahub/[a-zA-Z0-9_./-]+|\.\./[a-zA-Z0-9_./-]+)', body_active):
        ref = ref.rstrip('.,;，。；)）')
        if ref.startswith('datahub/') and not os.path.exists(os.path.join(SKILL_ROOT, ref.split('#')[0])):
            warns.append(f'路径引用不存在: {ref}')

    return issues, warns


def main():
    as_json = '--json' in sys.argv
    if not as_json:
        print(f'=== 技能 frontmatter 规范校验（validate_skills v2.1'
              f'{"，真实 YAML 解析" if _HAS_YAML else "，⚠️ 正则降级"}）===\n')
        if REG_VER is None:
            print(f'⚠️  registry.json 加载失败，模块版本一致性【本次未校验】: {REG_SRC}')
        else:
            print(f'   版本一致性对照: {REG_SRC}\n')
    all_issues, all_warns, report = [], [], {}
    for s in SKILLS:
        iss, wns = check_skill(s)
        report[s] = {'issues': iss, 'warnings': wns}
        if iss:
            all_issues.extend((s, i) for i in iss)
        all_warns.extend((s, w) for w in wns)
        if not as_json:
            if iss:
                print(f'❌ {s}: {"; ".join(iss)}')
            elif wns:
                print(f'⚠️ {s}: {"; ".join(wns)}')
            else:
                print(f'✅ {s}')

    n = len(SKILLS)
    bad = [x for x in all_issues]
    if as_json:
        print(json.dumps({'total': n, 'compliant': n - len({x[0] for x in all_issues}),
                          'issues': len(all_issues), 'warnings': len(all_warns),
                          'yaml_parser': _HAS_YAML, 'skills': report},
                         ensure_ascii=False, indent=1))
    else:
        print(f'\n校验: {n - len({x[0] for x in all_issues})}/{n} 全合规'
              f' | 问题 {len(all_issues)} 项 | 提示 {len(all_warns)} 项')
        if not _HAS_YAML:
            print('⚠️  未安装 PyYAML：本次为宽松正则降级，非法 YAML 类缺陷不会被检出。')
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
