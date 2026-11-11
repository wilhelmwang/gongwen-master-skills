---
name: govdoc-approval
tags: [govdoc, 公文, 请示/审批]
version: 2.0.0
description: "Use when the user asks to draft, revise, structure, or review Chinese official 批复. Trigger keywords: 答复下级机关请示事项；审批下级机关请求批准的项目、资金、人事等。常用触发：批复、审批、批准、核准、答复请示。"
copyright: "Gongwen Master Contributors © Apache-2.0"
---

# 批复写作

## 触发场景

- 答复下级机关请示事项；审批下级机关请求批准的项目、资金、人事等。

## 不适用

- 不用于请求上级批准（->govdoc-request）；不用于报告工作、反映情况（->govdoc-report）。

## 文种类型

- 审批类批复、指示类批复、转发类批复、答复类批复

## 公共规范（统一持有）

本模块的输入清单、输出形态，以及 GB/T 9704 格式规范、行文规则、15 种法定公文、
常见错误与规避、质量检查清单，统一持有在 `../../../shared-templates.md`（见该文件「文种模块公共规范」各节）。

**执行本模块工作流前，须先读取上述文件对应小节**，默认工作流为：
1. 明确任务 → 2. 收集信息 → 3. 按**本模块自己的** `references/formulas.md` 套用结构 → 4. 按上述文件质量检查


## 第三方组件与许可
本 Skill 聚合或引用了若干第三方开源组件，它们各自遵循其原始许可证（非本文件 Apache-2.0），商业化再分发时须一并保留其许可与声明。完整清单见仓库根目录 `THIRD_PARTY_NOTICES.md`。
