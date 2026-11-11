---
name: article-review
description: >-
  当用户需要「深度分析一篇文章」或「核查文章事实」时使用我（文章审查两模式合一）：
  - 模式A 深度分析（原 article-analysis-workflow）：六步流程（需求澄清→素材并行→文体结构→分析论证→图形工具→DoD 验收），产出分析/评注/研究报告。
  - 模式B 事实核查（原 article-fact-check-team）：**路由至顶层现役技能 `unified-article-review` V4.15.1**（7 阶段标准模式 / 1+5 团队模式 + 9 脚本确定性工具链），产出 P0/P1/P2 分级核查报告。
  触发词：分析这篇文章、深度分析、文章核查、事实核查、核查一下、研究报告、案件评注、这篇文章有没有问题。
  v6.8.1（2026-10-21）：模式 B 改路由至 unified-article-review V4.15.1；内嵌 v3.1.0 降为历史快照回退件。
tags: [article, 文章分析, 事实核查, 核查报告]
display_name: "文章审查（分析+核查）"
visibility: "public"
agent_created: true
version: "6.8.1"
compatibility: "Designed for WorkBuddy/Claude/豆包等 agent 技能平台（standalone 包）；引擎脚本需 Python 3.10+ 与 requirements.txt 依赖（jieba/numpy/scikit-learn/rank-bm25）；数据层 datahub/ 随包（详见 requires）"
requires:
  references: "references/ 子模块方法论文件（随包）"
  data: "可选引用 qiushi-db 数据中枢（经 gongwen-master 路由）"
permissions:
  fs_write: "无"
  network: "无"
  secrets: "无"
copyright: "Gongwen Master Contributors © Apache-2.0"
---

# 文章审查（article-review · 两模式合一）

> 深度分析 + 事实核查统一入口。按用户需求选择模式，完整方法论渐进式加载。

## 模式选择

| 模式 | 触发场景 | 方法论文档 |
|---|---|---|
| **A 深度分析** | "分析这篇文章""出研究报告""案件评注" | `references/article-analysis-workflow/SKILL.md`（六步 + DoD 验收） |
| **B 事实核查** | "核查这篇""查证事实""P0/P1/P2 报告" | **优先走顶层现役技能 `unified-article-review` V4.15.1**：`~/.workbuddy/skills/unified-article-review/SKILL.md`（7 阶段 + 9 脚本 + 辩论式裁决 + 投资研判） |

> **路由优先级（2026-10-21 起）**：凡「事实核查 / 核查一篇 / 文章核查 / 这篇靠谱吗」类请求，一律加载 `unified-article-review`（V4.15.1，含 scripts 确定性工具链）。
> 本目录内 `references/article-fact-check-team/SKILL.md`（v3.1.0）为**历史快照与回退件**——仅在顶层技能缺失或用户明确要求"用老版三阶段流程"时使用，不得作为默认路径。

## 通用准则

- 先定合格标准再动手（需求澄清缺失致 80% 返工）
- 核查报告按 P0（致命）/P1（严重）/P2（中等）分级，每条给可操作修复建议
- 覆盖维度：逻辑/完整性/技术错误/结构/性能/安全/可维护性/投资可行性
