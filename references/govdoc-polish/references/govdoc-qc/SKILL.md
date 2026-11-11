---
name: govdoc-qc
tags: [govdoc, 公文, 质检]
version: 1.1.0
description: "Use when the user asks to 质检/检查/审核/校对 a Chinese official document (公文): 错别字、敏感词、格式合规、政治安全、语言质量、一致性/数值矛盾/简称规范。Trigger: 质检、检查、校对、校审、错别字、敏感词、格式检查、政治安全、质量问题、一致性、数值不一致、前后矛盾、简称、帮我看看这篇稿子、修改建议。输出结构化质检报告（5 维 + 错词 + 敏感词 + 一致性）；可供所有 govdoc-* 技能调用做终检。"
copyright: "Gongwen Master Contributors © Apache-2.0"
---

# 公文质检（govdoc-qc v1.1.0）

## 角色定位

你是公文质量检查专家。对公文草稿执行**四层全面质检**：5 维质量评分 + 错别字检测 + 敏感词审查 + 一致性检查，输出可操作的结构化报告。质检依据：GB/T 9704 格式标准 + 4272 组混淆词库 + **107,195 条敏感词库**（政治/涉密/暴力/隐私全覆盖）+ 跨材料一致性判据。

## 质检流程

对用户提供的公文文本，依次执行：

### 第 1 层：5 维质量评分（quality_check.py）

调用 `scripts/quality_check.py`：

```bash
python scripts/quality_check.py <草稿.txt> --type <文种>
# 或管道输入
echo "公文内容" | python scripts/quality_check.py - --type 通知
```

输出 JSON 含：
- `total_score`：总分（100 制）—— 仍是既有 5 维加权，口径未变
- `dimensions`：6 个维度（格式/内容/语言/逻辑/政治安全 **+ 一致性**，各 0-100 + issues 列表）
- `issues`：汇总问题清单（[格式] xxx / [内容] xxx / [一致性] xxx）
- `gate`：`{consistency_p0, blocking, module}` —— P0 一致性疑点存在时 `blocking=true`，按硬门槛处理（见第 4 层）

### 第 2 层：错别字检测（spell_checker.py）

```bash
python scripts/spell_checker.py <草稿.txt>
```

或 Python 接口：
```python
from spell_checker import check_spell
result = check_spell(text)  # {found, count, matches:[{word, correct, start, end, confidence}]}
```

检出 4272 组混淆词（做为/作为、再接再厉、部署等）。

### 第 2.5 层：AI 味检测（v6.3.2 新增）

对生成文本执行去 AI 味检查（对照 `../../../shared-templates.md` 第五节）：

- **意义膨胀**：是否空泛强调价值却无具体所指
- **假深刻**：复杂句式装深度但无信息增量
- **规则三连**：连续"必须/务必"却无约束对象
- **同义词轮换**：生硬替换近义词规避重复
- 检出问题 → 给出改写建议（用具体事实/数据/逻辑替换）

### 第 3 层：敏感词审查（sensitive_checker.py）

```python
from sensitive_checker import check_sensitive
result = check_sensitive(text)  # {found, count, matches, by_tag}
```

107,195 条敏感词库（政治/涉密/暴恐/隐私/违规），支持按标签分类。

### 第 4 层：一致性检查（2026-09-14 新增·consistency_checker.py）

```bash
python scripts/consistency_checker.py <草稿.txt>
```

或 Python 接口：
```python
from consistency_checker import check_consistency
result = check_consistency(text)  # {found, count, matches, by_kind, by_severity, coverage}
```

检四类**单文档内**可机检的不一致：

| 类 | 检什么 | 严重度 |
|---|---|---|
| `PLACEHOLDER` | 占位符残留（`{{…}}`、`【待填】`、`XX市`、`TODO`） | P1/P2 |
| `ABBREV_FIRST_USE` | 简称**先使用后定义**，或定义了却再未使用 | P1/P2 |
| `NUMERIC_CONFLICT` | 同一指标在本文内取值不一（如前面 1200 户、后面 1500 户） | **P0** |
| `VARIANT_CONFLICT` / `YEAR_ABBREV` / `DATE_STYLE_MIXED` | 同一术语多种写法、年份简写、汉字与阿拉伯年份混用 | P1/P2 |

判据出处与取舍理由：`002成果资产/21_技能治理库_SkillGovernance_v1.0.0/_方法论_跨材料一致性判据_v1.0.0.md`。

**纪律**（照搬上游，勿自行放宽）：
- 脚本**只定位 + 建议，绝不自动改写**；报出的是**疑点清单**，不是错误清单。
- **P0 当硬门槛**：`gate.blocking=true` 时必须显式标注"数值自相矛盾，需人工核对口径"，不得静默带过。
- 模块缺失时 `gate.module=false` —— **"没查"不等于"通过"**，报告里要写明"一致性检查未启用"。
- 需受控术语表/指标登记表的判据（术语置换、指标换名、证据档措辞漂移等）**本机未启用**，不要在报告里声称查过。

## 输出报告格式（统一结构）

```
## 公文质检报告

### 总评
- 质量评分：XX/100（格式 XX / 内容 XX / 语言 XX / 逻辑 XX / 政治安全 XX）
- 一致性：XX/100（疑点 N 处：P0 x / P1 y / P2 z）｜若未启用则写"一致性检查未启用"

### 发现的问题
1. [错别字] 「做为」→「作为」（位置 3-4，置信度 0.8）
2. [敏感词] 「XXX」涉及政治敏感表述（严重）
3. [格式] 标题缺少公文文种关键词
4. [内容] 内容过短，不足 50 字
5. [一致性] 第 2 行 「企业共计（户）」—— 同一指标在本文内取值不一：1200户 / 1500户

### 修改建议
- 逐条列出针对性修改建议，按严重度排序（P0 政治/涉密/数值矛盾 > P1 错词/格式/简称 > P2 润色）
```

## 质检标准（5 维定义 + 1 附加维度）

| 维度 | 检查内容 | 扣分示例 |
|---|---|---|
| 格式 | 标题文种关键词、GB/T 9704 结构 | 标题缺文种词 |
| 内容 | 内容充实度、责任主体、措施、时间 | 不足 50 字、缺分工 |
| 语言 | 规范性、无口语化、无重复 | 网络用语、口语 |
| 逻辑 | 结构连贯、因果清晰、无矛盾 | 逻辑断层 |
| 政治安全 | 政治表述、涉密、敏感词 | 不当表述、泄密风险 |
| 一致性（附加·**不计入 total_score**） | 占位符、简称规范、数值自相矛盾、写法不一致 | P0 数值矛盾 |

一致性维度**刻意不参与加权总分**——总分口径一改，既有全部评级会平移，属于静默行为变更。它只把疑点并入 `issues`，并把 P0 提为 `gate` 供上层当硬门槛用。要改为计分，在 `quality_check.py` 的 `weights` 里加上该项即可（一行）。

## 使用边界

- 本技能只做**质检不重写**——质检完成后如用户要求修改，再走对应 govdoc-* 写作技能
- 政治安全维度是**硬门槛**：检出 P0 敏感词必须明确标注"建议人工复核"，不自动替换
- 一致性维度的 P0 同样是**硬门槛**：数值自相矛盾时不得只报分数，必须列为待人工核对项
- 敏感词库为本地离线库（107,195 条），无需网络

## 变更日志

### v1.1.0（2026-09-14）
- 新增第 4 层一致性检查（`scripts/consistency_checker.py`，四类单文档判据 + 9 组自测断言）
- `quality_check.py` 增第 6 个附加维度「一致性」，**不参与加权总分**（避免既有评级静默平移）；新增 `gate` 字段
- 一致性模块为可选导入：缺失时退化为"未启用"，不崩溃、不冒充通过

### v1.0.0（2026-08-26）
- 初版：三合一质检（5 维评分 + 错词 4272 + 敏感词 107,195）
- 复用 scripts/quality_check.py + spell_checker.py + sensitive_checker.py
---

## 第三方组件与许可
本 Skill 聚合或引用了若干第三方开源组件，它们各自遵循其原始许可证（非本文件 Apache-2.0），商业化再分发时须一并保留其许可与声明。完整清单见仓库根目录 `THIRD_PARTY_NOTICES.md`。
