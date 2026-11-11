# -*- coding: utf-8 -*-
"""技能清单单一来源（v7.3.0 · 消除清单漂移）

背景
----
技能清单曾在 4 处独立硬编码：`validate_skills.py`、`verify_install.py`、
`upgrade_check.py`、`install-gongwen/scripts/install.py`。历次改名/新增
（41→23 合并、biganzi→govdoc-styles、新增 govdoc-workflow）都出现
"改一处漏三处"：升级静默跳过文风族、安装漏拷目录、校验器漏检。

本模块把清单收敛为唯一事实源，并提供 `audit()` 主动比对清单与磁盘实际目录，
让漂移**被检出**而不是被忽略。

用法
----
  >>> from skills_manifest import GOVERNED, INSTALLER, discover, audit
  >>> missing, unexpected = audit()      # 均为空才算清单与目录一致
"""
import os

BASE = os.path.dirname(os.path.abspath(__file__))


def _detect_skill_root():
    """布局解析（v8.0.0 单技能化 · 双态）：
    部署态（工具随技能包内置于 gongwen-master/ 内）→ 技能根 = 本目录；
    开发态（工具在包根，技能目录为其子目录）→ 技能根 = 包根/gongwen-master；
    v7 兼容（多技能平铺包根，无 gongwen-master/VERSION）→ 技能根 = 包根。
    部署态判据须同时有自身 SKILL.md 与嵌套模块目录（包根的 v7 遗留 references/
    设计文档目录不足以证明部署态）。"""
    if os.path.isfile(os.path.join(BASE, 'SKILL.md')) and \
            os.path.isdir(os.path.join(BASE, 'references', 'govdoc-notice')):
        return BASE
    cand = os.path.join(BASE, 'gongwen-master')
    if os.path.isfile(os.path.join(cand, 'VERSION')):
        return cand
    return BASE


SKILL_ROOT = _detect_skill_root()
#: v8 嵌套布局：24 模块位于 SKILL_ROOT/references/{名}/SKILL.md
LAYOUT_V8 = os.path.isdir(os.path.join(SKILL_ROOT, 'references', 'govdoc-notice'))

#: 受治理技能（24 个）—— 变更技能目录时必须同步本清单
GOVERNED = [
    # 路由中枢
    'gongwen-master',
    # 文种写作（16）
    'govdoc-circular', 'govdoc-duty', 'govdoc-experience', 'govdoc-letter',
    'govdoc-minutes', 'govdoc-news', 'govdoc-notice', 'govdoc-plan',
    'govdoc-reflection', 'govdoc-regulation', 'govdoc-report', 'govdoc-request',
    'govdoc-research', 'govdoc-speech', 'govdoc-summary', 'govdoc-theory',
    # 动作类（2）
    'govdoc-polish', 'govdoc-layout',
    'govdoc-material', 'govdoc-corpus',   # v7.6.0 C3a/C3b
    # 风格族（2）
    'govdoc-styles', 'shuji',
    # 流程 / 评审 / 数据族（3）
    'govdoc-workflow', 'article-review', 'qiushi-db',
]

#: 安装器（v8 起退役为嵌套参考文档，不再作为顶层技能注册）
INSTALLER = 'install-gongwen'

#: master 自带的嵌套参考技能（v7 起即为嵌套，非受治理顶层；v8 下位于 references/ 同层）
MASTER_NESTED = ('govdoc-feedback', 'govdoc-onboarding', 'govdoc-style-learn')

#: 兼容字段：v7 顶层目录总数；v8 下顶层仅 gongwen-master 1 个
TOP_LEVEL_TOTAL = len(GOVERNED) + 1


def skill_dir(name):
    """技能/模块目录绝对路径（v7 平铺 与 v8 嵌套 双布局统一入口）
    v8 下 master 即技能根本身；v7 下是包根的同名子目录"""
    if LAYOUT_V8:
        return SKILL_ROOT if name == 'gongwen-master' else os.path.join(SKILL_ROOT, 'references', name)
    return os.path.join(SKILL_ROOT, name)


def skill_md(name):
    """技能 SKILL.md 绝对路径"""
    return os.path.join(skill_dir(name), 'SKILL.md')


def nested_modules():
    """v8：references/ 下含 SKILL.md 的模块目录名（排序；v7 返回空）"""
    refs = os.path.join(SKILL_ROOT, 'references')
    if not os.path.isdir(refs):
        return []
    return sorted(d for d in os.listdir(refs)
                  if os.path.isfile(os.path.join(refs, d, 'SKILL.md')))


def discover():
    """扫描实际技能目录（排序）。v7=包根顶层目录；v8=[gongwen-master] + references/ 嵌套模块"""
    if not LAYOUT_V8:
        out = []
        for name in sorted(os.listdir(SKILL_ROOT)):
            p = os.path.join(SKILL_ROOT, name)
            if os.path.isdir(p) and os.path.exists(os.path.join(p, 'SKILL.md')):
                out.append(name)
        return out
    return ['gongwen-master'] + [d for d in nested_modules() if d != 'gongwen-master']


def audit():
    """比对清单与磁盘实际目录。

    返回 (missing, unexpected)：
      missing    —— 清单里有、磁盘上没有（安装残缺 / 改名未同步）
      unexpected —— 磁盘上有、清单里没有（新增未登记 / 残留目录）
    """
    actual = set(discover())
    expected = set(GOVERNED) | {INSTALLER} | set(MASTER_NESTED)
    return sorted(expected - actual), sorted(actual - expected)


if __name__ == '__main__':
    missing, unexpected = audit()
    mode = 'v8 单技能（1 顶层 + references/ 嵌套模块）' if LAYOUT_V8 else 'v7 多技能平铺'
    print(f'布局      : {mode}')
    print(f'技能根    : {SKILL_ROOT}')
    print(f'受治理技能: {len(GOVERNED)} ｜ 安装器: {INSTALLER}')
    print(f'磁盘实际  : {len(discover())}（顶层 1 + references/ 一级嵌套 {len(nested_modules()) if LAYOUT_V8 else 0}）')
    print(f'缺失      : {missing or "无"}')
    print(f'未登记    : {unexpected or "无"}')
