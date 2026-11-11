# -*- coding: utf-8 -*-
"""技能元数据单一解析器（v7.3.1）

背景
----
SKILL.md 的 frontmatter / version 解析此前有 **4 套独立实现**，且行为可观察地不一致：

  · `validate_skills.py`  真实 YAML + 严格 loader（会因非法 YAML / 重复键报错）
  · `verify_install.py`   宽松正则（对畸形 frontmatter 不敏感）
  · `upgrade_check.py`    带引号正则（曾因不支持无引号 version 而把版本矩阵显示成全 `?`）
  · `release.py`          yaml.safe_load（无重复键防护）

同一份 SKILL.md 在不同工具下会得出不同结论——这类"口径不一"正是本包反复出问题的形态。
本模块提供**唯一实现**，供上述消费方复用。

对外接口
--------
  read_frontmatter(path) -> (fm_text, body, errs)   CRLF 安全；正文取 m.end(0)
  parse(path)            -> (dict, errs)            严格 YAML（含重复键检测）
  get(path, key, default=None)                       取单字段
  version(path)          -> str | None               带引号/不带引号通吃

设计约束
--------
  · 行尾：本包 SKILL.md 混用 CRLF 与 LF，解析一律先归一
  · 正文边界：必须用 `m.end(0)`（整个匹配之后）。误用 `m.end(1)/end(2)` 会把结束界符
    `---` 混入正文或吞掉正文（v6.9.0 曾踩坑，见交接文档 §6.2）
  · PyYAML 缺失时降级为宽松正则，并**显式告知**调用方（errs/warnings 返回），不静默
"""
import os
import re

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

#: frontmatter 三组：g1 开头界符 / g2 内容 / g3 结束界符
_FM_RE = re.compile(r'^(---\r?\n)(.*?)(\r?\n---\r?\n)', re.S)

_VER_RE = re.compile(r'^version:\s*["\']?([\w.]+)["\']?\s*$', re.M)


class _StrictLoader(yaml.SafeLoader if _HAS_YAML else object):
    """重复键直接报错的 SafeLoader（PyYAML 默认静默取后者，掩盖配置错误）"""


if _HAS_YAML:
    def _no_dup(loader, node, deep=False):
        mapping = {}
        for k, v in node.value:
            key = loader.construct_object(k, deep=deep)
            if key in mapping:
                raise yaml.constructor.ConstructorError(
                    None, None, f'duplicate key: {key}', k.start_mark)
            mapping[key] = loader.construct_object(v, deep=deep)
        return mapping

    _StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dup)


def read_frontmatter(path):
    """返回 (frontmatter 原文, 正文, 错误列表)。文件不存在或界符缺失时 fm 为 None。"""
    if not os.path.exists(path):
        return None, None, ['文件不存在']
    try:
        src = open(path, encoding='utf-8').read()
    except Exception as e:
        return None, None, [f'读取失败: {type(e).__name__}: {e}']
    m = _FM_RE.match(src)
    if not m:
        return None, src, ['frontmatter 缺失（未找到 --- 界符）']
    return m.group(2), src[m.end(0):], []


def parse(path):
    """返回 (frontmatter dict, 错误列表)。严格 YAML；缺 PyYAML 时降级并给出告警。"""
    fm, _body, errs = read_frontmatter(path)
    if fm is None:
        return {}, errs
    if not _HAS_YAML:
        d = {}
        for k, v in re.findall(r'^([A-Za-z_][\w-]*):\s*(.*)$', fm, re.M):
            d.setdefault(k, v.strip().strip('"\''))
        return d, errs + ['PyYAML 未安装 → 降级宽松正则解析（无法检出非法 YAML/重复键）']
    # 重复键检测：改由 frontmatter 文本层预检（避免 yaml.load + 动态 Loader 触发
    # 不安全反序列化静态告警；顶层键即在列首的键，嵌套键有缩进不参与）
    _seen, _dup = set(), []
    for _k in re.findall(r'^([A-Za-z_][\w-]*):', fm, re.M):
        if _k in _seen:
            _dup.append(_k)
        _seen.add(_k)
    if _dup:
        return {}, errs + [f'非法 YAML: duplicate key: {_dup[0]}']
    try:
        data = yaml.safe_load(fm)
    except Exception as e:
        mark = getattr(e, 'problem_mark', None)
        loc = f' (line {mark.line + 1})' if mark is not None else ''
        return {}, errs + [f'非法 YAML{loc}: {type(e).__name__}: {str(e)[:90]}']
    if not isinstance(data, dict):
        return {}, errs + ['frontmatter 不是映射（YAML 顶层非 dict）']
    return data, errs


def get(path, key, default=None):
    data, _errs = parse(path)
    return data.get(key, default)


def version(path):
    """取 version 字段：兼容带引号 / 不带引号（upgrade_check 曾因只认引号而全显 `?`）"""
    v = get(path, 'version')
    if v is not None:
        return str(v)
    fm, _b, _e = read_frontmatter(path)
    if fm:
        m = _VER_RE.search(fm)
        if m:
            return m.group(1)
    return None


if __name__ == '__main__':
    import sys
    base = os.path.dirname(os.path.abspath(__file__))
    bad = 0
    for d in sorted(os.listdir(base)):
        p = os.path.join(base, d, 'SKILL.md')
        if not os.path.isfile(p):
            continue
        data, errs = parse(p)
        mark = 'OK ' if not errs else 'ERR'
        print(f'  {mark} {d:24s} version={version(p)}  keys={len(data)}'
              + (f'  {errs}' if errs else ''))
        bad += bool(errs)
    print(f'\n（PyYAML {"可用" if _HAS_YAML else "缺失"}）异常 {bad} 个')
    sys.exit(1 if bad else 0)
