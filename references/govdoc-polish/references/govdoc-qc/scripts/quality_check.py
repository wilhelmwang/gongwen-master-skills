#!/usr/bin/env python3
"""公文质检 API（v2.0 新增）

统一质检接口，5 维度评分：格式/内容/语言/逻辑/政治安全。
    + 一致性维度（2026-09-14 新增）：同级 consistency_checker.py，见文件末尾说明。
可被其他 skill（如 govdoc-workflow）调用。

用法：
    python quality_check.py input.txt --type 通知
    echo "公文内容" | python quality_check.py - --type 总结

输出：JSON 格式的质检报告
"""

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
import json
import re
from collections import Counter

# 一致性检查（判据出处见 21_技能治理库/_方法论_跨材料一致性判据_v1.0.0.md）。
# 刻意做成**可选导入**：若运行时未同步该模块则退化为"未启用"，
# 绝不因缺件而崩溃，也绝不把缺件当成"检查通过"。
try:
    from consistency_checker import check_consistency
except ImportError:
    check_consistency = None


# ============================================================
# 1. 格式检查（GB/T 9704）
# ============================================================

def check_format(text):
    """检查公文格式合规性"""
    issues = []
    score = 100
    
    # 检查标题格式
    lines = text.strip().split('\n')
    if lines:
        first_line = lines[0].strip()
        if not any(kw in first_line for kw in ['关于', '通知', '请示', '报告', '意见', '决定', '通报', '批复', '函', '纪要']):
            issues.append("标题缺少公文文种关键词")
            score -= 10
    
    # 检查序号层级
    has_一 = bool(re.search(r'^[一二三四五六七八九十]+[、．.]', text, re.M))
    has_括号 = bool(re.search(r'^（[一二三四五六七八九十]+）', text, re.M))
    has_数字 = bool(re.search(r'^\d+[、．.]', text, re.M))
    
    if has_数字 and has_一:
        # 混用中英文序号
        issues.append("序号层级混用中英文格式")
        score -= 5
    
    # 检查段落缩进
    if re.search(r'^[^\s]', text, re.M) and len(lines) > 5:
        # 可能缺少首行缩进
        pass  # 纯文本难以判断，标记为建议
    
    # 检查标点符号
    if '。。' in text or '，，' in text:
        issues.append("存在重复标点")
        score -= 5
    
    return {"score": max(0, score), "issues": issues}


# ============================================================
# 2. 内容检查
# ============================================================

def check_content(text, doc_type=""):
    """检查公文内容质量"""
    issues = []
    score = 100
    
    # 检查是否为空
    if len(text.strip()) < 50:
        issues.append("内容过短，不足 50 字")
        score -= 30
    
    # 检查是否有具体数据
    has_data = bool(re.search(r'\d+[\.％%]|\d+年|\d+月|\d+日|\d+万|\d+亿', text))
    if not has_data and doc_type in ['总结', '报告', '调研报告']:
        issues.append("缺少具体数据支撑")
        score -= 10
    
    # 检查是否有明确的措施
    measure_keywords = ['措施', '办法', '方案', '路径', '步骤', '安排', '落实', '推进', '加强']
    has_measure = any(kw in text for kw in measure_keywords)
    if not has_measure and doc_type in ['通知', '方案', '计划']:
        issues.append("缺少具体措施或落实路径")
        score -= 15
    
    # 检查是否有明确的责任主体
    responsibility_keywords = ['负责', '牵头', '配合', '责任单位', '责任人', '落实到']
    has_responsibility = any(kw in text for kw in responsibility_keywords)
    if not has_responsibility and doc_type in ['通知', '方案', '部署']:
        issues.append("缺少责任主体或分工说明")
        score -= 10
    
    return {"score": max(0, score), "issues": issues}


# ============================================================
# 3. 语言检查
# ============================================================

def check_language(text):
    """检查公文语言规范性"""
    issues = []
    score = 100
    
    # 检查口语化表达
    colloquial_patterns = [r'我觉得', r'我认为', r'可能大概', r'差不多', r'反正', r'其实']
    for pattern in colloquial_patterns:
        if re.search(pattern, text):
            issues.append(f"存在口语化表达：{pattern}")
            score -= 5
    
    # 检查 AI 味套话
    ai_patterns = [r'值得注意的是', r'需要指出的是', r'综上所述', r'一方面.*另一方面']
    for pattern in ai_patterns:
        if re.search(pattern, text):
            issues.append(f"存在 AI 味套话：{pattern}")
            score -= 3
    
    # 检查万能动词过度使用
    action_words = ['加强', '推进', '落实', '完善', '健全', '优化', '提升', '强化']
    action_counts = Counter()
    for word in action_words:
        action_counts[word] = len(re.findall(word, text))
    
    overused = [w for w, c in action_counts.items() if c > 5]
    if overused:
        issues.append(f"万能动词过度使用：{', '.join(overused)}")
        score -= 5
    
    # 检查模糊表述
    vague_patterns = [r'若干', r'一些', r'部分', r'一定程度', r'基本']
    for pattern in vague_patterns:
        if re.search(pattern, text):
            issues.append(f"存在模糊表述：{pattern}")
            score -= 3
    
    return {"score": max(0, score), "issues": issues}


# ============================================================
# 4. 逻辑检查
# ============================================================

def check_logic(text):
    """检查公文逻辑结构"""
    issues = []
    score = 100
    
    # 检查是否有明确的结构（一、二、三...）
    has_structure = bool(re.search(r'^[一二三四五六七八九十]+[、．.]', text, re.M))
    if not has_structure and len(text) > 200:
        issues.append("缺少明确的结构层次（一、二、三...）")
        score -= 10
    
    # 检查开头和结尾
    lines = text.strip().split('\n')
    if lines:
        first_line = lines[0]
        last_line = lines[-1]
        
        # 检查结尾是否有"特此通知"等结束语
        end_keywords = ['特此', '请遵照执行', '请认真贯彻', '以上通知']
        has_end = any(kw in last_line for kw in end_keywords)
        if not has_end and len(lines) > 3:
            issues.append("缺少正式的结束语")
            score -= 5
    
    return {"score": max(0, score), "issues": issues}


# ============================================================
# 5. 政治安全检查
# ============================================================

def check_political_safety(text):
    """检查公文政治安全性"""
    issues = []
    score = 100
    
    # 检查敏感词
    sensitive_words = ['台湾', '西藏', '新疆', '香港', '澳门']
    for word in sensitive_words:
        if word in text and '中国' not in text and '我国' not in text:
            issues.append(f"涉及敏感地区 '{word}' 未标注归属")
            score -= 10
    
    # 检查政治表述准确性
    political_terms = {
        '习近平新时代中国特色社会主义思想': '必须完整准确',
        '两个维护': '必须准确表述',
        '四个意识': '必须准确表述',
        '四个自信': '必须准确表述',
    }
    
    for term, note in political_terms.items():
        if term in text:
            # 检查是否被错误使用或断章取义
            pass  # 需要更复杂的语义分析，这里只标记
    
    # 检查是否有涉密风险
    secret_patterns = [r'机密', r'绝密', r'秘密', r'内部资料', r'不得外传']
    for pattern in secret_patterns:
        if re.search(pattern, text):
            issues.append(f"涉及涉密标识：{pattern}")
            score -= 15
    
    return {"score": max(0, score), "issues": issues}


# ============================================================
# 6. 一致性检查（2026-09-14 新增·附加维度）
# ============================================================

def check_consistency_dim(text):
    """把一致性检查结果翻译成质检维度格式。

    **刻意不计入加权总分**：总分口径一改，既有全部评级都会平移，属于静默行为变更。
    本维度只做两件事——把疑点并入 issues 清单、把 P0 提为 gate 供上层当硬门槛用。
    要改为计分，把 total_score 的 weights 加上本维度即可（一行）。
    """
    if check_consistency is None:
        return {"score": None, "issues": [], "coverage": "未启用（consistency_checker.py 未同步）",
                "gate": {"consistency_p0": 0, "blocking": False, "module": False}}

    res = check_consistency(text)
    issues = []
    for m in res["matches"]:
        issues.append("[%s] 第%d行 %s —— %s" % (m["severity"], m["line"], m["word"], m["detail"]))

    sev = res.get("by_severity", {})
    p0, p1, p2 = sev.get("P0", 0), sev.get("P1", 0), sev.get("P2", 0)
    score = max(0, 100 - 15 * p0 - 8 * p1 - 3 * p2)
    return {
        "score": score,
        "issues": issues,
        "coverage": res.get("coverage", ""),
        "by_kind": res.get("by_kind", {}),
        "gate": {"consistency_p0": p0, "blocking": p0 > 0, "module": True},
    }


# ============================================================
# 综合质检
# ============================================================

def quality_check(text, doc_type=""):
    """综合质检：5 维度评分 + 1 个附加维度"""
    results = {
        "格式": check_format(text),
        "内容": check_content(text, doc_type),
        "语言": check_language(text),
        "逻辑": check_logic(text),
        "政治安全": check_political_safety(text),
    }
    consistency = check_consistency_dim(text)
    results["一致性"] = consistency

    # 计算总分（加权平均）——只对既有 5 维加权，遍历 weights 而非 results，
    # 附加维度不参与，保证既有评级口径不变
    weights = {"格式": 0.2, "内容": 0.3, "语言": 0.2, "逻辑": 0.15, "政治安全": 0.15}
    total_score = sum(results[dim]["score"] * weights[dim] for dim in weights)

    # 汇总所有问题
    all_issues = []
    for dim, result in results.items():
        for issue in result["issues"]:
            all_issues.append(f"[{dim}] {issue}")

    return {
        "total_score": round(total_score, 1),
        "dimensions": results,
        "issues": all_issues,
        "issue_count": len(all_issues),
        "consistency_coverage": consistency["coverage"],
        "gate": consistency["gate"],
        "grade": "A" if total_score >= 90 else "B" if total_score >= 80 else "C" if total_score >= 70 else "D" if total_score >= 60 else "F",
    }


# ============================================================
# CLI 入口
# ============================================================

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python quality_check.py input.txt --type 通知")
        print("      echo '公文内容' | python quality_check.py - --type 总结")
        sys.exit(1)
    
    input_file = sys.argv[1]
    doc_type = ""
    
    if '--type' in sys.argv:
        idx = sys.argv.index('--type')
        if idx + 1 < len(sys.argv):
            doc_type = sys.argv[idx + 1]
    
    if input_file == '-':
        text = sys.stdin.read()
    else:
        with open(input_file, 'r', encoding='utf-8') as f:
            text = f.read()
    
    result = quality_check(text, doc_type)
    print(json.dumps(result, ensure_ascii=False, indent=2))
