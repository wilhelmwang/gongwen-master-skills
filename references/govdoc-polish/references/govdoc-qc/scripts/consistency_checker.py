#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
一致性检查系统（公文单文档版）
基于跨材料一致性判据，收窄到「单份公文内可机检」的四类：
  占位符残留 / 简称先定义后使用 / 同一指标数值自相矛盾 / 写法不一致

判据出处与取舍理由见：
  002成果资产/21_技能治理库_SkillGovernance_v1.0.0/_方法论_跨材料一致性判据_v1.0.0.md
（判据 2/8 已落本脚本；判据 1/3/4/6/7/10 需受控术语表与指标登记表，本机未立，故不做。
  判据 5 的"超容差"阈值在本脚本体现为 3 倍量级闸门。）

纪律：本模块只定位、只建议，**绝不自动改写**；报出的是疑点清单，不是错误清单。
宁可漏报不可误报——误报会让人不再看报告，等于检查不存在。
"""

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
from collections import defaultdict
from pathlib import Path

# ============================================================
# 通用工具
# ============================================================

# 围栏代码块 ```…```：先剥离再扫，避免代码里的词被当正文（上游 scope-aware 机制）
FENCE_RE = re.compile(r"```.*?```", re.S)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")


def strip_code(text):
    """剥掉代码块与行内代码，返回等长同构的文本（行号保持一致）。"""
    def blank(m):
        return "\n" * m.group(0).count("\n") + " " * (len(m.group(0)) - m.group(0).count("\n"))
    return INLINE_CODE_RE.sub(blank, FENCE_RE.sub(blank, text))


def norm_key(token):
    """归一化比较键：全角转半角、去大小写、去分隔符。"""
    s = token.strip()
    s = "".join(chr(ord(c) - 0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E else c for c in s)
    return s.lower().replace("-", "").replace("_", "").replace(" ", "")


_TOK_ASCII = re.compile(r"[A-Za-z][A-Za-z0-9._-]{1,30}")
_TOK_CJK = re.compile(r"[\u4e00-\u9fff]{2,12}")


def is_term_candidate(tok):
    """术语候选：拉丁词（≥2 字符）或中文词（≥2 字），排除纯数字与纯标点。"""
    if not tok or tok.isdigit():
        return False
    core = tok.strip("._- ")
    return len(core) >= 2


# ============================================================
# 第 1 类：占位符残留
# ============================================================

# 只留**无歧义**的写法。`<name>` / `<dir>` 这类尖括号占位在技术文档里是正当写法，
# 实测误报率过高，故整体剔除（详见方法论 §五）。
PLACEHOLDER_PATTERNS = [
    (re.compile(r"\{\{[^}]{0,80}\}\}"), "模板未渲染 {{…}}", "P1"),
    (re.compile(r"【[^】]{0,20}(?:待填|待补|待定|填写|补充)[^】]{0,20}】"), "未填写的提示位", "P1"),
    (re.compile(r"[Xx]{2,}(?=[市省县区镇乡村局委办处科股室组])"), "占位符 XX（未替换为实际名称）", "P1"),
    (re.compile(r"replace[-_ ]?with", re.I), "未替换 replace-with", "P1"),
    (re.compile(r"\bTODO\b", re.I), "待补 TODO", "P2"),
    (re.compile(r"\bTBD\b", re.I), "待补 TBD", "P2"),
]


def check_placeholder(text):
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        for pat, label, sev in PLACEHOLDER_PATTERNS:
            if pat.search(line):
                out.append({
                    "kind": "PLACEHOLDER",
                    "severity": sev,
                    "line": i,
                    "word": label,
                    "detail": line.strip()[:90],
                    "suggestion": "占位符出现即视为未完成，补齐后再交付",
                })
                break
    return out


# ============================================================
# 第 2 类：简称先定义后使用（判据 8 ABBREV_FIRST_USE）
# ============================================================

# 公文里"首次全称（缩写）"的常见定义写法
ABBREV_DEF_RE = re.compile(
    r"(?:以下|下)(?:简称|称|缩写为)\s*[「“\"']?([\u4e00-\u9fffA-Za-z0-9]{2,20})[」”\"']?"
)


def check_abbrev(text):
    out = []
    for m in ABBREV_DEF_RE.finditer(text):
        abbr = m.group(1).strip()
        if not abbr:
            continue
        pos = m.start()
        line = text[:pos].count("\n") + 1
        before = text[:pos]
        after = text[m.end():]

        # 违反 1：定义之前就已使用该简称
        if abbr in before:
            first = before.index(abbr)
            out.append({
                "kind": "ABBREV_FIRST_USE",
                "severity": "P1",
                "line": before[:first].count("\n") + 1,
                "word": abbr,
                "detail": "「%s」在第 %d 行已出现，直到第 %d 行才定义" % (abbr, before[:first].count("\n") + 1, line),
                "suggestion": "首次出现处改为全称并就地定义，或删除后置的这处定义",
            })
        # 违反 2：定义了但全文再未使用（多此一举）
        elif abbr not in after:
            out.append({
                "kind": "ABBREV_FIRST_USE",
                "severity": "P2",
                "line": line,
                "word": abbr,
                "detail": "定义「%s」后全文再未使用" % abbr,
                "suggestion": "删掉这处简称定义，或改用简称保持一致",
            })
    return out


# ============================================================
# 第 3 类：同一指标数值自相矛盾（判据 4/5，无登记表版）
# ============================================================

UNIT_ALT = r"(?:%|％|万|亿|元|美元|人|户|个|项|件|条|篇|次|倍|吨|亩|平方米|公里|km|kg)"
NUM_UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(" + UNIT_ALT + r")")
# 数值前紧邻这些词 → 不是指标（年份、编号、序号、条款）
NOT_A_METRIC_BEFORE = re.compile(r"(?:年|月|日|第|条款|版本?|v|V|编号|序号|〔|\[)\s*$")


def adjacent_term(head):
    """取紧邻数值之前的术语。

    拉丁词取整词；中文取**定宽 4 字后缀**——定宽是关键：若按"窗口前 N 字"截，
    同一指标在不同句子里会被截成不同字符串（"本次检查覆盖企业共计" vs "覆盖企业共计"），
    结果是该报的冲突漏报。
    """
    s = head.rstrip().rstrip("：:、，,（(【[「“\"'件 ")
    if not s:
        return ""
    m = re.search(r"[A-Za-z][A-Za-z0-9._-]*$", s)
    if m:
        return m.group(0)
    m = re.search(r"[\u4e00-\u9fff]+$", s)
    if m:
        run = m.group(0)
        return run if len(run) <= 4 else run[-4:]
    return ""


def check_numeric(text):
    # 术语 → 单位 → 数值 → 行号集合
    table = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    for i, line in enumerate(text.splitlines(), 1):
        for m in NUM_UNIT_RE.finditer(line):
            num, unit = m.group(1), m.group(2)
            before6 = line[max(0, m.start() - 6):m.start()]
            if NOT_A_METRIC_BEFORE.search(before6):
                continue
            term = adjacent_term(line[:m.start()])
            if not is_term_candidate(term):
                continue
            table[norm_key(term)][unit][num].add(i)

    out = []
    for key, by_unit in sorted(table.items()):
        for unit, by_num in sorted(by_unit.items()):
            if len(by_num) < 2:
                continue
            nums = sorted(float(n) for n in by_num)
            lo, hi = nums[0], nums[-1]
            # 差一个量级的多半不是同一个指标，不报
            if lo <= 0 or hi / lo > 3.0:
                continue
            where = "；".join("%s%s（第 %s 行）" % (n, unit, "/".join(map(str, sorted(by_num[n]))))
                             for n in sorted(by_num, key=float))
            out.append({
                "kind": "NUMERIC_CONFLICT",
                "severity": "P0",
                "line": min(min(v) for v in by_num.values()),
                "word": "%s（%s）" % (key, unit),
                "detail": "同一指标在本文内取值不一：" + where,
                "suggestion": "核对哪个是对的；若口径不同（不同期间/不同范围），在文中写明口径",
            })
    return out


# ============================================================
# 第 4 类：写法不一致（判据 2 VARIANT_CONFLICT + 公文写法规则）
# ============================================================

YEAR_SHORT_RE = re.compile(r"(?<![\d])([0-9]{2})年(?![\d])")
CN_NUM_DATE_RE = re.compile(r"[〇○零一二三四五六七八九十]{2,}年")


def check_variant(text):
    out = []
    lines = text.splitlines()

    # 4a. 同一术语的写法变体：去掉分隔符后相同、分隔符形态不同
    positions = defaultdict(lambda: defaultdict(list))
    for i, line in enumerate(lines, 1):
        for tok in _TOK_ASCII.findall(line) + _TOK_CJK.findall(line):
            core = tok.strip("._- ")
            if len(core) < 2:
                continue
            positions[norm_key(core)][core].append(i)
    for key, variants in sorted(positions.items()):
        if len(variants) < 2:
            continue

        def _sep_sig(s):
            return "".join(ch for ch in s if ch in "-_ ")

        def _strip_all(s):
            return re.sub(r"[-_\s]", "", s)

        forms = sorted(variants)
        sep_differs = any(
            _sep_sig(a) != _sep_sig(b) and _strip_all(a).lower() == _strip_all(b).lower()
            for i2, a in enumerate(forms) for b in forms[i2 + 1:]
        )
        if not sep_differs:
            continue  # 纯大小写差异一律不报——实测噪声淹没信号
        out.append({
            "kind": "VARIANT_CONFLICT",
            "severity": "P2",
            "line": min(min(v) for v in variants.values()),
            "word": " / ".join(forms),
            "detail": "同一术语在本文内有 %d 种写法" % len(forms),
            "suggestion": "选定一种为规范写法，其余改为它",
        })

    # 4b. 年份简写（公文中年份不应简写）
    for i, line in enumerate(lines, 1):
        m = YEAR_SHORT_RE.search(line)
        if m:
            out.append({
                "kind": "YEAR_ABBREV",
                "severity": "P1",
                "line": i,
                "word": m.group(0),
                "detail": "年份简写「%s」" % m.group(0),
                "suggestion": "补全为四位年份（如 2025年），公文中年份不简写",
            })

    # 4c. 成文日期汉字/阿拉伯数字混用
    cn = CN_NUM_DATE_RE.search(text)
    ar = re.search(r"(?<![\d])[12][0-9]{3}年", text)
    if cn and ar:
        out.append({
            "kind": "DATE_STYLE_MIXED",
            "severity": "P2",
            "line": text[:cn.start()].count("\n") + 1,
            "word": cn.group(0) + " / " + ar.group(0),
            "detail": "汉字年份与阿拉伯年份混用",
            "suggestion": "统一一种；成文日期按 GB/T 9704 用阿拉伯数字",
        })
    return out


# ============================================================
# 汇总
# ============================================================

CHECKS = [
    ("placeholder", check_placeholder, "占位符残留"),
    ("abbrev", check_abbrev, "简称先定义后使用"),
    ("numeric", check_numeric, "数值自相矛盾"),
    ("variant", check_variant, "写法不一致"),
]


def check_consistency(text):
    """公文单文档一致性检查。

    返回 {found, count, matches, by_kind, by_severity}
    matches 每条含 kind / severity / line / word / detail / suggestion
    """
    if not text or not text.strip():
        # 空输入不算"检查通过"——显式报未覆盖，不冒充已一致
        return {
            "found": False, "count": 0, "matches": [],
            "by_kind": {}, "by_severity": {},
            "coverage": "未覆盖（输入为空）",
        }

    cleaned = strip_code(text)
    matches = []
    by_kind = {}
    for key, fn, label in CHECKS:
        found = fn(cleaned)
        if found:
            by_kind[label] = len(found)
        matches += found

    by_severity = defaultdict(int)
    for m in matches:
        by_severity[m["severity"]] += 1
    matches.sort(key=lambda m: (m["severity"], m["line"]))

    return {
        "found": bool(matches),
        "count": len(matches),
        "matches": matches,
        "by_kind": by_kind,
        "by_severity": dict(by_severity),
        "coverage": "全文（已剥代码块；需受控术语表的判据未启用，见方法论 §四）",
    }


# ============================================================
# 自测
# ============================================================

def _selftest():
    fails = []

    # 干净样例：不该报
    good = (
        "关于X市市场监督管理局开展2025年度检查工作的通知\n"
        "各有关单位：\n"
        "为落实工作要求，现将有关事项通知如下。\n"
        "一、检查范围为全市市场主体，共计1200户。\n"
        "X市市场监督管理局（以下简称市监局）负责牵头。\n"
        "二、市监局应于2025年12月31日前完成。\n"
    )
    r = check_consistency(good)
    if r["count"] != 0:
        fails.append("干净样例误报 %d 条：%s" % (r["count"], [m["word"] for m in r["matches"]]))

    # 占位符
    r = check_consistency("关于XX市开展工作的通知\n待办事项：{{事项}}\n")
    if not any(m["kind"] == "PLACEHOLDER" for m in r["matches"]):
        fails.append("应检出占位符")

    # 简称先使用后定义
    r = check_consistency("市监局负责此项工作。X市市场监督管理局（以下简称市监局）另行发文。\n")
    if not any(m["kind"] == "ABBREV_FIRST_USE" and "已出现" in m["detail"] for m in r["matches"]):
        fails.append("应检出简称先使用后定义")
    # 简称定义后未使用
    r = check_consistency("X市市场监督管理局（以下简称市监局）负责此项工作，各处室配合。\n")
    if not any(m["kind"] == "ABBREV_FIRST_USE" and "再未使用" in m["detail"] for m in r["matches"]):
        fails.append("应检出简称定义后未使用")

    # 数值自相矛盾
    r = check_consistency("本次检查覆盖企业共计1200户。\n经复核，覆盖企业共计1500户。\n")
    if not any(m["kind"] == "NUMERIC_CONFLICT" for m in r["matches"]):
        fails.append("应检出数值冲突")

    # 边界：补零写法是同一个数，不报
    r = check_consistency("完成率53.20%。\n复核完成率53.2%。\n")
    if any(m["kind"] == "NUMERIC_CONFLICT" for m in r["matches"]):
        fails.append("补零写法被误判为数值冲突")

    # 边界：年份不算指标；年份简写单独报 YEAR_ABBREV
    r = check_consistency("2024年开展工作。\n2025年完成工作。\n")
    if any(m["kind"] == "NUMERIC_CONFLICT" for m in r["matches"]):
        fails.append("年份被误判为数值冲突")

    # 边界：纯大小写差异不报
    r = check_consistency("执行 GB/T9704 标准。\n另见 GB/T 9704 附录。\n")
    if any(m["kind"] == "VARIANT_CONFLICT" for m in r["matches"]):
        fails.append("纯大小写差异被误报为写法不一致")

    # 边界：代码块内的内容不算正文
    r = check_consistency("正文说明如下。\n```\nfoo_bar = 1  # TODO 未替换\n```\n")
    if r["count"] != 0:
        fails.append("代码块内内容被当正文：%s" % [m["kind"] for m in r["matches"]])

    # 边界：空输入不冒充"已一致"
    r = check_consistency("")
    if r["count"] != 0 or "未覆盖" not in r["coverage"]:
        fails.append("空输入未显式报未覆盖")

    if fails:
        print("consistency_checker selftest: 失败 %d 项" % len(fails))
        for f in fails:
            print("  × " + f)
        return 1
    print("consistency_checker selftest: 全绿")
    print("  9 组断言通过（干净样例零疑点 / 占位符 / 简称双向 / 数值冲突 / 补零不算冲突 /"
          " 年份不误判 / 大小写不误报 / 代码块跳过 / 空输入不冒充一致）")
    return 0


def _format_text(result):
    if not result["found"]:
        return "一致性检查：无疑点（%s）" % result["coverage"]
    lines = ["一致性检查：%d 处疑点  %s" % (
        result["count"],
        " ".join("%s=%d" % kv for kv in sorted(result["by_severity"].items())))]
    for m in result["matches"]:
        lines.append("[%s/%s] 第%d行 %s —— %s" % (
            m["severity"], m["kind"], m["line"], m["word"], m["detail"]))
        lines.append("    → " + m["suggestion"])
    lines.append("本清单是**疑点**不是判定，人工过一遍即可。")
    return "\n".join(lines)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("用法: python consistency_checker.py <草稿.txt>")
        print("      python consistency_checker.py --selftest")
        print("      echo '公文内容' | python consistency_checker.py -")
        sys.exit(1)
    if args[0] == "-":
        src = sys.stdin.read()
    else:
        src = Path(args[0]).read_text(encoding="utf-8", errors="replace")
    res = check_consistency(src)
    if "--json" in sys.argv:
        import json
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(_format_text(res))
