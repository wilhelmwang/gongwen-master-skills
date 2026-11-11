# 嵌套子技能清单（Sub-skills Inventory）

> 生成：2026-09-21 ｜ 包版本 8.0.0 ｜ **由门禁 C9 双向校验，勿手改结构**

本包含 **1 个顶层技能**（v8.0.0 单技能化：顶层仅 gongwen-master；24 受治理模块 + 1 退役安装器 + 3 参考技能均嵌套）与 **54 个嵌套子技能**。

**嵌套子技能的定义**：位于某个顶层技能的 `references/<子技能>/SKILL.md`，**由父技能按路径加载**，
不作为独立技能注册。宿主面板若按 `**/SKILL.md` 递归扫描，会把这些一并发现 —— 本清单用来声明
「哪些嵌套是有意的」，并保证技能名全局唯一（重名会导致同一技能被注册两次）。

## 为什么需要这份清单

2026-09-11 排查发现：这 54 个嵌套 SKILL.md **长期不在任何门禁覆盖范围内**（`yaml_strict` 当时只查顶层 25 个），结果里面藏着两处真实缺陷：

1. `gongwen-master/references/govdoc-onboarding/SKILL.md` —— `description` 内嵌 4 个裸双引号
   （`（如"写个通知"）` / `兜底"新手/不确定"场景`），**严格 YAML 解析直接 ParserError**，
   与 v7.3.0 修掉的 P0-A 同类缺陷。宿主解析失败则该子技能完全不可用。
2. `govdoc-layout/references/govdoc-workflow/SKILL.md` —— 声明 `name: govdoc-workflow`，
   **与顶层受治理技能 `govdoc-workflow` 同名**，但两者是不同技能（顶层=流程场景编排；
   该嵌套=公文写作通用底座）。面板按 name 注册 → 重复技能。已改名为 `govdoc-writing-base`（目录保留原路径以免断引用）。

两处均已在 v7.5.1 修复；`yaml_strict` 门禁的覆盖范围同时从「顶层 25 个」扩到「全部 55 个」。

## 清单

| 子技能 name | 版本 | 父技能 | 路径 |
|---|---|---|---|
| `article-review` | 6.8.0 | `gongwen-master` | `gongwen-master/references/article-review/SKILL.md` |
| `article-analysis-workflow` | 1.2.0 | `gongwen-master` | `gongwen-master/references/article-review/references/article-analysis-workflow/SKILL.md` |
| `article-fact-check-team` | 3.1.0 | `gongwen-master` | `gongwen-master/references/article-review/references/article-fact-check-team/SKILL.md` |
| `govdoc-circular` | 2.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-circular/SKILL.md` |
| `govdoc-brief` | 2.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-circular/references/govdoc-brief/SKILL.md` |
| `govdoc-briefing` | 2.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-circular/references/govdoc-briefing/SKILL.md` |
| `govdoc-corpus` | 1.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-corpus/SKILL.md` |
| `govdoc-duty` | 2.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-duty/SKILL.md` |
| `govdoc-experience` | 2.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-experience/SKILL.md` |
| `govdoc-feedback` | 1.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-feedback/SKILL.md` |
| `govdoc-layout` | 2.1.0 | `gongwen-master` | `gongwen-master/references/govdoc-layout/SKILL.md` |
| `govdoc-writing-base` | 1.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-layout/references/govdoc-workflow/SKILL.md` |
| `govdoc-letter` | 2.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-letter/SKILL.md` |
| `govdoc-open-letter` | 2.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-letter/references/govdoc-open-letter/SKILL.md` |
| `govdoc-material` | 1.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-material/SKILL.md` |
| `govdoc-minutes` | 2.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-minutes/SKILL.md` |
| `govdoc-news` | 2.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-news/SKILL.md` |
| `govdoc-notice` | 2.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-notice/SKILL.md` |
| `govdoc-onboarding` | 2.1.0 | `gongwen-master` | `gongwen-master/references/govdoc-onboarding/SKILL.md` |
| `govdoc-plan` | 2.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-plan/SKILL.md` |
| `govdoc-polish` | 1.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-polish/SKILL.md` |
| `govdoc-qc` | 1.1.0 | `gongwen-master` | `gongwen-master/references/govdoc-polish/references/govdoc-qc/SKILL.md` |
| `govdoc-reflection` | 2.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-reflection/SKILL.md` |
| `govdoc-regulation` | 2.1.0 | `gongwen-master` | `gongwen-master/references/govdoc-regulation/SKILL.md` |
| `govdoc-rule` | 2.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-regulation/references/govdoc-rule/SKILL.md` |
| `govdoc-report` | 2.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-report/SKILL.md` |
| `govdoc-request` | 2.1.0 | `gongwen-master` | `gongwen-master/references/govdoc-request/SKILL.md` |
| `govdoc-approval` | 2.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-request/references/govdoc-approval/SKILL.md` |
| `govdoc-research` | 2.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-research/SKILL.md` |
| `govdoc-speech` | 2.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-speech/SKILL.md` |
| `govdoc-style-learn` | 1.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-style-learn/SKILL.md` |
| `govdoc-styles` | 6.9.0 | `gongwen-master` | `gongwen-master/references/govdoc-styles/SKILL.md` |
| `文风一` | 1.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-styles/references/biganzi-1/SKILL.md` |
| `文风二` | 1.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-styles/references/biganzi-2/SKILL.md` |
| `文风三` | 1.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-styles/references/biganzi-3/SKILL.md` |
| `文风四` | 1.3.0 | `gongwen-master` | `gongwen-master/references/govdoc-styles/references/biganzi-4/SKILL.md` |
| `文风五` | 1.2.0 | `gongwen-master` | `gongwen-master/references/govdoc-styles/references/biganzi-5/SKILL.md` |
| `文风六` | 1.2.0 | `gongwen-master` | `gongwen-master/references/govdoc-styles/references/biganzi-6/SKILL.md` |
| `五笔会诊` | 2.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-styles/references/biganzi-roundtable/SKILL.md` |
| `govdoc-summary` | 2.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-summary/SKILL.md` |
| `govdoc-theory` | 2.0.0 | `gongwen-master` | `gongwen-master/references/govdoc-theory/SKILL.md` |
| `govdoc-workflow` | 1.3.0 | `gongwen-master` | `gongwen-master/references/govdoc-workflow/SKILL.md` |
| `install-gongwen` | 1.0.0 | `gongwen-master` | `gongwen-master/references/install-gongwen/SKILL.md` |
| `qiushi-db` | 1.2.0 | `gongwen-master` | `gongwen-master/references/qiushi-db/SKILL.md` |
| `shuji` | 6.8.0 | `gongwen-master` | `gongwen-master/references/shuji/SKILL.md` |
| `dangdai-zhengfu` | 2.0.0 | `gongwen-master` | `gongwen-master/references/shuji/references/dangdai-zhengfu/SKILL.md` |
| `jiegou-gaige` | 2.0.0 | `gongwen-master` | `gongwen-master/references/shuji/references/jiegou-gaige/SKILL.md` |
| `liyi-weili` | 2.0.0 | `gongwen-master` | `gongwen-master/references/shuji/references/liyi-weili/SKILL.md` |
| `shizhi-shinei` | 2.0.0 | `gongwen-master` | `gongwen-master/references/shuji/references/shizhi-shinei/SKILL.md` |
| `xianxiang-zhongguo` | 2.0.0 | `gongwen-master` | `gongwen-master/references/shuji/references/xianxiang-zhongguo/SKILL.md` |
| `xiaozhen-xuanxiao` | 2.0.0 | `gongwen-master` | `gongwen-master/references/shuji/references/xiaozhen-xuanxiao/SKILL.md` |
| `zhidu-luoji` | 2.0.0 | `gongwen-master` | `gongwen-master/references/shuji/references/zhidu-luoji/SKILL.md` |
| `zhongxian-ganbu` | 2.0.0 | `gongwen-master` | `gongwen-master/references/shuji/references/zhongxian-ganbu/SKILL.md` |
| `zhuanxing-zhengfu` | 2.0.0 | `gongwen-master` | `gongwen-master/references/shuji/references/zhuanxing-zhengfu/SKILL.md` |

## 分类说明

上表 54 项全部为**技能**（均有 `name` + `description`，可被独立加载），
不存在「仅作资料存放但不构成技能」的条目。若后续在某 `references/` 下放入仅供引用的
Markdown 说明文档，**不要命名为 `SKILL.md`**，否则会被计入本清单并被 C9 视为新增技能。

## 维护约定

- 新增/删除嵌套子技能后，重跑 `python gongwen_tool.py subskills --write` 重建本清单。
- C9 门禁会双向校验：清单里写了但实际不存在 → 报错；实际存在但清单没写 → 报错。
- 技能名必须全局唯一（顶层 + 嵌套一起算），`yaml_strict` 门禁强制。
